from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import Enum
from typing import Optional
from ..db.base_class import Base

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

class Order(Base):
    """Broker-agnostic order model"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    broker_order_id = Column(String(100), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    strategy_id = Column(Integer, ForeignKey("activated_strategies.id", ondelete="SET NULL"), nullable=True)
    broker_account_id = Column(Integer, ForeignKey("broker_accounts.id"))
    
    # Order details
    symbol = Column(String(20), nullable=False)
    side = Column(SQLEnum(OrderSide), nullable=False)
    order_type = Column(SQLEnum(OrderType), nullable=False)
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING)
    
    # Quantities
    quantity = Column(Float, nullable=False)
    filled_quantity = Column(Float, default=0)
    remaining_quantity = Column(Float)
    
    # Pricing
    price = Column(Float, nullable=True)  # For limit orders
    stop_price = Column(Float, nullable=True)  # For stop orders
    average_fill_price = Column(Float, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    
    # Additional fields
    time_in_force = Column(String(10), default="GTC")  # GTC, IOC, FOK, etc.
    error_message = Column(String, nullable=True)
    broker_response = Column(String, nullable=True)  # Store raw broker response
    notes = Column(String, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="orders")
    strategy = relationship("ActivatedStrategy", back_populates="orders")
    broker_account = relationship("BrokerAccount", back_populates="orders")

    def __str__(self):
        return f"Order(id={self.id}, broker_order_id={self.broker_order_id}, symbol={self.symbol}, side={self.side}, status={self.status})"