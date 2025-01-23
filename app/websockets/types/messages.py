from datetime import datetime
from typing import Dict, Optional, List, Any, Union
from enum import Enum
import logging
from decimal import Decimal
from pydantic import BaseModel, Field
import uuid

logger = logging.getLogger(__name__)

class WSMessageType(str, Enum):
    """WebSocket message types"""
    AUTH = "auth"
    MARKET_DATA = "market_data"
    ORDER = "order"
    POSITION = "position"
    ACCOUNT = "account"
    SUBSCRIPTION = "subscription"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    ERROR = "error"
    SYSTEM = "system"

class OrderStatus(str, Enum):
    """Order status enumeration"""
    PENDING = "pending"
    WORKING = "working"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PARTIALLY_FILLED = "partially_filled"

class OrderSide(str, Enum):
    """Order side enumeration"""
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    """Order type enumeration"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class SubscriptionAction(str, Enum):
    """Subscription actions"""
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"

class ErrorCode(str, Enum):
    """Error codes for WebSocket messages"""
    AUTHENTICATION_FAILED = "auth_failed"
    INVALID_MESSAGE = "invalid_message"
    SUBSCRIPTION_FAILED = "subscription_failed"
    ORDER_FAILED = "order_failed"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INVALID_SYMBOL = "invalid_symbol"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    SYSTEM_ERROR = "system_error"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    HEARTBEAT_MISSED = "heartbeat_missed"

# Base message model
class WSBaseMessage(BaseModel):
    """Base model for all WebSocket messages"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: WSMessageType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    broker: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }

# Authentication messages
class WSAuthRequest(WSBaseMessage):
    """Authentication request message"""
    type: WSMessageType = WSMessageType.AUTH
    token: str
    environment: str = "demo"

class WSAuthResponse(WSBaseMessage):
    """Authentication response message"""
    type: WSMessageType = WSMessageType.AUTH
    success: bool
    message: Optional[str] = None
    user_id: Optional[int] = None

# Market data messages
class MarketDataLevel(BaseModel):
    """Price level for order book"""
    price: Decimal
    size: Decimal

class WSMarketDataMessage(WSBaseMessage):
    """Market data message"""
    type: WSMessageType = WSMessageType.MARKET_DATA
    symbol: str
    last_price: Decimal
    volume: Optional[Decimal] = None
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    open: Optional[Decimal] = None
    close: Optional[Decimal] = None
    orderbook: Optional[Dict[str, List[MarketDataLevel]]] = None

# Order messages
class WSOrderRequest(WSBaseMessage):
    """Order request message"""
    type: WSMessageType = WSMessageType.ORDER
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: str = "GTC"
    client_order_id: Optional[str] = None

class WSOrderResponse(WSBaseMessage):
    """Order response message"""
    type: WSMessageType = WSMessageType.ORDER
    order_id: str
    client_order_id: Optional[str] = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    filled_quantity: Decimal = Decimal(0)
    remaining_quantity: Decimal
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    status: OrderStatus
    message: Optional[str] = None

class WSOrderUpdate(WSBaseMessage):
    """Order update message"""
    type: WSMessageType = WSMessageType.ORDER
    order_id: str
    client_order_id: Optional[str] = None
    symbol: str
    side: OrderSide
    status: OrderStatus
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_price: Optional[Decimal] = None
    last_fill_price: Optional[Decimal] = None
    last_fill_quantity: Optional[Decimal] = None

# Position messages
class WSPosition(WSBaseMessage):
    """Position message"""
    type: WSMessageType = WSMessageType.POSITION
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    liquidation_price: Optional[Decimal] = None
    margin_used: Optional[Decimal] = None

# Account messages
class WSAccountUpdate(WSBaseMessage):
    """Account update message"""
    type: WSMessageType = WSMessageType.ACCOUNT
    account_id: str
    balance: Decimal
    available_balance: Decimal
    margin_used: Optional[Decimal] = None
    positions: List[WSPosition] = []
    currency: str = "USD"

# Subscription messages
class WSSubscriptionRequest(WSBaseMessage):
    """Subscription request message"""
    type: WSMessageType = WSMessageType.SUBSCRIPTION
    action: SubscriptionAction
    symbols: List[str]
    channels: Optional[List[str]] = None

