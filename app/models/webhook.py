# app/models/webhook.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, Float, Enum
from sqlalchemy.orm import relationship, backref, Session
from datetime import datetime
from typing import Optional
import secrets
import hmac
import hashlib
import json
import sqlalchemy
import enum
import logging
from ..db.base_class import Base

logger = logging.getLogger(__name__)

class StrategyType(str, enum.Enum):
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    ARBITRAGE = "arbitrage"
    SCALPING = "scalping"

class Webhook(Base):
    """
    Model for storing webhook configurations and metadata.
    """
    __tablename__ = "webhooks"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Core Fields
    token = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    secret_key = Column(String(64), nullable=False)
    is_shared = Column(Boolean, default=False)
    sharing_enabled_at = Column(DateTime, nullable=True)
    
    # Configuration
    source_type = Column(String(50), default='custom')
    is_active = Column(Boolean, default=True)
    allowed_ips = Column(Text, nullable=True)  # Comma-separated list of allowed IPs
    max_triggers_per_minute = Column(Integer, default=60)
    require_signature = Column(Boolean, default=True)
    max_retries = Column(Integer, default=3)
    retry_interval = Column(Integer, default=60)
    
    # Strategy Fields
    strategy_type = Column(Enum(StrategyType), nullable=True)
    subscriber_count = Column(Integer, default=0)
    rating = Column(Float, default=0.0)
    total_ratings = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_triggered = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship(
        "User", 
        back_populates="webhooks"
    )
    
    strategies = relationship(
        "ActivatedStrategy",
        back_populates="webhook",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="[ActivatedStrategy.webhook_id]"
    )
    
    webhook_logs = relationship(
        "WebhookLog",
        back_populates="webhook",
        cascade="all, delete-orphan"
    )

    subscribers = relationship(
        "WebhookSubscription",
        back_populates="webhook",
        cascade="all, delete-orphan"
    )

    ratings = relationship(
        "WebhookRating",
        back_populates="webhook",
        cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.secret_key:
            self.secret_key = secrets.token_hex(32)

    def to_dict(self) -> dict:
        """Convert webhook to dictionary representation"""
        return {
            'id': self.id,
            'token': self.token,
            'name': self.name,
            'source_type': self.source_type,
            'details': self.details,
            'is_active': self.is_active,
            'allowed_ips': self.allowed_ips,
            'max_triggers_per_minute': self.max_triggers_per_minute,
            'require_signature': self.require_signature,
            'max_retries': self.max_retries,
            'retry_interval': self.retry_interval,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_triggered': self.last_triggered.isoformat() if self.last_triggered else None,
            'strategy_type': self.strategy_type.value if self.strategy_type else None,
            'is_shared': self.is_shared,
            'subscriber_count': self.subscriber_count,
            'rating': float(self.rating) if self.rating else 0.0
        }

    def get_configuration(self) -> dict:
        """Get webhook configuration settings"""
        return {
            'require_signature': self.require_signature,
            'allowed_ips': self.allowed_ips.split(',') if self.allowed_ips else [],
            'max_triggers_per_minute': self.max_triggers_per_minute,
            'max_retries': self.max_retries,
            'retry_interval': self.retry_interval,
            'strategy_type': self.strategy_type.value if self.strategy_type else None
        }

    def validate_ip(self, ip_address: str) -> bool:
        """Validate if an IP address is allowed"""
        if not self.allowed_ips:
            return True
        allowed_ips = [ip.strip() for ip in self.allowed_ips.split(',')]
        return ip_address in allowed_ips

    def update_last_triggered(self) -> None:
        """Update the last triggered timestamp"""
        self.last_triggered = datetime.utcnow()

    def verify_signature(self, payload: str, signature: str) -> bool:
        """Verify webhook signature"""
        computed_signature = hmac.new(
            self.secret_key.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed_signature, signature)

    def update_rating(self, new_rating: int) -> None:
        """Update the webhook's rating"""
        if not self.total_ratings:
            self.rating = float(new_rating)
            self.total_ratings = 1
        else:
            total_score = self.rating * self.total_ratings
            self.total_ratings += 1
            self.rating = (total_score + new_rating) / self.total_ratings

    def increment_subscriber_count(self) -> None:
        """Increment the subscriber count"""
        self.subscriber_count = (self.subscriber_count or 0) + 1

    def decrement_subscriber_count(self) -> None:
        """Decrement the subscriber count"""
        if self.subscriber_count and self.subscriber_count > 0:
            self.subscriber_count -= 1

    def __repr__(self):
        return f"<Webhook(id={self.id}, name={self.name}, source={self.source_type})>"


class WebhookLog(Base):
    """
    Model for storing webhook execution logs.
    """
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"))
    triggered_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    payload = Column(Text)
    error_message = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    processing_time = Column(Float, nullable=True)

    # Relationship
    webhook = relationship("Webhook", back_populates="webhook_logs")

    def to_dict(self) -> dict:
        """Convert log entry to dictionary representation"""
        return {
            'id': self.id,
            'webhook_id': self.webhook_id,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'success': self.success,
            'error_message': self.error_message,
            'ip_address': self.ip_address,
            'processing_time': self.processing_time
        }

    def __repr__(self):
        return f"<WebhookLog(id={self.id}, success={self.success}, time={self.triggered_at})>"


class WebhookSubscription(Base):
    """
    Model for tracking webhook subscriptions.
    """
    __tablename__ = "webhook_subscriptions"

    id = Column(Integer, primary_key=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    subscribed_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    webhook = relationship("Webhook", back_populates="subscribers")
    user = relationship("User", backref="webhook_subscriptions")

    __table_args__ = (
        sqlalchemy.UniqueConstraint('webhook_id', 'user_id', name='uq_webhook_subscription'),
    )


class WebhookRating(Base):
    """
    Model for storing webhook ratings.
    """
    __tablename__ = "webhook_ratings"

    id = Column(Integer, primary_key=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    rating = Column(Integer)  # 1-5 stars
    rated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    webhook = relationship("Webhook", back_populates="ratings")
    user = relationship("User", backref="webhook_ratings")

    __table_args__ = (
        sqlalchemy.UniqueConstraint('webhook_id', 'user_id', name='uq_webhook_rating'),
    )