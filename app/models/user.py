# In app/models/user.py
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey
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
    
    # Add promo_code_id column
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    webhooks = relationship("Webhook", back_populates="user", cascade="all, delete-orphan")
    broker_accounts = relationship("BrokerAccount", back_populates="user", cascade="all, delete-orphan")
    strategies = relationship("ActivatedStrategy", back_populates="user", cascade="all, delete-orphan")
    websocket_connections = relationship("WebSocketConnection", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    support_tickets = relationship("SupportTicketLog", back_populates="user")
    
    # Add relationship to used promo code
    used_promo_code = relationship("PromoCode", foreign_keys=[promo_code_id])
    
    def __str__(self):
        return f"User(email={self.email})"