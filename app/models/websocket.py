# app/models/websocket.py
from datetime import datetime
from typing import Dict, Any, Optional, Set
from enum import Enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from ..db.base_class import Base

# SQLAlchemy Models
class WebSocketConnection(Base):
    """Database model for tracking WebSocket connections"""
    __tablename__ = "websocket_connections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    client_id = Column(String, unique=True, index=True)
    broker = Column(String)
    environment = Column(String)
    connected_at = Column(DateTime, default=datetime.utcnow)
    last_heartbeat = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    user = relationship("User", back_populates="websocket_connections")

# Enums for WebSocket types
class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"
    AUTHENTICATING = "authenticating"
    READY = "ready"

class MessageCategory(str, Enum):
    MARKET_DATA = "market_data"
    ORDER_UPDATE = "order_update"
    ACCOUNT_UPDATE = "account_update"
    SYSTEM = "system"
    ERROR = "error"
    AUTH = "auth"
    HEARTBEAT = "heartbeat"

# Configuration class
class ManagerConfig:
    def __init__(self):
        self.heartbeat_interval: int = 30
        self.connection_timeout: int = 60
        self.max_connections_per_user: int = 5
        self.max_subscriptions_per_client: int = 50
        self.cleanup_interval: int = 300
        self.max_message_size: int = 1024 * 1024  # 1MB
        self.enable_message_logging: bool = True
        self.broker_configs: Dict[str, Dict[str, Any]] = {}

# Connection statistics
class ConnectionStats:
    def __init__(self):
        self.connected_at: datetime = datetime.utcnow()
        self.last_heartbeat: datetime = datetime.utcnow()
        self.messages_received: int = 0
        self.messages_sent: int = 0
        self.errors: int = 0
        self.reconnections: int = 0
        self.subscribed_symbols: Set[str] = set()

# Client metadata
class ClientMetadata:
    def __init__(
        self,
        user_id: int,
        client_id: str,
        environment: str,
        broker: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        self.user_id = user_id
        self.client_id = client_id
        self.environment = environment
        self.broker = broker
        self.ip_address = ip_address
        self.user_agent = user_agent