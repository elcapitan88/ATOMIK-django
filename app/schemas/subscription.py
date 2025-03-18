# app/schemas/subscription.py
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class SubscriptionBase(BaseModel):
    """Base subscription schema"""
    stripe_customer_id: str

class SubscriptionCreate(SubscriptionBase):
    """Schema for creating a subscription"""
    user_id: int
    tier: str = "starter"
    is_lifetime: bool = False

class SubscriptionOut(SubscriptionBase):
    """Schema for subscription response"""
    id: int
    user_id: int
    tier: str
    status: str
    is_lifetime: bool

    class Config:
        from_attributes = True

class SubscriptionVerification(BaseModel):
    """Schema for subscription verification response"""
    has_access: bool
    dev_mode: Optional[bool] = None
    reason: Optional[str] = None
    customer_id: Optional[str] = None
    tier: Optional[str] = None
    is_lifetime: Optional[bool] = False

class PortalSession(BaseModel):
    """Schema for Stripe Customer Portal session"""
    url: str

class SubscriptionConfig(BaseModel):
    """Schema for subscription configuration"""
    publishable_key: str
    checks_disabled: bool
    environment: str

class SubscriptionTierFeature(BaseModel):
    """Schema for a subscription tier feature"""
    text: str
    available: bool

class SubscriptionTier(BaseModel):
    """Schema for a subscription tier"""
    id: str
    name: str
    description: str
    prices: Dict[str, float]
    features: List[str]

class SubscriptionTiersResponse(BaseModel):
    """Schema for all subscription tiers"""
    tiers: List[SubscriptionTier]