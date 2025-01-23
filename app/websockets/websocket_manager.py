from typing import Dict, Optional, Set, Any
from datetime import datetime
import asyncio
import logging
from starlette.websockets import WebSocket, WebSocketState

# Local imports
from .websocket_config import WebSocketConfig
from .heartbeat_monitor import heartbeat_monitor
from .metrics import HeartbeatMetrics
from .scaling.resource_manager import resource_manager
from .monitoring.monitor import MonitoringService
from .handlers.endpoint_handlers import TradovateEndpointHandler
from .handlers.event_handlers import TradovateEventHandler
from .handlers.webhook_handlers import TradovateWebhookHandler
from .handlers.order_executor import TradovateOrderExecutor
from ..core.config import settings

logger = logging.getLogger(__name__)

class WebSocketManager:
    """
    Manages WebSocket connections, heartbeats, and message handling.
    Implements connection pooling, heartbeat monitoring, and error recovery.
    """
    def __init__(self):
        # Connection management
        self.connections: Dict[str, WebSocket] = {}
        self.connection_states: Dict[str, str] = {}
        self.metrics: Dict[str, HeartbeatMetrics] = {}
        
        # Configuration
        self.config = WebSocketConfig.HEARTBEAT
        self.is_initialized = False
        
        # Message handling
        self.message_queue: Dict[str, asyncio.Queue] = {}
        self.pending_messages: Dict[str, Set[str]] = {}
        
        # Connection tracking
        self.reconnect_attempts: Dict[str, int] = {}
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.HEARTBEAT_INTERVAL = 30  # seconds
        self.CONNECTION_TIMEOUT = 10  # seconds
        
        # Circuit breaker pattern
        self.circuit_breakers: Dict[str, Dict[str, Any]] = {}
        
        # Background tasks
        self.cleanup_task: Optional[asyncio.Task] = None
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}
        self.resource_manager = resource_manager
        

    async def initialize(self) -> bool:
        """Initialize the WebSocket manager"""
        try:
            if self.is_initialized:
                logger.info("WebSocket manager already initialized")
                return True

            logger.info("Initializing WebSocket manager...")
            
            # Clear any existing connections
            await self.cleanup()
            
            # Start cleanup task
            self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
            
            self.is_initialized = True
            logger.info("WebSocket manager initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize WebSocket manager: {str(e)}")
            return False

    
    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
    ) -> bool:
        """Establish new WebSocket connection"""
        try:
            # Store connection info without locking first
            self.active_connections[client_id] = websocket
            
            # Initialize connection details
            self.connection_details[client_id] = {
                'connected_at': datetime.utcnow(),
                'last_heartbeat': datetime.utcnow(),
                'message_count': 0,
                'state': 'connected'
            }
            
            # Initialize metrics
            self.metrics[client_id] = HeartbeatMetrics()
            
            logger.info(f"New WebSocket connection established: {client_id}")
            return True

        except Exception as e:
            logger.error(f"Error establishing connection: {str(e)}")
            # Clean up if there was an error
            self.active_connections.pop(client_id, None)
            self.connection_details.pop(client_id, None)
            self.metrics.pop(client_id, None)
            return False

    async def disconnect(self, client_id: str) -> None:
        """Clean up connection resources"""
        try:
            # Simple cleanup without trying to close the socket
            self.active_connections.pop(client_id, None)
            self.connection_details.pop(client_id, None)
            self.metrics.pop(client_id, None)
            logger.info(f"Cleaned up connection: {client_id}")
        except Exception as e:
            logger.error(f"Error in disconnect: {str(e)}")

        async def handle_message(self, account_id: str, message: Dict[str, Any]) -> None:
            """Handle incoming messages"""
            try:
                if account_id not in self.connections:
                    logger.error(f"No connection found for account {account_id}")
                    return

                websocket = self.connections[account_id]
                message_type = message.get('type')

                if message_type == 'heartbeat':
                    await self.handle_heartbeat(account_id)
                else:
                    # Queue message for processing
                    await self.message_queue[account_id].put(message)
                    
                    # Process queued messages
                    await self._process_message_queue(account_id)

            except Exception as e:
                logger.error(f"Error handling message: {str(e)}")
                await self._handle_message_error(account_id, e)

    async def handle_heartbeat(self, account_id: str) -> bool:
        """Handle heartbeat message from client"""
        try:
            if account_id not in self.connections:
                logger.error(f"No connection found for account {account_id}")
                return False

            metrics = self.metrics.get(account_id)
            if not metrics:
                metrics = HeartbeatMetrics()
                self.metrics[account_id] = metrics

            # Record heartbeat
            await metrics.record_heartbeat()
            
            # Reset circuit breaker on successful heartbeat
            self.circuit_breakers[account_id]['failures'] = 0
            self.circuit_breakers[account_id]['status'] = 'closed'

            return True

        except Exception as e:
            logger.error(f"Error handling heartbeat for account {account_id}: {str(e)}")
            await self._handle_heartbeat_error(account_id, e)
            return False

    async def _handle_heartbeat_error(self, account_id: str, error: Exception) -> None:
        """Handle heartbeat errors"""
        try:
            metrics = self.metrics.get(account_id)
            if metrics:
                missed = await metrics.record_missed()
                
                # Update circuit breaker
                breaker = self.circuit_breakers[account_id]
                breaker['failures'] += 1
                breaker['last_failure'] = datetime.utcnow()
                
                if breaker['failures'] >= self.config['MAX_MISSED']:
                    breaker['status'] = 'open'
                    await self.disconnect(account_id)

        except Exception as e:
            logger.error(f"Error handling heartbeat error: {str(e)}")

    async def _heartbeat_loop(self, account_id: str) -> None:
        """Heartbeat monitoring loop for a connection"""
        try:
            while True:
                try:
                    websocket = self.connections.get(account_id)
                    if not websocket:
                        break

                    try:
                        # Send heartbeat
                        await websocket.send_json({
                            "type": "heartbeat",
                            "timestamp": datetime.utcnow().isoformat()
                        })

                        # Update metrics
                        metrics = self.metrics[account_id]
                        metrics.totalHeartbeats += 1
                        metrics.lastHeartbeat = datetime.utcnow()

                    except RuntimeError:
                        # Socket is closed or closing
                        break
                    except Exception as send_error:
                        logger.error(f"Error sending heartbeat to {account_id}: {str(send_error)}")
                        await self._handle_heartbeat_error(account_id, send_error)
                        continue

                    # Wait for next interval
                    await asyncio.sleep(self.HEARTBEAT_INTERVAL)

                except Exception as e:
                    logger.error(f"Error in heartbeat loop: {str(e)}")
                    await self._handle_heartbeat_error(account_id, e)

        except asyncio.CancelledError:
            logger.info(f"Heartbeat loop cancelled for account {account_id}")
        except Exception as e:
            logger.error(f"Heartbeat loop error: {str(e)}")
        finally:
            await self.disconnect(account_id)

    async def _process_message_queue(self, account_id: str) -> None:
        """Process queued messages for an account"""
        while True:
            try:
                # Get next message
                message = await self.message_queue[account_id].get()
                
                # Process message
                websocket = self.connections.get(account_id)
                if websocket:
                    try:
                        await websocket.send_json({
                            "type": "message_processed",
                            "original_message": message,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                    except RuntimeError:
                        # Socket is closed or closing
                        break
                    except Exception as send_error:
                        logger.error(f"Error sending message to {account_id}: {str(send_error)}")
                        break

            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.error(f"Error processing message queue: {str(e)}")
                break

    async def _periodic_cleanup(self) -> None:
        """Periodic cleanup of dead connections"""
        while True:
            try:
                current_time = datetime.utcnow()
                
                for account_id in list(self.connections.keys()):
                    try:
                        metrics = self.metrics.get(account_id)
                        if not metrics:
                            continue
                            
                        # Check last heartbeat
                        if metrics.lastHeartbeat:
                            time_since_heartbeat = (current_time - metrics.lastHeartbeat).total_seconds()
                            if time_since_heartbeat > self.config['INTERVAL'] * 2:
                                logger.warning(f"No heartbeat received for {time_since_heartbeat}s from {account_id}")
                                await self.disconnect(account_id)

                    except Exception as e:
                        logger.error(f"Error cleaning up connection {account_id}: {str(e)}")

                await asyncio.sleep(self.config['CLEANUP_INTERVAL'])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {str(e)}")
                await asyncio.sleep(60)  # Wait before retrying

    async def cleanup(self) -> None:
        """Cleanup all connections and resources"""
        try:
            # Cancel cleanup task
            if self.cleanup_task:
                self.cleanup_task.cancel()
                self.cleanup_task = None

            # Disconnect all connections
            for account_id in list(self.connections.keys()):
                await self.disconnect(account_id)

            # Clear all collections
            self.connections.clear()
            self.connection_states.clear()
            self.metrics.clear()
            self.message_queue.clear()
            self.pending_messages.clear()
            self.circuit_breakers.clear()
            self.reconnect_attempts.clear()
            self.heartbeat_tasks.clear()

            self.is_initialized = False
            logger.info("WebSocket manager cleaned up successfully")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    def get_connection_stats(self, account_id: str) -> Dict[str, Any]:
        """Get connection statistics"""
        return {
            "connection_state": self.connection_states.get(account_id),
            "metrics": self.metrics.get(account_id),
            "circuit_breaker": self.circuit_breakers.get(account_id),
            "reconnect_attempts": self.reconnect_attempts.get(account_id, 0),
            "pending_messages": len(self.pending_messages.get(account_id, set())),
            "queued_messages": self.message_queue.get(account_id, asyncio.Queue()).qsize() if account_id in self.message_queue else 0
        }

    def get_status(self) -> Dict[str, Any]:
        """Get overall manager status"""
        return {
            "active_connections": len(self.connections),
            "initialized": self.is_initialized,
            "cleanup_task_running": bool(self.cleanup_task and not self.cleanup_task.done()),
            "total_pending_messages": sum(len(msgs) for msgs in self.pending_messages.values()),
            "total_queued_messages": sum(queue.qsize() for queue in self.message_queue.values())
        }

# Create singleton instance
websocket_manager = WebSocketManager()