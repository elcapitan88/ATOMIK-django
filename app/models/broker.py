from typing import Optional, Dict, Any
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from sqlalchemy import UniqueConstraint
from ..db.base_class import Base

class BrokerAccount(Base):
    """Base model for broker accounts"""
    __tablename__ = "broker_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    broker_id = Column(String(50))  # e.g., "tradovate"
    account_id = Column(String, unique=True, nullable=False)
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

    __table_args__ = (
        UniqueConstraint(
            'user_id', 
            'account_id', 
            'broker_id', 
            'environment', 
            name='uq_user_account_broker_env'
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert broker account to dictionary representation"""
        account_dict = {
            "id": self.id,
            "account_id": self.account_id,
            "broker_id": self.broker_id,
            "name": self.name,
            "environment": self.environment,
            "is_active": self.is_active,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_connected": self.last_connected.isoformat() if self.last_connected else None,
            "is_deleted": self.is_deleted,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None
        }

        # Add token validity status if credentials exist
        if self.credentials:
            account_dict.update({
                "has_credentials": True,
                "is_token_valid": self.credentials.is_valid,
                "token_expires_at": self.credentials.expires_at.isoformat() if self.credentials.expires_at else None,
                "token_refresh_fail_count": self.credentials.refresh_fail_count,
                "last_refresh_attempt": self.credentials.last_refresh_attempt.isoformat() if self.credentials.last_refresh_attempt else None,
                "last_refresh_error": self.credentials.last_refresh_error
            })
        else:
            account_dict.update({
                "has_credentials": False,
                "is_token_valid": False
            })

        return account_dict

class BrokerCredentials(Base):
    """Model for storing broker authentication credentials"""
    __tablename__ = "broker_credentials"

    id = Column(Integer, primary_key=True, index=True)
    broker_id = Column(String, nullable=False)
    account_id = Column(Integer, ForeignKey("broker_accounts.id", ondelete="CASCADE"))
    credential_type = Column(String(20))  # oauth, api_key, etc.
    access_token = Column(String)
    expires_at = Column(DateTime)
    is_valid = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    refresh_fail_count = Column(Integer, default=0)
    last_refresh_attempt = Column(DateTime, nullable=True)
    last_refresh_error = Column(String, nullable=True)

    # Relationship to broker account
    account = relationship("BrokerAccount", back_populates="credentials")

    def to_dict(self) -> Dict[str, Any]:
        """Convert credentials to dictionary representation"""
        return {
            "id": self.id,
            "broker_id": self.broker_id,
            "credential_type": self.credential_type,
            "is_valid": self.is_valid,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "refresh_fail_count": self.refresh_fail_count,
            "last_refresh_attempt": self.last_refresh_attempt.isoformat() if self.last_refresh_attempt else None,
            "last_refresh_error": self.last_refresh_error
        }