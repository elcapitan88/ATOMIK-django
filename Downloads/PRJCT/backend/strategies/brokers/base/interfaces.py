from abc import ABC, abstractmethod
from typing import Dict, List, Union, Any, TypeVar, Generic, Optional
from datetime import datetime
from decimal import Decimal

from .types import (
    OrderRequest,
    OrderResponse,
    PositionData,
    PositionUpdate,
    MarketData,
    AccountData,
    WebSocketMessage,
    WebSocketConfig,
    BrokerCredentials,
    OrderStatus,
    AccountUpdate,
    TradeUpdate,
    AccountBalance,
    OrderSide,
    OrderType,
    Position
)
from .exceptions import (
    BrokerBaseException,
    BrokerConnectionError,
    BrokerAuthenticationError,
    OrderValidationError
)

T = TypeVar('T')

class IConnectionManager(ABC):
    """Interface for managing broker connections."""

    @abstractmethod
    async def connect(self, credentials: BrokerCredentials) -> bool:
        """
        Establish connection with broker.
        
        Args:
            credentials: Broker authentication credentials
            
        Returns:
            bool: True if connection successful
            
        Raises:
            BrokerConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Close broker connection and cleanup resources.
        
        Raises:
            BrokerConnectionError: If disconnection fails
        """
        pass

    @abstractmethod
    async def check_connection(self) -> bool:
        """
        Check if connection is healthy.
        
        Returns:
            bool: True if connection is healthy
        """
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """
        Get current connection status.
        
        Returns:
            bool: True if connected
        """
        pass

    @abstractmethod
    async def reconnect(self) -> bool:
        """
        Attempt to reconnect to broker.
        
        Returns:
            bool: True if reconnection successful
        """
        pass

class IWebSocketClient(ABC):
    """Interface for broker WebSocket operations."""

    @abstractmethod
    async def subscribe_market_data(self, symbols: List[str]) -> None:
        """
        Subscribe to market data for symbols.
        
        Args:
            symbols: List of trading symbols
            
        Raises:
            BrokerConnectionError: If subscription fails
        """
        pass

    @abstractmethod
    async def unsubscribe_market_data(self, symbols: List[str]) -> None:
        """
        Unsubscribe from market data.
        
        Args:
            symbols: List of symbols to unsubscribe from
        """
        pass

    @abstractmethod
    async def subscribe_account_updates(self, account_id: str) -> None:
        """
        Subscribe to account updates.
        
        Args:
            account_id: Trading account identifier
        """
        pass

    @abstractmethod
    async def subscribe_positions(self, account_id: str) -> None:
        """
        Subscribe to position updates.
        
        Args:
            account_id: Trading account identifier
        """
        pass

    @abstractmethod
    async def subscribe_orders(self, account_id: str) -> None:
        """
        Subscribe to order updates.
        
        Args:
            account_id: Trading account identifier
        """
        pass

    @abstractmethod
    async def process_message(self, message: WebSocketMessage) -> None:
        """
        Process incoming WebSocket message.
        
        Args:
            message: Message to process
        """
        pass

