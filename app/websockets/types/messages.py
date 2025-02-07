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
    SYNC_REQUEST = "sync_request"  # Added for Tradovate sync
    ACCOUNT_STATE = "account_state"  # Added for combined account state

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
    SYNC = "sync"  # Added for Tradovate sync request

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
    SYNC_FAILED = "sync_failed"  # Added for sync failures

# Base message model
class WSBaseMessage(BaseModel):
    """Base model for all WebSocket messages"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: WSMessageType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    broker: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
            Decimal: str
        }

# Sync Request Messages
class WSSyncRequest(WSBaseMessage):
    """Sync request message for Tradovate"""
    type: WSMessageType = WSMessageType.SYNC_REQUEST
    account_id: str
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    endpoints: List[str]  # List of endpoints to sync (e.g., ['user', 'account', 'position'])

class WSSyncResponse(WSBaseMessage):
    """Sync response message"""
    type: WSMessageType = WSMessageType.SYNC_REQUEST
    request_id: str
    success: bool
    message: Optional[str] = None

# Account State Message (Combined Updates)
class AccountBalance(BaseModel):
    """Account balance information"""
    cash_balance: Decimal
    available_balance: Decimal
    margin_used: Decimal
    unrealized_pl: Decimal
    realized_pl: Decimal
    initial_margin: Optional[Decimal] = None
    maintenance_margin: Optional[Decimal] = None

class Position(BaseModel):
    """Position information"""
    contract_id: str
    symbol: str
    net_position: Decimal
    average_price: Decimal
    unrealized_pl: Decimal
    realized_pl: Decimal
    timestamp: datetime

class Order(BaseModel):
    """Order information"""
    order_id: str
    contract_id: str
    symbol: str
    order_type: OrderType
    side: OrderSide
    quantity: Decimal
    filled_quantity: Decimal
    price: Optional[Decimal] = None
    status: OrderStatus
    timestamp: datetime

class WSAccountState(WSBaseMessage):
    """Combined account state message"""
    type: WSMessageType = WSMessageType.ACCOUNT_STATE
    account_id: str
    balance: AccountBalance
    positions: List[Position] = []
    orders: List[Order] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    sequence_number: int  # For tracking message order

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

# Subscription messages
class WSSubscriptionRequest(WSBaseMessage):
    """Subscription request message"""
    type: WSMessageType = WSMessageType.SUBSCRIPTION
    action: SubscriptionAction
    account_id: str
    endpoints: List[str] = []  # For specifying which endpoints to subscribe to

class WSSubscriptionResponse(WSBaseMessage):
    """Subscription response message"""
    type: WSMessageType = WSMessageType.SUBSCRIPTION
    success: bool
    account_id: str
    endpoints: List[str]
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

# Message type union
WSMessage = Union[
    WSAuthRequest,
    WSAuthResponse,
    WSSyncRequest,
    WSSyncResponse,
    WSAccountState,
    WSSubscriptionRequest,
    WSSubscriptionResponse,
    WSErrorMessage,
    WSSystemMessage
]

def parse_ws_message(data: Dict[str, Any]) -> WSMessage:
    """Parse a raw WebSocket message into the appropriate type"""
    try:
        message_type = data.get("type")
        logger.info(f"Parsing message of type: {message_type}")  # Add this line
        
        if not message_type:
            raise ValueError("Message type not specified")

        message_classes = {
            WSMessageType.SYNC_REQUEST: WSSyncRequest,
            WSMessageType.SUBSCRIPTION: WSSubscriptionRequest,
            WSMessageType.AUTH: WSAuthRequest if "token" in data else WSAuthResponse,
            WSMessageType.ERROR: WSErrorMessage,
            WSMessageType.SYSTEM: WSSystemMessage
        }

        # Log the available message types and the one we're trying to match
        logger.info(f"Looking for type {message_type} in available types: {[t.value for t in WSMessageType]}")

        try:
            message_type_enum = WSMessageType(message_type)
            message_class = message_classes.get(message_type_enum)
        except ValueError as e:
            logger.error(f"Invalid message type: {message_type}")
            raise ValueError(f"Unknown message type: {message_type}")

        if not message_class:
            raise ValueError(f"No handler for message type: {message_type}")

        return message_class(**data)
        
    except Exception as e:
        logger.error(f"Error parsing WebSocket message: {str(e)}")
        raise ValueError(f"Invalid message format: {str(e)}")

def create_account_state_message(
    account_id: str,
    balance: AccountBalance,
    positions: List[Position],
    orders: List[Order],
    sequence_number: int
) -> WSAccountState:
    """Create a combined account state message"""
    return WSAccountState(
        account_id=account_id,
        balance=balance,
        positions=positions,
        orders=orders,
        sequence_number=sequence_number,
        timestamp=datetime.utcnow()
    )