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
from .monitoring.monitor import MonitoringService
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
    def __init__(self):
        # Connection Management
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_states: Dict[str, str] = {}
        self.user_connections: Dict[int, Set[str]] = {}
        self.connection_details: Dict[str, Dict[str, Any]] = {}
        
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
        self.last_message_times: Dict[str, float] = {}
        
        # State Management
        self._initialized = False
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self.is_accepted: Dict[str, bool] = {}
        
        # Configuration
        self.config = WebSocketConfig.HEARTBEAT
        self.MAX_RECONNECT_ATTEMPTS = 5
        self.CONNECTION_TIMEOUT = 10  # seconds
        self.MAX_CONNECTIONS_PER_USER = 5
        self.HEARTBEAT_THRESHOLD = 2500  # 2.5 seconds in milliseconds

    async def initialize(self) -> bool:
        """Initialize the WebSocket manager and its dependencies"""
        if self._initialized:
            return True

        try:
            async with self._lock:
                logger.info("Initializing WebSocket manager...")
                
                # Initialize message queues and state tracking
                self.active_connections = {}
                self.connection_states = {}
                self.connection_details = {}
                self.message_queues = {}
                
                # Start monitoring service
                await self.monitoring_service.start()
                logger.info("Monitoring service started")

                # Start background cleanup task
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                logger.info("Cleanup task started")
                
                self._initialized = True
                logger.info("WebSocket manager initialized successfully")
                return True

        except Exception as e:
            logger.error(f"Failed to initialize WebSocket manager: {str(e)}")
            await self.cleanup()
            return False

    async def connect(self, websocket: WebSocket, client_id: str, user_id: Optional[int] = None) -> bool:
        """Accept and initialize a new WebSocket connection"""
        try:
            # Don't try to accept again, just track the connection
            self.active_connections[client_id] = websocket
            self.connection_states[client_id] = ConnectionState.CONNECTED
            self.is_accepted[client_id] = True
            
            if user_id:
                if user_id not in self.user_connections:
                    self.user_connections[user_id] = set()
                self.user_connections[user_id].add(client_id)
            
            self.connection_details[client_id] = {
                'connected_at': datetime.utcnow(),
                'user_id': user_id,
                'last_message': datetime.utcnow(),
                'message_count': 0
            }

            logger.info(f"WebSocket connected - Client: {client_id}, User: {user_id}")
            return True
                
        except Exception as e:
            logger.error(f"Connection error: {str(e)}")
            return False

    async def disconnect(self, client_id: str) -> None:
        """Handle WebSocket disconnection and cleanup"""
        try:
            ws = self.active_connections.get(client_id)
            if ws and ws.client_state == WebSocketState.CONNECTED:
                await ws.close()

            self.active_connections.pop(client_id, None)
            self.connection_states.pop(client_id, None)
            self.is_accepted.pop(client_id, None)  # Clean up acceptance tracking
            
            # Clean up user connections
            user_id = self.connection_details.get(client_id, {}).get('user_id')
            if user_id and user_id in self.user_connections:
                self.user_connections[user_id].discard(client_id)
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]

            self.connection_details.pop(client_id, None)
            
            logger.info(f"WebSocket disconnected - Client: {client_id}")

        except Exception as e:
            logger.error(f"Error in disconnect: {str(e)}")

    async def process_message(self, client_id: str, message: str) -> None:
        """Process incoming WebSocket messages"""
        if client_id not in self.message_queues:
            logger.warning(f"No message queue for client {client_id}")
            return

        try:
            # Update last message time
            current_time = datetime.utcnow().timestamp() * 1000
            self.last_message_times[client_id] = current_time
            
            # Handle heartbeat message
            if message == '[]':
                if client_id in self.metrics:
                    await self.metrics[client_id].record_heartbeat()
                return
            
            # Process non-heartbeat message
            await self.message_queues[client_id].put(message)
            
            # Update message stats
            if client_id in self.connection_details:
                self.connection_details[client_id]['message_count'] += 1
                self.connection_details[client_id]['last_message'] = datetime.utcnow()
                
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of stale connections"""
        while True:
            try:
                await asyncio.sleep(60)  # Run cleanup every minute
                
                current_time = datetime.utcnow().timestamp() * 1000
                
                for client_id, last_time in list(self.last_message_times.items()):
                    time_since_last = current_time - last_time
                    
                    # Check for stale connections (no messages for 7.5 seconds - 3 missed heartbeats)
                    if time_since_last > (self.HEARTBEAT_THRESHOLD * 3):
                        logger.warning(f"Stale connection detected for {client_id}")
                        await self.disconnect(
                            client_id,
                            code=4000,
                            reason="Connection stale - no heartbeat"
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {str(e)}")
                await asyncio.sleep(5)  # Wait before retrying

    def get_connection_info(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific connection"""
        metrics = self.metrics.get(client_id)
        return {
            "status": self.connection_states.get(client_id),
            "details": self.connection_details.get(client_id),
            "metrics": metrics.get_metrics() if metrics else None,
            "last_message": self.last_message_times.get(client_id)
        }

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive WebSocket manager status"""
        return {
            "active_connections": len(self.active_connections),
            "user_count": len(self.user_connections),
            "initialized": self._initialized,
            "monitoring_active": self.monitoring_service.is_running(),
            "connection_states": self.connection_states.copy()
        }

    async def cleanup(self) -> None:
        """Cleanup all WebSocket manager resources"""
        try:
            async with self._lock:
                logger.info("Cleaning up WebSocket manager...")
                
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
                    await self.disconnect(
                        client_id,
                        code=1001,
                        reason="Server shutdown"
                    )

                # Clear all collections
                self.active_connections.clear()
                self.connection_states.clear()
                self.user_connections.clear()
                self.connection_details.clear()
                self.message_queues.clear()
                self.metrics.clear()
                self.last_message_times.clear()
                
                self._initialized = False
                logger.info("WebSocket manager cleaned up successfully")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

# Create singleton instance
websocket_manager = WebSocketManager()