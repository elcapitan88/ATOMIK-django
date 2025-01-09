from enum import Enum
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from typing import Optional
from ..db.base_class import Base

class SubscriptionTier(str, Enum):
    """Subscription tier levels"""
    STARTED = "started"
    PLUS = "plus"
    PRO = "pro"
    LIFETIME = "lifetime"

class SubscriptionStatus(str, Enum):
    """Subscription statuses"""
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"

class BillingInterval(str, Enum):
    """Billing interval types"""
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"

class Subscription(Base):
    """Model for user subscriptions"""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    stripe_customer_id = Column(String, unique=True, index=True)
    stripe_subscription_id = Column(String, unique=True, nullable=True)
    stripe_price_id = Column(String)
    
    tier = Column(SQLEnum(SubscriptionTier), nullable=False)
    status = Column(SQLEnum(SubscriptionStatus), default=SubscriptionStatus.INCOMPLETE)
    billing_interval = Column(SQLEnum(BillingInterval))
    
    trial_end = Column(DateTime, nullable=True)
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    cancel_at_period_end = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    canceled_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="subscription")
    payment_history = relationship("PaymentHistory", back_populates="subscription")

class PaymentHistory(Base):
    """Model for payment history"""
    __tablename__ = "payment_history"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="CASCADE"))
    stripe_payment_intent_id = Column(String, unique=True)
    amount = Column(Float)
    currency = Column(String(3), default="USD")
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    subscription = relationship("Subscription", back_populates="payment_history")