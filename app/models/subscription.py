# app/models/subscription.py
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from ..db.base_class import Base

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    stripe_customer_id = Column(String, unique=True, index=True, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    status = Column(String, default="active")
    tier = Column(String, default="starter")
    is_lifetime = Column(Boolean, default=False)
    is_legacy_free = Column(Boolean, default=False)  # Track grandfathered free users
    connected_accounts_count = Column(Integer, default=0)
    active_webhooks_count = Column(Integer, default=0) 
    active_strategies_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Trial-related fields
    trial_ends_at = Column(DateTime, nullable=True)
    is_in_trial = Column(Boolean, default=False)
    trial_converted = Column(Boolean, default=False)  # Track if trial converted to paid

    # Relationship
    user = relationship("User", back_populates="subscription")
    
    @property
    def is_trial_active(self):
        """Check if the subscription is in an active trial period"""
        if not self.is_in_trial or not self.trial_ends_at:
            return False
        return datetime.utcnow() <= self.trial_ends_at
        
    @property
    def days_left_in_trial(self):
        """Get number of days left in trial"""
        if not self.is_trial_active:
            return 0
        delta = self.trial_ends_at - datetime.utcnow()
        return max(0, delta.days)
    
    @property
    def display_tier_name(self):
        """Get the marketing display name for the tier"""
        from app.core.subscription_tiers import get_tier_display_name
        return get_tier_display_name(self.tier)
        
    def set_trial_period(self, days=14):
        """Set up a trial period for this subscription"""
        self.is_in_trial = True
        self.trial_ends_at = datetime.utcnow() + timedelta(days=days)
        self.status = "trialing"