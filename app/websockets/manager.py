from typing import Dict, Set, Optional, Any
import logging
import asyncio
from datetime import datetime
from fastapi import WebSocket
from enum import Enum

# Import new WebSocket components
from .handlers.endpoint_handlers import TradovateEndpointHandler
from .handlers.event_handlers import TradovateEventHandler
from .handlers.webhook_handlers import TradovateWebhookHandler
from .handlers.order_executor import TradovateOrderExecutor
from .monitoring.monitor import MonitoringService
from .scaling.resource_manager import ResourceManager
from app.websockets.metrics import HeartbeatMetrics
from app.websockets.heartbeat_monitor import heartbeat_monitor
from .errors import WebSocketError, handle_websocket_error
from .scaling.resource_manager import ResourceManager

logger = logging.getLogger(__name__)

class WebSocketState(str, Enum):
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"

class WebSocketManager:
    """
    WebSocket manager that bridges old and new implementations.
    Maintains backward compatibility while using new features.
    """
    
    def __init__(self):
        # Initialize new components
        self.resource_manager = ResourceManager()
        self.monitoring_service = MonitoringService()
        self.heartbeat_monitor = heartbeat_monitor
        self.order_executor = TradovateOrderExecutor()
        self.event_handler = TradovateEventHandler()
        self.endpoint_handler = TradovateEndpointHandler(
            config={
                "path": "/ws/tradovate",
                "auth_required": True
            }
        )
        
        # Maintain compatibility with old implementation
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_tokens: Dict[str, str] = {}
        self.user_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the WebSocket manager"""
        if self._initialized:
            return True

        try:
            await self.resource_manager.initialize()
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize WebSocket manager: {str(e)}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get current WebSocket manager status."""
        return {
            "active_connections": len(self.active_connections),
            "user_connections": len(self.user_connections),
            "monitoring_active": self._initialized and self.monitoring_service.is_running(),
            "initialized": self._initialized
        }

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,  # Changed from account_id
    ) -> bool:
        """
        Establish new WebSocket connection
        
        Args:
            websocket: The WebSocket connection
            client_id: Unique identifier for the client
            
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            async with self._lock:
                # Store connection info
                self.active_connections[client_id] = websocket
                
                # Initialize connection details
                self.connection_details[client_id] = {
                    'connected_at': datetime.utcnow(),
                    'last_heartbeat': datetime.utcnow(),
                    'message_count': 0
                }
                
                # Initialize metrics
                self.metrics[client_id] = HeartbeatMetrics()
                
                logger.info(f"New WebSocket connection established: {client_id}")
                return True

        except Exception as e:
            logger.error(f"Error establishing connection: {str(e)}")
            return False
        
    async def disconnect(self, client_id: str) -> None:
        """Clean up connection resources"""
        try:
            async with self._lock:
                if client_id in self.active_connections:
                    websocket = self.active_connections[client_id]
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.close()
                    
                    # Cleanup all resources
                    self.active_connections.pop(client_id, None)
                    self.connection_details.pop(client_id, None)
                    self.metrics.pop(client_id, None)
                    
                    # Release from resource manager
                    await self.resource_manager.release_connection(client_id)
                    
                    logger.info(f"Cleaned up connection: {client_id}")

        except Exception as e:
            logger.error(f"Error in disconnect: {str(e)}")

    async def update_heartbeat(self, client_id: str) -> bool:
        """Update last heartbeat time for a connection"""
        try:
            if client_id in self.connection_details:
                self.connection_details[client_id]["last_heartbeat"] = datetime.utcnow()
                return True
            return False
        except Exception as e:
            logger.error(f"Error updating heartbeat: {str(e)}")
            return False

    # UPDATE: Add method to broadcast messages
    async def broadcast_message(self, message: Dict[str, Any], exclude: Optional[str] = None) -> None:
        """Broadcast message to all connections except excluded one"""
        disconnected = []
        for client_id, websocket in self.active_connections.items():
            if client_id != exclude:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to {client_id}: {str(e)}")
                    disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            await self.disconnect(client_id)

    def get_connection_status(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific connection"""
        if client_id not in self.connection_details:
            return None
            
        details = self.connection_details[client_id]
        metrics = self.metrics.get(client_id)
        
        return {
            "connected_at": details["connected_at"].isoformat(),
            "last_heartbeat": details["last_heartbeat"].isoformat(),
            "message_count": details["message_count"],
            "metrics": metrics.get_metrics() if metrics else None
        }

    # NEW: Add method to get overall status
    def get_status(self) -> Dict[str, Any]:
        """Get overall WebSocket manager status"""
        return {
            "active_connections": len(self.active_connections),
            "initialized": self._initialized,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def send_personal_message(self, message: Any, websocket: WebSocket):
        """Send a message to a specific WebSocket connection."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {str(e)}")
            await self.disconnect(websocket)

    async def broadcast(self, message: Any):
        """Broadcast a message to all active connections."""
        disconnected = []
        
        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {connection_id}: {str(e)}")
                disconnected.append(websocket)

        # Clean up disconnected websockets
        for websocket in disconnected:
            await self.disconnect(websocket)

    async def send_to_user(self, user_id: str, message: Any):
        """Send a message to all connections of a specific user."""
        if user_id in self.user_connections:
            disconnected = []
            
            for websocket in self.user_connections[user_id]:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending to user {user_id}: {str(e)}")
                    disconnected.append(websocket)

            # Clean up disconnected websockets
            for websocket in disconnected:
                await self.disconnect(websocket)

    async def associate_user(self, user_id: str, websocket: WebSocket, token: str):
        """Associate a WebSocket connection with a user."""
        async with self._lock:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = set()
            
            self.user_connections[user_id].add(websocket)
            self.connection_tokens[str(id(websocket))] = token
            
            logger.info(f"Associated user {user_id} with WebSocket")

    async def cleanup(self):
        """Clean up resources and close all connections."""
        try:
            # Stop monitoring service
            if self._initialized:
                await self.monitoring_service.stop()

            # Close all connections
            async with self._lock:
                for websocket in self.active_connections.values():
                    await websocket.close()
                
                self.active_connections.clear()
                self.connection_tokens.clear()
                self.user_connections.clear()

            self._initialized = False
            logger.info("WebSocket manager cleaned up successfully")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    async def shutdown(self):
        """Shutdown the WebSocket manager."""
        await self.cleanup()

# Create a singleton instance
websocket_manager = WebSocketManager()