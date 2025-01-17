import json
import logging
import asyncio
from typing import Dict, Any, Optional, Set
from collections import defaultdict
from datetime import datetime, timedelta
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from django.conf import settings
from channels.db import database_sync_to_async

from .mixins import (
    ConnectionPoolMixin,
    AuthenticationMixin,
    MessageHandlerMixin,
    HeartbeatMixin,
    RateLimitMixin
)
from ..brokers.tradovate.models import TradovateAccount, TradovateToken
from ..brokers.tradovate.consumers import TradovateConsumer
from ..brokers.base.exceptions import (
    WebSocketError,
    WebSocketAuthenticationError,
    BrokerConnectionError
)
from ..monitoring.logging_config import trade_logger
from ..monitoring.performance import PerformanceMonitoringMixin

logger = logging.getLogger(__name__)

class ConnectionPool:
    """Manages a pool of WebSocket connections with health monitoring."""
    
    def __init__(self, max_size: int = 100, cleanup_interval: int = 300):
        self.max_size = max_size
        self.cleanup_interval = cleanup_interval
        self.pools: Dict[str, Dict[str, Any]] = {}
        self.health_metrics: Dict[str, Dict[str, Any]] = {}
        self._cleanup_task = None
        self._lock = asyncio.Lock()

    async def get_connection(self, pool_id: str, connection_class: type, **kwargs) -> Any:
        """Get or create a connection from the pool with load balancing."""
        async with self._lock:
            pool = self.pools.setdefault(pool_id, {
                'connections': {},
                'last_cleanup': timezone.now(),
                'total_requests': 0,
                'errors': 0
            })

            # Check pool health
            if pool['errors'] > 10 and pool['total_requests'] > 0:
                error_rate = pool['errors'] / pool['total_requests']
                if error_rate > 0.3:  # 30% error rate threshold
                    await self._reset_pool(pool_id)

            # Try to find available connection
            for conn_id, conn_data in pool['connections'].items():
                if self._is_connection_healthy(conn_data):
                    conn_data['last_used'] = timezone.now()
                    conn_data['use_count'] += 1
                    return conn_data['connection']

            # Create new connection if pool not full
            if len(pool['connections']) < self.max_size:
                connection = await self._create_connection(connection_class, **kwargs)
                conn_id = str(len(pool['connections']))
                
                pool['connections'][conn_id] = {
                    'connection': connection,
                    'created_at': timezone.now(),
                    'last_used': timezone.now(),
                    'use_count': 1,
                    'errors': 0,
                    'last_error': None,
                    'health_check_failures': 0
                }
                
                return connection

            # Load balance if pool is full
            return self._get_least_loaded_connection(pool)

    async def _create_connection(self, connection_class: type, **kwargs) -> Any:
        """Create and initialize a new connection."""
        try:
            connection = connection_class(**kwargs)
            await connection.connect()
            return connection
        except Exception as e:
            logger.error(f"Error creating connection: {str(e)}")
            raise

    def _is_connection_healthy(self, conn_data: Dict[str, Any]) -> bool:
        """Check if a connection is healthy and available."""
        if conn_data['health_check_failures'] > 3:
            return False
            
        if conn_data['errors'] > 5:
            error_window = (timezone.now() - conn_data['last_error']).seconds
            if error_window < 60:  # Recent errors
                return False

        return (
            hasattr(conn_data['connection'], 'is_connected') and
            conn_data['connection'].is_connected and
            (timezone.now() - conn_data['last_used']).seconds < 300
        )

    def _get_least_loaded_connection(self, pool: Dict[str, Any]) -> Any:
        """Get the least loaded connection from the pool."""
        connections = sorted(
            pool['connections'].values(),
            key=lambda x: (x['use_count'], x['errors'])
        )
        return connections[0]['connection'] if connections else None

    async def _reset_pool(self, pool_id: str) -> None:
        """Reset an unhealthy connection pool."""
        logger.warning(f"Resetting unhealthy pool: {pool_id}")
        pool = self.pools[pool_id]
        
        for conn_data in pool['connections'].values():
            try:
                await conn_data['connection'].disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting during pool reset: {str(e)}")

        pool['connections'].clear()
        pool['errors'] = 0
        pool['total_requests'] = 0

