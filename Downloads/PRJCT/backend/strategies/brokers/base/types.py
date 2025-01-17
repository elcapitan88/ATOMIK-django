from typing import TypedDict, Dict, List, Union, Optional, Literal, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum

# Enums
class OrderType(Enum):
    """Enumeration of supported order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"

class OrderSide(Enum):
    """Enumeration of order sides."""
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(Enum):
    """Enumeration of order statuses."""
    PENDING = "PENDING"
    WORKING = "WORKING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

class TimeInForce(Enum):
    """Enumeration of time-in-force options."""
    GTC = "GTC"  # Good Till Cancelled
    DAY = "DAY"  # Day Order
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill
    GTD = "GTD"  # Good Till Date

class PositionSide(Enum):
    """Enumeration of position sides."""
    LONG = "LONG"
    SHORT = "SHORT"

class AccountStatus(Enum):
    """Enumeration of account statuses."""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    ERROR = "ERROR"

class WebSocketMessageType(Enum):
    """Enumeration of WebSocket message types."""
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    ORDER_UPDATE = "order_update"
    POSITION_UPDATE = "position_update"
    TRADE_UPDATE = "trade_update"
    ACCOUNT_UPDATE = "account_update"
    QUOTE_UPDATE = "quote_update"

# TypedDict definitions
class OrderRequest(TypedDict):
    """Type definition for order requests."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Union[int, float, Decimal]
    price: Optional[Union[float, Decimal]]
    stop_price: Optional[Union[float, Decimal]]
    time_in_force: TimeInForce
    client_order_id: Optional[str]
    broker_order_id: Optional[str]

class OrderResponse(TypedDict):
    """Type definition for order response."""
    order_id: str
    client_order_id: Optional[str]
    broker_order_id: str
    status: OrderStatus
    symbol: str
    side: OrderSide
    quantity: Union[int, float, Decimal]
    filled_quantity: Union[int, float, Decimal]
    remaining_quantity: Union[int, float, Decimal]
    price: Optional[Union[float, Decimal]]
    average_price: Optional[Union[float, Decimal]]
    created_at: datetime
    updated_at: datetime

class PositionData(TypedDict):
    """Type definition for position data."""
    symbol: str
    quantity: Union[int, float, Decimal]
    entry_price: Union[float, Decimal]
    current_price: Union[float, Decimal]
    unrealized_pnl: Union[float, Decimal]
    realized_pnl: Union[float, Decimal]
    side: PositionSide
    timestamp: datetime
    broker: str
    account_id: str
    contract_info: Optional[Dict[str, Any]]

class PositionUpdate(TypedDict):
    """Type definition for position updates."""
    symbol: str
    quantity: Union[int, float, Decimal]
    entry_price: Union[float, Decimal]
    current_price: Union[float, Decimal]
    unrealized_pnl: Union[float, Decimal]
    realized_pnl: Union[float, Decimal]
    side: PositionSide
    timestamp: datetime

class AccountUpdate(TypedDict):
    """Type definition for account updates."""
    account_id: str
    status: AccountStatus
    balance: Union[float, Decimal]
    equity: Union[float, Decimal]
    margin_used: Union[float, Decimal]
    margin_available: Union[float, Decimal]
    timestamp: datetime

class TradeUpdate(TypedDict):
    """Type definition for trade updates."""
    trade_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: Union[int, float, Decimal]
    price: Union[float, Decimal]
    timestamp: datetime

class MarketData(TypedDict):
    """Type definition for market data."""
    symbol: str
    bid: Union[float, Decimal]
    ask: Union[float, Decimal]
    last: Union[float, Decimal]
    volume: Union[int, float]
    timestamp: datetime

class WebhookPayload(TypedDict):
    """Type definition for webhook payloads."""
    webhook_id: str
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime
    signature: Optional[str]

class Position(TypedDict):
    """Type definition for a trading position."""
    id: str
    symbol: str
    quantity: Union[int, float, Decimal]
    side: PositionSide
    entry_price: Union[float, Decimal]
    current_price: Union[float, Decimal]
    unrealized_pnl: Union[float, Decimal]
    realized_pnl: Union[float, Decimal]
    account_id: str
    broker: str
    timestamp: datetime
    margin_used: Optional[Union[float, Decimal]]
    liquidation_price: Optional[Union[float, Decimal]]
    contract_info: Optional[Dict[str, Any]]
    status: str  # 'OPEN', 'CLOSED', 'LIQUIDATED'
    tags: Optional[List[str]]
    metadata: Optional[Dict[str, Any]]

class AccountBalance(TypedDict):
    """Type definition for account balance information."""
    total_equity: Union[float, Decimal]
    cash_balance: Union[float, Decimal]
    used_margin: Union[float, Decimal]
    available_margin: Union[float, Decimal]
    maintenance_margin: Union[float, Decimal]
    unrealized_pnl: Union[float, Decimal]
    realized_pnl: Union[float, Decimal]
    account_id: str
    currency: str
    timestamp: datetime
    buying_power: Optional[Union[float, Decimal]]
    initial_margin: Optional[Union[float, Decimal]]

class WebSocketMessage(TypedDict):
    """Type definition for WebSocket messages."""
    type: WebSocketMessageType
    data: Dict[str, Any]
    timestamp: datetime

class BrokerCredentials(TypedDict):
    """Type definition for broker credentials."""
    api_key: Optional[str]
    secret_key: Optional[str]
    passphrase: Optional[str]
    access_token: Optional[str]
    refresh_token: Optional[str]
    environment: str  # 'live' or 'demo'
    broker_id: Optional[str]
    username: Optional[str]
    password: Optional[str]
    auth_type: str  # 'oauth', 'api_key', or 'password'
    additional_params: Optional[Dict[str, Any]]

class AccountData(TypedDict):
    """Type definition for comprehensive account information."""
    account_id: str
    name: Optional[str]
    status: AccountStatus
    balance: Union[float, Decimal]
    equity: Union[float, Decimal]
    margin_used: Union[float, Decimal]
    margin_available: Union[float, Decimal]
    unrealized_pnl: Union[float, Decimal]
    realized_pnl: Union[float, Decimal]
    positions: List[PositionData]
    environment: str  # 'live' or 'demo'
    broker: str
    last_updated: datetime
    currency: Optional[str]
    leverage: Optional[Union[int, float]]
    permissions: Optional[List[str]]

class WebSocketConfig(TypedDict):
    """Type definition for WebSocket configuration."""
    url: str
    reconnect_attempts: int
    reconnect_interval: int
    heartbeat_interval: int
    connection_timeout: int

# Type Aliases
AccountId = str
OrderId = str
Symbol = str
Price = Union[int, float, Decimal]
Quantity = Union[int, float, Decimal]

# Validation Sets
VALID_ORDER_TYPES = {order_type.value for order_type in OrderType}
VALID_ORDER_SIDES = {order_side.value for order_side in OrderSide}
VALID_ORDER_STATUSES = {order_status.value for order_status in OrderStatus}
VALID_TIME_IN_FORCE = {tif.value for tif in TimeInForce}
VALID_POSITION_SIDES = {position_side.value for position_side in PositionSide}
VALID_ACCOUNT_STATUSES = {account_status.value for account_status in AccountStatus}