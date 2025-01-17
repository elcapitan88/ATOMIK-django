import json
import logging
import asyncio
from typing import Dict, List, Any, Optional, Callable, Set
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from channels.db import database_sync_to_async
from ..brokers.base.exceptions import (
    WebSocketError,
    WebSocketAuthenticationError,
    WebSocketMessageError,
    RateLimitError,
    BrokerBaseException
)

logger = logging.getLogger(__name__)

class ConnectionPoolMixin:
    """Mixin for managing a pool of WebSocket connections."""
    
    def __init__(self, max_connections: int = 100, cleanup_interval: int = 300):
        self.max_connections = max_connections
        self.cleanup_interval = cleanup_interval
        self.pools: Dict[str, Dict[str, Any]] = {}
        self.locks: Dict[str, asyncio.Lock] = {}
        self._cleanup_task = None
        super().__init__()

    async def initialize_pool(self):
        """Start the connection pool and cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Connection pool initialized")

    async def shutdown_pool(self):
        """Shutdown the connection pool and cleanup resources."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cleanup all pools
        for pool_id in list(self.pools.keys()):
            await self._cleanup_pool(pool_id)
            
        logger.info("Connection pool shut down")

    async def get_connection(self, pool_id: str, connection_class: type, **kwargs) -> Any:
        """Get or create a connection from the pool."""
        if pool_id not in self.locks:
            self.locks[pool_id] = asyncio.Lock()

        async with self.locks[pool_id]:
            pool = self.pools.setdefault(pool_id, {
                'connections': {},
                'last_cleanup': timezone.now()
            })

            # Try to reuse existing connection
            for conn_id, conn_data in pool['connections'].items():
                if self._is_connection_available(conn_data):
                    logger.debug(f"Reusing connection {conn_id} from pool {pool_id}")
                    conn_data['last_used'] = timezone.now()
                    conn_data['use_count'] += 1
                    return conn_data['connection']

            # Create new connection if pool not full
            if len(pool['connections']) < self.max_connections:
                connection = connection_class(**kwargs)
                conn_id = str(len(pool['connections']))
                
                pool['connections'][conn_id] = {
                    'connection': connection,
                    'created_at': timezone.now(),
                    'last_used': timezone.now(),
                    'use_count': 1,
                    'is_active': True
                }
                
                try:
                    await connection.connect()
                    logger.info(f"Created new connection {conn_id} in pool {pool_id}")
                    return connection
                except Exception as e:
                    del pool['connections'][conn_id]
                    logger.error(f"Error creating connection: {str(e)}")
                    raise

            raise RuntimeError(f"Connection pool {pool_id} is full")

    async def release_connection(self, pool_id: str, connection: Any):
        """Release a connection back to the pool."""
        if pool_id in self.pools:
            async with self.locks[pool_id]:
                for conn_data in self.pools[pool_id]['connections'].values():
                    if conn_data['connection'] == connection:
                        conn_data['last_used'] = timezone.now()
                        return

    async def _cleanup_loop(self):
        """Periodically cleanup inactive connections."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                for pool_id in list(self.pools.keys()):
                    await self._cleanup_pool(pool_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {str(e)}")

    async def _cleanup_pool(self, pool_id: str):
        """Cleanup inactive connections in a specific pool."""
        if pool_id not in self.pools:
            return

        async with self.locks[pool_id]:
            pool = self.pools[pool_id]
            current_time = timezone.now()
            to_remove = []

            for conn_id, conn_data in pool['connections'].items():
                if self._should_remove_connection(conn_data, current_time):
                    to_remove.append(conn_id)

            for conn_id in to_remove:
                conn_data = pool['connections'][conn_id]
                try:
                    await conn_data['connection'].disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting connection {conn_id}: {str(e)}")
                del pool['connections'][conn_id]

            pool['last_cleanup'] = current_time
            
            if not pool['connections']:
                del self.pools[pool_id]
                del self.locks[pool_id]

    def _is_connection_available(self, conn_data: Dict[str, Any]) -> bool:
        """Check if a connection is available for reuse."""
        return (
            conn_data['is_active'] and
            hasattr(conn_data['connection'], 'is_connected') and
            conn_data['connection'].is_connected and
            (timezone.now() - conn_data['last_used']).seconds < 300
        )

    def _should_remove_connection(self, conn_data: Dict[str, Any], current_time: datetime) -> bool:
        """Determine if a connection should be removed from the pool."""
        inactive_time = (current_time - conn_data['last_used']).seconds
        return (
            not conn_data['is_active'] or
            not hasattr(conn_data['connection'], 'is_connected') or
            not conn_data['connection'].is_connected or
            inactive_time > 600 or
            (inactive_time > 300 and conn_data['use_count'] < 5)
        )

class AuthenticationMixin:
    """Mixin for handling WebSocket authentication."""

    async def authenticate(self) -> bool:
        """Authenticate the WebSocket connection."""
        if not self.scope["user"].is_authenticated:
            logger.warning("Unauthorized WebSocket connection attempt")
            await self.send_error("Authentication required")
            return False
        return True

    @database_sync_to_async
    def get_user_brokers(self):
        """Get all active brokers for the authenticated user."""
        return list(Broker.objects.filter(is_active=True))

    async def verify_broker_access(self, broker_id: str) -> bool:
        """Verify user has access to specified broker."""
        try:
            brokers = await self.get_user_brokers()
            return any(str(broker.id) == broker_id for broker in brokers)
        except Exception as e:
            logger.error(f"Error verifying broker access: {str(e)}")
            return False

class MessageHandlerMixin:
    """Mixin for handling WebSocket messages."""

    async def handle_message(self, message_text: str) -> None:
        """Process incoming WebSocket messages."""
        try:
            message = json.loads(message_text)
            message_type = message.get('type')

            if not message_type:
                await self.send_error("Message type is required")
                return

            handler = getattr(self, f"handle_{message_type}", None)
            if handler:
                await handler(message)
            else:
                await self.send_error(f"Unknown message type: {message_type}")

        except json.JSONDecodeError:
            await self.send_error("Invalid JSON format")
        except Exception as e:
            logger.error(f"Error handling message: {str(e)}", exc_info=True)
            await self.send_error("Internal server error")

    async def send_json(self, content: Dict[str, Any]) -> None:
        """Send JSON message to client."""
        if not hasattr(self, 'send'):
            raise WebSocketError("WebSocket connection not established")

        try:
            await self.send(text_data=json.dumps(content))
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            raise WebSocketError(f"Failed to send message: {str(e)}")

    async def send_error(self, message: str, code: Optional[str] = None) -> None:
        """Send error message to client."""
        await self.send_json({
            'type': 'error',
            'message': message,
            'code': code,
            'timestamp': timezone.now().isoformat()
        })

class HeartbeatMixin:
    """Mixin for handling WebSocket heartbeat."""

    async def start_heartbeat(self) -> None:
        """Start heartbeat mechanism."""
        self.heartbeat_task = self.loop.create_task(self._heartbeat())

    async def stop_heartbeat(self) -> None:
        """Stop heartbeat mechanism."""
        if hasattr(self, 'heartbeat_task'):
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except Exception:
                pass

    async def _heartbeat(self) -> None:
        """Send periodic heartbeat messages."""
        while True:
            try:
                await self.send_json({
                    'type': 'heartbeat',
                    'timestamp': timezone.now().isoformat()
                })
                await asyncio.sleep(15)
            except Exception as e:
                logger.error(f"Heartbeat error: {str(e)}")
                break

class RateLimitMixin:
    """Mixin for WebSocket rate limiting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message_timestamps = []
        self.rate_limit = getattr(settings, 'WEBSOCKET_RATE_LIMIT', 60)
        self.rate_window = 60

    async def check_rate_limit(self) -> bool:
        """Check if rate limit is exceeded."""
        now = timezone.now()
        
        # Remove old timestamps
        self.message_timestamps = [
            ts for ts in self.message_timestamps 
            if (now - ts).seconds <= self.rate_window
        ]

        if len(self.message_timestamps) >= self.rate_limit:
            await self.send_error("Rate limit exceeded", code="RATE_LIMIT_EXCEEDED")
            return False

        self.message_timestamps.append(now)
        return True