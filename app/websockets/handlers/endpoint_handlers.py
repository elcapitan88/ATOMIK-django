from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable, Union
from datetime import datetime
import logging
import asyncio
from enum import Enum
import json

logger = logging.getLogger(__name__)

class EndpointConfig:
    """Configuration for a WebSocket endpoint."""
    def __init__(
        self,
        path: str,
        auth_required: bool = True,
        rate_limit: int = 100,
        timeout: float = 30.0,
        retry_attempts: int = 3,
        backoff_factor: float = 1.5
    ):
        self.path = path
        self.auth_required = auth_required
        self.rate_limit = rate_limit
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.backoff_factor = backoff_factor

class BaseEndpointHandler(ABC):
    """Abstract base class for WebSocket endpoint handlers."""
    
    def __init__(self, config: Dict[str, Any]):
        # Convert dictionary config to EndpointConfig object
        self.config = EndpointConfig(
            path=config.get("path", "/ws"),
            auth_required=config.get("auth_required", True),
            rate_limit=config.get("rate_limit", 100),
            timeout=config.get("timeout", 30.0),
            retry_attempts=config.get("retry_attempts", 3),
            backoff_factor=config.get("backoff_factor", 1.5)
        )
        self._active_connections: Dict[str, Any] = {}
        self._message_handlers: Dict[str, Callable] = {}
        self._rate_limiter = asyncio.Semaphore(self.config.rate_limit)

    @abstractmethod
    async def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """Authenticate the connection."""
        pass

    @abstractmethod
    async def handle_message(self, message: Dict[str, Any], connection_id: str) -> Dict[str, Any]:
        """Process incoming WebSocket messages."""
        pass

    async def handle_market_data(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle market data messages."""
        return await self._handle_market_data(message)

    async def _handle_market_data(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process market data messages."""
        return {'status': 'processed', 'type': 'market_data'}

    async def connect(self, connection_id: str, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Establish a new WebSocket connection."""
        try:
            if self.config.auth_required and not await self.authenticate(credentials):
                logger.warning(f"Authentication failed for connection {connection_id}")
                return False

            self._active_connections[connection_id] = {
                'connected_at': datetime.utcnow(),
                'last_message': None,
                'message_count': 0
            }
            logger.info(f"New connection established: {connection_id}")
            return True

        except Exception as e:
            logger.error(f"Connection error for {connection_id}: {str(e)}")
            return False

    async def disconnect(self, connection_id: str) -> None:
        """Handle connection termination."""
        if connection_id in self._active_connections:
            del self._active_connections[connection_id]
            logger.info(f"Connection closed: {connection_id}")

    async def send_message(self, message: Dict[str, Any], connection_id: str) -> None:
        """Send message with rate limiting."""
        async with self._rate_limiter:
            await self._send_message(message, connection_id)

    async def _send_message(self, message: Dict[str, Any], connection_id: str) -> None:
        """Implement actual message sending logic."""
        if connection_id not in self._active_connections:
            raise ValueError(f"Invalid connection ID: {connection_id}")
        logger.debug(f"Sending message to {connection_id}: {json.dumps(message)}")

    def register_message_handler(self, message_type: str, handler: Callable) -> None:
        """Register a handler for a specific message type."""
        self._message_handlers[message_type] = handler
        logger.info(f"Registered handler for message type: {message_type}")

class TradovateEndpointHandler(BaseEndpointHandler):
    """Tradovate-specific implementation of the endpoint handler."""
    
    async def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """Implement Tradovate-specific authentication."""
        try:
            access_token = credentials.get('access_token')
            if not access_token:
                return False
            return True
        except Exception as e:
            logger.error(f"Tradovate authentication error: {str(e)}")
            return False

    async def handle_message(self, message: Dict[str, Any], connection_id: str) -> Dict[str, Any]:
        """Handle Tradovate-specific message formats."""
        try:
            internal_message = self._transform_message(message)
            
            if internal_message['type'] == 'market_data':
                return await self.handle_market_data(internal_message)
            elif internal_message['type'] == 'order_update':
                return await self._handle_order_update(internal_message)
            else:
                logger.warning(f"Unknown message type: {internal_message['type']}")
                return {'error': 'Unknown message type'}
                
        except Exception as e:
            logger.error(f"Error handling Tradovate message: {str(e)}")
            return {'error': str(e)}

    def _transform_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Tradovate message format to internal format."""
        return {
            'type': message.get('e', 'unknown'),
            'timestamp': datetime.utcnow().isoformat(),
            'data': message.get('d', {}),
            'sequence': message.get('s', 0)
        }

    async def _handle_order_update(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process Tradovate order update messages."""
        return {'status': 'processed', 'type': 'order_update'}