class WSSubscriptionResponse(WSBaseMessage):
    """Subscription response message"""
    type: WSMessageType = WSMessageType.SUBSCRIPTION
    success: bool
    symbols: List[str]
    message: Optional[str] = None

# Error messages
class WSErrorMessage(WSBaseMessage):
    """Error message"""
    type: WSMessageType = WSMessageType.ERROR
    code: ErrorCode
    message: str
    details: Optional[Dict[str, Any]] = None

# System messages
class WSSystemMessage(WSBaseMessage):
    """System message"""
    type: WSMessageType = WSMessageType.SYSTEM
    event: str
    details: Optional[Dict[str, Any]] = None

# Heartbeat messages
class HeartbeatMessage(WSBaseMessage):
    """Heartbeat message"""
    type: WSMessageType = WSMessageType.HEARTBEAT
    sequence_number: int
    client_id: Optional[str] = None
    account_id: str
    metrics: Optional[Dict[str, Any]] = None

class HeartbeatAckMessage(WSBaseMessage):
    """Heartbeat acknowledgment message"""
    type: WSMessageType = WSMessageType.HEARTBEAT_ACK
    sequence_number: int
    original_timestamp: datetime
    account_id: str
    latency: Optional[float] = None
    client_metrics: Optional[Dict[str, Any]] = None

# Message type union
WSMessage = Union[
    WSAuthRequest,
    WSAuthResponse,
    WSMarketDataMessage,
    WSOrderRequest,
    WSOrderResponse,
    WSOrderUpdate,
    WSPosition,
    WSAccountUpdate,
    WSSubscriptionRequest,
    WSSubscriptionResponse,
    WSErrorMessage,
    HeartbeatMessage,
    HeartbeatAckMessage,
    WSSystemMessage
]

def parse_ws_message(data: Dict[str, Any]) -> WSMessage:
    """Parse a raw WebSocket message into the appropriate type"""
    try:
        message_type = data.get("type")
        if not message_type:
            raise ValueError("Message type not specified")

        message_classes = {
            WSMessageType.AUTH: WSAuthRequest if "token" in data else WSAuthResponse,
            WSMessageType.MARKET_DATA: WSMarketDataMessage,
            WSMessageType.ORDER: (
                WSOrderRequest if "client_order_id" in data 
                else WSOrderResponse if "order_id" in data 
                else WSOrderUpdate
            ),
            WSMessageType.POSITION: WSPosition,
            WSMessageType.ACCOUNT: WSAccountUpdate,
            WSMessageType.SUBSCRIPTION: (
                WSSubscriptionRequest if "action" in data 
                else WSSubscriptionResponse
            ),
            WSMessageType.ERROR: WSErrorMessage,
            WSMessageType.HEARTBEAT: HeartbeatMessage,
            WSMessageType.HEARTBEAT_ACK: HeartbeatAckMessage,
            WSMessageType.SYSTEM: WSSystemMessage
        }

        message_class = message_classes.get(message_type)
        if not message_class:
            raise ValueError(f"Unknown message type: {message_type}")

        return message_class(**data)
        
    except Exception as e:
        logger.error(f"Error parsing WebSocket message: {str(e)}")
        raise ValueError(f"Invalid message format: {str(e)}")

def create_heartbeat_message(account_id: str, sequence_number: int, metrics: Optional[Dict[str, Any]] = None) -> HeartbeatMessage:
    """Create a heartbeat message"""
    return HeartbeatMessage(
        account_id=account_id,
        sequence_number=sequence_number,
        metrics=metrics,
        timestamp=datetime.utcnow()
    )

def create_heartbeat_ack(
    original_message: HeartbeatMessage,
    latency: Optional[float] = None,
    client_metrics: Optional[Dict[str, Any]] = None
) -> HeartbeatAckMessage:
    """Create a heartbeat acknowledgment message"""
    return HeartbeatAckMessage(
        sequence_number=original_message.sequence_number,
        original_timestamp=original_message.timestamp,
        account_id=original_message.account_id,
        latency=latency,
        client_metrics=client_metrics
    )