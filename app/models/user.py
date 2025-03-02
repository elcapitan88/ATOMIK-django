from sqlalchemy import Boolean, Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    full_name = Column(String, nullable=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    webhooks = relationship("Webhook", back_populates="user", cascade="all, delete-orphan")
    broker_accounts = relationship("BrokerAccount", back_populates="user", cascade="all, delete-orphan")
    strategies = relationship("ActivatedStrategy", back_populates="user", cascade="all, delete-orphan")
    websocket_connections = relationship("WebSocketConnection", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    support_tickets = relationship("SupportTicketLog", back_populates="user")
    
    def __str__(self):
        return f"User(email={self.email})"