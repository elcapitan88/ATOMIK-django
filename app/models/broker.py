from typing import Optional
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

class BrokerAccount(Base):
    """Base model for broker accounts"""
    __tablename__ = "broker_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    broker_id = Column(String(50))  # e.g., "tradovate"
    account_id = Column(String(100))
    name = Column(String(200))
    environment = Column(String(10))
    is_active = Column(Boolean, default=True)
    status = Column(String(20), default='inactive')
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    last_connected = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False)

    # Relationships
    user = relationship("User", back_populates="broker_accounts")
    credentials = relationship("BrokerCredentials", back_populates="account", uselist=False)
    orders = relationship("Order", back_populates="broker_account", cascade="all, delete-orphan")

class BrokerCredentials(Base):
    """Model for storing broker authentication credentials"""
    __tablename__ = "broker_credentials"

    id = Column(Integer, primary_key=True, index=True)
    broker_id = Column(String, nullable=False)
    account_id = Column(Integer, ForeignKey("broker_accounts.id", ondelete="CASCADE"))
    credential_type = Column(String(20))  # oauth, api_key, etc.
    access_token = Column(String)
    # Remove refresh_token column
    expires_at = Column(DateTime)
    is_valid = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    refresh_fail_count = Column(Integer, default=0)
    last_refresh_attempt = Column(DateTime, nullable=True)
    last_refresh_error = Column(String, nullable=True)

    # Relationship to broker account
    account = relationship("BrokerAccount", back_populates="credentials")