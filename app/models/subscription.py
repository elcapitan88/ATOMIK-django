# app/models/subscription.py
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Enum, TypeDecorator
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from ..db.base_class import Base
import enum

class DunningStage(str, enum.Enum):
    NONE = "none"
    WARNING = "warning"
    URGENT = "urgent"
    FINAL = "final"
    SUSPENDED = "suspended"

class SafeDunningStageType(TypeDecorator):
    """Custom type that safely handles DunningStage enum conversion"""
    impl = Enum
    cache_ok = True
    
    def __init__(self):
        super().__init__(DunningStage, name='dunningstage')
    
    def process_result_value(self, value, dialect):
        """Convert database value to enum, with fallback to NONE"""
        if value is None:
            return DunningStage.NONE
        
        try:
            if isinstance(value, DunningStage):
                return value
            return DunningStage(value)
        except (ValueError, TypeError):
            # Fallback to NONE for any invalid values
            return DunningStage.NONE
    
    def process_bind_param(self, value, dialect):
        """Convert enum to database value"""
        if value is None:
            return DunningStage.NONE.value
        
        if isinstance(value, DunningStage):
            return value.value
        
        try:
            return DunningStage(value).value
        except (ValueError, TypeError):
            return DunningStage.NONE.value

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
    
    # Payment failure tracking fields
    payment_failed_at = Column(DateTime, nullable=True)
    payment_failure_count = Column(Integer, default=0)
    grace_period_ends_at = Column(DateTime, nullable=True)
    last_payment_failure_reason = Column(String, nullable=True)
    dunning_stage = Column(SafeDunningStageType(), default=DunningStage.NONE, nullable=False, server_default='none')

    # Relationship
    user = relationship("User", back_populates="subscription")
    
    @property
    def safe_dunning_stage(self):
        """Get dunning stage with fallback to NONE if invalid"""
        # With SafeDunningStageType, this should always be a valid enum
        return self.dunning_stage or DunningStage.NONE
    
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
    
    @property
    def is_in_grace_period(self):
        """Check if subscription is currently in grace period after payment failure"""
        if not self.grace_period_ends_at:
            return False
        return datetime.utcnow() <= self.grace_period_ends_at
    
    @property
    def days_left_in_grace_period(self):
        """Get number of days left in grace period"""
        if not self.is_in_grace_period:
            return 0
        delta = self.grace_period_ends_at - datetime.utcnow()
        return max(0, delta.days)
    
    @property
    def has_payment_issues(self):
        """Check if subscription has active payment issues"""
        return self.dunning_stage != DunningStage.NONE
    
    @property
    def is_suspended(self):
        """Check if subscription is suspended due to payment failure"""
        return self.dunning_stage == DunningStage.SUSPENDED
    
    def start_grace_period(self, grace_days=7):
        """Start grace period after payment failure"""
        self.payment_failed_at = datetime.utcnow()
        self.payment_failure_count += 1
        self.grace_period_ends_at = datetime.utcnow() + timedelta(days=grace_days)
        self.dunning_stage = DunningStage.WARNING
        self.status = "past_due"
    
    def advance_dunning_stage(self):
        """Advance to next dunning stage"""
        if self.dunning_stage == DunningStage.WARNING:
            self.dunning_stage = DunningStage.URGENT
        elif self.dunning_stage == DunningStage.URGENT:
            self.dunning_stage = DunningStage.FINAL
        elif self.dunning_stage == DunningStage.FINAL:
            self.dunning_stage = DunningStage.SUSPENDED
            self.status = "suspended"
    
    def resolve_payment_failure(self):
        """Reset payment failure state after successful payment"""
        self.payment_failed_at = None
        self.payment_failure_count = 0
        self.grace_period_ends_at = None
        self.last_payment_failure_reason = None
        self.dunning_stage = DunningStage.NONE
        self.status = "active"