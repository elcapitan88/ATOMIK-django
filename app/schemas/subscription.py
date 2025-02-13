# app/schemas/subscription.py
from pydantic import BaseModel
from typing import Optional

class SubscriptionBase(BaseModel):
    """Base subscription schema"""
    stripe_customer_id: str

class SubscriptionCreate(SubscriptionBase):
    """Schema for creating a subscription"""
    user_id: int

class SubscriptionOut(SubscriptionBase):
    """Schema for subscription response"""
    id: int
    user_id: int

    class Config:
        from_attributes = True

class SubscriptionVerification(BaseModel):
    """Schema for subscription verification response"""
    has_access: bool
    dev_mode: Optional[bool] = None
    reason: Optional[str] = None
    customer_id: Optional[str] = None

class PortalSession(BaseModel):
    """Schema for Stripe Customer Portal session"""
    url: str

class SubscriptionConfig(BaseModel):
    """Schema for subscription configuration"""
    publishable_key: str
    checks_disabled: bool
    environment: str