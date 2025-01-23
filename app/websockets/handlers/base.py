from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging
import asyncio
from enum import Enum

logger = logging.getLogger(__name__)

class WSConnectionStatus(str, Enum):
    """WebSocket connection status enum"""
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"

class WSMessageType(str, Enum):
    """WebSocket message type enum"""
    MARKET_DATA = "MARKET_DATA"
    ORDER_UPDATE = "ORDER_UPDATE"
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    AUTH = "AUTH"
    SUBSCRIPTION = "SUBSCRIPTION"

class BrokerWebSocketHandler(ABC):
    """
    Abstract base class for broker-specific WebSocket handlers.
    All broker implementations must inherit from this class and implement its methods.
    """

    def __init__(self):
        """Initialize the handler with basic attributes"""
        self.status: WSConnectionStatus = WSConnectionStatus.DISCONNECTED
        self.last_heartbeat: Optional[datetime] = None
        self.subscribed_symbols: set[str] = set()
        self.connection_id: Optional[str] = None
        self.user_id: Optional[int] = None
        self.error_count: int = 0
        self.max_errors: int = 3
        self.reconnect_attempts: int = 0
        self.max_reconnect_attempts: int = 5

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to the broker's WebSocket API.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """
        Disconnect from the broker's WebSocket API.
        
        Returns:
            bool: True if disconnect successful, False otherwise
        """
        pass

    @abstractmethod
    async def reconnect(self) -> bool:
        """
        Attempt to reconnect to the broker's WebSocket API.
        
        Returns:
            bool: True if reconnection successful, False otherwise
        """
        pass

    @abstractmethod
    async def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """
        Authenticate with the broker's WebSocket API.
        
        Args:
            credentials: Dictionary containing authentication credentials
            
        Returns:
            bool: True if authentication successful, False otherwise
        """
        pass

    @abstractmethod
    async def subscribe(self, symbols: List[str]) -> bool:
        """
        Subscribe to market data for specified symbols.
        
        Args:
            symbols: List of symbols to subscribe to
            
        Returns:
            bool: True if subscription successful, False otherwise
        """
        pass

    @abstractmethod
    async def unsubscribe(self, symbols: List[str]) -> bool:
        """
        Unsubscribe from market data for specified symbols.
        
        Args:
            symbols: List of symbols to unsubscribe from
            
        Returns:
            bool: True if unsubscription successful, False otherwise
        """
        pass

    @abstractmethod
    async def send_message(self, message: Dict[str, Any]) -> bool:
        """
        Send a message to the broker's WebSocket API.
        
        Args:
            message: Message to send
            
        Returns:
            bool: True if message sent successfully, False otherwise
        """
        pass

    @abstractmethod
    async def handle_message(self, message: Dict[str, Any]) -> None:
        """
        Handle incoming messages from the broker's WebSocket API.
        
        Args:
            message: Received message to handle
        """
        pass

    @abstractmethod
    async def handle_error(self, error: Exception) -> None:
        """
        Handle WebSocket errors.
        
        Args:
            error: Exception that occurred
        """
        pass

    @abstractmethod
    async def send_heartbeat(self) -> bool:
        """
        Send heartbeat message to maintain connection.
        
        Returns:
            bool: True if heartbeat sent successfully, False otherwise
        """
        pass

    @abstractmethod
    async def process_market_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and normalize market data messages.
        
        Args:
            data: Raw market data from broker
            
        Returns:
            Dict[str, Any]: Normalized market data
        """
        pass

    @abstractmethod
    async def process_order_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and normalize order update messages.
        
        Args:
            data: Raw order update from broker
            
        Returns:
            Dict[str, Any]: Normalized order update
        """
        pass

    @abstractmethod
    async def process_account_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and normalize account update messages.
        
        Args:
            data: Raw account update from broker
            
        Returns:
            Dict[str, Any]: Normalized account update
        """
        pass

    # Utility methods that can be used by all implementations
    def is_connected(self) -> bool:
        """Check if the WebSocket connection is active"""
        return self.status == WSConnectionStatus.CONNECTED

    def get_status(self) -> WSConnectionStatus:
        """Get current connection status"""
        return self.status

    def reset_error_count(self) -> None:
        """Reset the error counter"""
        self.error_count = 0

    def increment_error_count(self) -> None:
        """Increment the error counter"""
        self.error_count += 1

    def should_reconnect(self) -> bool:
        """Determine if reconnection should be attempted"""
        return (
            self.reconnect_attempts < self.max_reconnect_attempts
            and self.status != WSConnectionStatus.CONNECTED
        )

    def update_heartbeat(self) -> None:
        """Update the last heartbeat timestamp"""
        self.last_heartbeat = datetime.utcnow()

    def check_connection_health(self) -> bool:
        """
        Check if the connection is healthy based on heartbeat and error count.
        
        Returns:
            bool: True if connection is healthy, False otherwise
        """
        if not self.last_heartbeat:
            return False

        # Check if we've exceeded error threshold
        if self.error_count >= self.max_errors:
            return False

        # Check if heartbeat is too old (more than 30 seconds)
        heartbeat_age = (datetime.utcnow() - self.last_heartbeat).total_seconds()
        return heartbeat_age <= 30

    async def cleanup(self) -> None:
        """Cleanup resources and reset state"""
        self.status = WSConnectionStatus.DISCONNECTED
        self.last_heartbeat = None
        self.subscribed_symbols.clear()
        self.error_count = 0
        self.reconnect_attempts = 0
        logger.info(f"Cleaned up WebSocket handler state for connection {self.connection_id}")