class ITrading(ABC):
    """Interface for trading operations."""

    @abstractmethod
    async def place_order(
        self,
        account_id: str,
        symbol: str,
        side: OrderSide,
        quantity: Union[int, Decimal],
        order_type: OrderType,
        price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        time_in_force: Optional[str] = None,
        **kwargs: Any
    ) -> OrderResponse:
        """
        Place a new trading order.
        
        Args:
            account_id: Trading account identifier
            symbol: Trading symbol
            side: Order side (buy/sell)
            quantity: Order quantity
            order_type: Type of order
            price: Optional limit price
            stop_price: Optional stop price
            time_in_force: Optional time in force
            **kwargs: Additional broker-specific parameters
            
        Returns:
            OrderResponse containing order details
            
        Raises:
            OrderValidationError: If order parameters are invalid
        """
        pass

    @abstractmethod
    async def cancel_order(self, account_id: str, order_id: str) -> bool:
        """
        Cancel an existing order.
        
        Args:
            account_id: Trading account identifier
            order_id: Order to cancel
            
        Returns:
            bool: True if cancellation successful
        """
        pass

    @abstractmethod
    async def get_order_status(self, account_id: str, order_id: str) -> OrderStatus:
        """
        Get current status of an order.
        
        Args:
            account_id: Trading account identifier
            order_id: Order to check
            
        Returns:
            Current order status
        """
        pass

    @abstractmethod
    async def get_orders(
        self,
        account_id: str,
        status: Optional[OrderStatus] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> List[OrderResponse]:
        """
        Get orders for an account.
        
        Args:
            account_id: Trading account identifier
            status: Optional filter by status
            from_date: Optional start date
            to_date: Optional end date
            
        Returns:
            List of orders matching criteria
        """
        pass

class IDataProvider(ABC):
    """Interface for market and account data operations."""

    @abstractmethod
    async def get_positions(self, account_id: str) -> List[Position]:
        """
        Get current positions.
        
        Args:
            account_id: Trading account identifier
            
        Returns:
            List of current positions
        """
        pass

    @abstractmethod
    async def get_account_balance(self, account_id: str) -> AccountBalance:
        """
        Get account balance information.
        
        Args:
            account_id: Trading account identifier
            
        Returns:
            Account balance data
        """
        pass

    @abstractmethod
    async def get_account_data(self, account_id: str) -> AccountData:
        """
        Get comprehensive account information.
        
        Args:
            account_id: Trading account identifier
            
        Returns:
            Account information
        """
        pass

    @abstractmethod
    async def get_market_data(
        self,
        symbol: str,
        interval: Optional[str] = None
    ) -> MarketData:
        """
        Get market data for symbol.
        
        Args:
            symbol: Trading symbol
            interval: Optional time interval
            
        Returns:
            Market data
        """
        pass

class IAuthenticationHandler(ABC):
    """Interface for broker authentication."""

    @abstractmethod
    async def authenticate(self, credentials: BrokerCredentials) -> bool:
        """
        Authenticate with broker.
        
        Args:
            credentials: Authentication credentials
            
        Returns:
            bool: True if authentication successful
            
        Raises:
            BrokerAuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    async def refresh_token(self) -> bool:
        """
        Refresh authentication token.
        
        Returns:
            bool: True if refresh successful
        """
        pass

    @abstractmethod
    async def validate_token(self) -> bool:
        """
        Validate current authentication token.
        
        Returns:
            bool: True if token is valid
        """
        pass

    @abstractmethod
    async def revoke_token(self) -> bool:
        """
        Revoke current authentication token.
        
        Returns:
            bool: True if revocation successful
        """
        pass

class BaseBroker(
    IConnectionManager,
    IWebSocketClient,
    ITrading,
    IDataProvider,
    IAuthenticationHandler
):
    """Base class implementing common broker functionality."""

    def __init__(self, config: WebSocketConfig):
        self.config = config
        self._is_connected = False
        self._last_heartbeat: Optional[datetime] = None
        self._subscriptions: set = set()
        self._market_data_cache: Dict[str, MarketData] = {}
        self._position_cache: Dict[str, Position] = {}
        self._order_cache: Dict[str, OrderResponse] = {}

    async def initialize(self) -> None:
        """Initialize broker connection and resources."""
        try:
            if await self.connect(self.config.credentials):
                self._is_connected = True
                await self._start_heartbeat()
        except BrokerBaseException as e:
            self._is_connected = False
            raise e

    async def cleanup(self) -> None:
        """Cleanup broker resources."""
        try:
            await self._stop_heartbeat()
            await self.disconnect()
        finally:
            self._is_connected = False
            self._subscriptions.clear()
            self._market_data_cache.clear()
            self._position_cache.clear()
            self._order_cache.clear()

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._last_heartbeat is not None

    async def _start_heartbeat(self) -> None:
        """Start heartbeat mechanism."""
        raise NotImplementedError

    async def _stop_heartbeat(self) -> None:
        """Stop heartbeat mechanism."""
        raise NotImplementedError

    async def validate_order(self, order: OrderRequest) -> None:
        """
        Validate order parameters.
        
        Args:
            order: Order to validate
            
        Raises:
            OrderValidationError: If validation fails
        """
        raise NotImplementedError

    async def normalize_market_data(self, data: Dict[str, Any]) -> MarketData:
        """
        Normalize market data to standard format.
        
        Args:
            data: Raw market data
            
        Returns:
            Normalized market data
        """
        raise NotImplementedError

    async def normalize_position_data(self, data: Dict[str, Any]) -> Position:
        """
        Normalize position data to standard format.
        
        Args:
            data: Raw position data
            
        Returns:
            Normalized position data
        """
        raise NotImplementedError

    def get_cache_key(self, type_key: str, identifier: str) -> str:
        """Generate cache key."""
        return f"{type_key}:{identifier}"

    async def update_cache(self, cache_type: str, key: str, data: T) -> None:
        """Update cache with new data."""
        cache = getattr(self, f"_{cache_type}_cache")
        cache[key] = data

class TokenRefreshMixin:
    """Mixin for token refresh functionality"""
    
    def refresh_token(self):
        """Refresh the broker's access token"""
        raise NotImplementedError("Subclass must implement refresh_token")

    def is_token_expired(self) -> bool:
        """Check if the token is expired"""
        raise NotImplementedError("Subclass must implement is_token_expired")

    def get_token_expiry(self) -> Optional[datetime]:
        """Get token expiration datetime"""
        raise NotImplementedError("Subclass must implement get_token_expiry")