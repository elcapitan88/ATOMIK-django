from typing import Dict, List, Optional, Any, Set, Union
from datetime import datetime
import asyncio
import logging
from starlette.websockets import WebSocket, WebSocketState
from fastapi import WebSocketDisconnect, HTTPException
import json
from rx.subject import Subject

from ..core.config import settings
from .metrics import HeartbeatMetrics
from .scaling.resource_manager import resource_manager
from .monitoring.monitor import MonitoringService
from .handlers.endpoint_handlers import TradovateEndpointHandler
from .handlers.event_handlers import TradovateEventHandler
from .handlers.webhook_handlers import TradovateWebhookHandler
from .handlers.order_executor import TradovateOrderExecutor
from .errors import WebSocketError, handle_websocket_error
from .websocket_config import WebSocketConfig

logger = logging.getLogger(__name__)

class ConnectionState:
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"

class WebSocketManager:
    """
    Consolidated WebSocket manager that handles all WebSocket operations
    including connection management, heartbeats, message routing, and user sessions.
    """
    
    def __init__(self):
        # Connection Management
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_states: Dict[str, str] = {}
        self.user_connections: Dict[int, Set[str]] = {}  # user_id -> set of connection_ids
        self.connection_details: Dict[str, Dict[str, Any]] = {}
        
        # Session and Token Management
        self.connection_tokens: Dict[str, str] = {}
        self.user_sessions: Dict[int, Set[str]] = {}  # user_id -> set of session_ids
        
        # Message Handling
        self.message_queues: Dict[str, asyncio.Queue] = {}
        self.pending_messages: Dict[str, Set[str]] = {}
        self.message_subject = Subject()
        self.market_data_subject = Subject()
        self.order_update_subject = Subject()
        self.account_update_subject = Subject()
        
        # Monitoring and Metrics
        self.metrics: Dict[str, HeartbeatMetrics] = {}
        self.monitoring_service = MonitoringService()
        self.last_heartbeats: Dict[str, datetime] = {}
        
        # Resource Management
        self.resource_manager = resource_manager
        
        # Handlers
        self.order_executor = TradovateOrderExecutor()
        self.event_handler = TradovateEventHandler()
        self.endpoint_handler = TradovateEndpointHandler(
            config={
                "path": "/ws/tradovate",
                "auth_required": True
            }
        )
        self.webhook_handler = TradovateWebhookHandler(
            secret_key=settings.WEBHOOK_SECRET_KEY
        )

        # State Management
        self._initialized = False
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}
        self.reconnect_attempts: Dict[str, int] = {}

        # Configuration
        self.config = WebSocketConfig.HEARTBEAT
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.HEARTBEAT_INTERVAL = 30  # seconds
        self.CONNECTION_TIMEOUT = 10  # seconds
        self.MAX_CONNECTIONS_PER_USER = 5

    async def initialize(self) -> bool:
        """Initialize the WebSocket manager and its dependencies"""
        if self._initialized:
            return True

        try:
            async with self._lock:
                # Start monitoring service
                await self.monitoring_service.start()
                
                # Initialize resource manager
                await self.resource_manager.initialize()
                
                # Register default node for load balancing
                await self.resource_manager.load_balancer.register_node(
                    "default_node",
                    capacity=1000,
                    metadata={"type": "default"}
                )

                # Start cleanup task
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                
                self._initialized = True
                logger.info("WebSocket manager initialized successfully")
                return True

        except Exception as e:
            logger.error(f"Failed to initialize WebSocket manager: {str(e)}")
            return False
        
    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        user_id: Optional[int] = None
) -> bool:
        """
        Establish and manage a new WebSocket connection with comprehensive error handling
        and resource management.
        """
        try:
            # Check connection limits for user
            if user_id and len(self.user_connections.get(user_id, set())) >= self.MAX_CONNECTIONS_PER_USER:
                logger.warning(f"Connection limit reached for user {user_id}")
                return False

            # Register with resource manager
            node_id = await self.resource_manager.register_connection(
                websocket.client.host,
                client_id
            )
            
            if not node_id:
                logger.error("Failed to register with resource manager")
                return False

            async with self._lock:
                try:
                    # Store connection details
                    self.active_connections[client_id] = websocket
                    self.connection_states[client_id] = ConnectionState.CONNECTED
                    self.connection_details[client_id] = {
                        'user_id': user_id,
                        'node_id': node_id,
                        'connected_at': datetime.utcnow(),
                        'last_heartbeat': datetime.utcnow(),
                        'message_count': 0,
                        'client_info': {
                            'host': websocket.client.host,
                            'port': websocket.client.port
                        }
                    }

                    # Initialize message queue
                    self.message_queues[client_id] = asyncio.Queue()
                    
                    # Track user connections
                    if user_id:
                        if user_id not in self.user_connections:
                            self.user_connections[user_id] = set()
                        self.user_connections[user_id].add(client_id)
                    
                    # Initialize metrics
                    metrics = HeartbeatMetrics()
                    self.metrics[client_id] = metrics
                    
                    # Start heartbeat monitoring
                    heartbeat_success = await self.heartbeat_monitor.start_monitoring(
                        websocket,
                        client_id,
                        metrics
                    )
                    
                    if not heartbeat_success:
                        logger.error(f"Failed to start heartbeat monitoring for {client_id}")
                        await self._cleanup_connection(client_id)
                        return False
                    
                    logger.info(f"Heartbeat monitoring started for {client_id}")
                    
                    # Start message processing
                    asyncio.create_task(self._process_messages(client_id))
                    
                    logger.info(f"WebSocket connection established - Client: {client_id}, User: {user_id}")
                    return True

                except Exception as e:
                    logger.error(f"Error during connection setup: {str(e)}")
                    await self._cleanup_connection(client_id)
                    return False

        except Exception as e:
            logger.error(f"Error establishing connection: {str(e)}")
            # Ensure cleanup even if error occurs outside the lock
            await self._cleanup_connection(client_id)
            return False


    async def disconnect(self, client_id: str, code: int = 1000, reason: str = "Normal closure") -> None:
        """
        Handle WebSocket disconnection with proper cleanup and resource release.
        Ensures graceful shutdown of all connection-related resources.
        """
        try:
            async with self._lock:
                logger.info(f"Initiating disconnect for client {client_id}")
                
                # Get connection details before cleanup
                details = self.connection_details.get(client_id, {})
                user_id = details.get('user_id')
                node_id = details.get('node_id')
                
                # Stop heartbeat monitoring first
                try:
                    await self.heartbeat_monitor.stop_monitoring(client_id)
                    logger.info(f"Heartbeat monitoring stopped for {client_id}")
                except Exception as e:
                    logger.error(f"Error stopping heartbeat monitoring for {client_id}: {str(e)}")
                
                # Close WebSocket if still open
                websocket = self.active_connections.get(client_id)
                if websocket and websocket.client_state == WebSocketState.CONNECTED:
                    try:
                        await websocket.close(code=code, reason=reason)
                        logger.info(f"WebSocket closed for {client_id}")
                    except Exception as e:
                        logger.error(f"Error closing websocket for {client_id}: {str(e)}")

                # Clean up message queue
                if client_id in self.message_queues:
                    try:
                        # Signal message processing to stop
                        self.message_queues[client_id].put_nowait(None)
                        self.message_queues.pop(client_id, None)
                    except Exception as e:
                        logger.error(f"Error cleaning up message queue for {client_id}: {str(e)}")

                # Update connection tracking
                self.active_connections.pop(client_id, None)
                self.connection_states[client_id] = ConnectionState.DISCONNECTED
                
                # Update user connections
                if user_id and user_id in self.user_connections:
                    self.user_connections[user_id].discard(client_id)
                    if not self.user_connections[user_id]:
                        del self.user_connections[user_id]

                # Clean up metrics and connection details
                self.metrics.pop(client_id, None)
                self.connection_details.pop(client_id, None)
                
                # Release resource manager connection
                if node_id:
                    try:
                        await self.resource_manager.release_connection(client_id)
                        logger.info(f"Released resource manager connection for {client_id}")
                    except Exception as e:
                        logger.error(f"Error releasing resource manager connection: {str(e)}")
                
                logger.info(f"WebSocket disconnected - Client: {client_id}, User: {user_id}")

        except Exception as e:
            logger.error(f"Error in disconnect for {client_id}: {str(e)}")
            # Attempt emergency cleanup
            try:
                await self._cleanup_connection(client_id)
            except Exception as cleanup_error:
                logger.error(f"Emergency cleanup failed for {client_id}: {str(cleanup_error)}")

    async def _process_messages(self, client_id: str) -> None:
        """
        Process messages from the client's message queue.
        Handles both regular messages and heartbeat responses.
        """
        try:
            logger.info(f"Starting message processing for client {client_id}")
            
            while True:
                if client_id not in self.message_queues:
                    logger.info(f"Message queue removed for {client_id}, stopping processing")
                    break
                
                try:
                    queue = self.message_queues[client_id]
                    message = await queue.get()
                    
                    # Check for shutdown signal
                    if message is None:
                        logger.info(f"Received shutdown signal for {client_id}")
                        break
                    
                    try:
                        # Handle Tradovate heartbeat response
                        if isinstance(message, str) and message == '[]':
                            await self.heartbeat_monitor.process_heartbeat_ack(client_id, {
                                'timestamp': datetime.utcnow().timestamp() * 1000
                            })
                            logger.debug(f"Processed heartbeat response for {client_id}")
                            continue
                        
                        # Handle structured messages
                        if isinstance(message, dict):
                            # Process different message types
                            message_type = message.get('type')
                            
                            if message_type == 'heartbeat':
                                await self._handle_heartbeat(client_id, message)
                            elif message_type == 'market_data':
                                await self._route_message(client_id, {
                                    **message,
                                    'timestamp': datetime.utcnow().isoformat()
                                })
                                self.market_data_subject.next(message)
                            elif message_type == 'order_update':
                                await self._route_message(client_id, message)
                                self.order_update_subject.next(message)
                            elif message_type == 'account_update':
                                await self._route_message(client_id, message)
                                self.account_update_subject.next(message)
                            else:
                                await self._route_message(client_id, message)
                                self.message_subject.next(message)
                        
                        # Update metrics
                        details = self.connection_details.get(client_id)
                        if details:
                            details['message_count'] += 1
                            details['last_message'] = datetime.utcnow()
                    
                    except Exception as msg_error:
                        logger.error(f"Error processing message for {client_id}: {str(msg_error)}")
                        # Don't break the loop for individual message errors
                        continue
                    
                    finally:
                        # Always mark the task as done
                        queue.task_done()
                
                except asyncio.CancelledError:
                    logger.info(f"Message processing cancelled for {client_id}")
                    break
                
                except Exception as queue_error:
                    logger.error(f"Queue processing error for {client_id}: {str(queue_error)}")
                    # Short sleep to prevent tight loop in case of persistent errors
                    await asyncio.sleep(0.1)
                    continue
        
        except Exception as e:
            logger.error(f"Fatal error in message processing for {client_id}: {str(e)}")
        
        finally:
            logger.info(f"Message processing stopped for {client_id}")
            # Ensure proper cleanup
            if client_id in self.message_queues:
                try:
                    while not self.message_queues[client_id].empty():
                        await self.message_queues[client_id].get()
                        self.message_queues[client_id].task_done()
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up message queue for {client_id}: {str(cleanup_error)}")

    async def _route_message(self, client_id: str, message: Dict[str, Any]) -> None:
        """
        Route messages to appropriate handlers based on message type.
        """
        try:
            message_type = message.get('type', 'unknown')
            
            if message_type == 'order':
                await self.order_executor.handle_order(client_id, message)
            elif message_type == 'market_data':
                await self.event_handler.handle_market_data(message)
            elif message_type == 'account_update':
                await self.event_handler.handle_account_update(message)
            else:
                logger.debug(f"Unhandled message type received: {message_type}")
                
        except Exception as e:
            logger.error(f"Error routing message: {str(e)}")
            raise

    async def stop_heartbeat(self, client_id: str) -> None:
        """Stop heartbeat monitoring for a connection"""
        task = self.heartbeat_tasks.pop(client_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self, client_id: str) -> None:
        """Heartbeat monitoring loop with failure detection"""
        missed_heartbeats = 0
        
        try:
            while True:
                websocket = self.active_connections.get(client_id)
                if not websocket or websocket.client_state == WebSocketState.DISCONNECTED:
                    break

                try:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": datetime.utcnow().isoformat(),
                        "connection_id": client_id
                    })
                    
                    # Update heartbeat timestamp
                    self.last_heartbeats[client_id] = datetime.utcnow()
                    self.connection_details[client_id]['last_heartbeat'] = datetime.utcnow()
                    missed_heartbeats = 0

                except Exception as e:
                    logger.error(f"Heartbeat error for {client_id}: {str(e)}")
                    missed_heartbeats += 1
                    
                    if missed_heartbeats >= self.config['MAX_MISSED']:
                        logger.warning(f"Too many missed heartbeats for {client_id}, disconnecting")
                        break

                await asyncio.sleep(self.HEARTBEAT_INTERVAL)

        except asyncio.CancelledError:
            logger.info(f"Heartbeat loop cancelled for {client_id}")
        except Exception as e:
            logger.error(f"Error in heartbeat loop for {client_id}: {str(e)}")
        finally:
            await self.disconnect(client_id, code=4000, reason="Heartbeat failure")

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of stale connections"""
        while True:
            try:
                await asyncio.sleep(self.config['CLEANUP_INTERVAL'])
                
                async with self._lock:
                    current_time = datetime.utcnow()
                    
                    for client_id, last_heartbeat in list(self.last_heartbeats.items()):
                        if (current_time - last_heartbeat).total_seconds() > self.HEARTBEAT_INTERVAL * 3:
                            logger.warning(f"Cleaning up stale connection: {client_id}")
                            await self.disconnect(client_id, code=4001, reason="Connection stale")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {str(e)}")
                await asyncio.sleep(5)  # Wait before retrying

    def get_connection_info(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific connection"""
        return {
            **self.connection_details.get(client_id, {}),
            "state": self.connection_states.get(client_id),
            "metrics": self.metrics.get(client_id, HeartbeatMetrics()).get_metrics(),
            "last_heartbeat": self.last_heartbeats.get(client_id)
        }

    def get_user_connections(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all connections for a specific user"""
        connections = []
        for client_id in self.user_connections.get(user_id, set()):
            connection_info = self.get_connection_info(client_id)
            if connection_info:
                connections.append(connection_info)
        return connections

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive WebSocket manager status"""
        return {
            "active_connections": len(self.active_connections),
            "user_count": len(self.user_connections),
            "initialized": self._initialized,
            "monitoring_active": self.monitoring_service.is_running(),
            "connection_states": self.connection_states.copy(),
            "metrics": {
                "total_messages": sum(
                    details.get('message_count', 0) 
                    for details in self.connection_details.values()
                ),
                "active_heartbeats": len(self.heartbeat_tasks),
                "monitoring_stats": self.monitoring_service.get_stats()
            }
        }

    async def cleanup(self) -> None:
        """Cleanup all WebSocket manager resources"""
        try:
            async with self._lock:
                # Stop monitoring service
                await self.monitoring_service.stop()

                # Cancel cleanup task
                if self._cleanup_task:
                    self._cleanup_task.cancel()
                    try:
                        await self._cleanup_task
                    except asyncio.CancelledError:
                        pass

                # Disconnect all clients
                for client_id in list(self.active_connections.keys()):
                    await self.disconnect(client_id, code=1001, reason="Server shutdown")

                # Clear all collections
                self.active_connections.clear()
                self.connection_states.clear()
                self.connection_details.clear()
                self.metrics.clear()
                self.message_queues.clear()
                self.pending_messages.clear()
                self.user_connections.clear()
                
                self._initialized = False
                logger.info("WebSocket manager cleaned up successfully")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

# Create singleton instance
websocket_manager = WebSocketManager()