class WebSocketManager(
    AsyncWebsocketConsumer,
    ConnectionPoolMixin,
    AuthenticationMixin,
    MessageHandlerMixin,
    HeartbeatMixin,
    RateLimitMixin
):
    """Enhanced WebSocket manager with improved error recovery and monitoring."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.active_subscriptions: Set[str] = set()
        self.has_active_accounts = False
        self.connection_pool = ConnectionPool(
            max_size=settings.WEBSOCKET_MAX_CONNECTIONS,
            cleanup_interval=settings.WEBSOCKET_CLEANUP_INTERVAL
        )
        
        # Performance monitoring
        self.metrics = defaultdict(int)
        self.error_counts = defaultdict(int)
        self.last_cleanup = timezone.now()

    async def connect(self) -> None:
        """Handle WebSocket connection with enhanced error recovery."""
        logger.info("WebSocket manager connecting...")
        
        try:
            # Authenticate user
            self.user = self.scope["user"]
            if not await self.authenticate():
                return

            # Check for active accounts
            self.has_active_accounts = await self.check_active_accounts()
            if not self.has_active_accounts:
                logger.info(f"No active accounts found for user {self.user.username}")
                await self.close()
                return

            # Accept connection
            await self.accept()
            logger.info(f"WebSocket connection accepted for user {self.user.username}")

            # Join user-specific group
            self.user_group = f"user_{self.user.id}"
            await self.channel_layer.group_add(
                self.user_group,
                self.channel_name
            )

            # Start monitoring tasks
            await self.start_monitoring()

        except Exception as e:
            logger.error(f"Connection error: {str(e)}", exc_info=True)
            await self.handle_error("Connection failed", e)
            await self.close()

    async def start_monitoring(self) -> None:
        """Start background monitoring tasks."""
        self.monitoring_task = asyncio.create_task(self._monitor_connections())
        self.cleanup_task = asyncio.create_task(self._cleanup_resources())

    async def _monitor_connections(self) -> None:
        """Monitor connection health and performance."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                pools_status = {}
                for pool_id, pool in self.connection_pool.pools.items():
                    total_conns = len(pool['connections'])
                    healthy_conns = sum(
                        1 for conn in pool['connections'].values()
                        if self.connection_pool._is_connection_healthy(conn)
                    )
                    
                    health_ratio = healthy_conns / total_conns if total_conns > 0 else 1
                    pools_status[pool_id] = {
                        'health_ratio': health_ratio,
                        'error_rate': pool['errors'] / pool['total_requests'] 
                            if pool['total_requests'] > 0 else 0
                    }

                    # Take action if pool is unhealthy
                    if health_ratio < 0.7:  # Less than 70% healthy connections
                        logger.warning(f"Unhealthy pool detected: {pool_id}")
                        await self.connection_pool._reset_pool(pool_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in connection monitoring: {str(e)}")
                await asyncio.sleep(5)  # Brief pause before retrying

    async def _cleanup_resources(self) -> None:
        """Periodically cleanup unused resources."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                
                # Cleanup old connections
                current_time = timezone.now()
                for pool_id, pool in self.connection_pool.pools.items():
                    to_remove = []
                    for conn_id, conn_data in pool['connections'].items():
                        if (current_time - conn_data['last_used']).seconds > 1800:  # 30 minutes
                            to_remove.append(conn_id)
                    
                    for conn_id in to_remove:
                        await self.remove_connection(pool_id, conn_id)

                # Update metrics
                self.metrics['last_cleanup'] = timezone.now()
                self.metrics['total_cleanups'] += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in resource cleanup: {str(e)}")
                await asyncio.sleep(5)

    async def receive(self, text_data: str) -> None:
        """Handle incoming WebSocket messages with enhanced error handling."""
        if not self.has_active_accounts:
            await self.close()
            return

        try:
            # Apply rate limiting
            if not await self.check_rate_limit():
                return

            # Parse and validate message
            try:
                message = json.loads(text_data)
            except json.JSONDecodeError:
                await self.handle_error("Invalid JSON format", None)
                return

            # Route message
            message_type = message.get('type')
            handler = self.message_handlers.get(message_type)
            
            if handler:
                try:
                    await handler(message)
                    self.metrics['messages_processed'] += 1
                except Exception as e:
                    self.error_counts[message_type] += 1
                    await self.handle_error(f"Error processing {message_type}", e)
            else:
                await self.handle_broker_message(message)

        except Exception as e:
            logger.error(f"Error in message handling: {str(e)}", exc_info=True)
            await self.handle_error("Message processing failed", e)

    @database_sync_to_async
    def check_active_accounts(self) -> bool:
        """Check for active accounts with valid tokens."""
        try:
            accounts = TradovateAccount.objects.filter(
                user=self.user,
                is_active=True,
                status='active'
            )

            if not accounts.exists():
                return False

            for account in accounts:
                try:
                    token = TradovateToken.objects.get(
                        user=self.user,
                        environment=account.environment,
                        is_valid=True
                    )
                    if not token.is_expired():
                        return True
                except TradovateToken.DoesNotExist:
                    continue

            return False

        except Exception as e:
            logger.error(f"Error checking active accounts: {str(e)}")
            return False

    def get_broker_consumer(self, broker: str) -> type:
        """Get appropriate consumer class for broker."""
        if broker == 'tradovate':
            return TradovateConsumer
        raise ValueError(f"Unsupported broker: {broker}")

    def get_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics."""
        return {
            'metrics': dict(self.metrics),
            'error_counts': dict(self.error_counts),
            'connection_pools': {
                pool_id: {
                    'total_connections': len(pool['connections']),
                    'active_connections': sum(
                        1 for conn in pool['connections'].values()
                        if self.connection_pool._is_connection_healthy(conn)
                    ),
                    'error_rate': pool['errors'] / pool['total_requests'] 
                        if pool['total_requests'] > 0 else 0
                }
                for pool_id, pool in self.connection_pool.pools.items()
            }
        }