from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from ..models.subscription import SubscriptionTier, SubscriptionStatus, BillingInterval

class PlanFeatures(BaseModel):
    """Schema for plan features"""
    webhooks: int
    strategies: int
    broker_connections: int
    multiple_accounts: bool
    marketplace_access: bool
    realtime_data: bool
    trial_days: int
    support_level: str
    analytics: str
    api_access: bool
    early_access: Optional[bool] = None

class SubscriptionBase(BaseModel):
    """Base subscription schema"""
    tier: SubscriptionTier
    billing_interval: BillingInterval

class SubscriptionCreate(SubscriptionBase):
    """Schema for creating a subscription"""
    payment_method_id: Optional[str] = None

class SubscriptionUpdate(BaseModel):
    """Schema for updating a subscription"""
    billing_interval: Optional[BillingInterval] = None

class SubscriptionOut(BaseModel):
    """Schema for subscription response"""
    id: int
    user_id: int
    tier: SubscriptionTier
    status: SubscriptionStatus
    billing_interval: BillingInterval
    trial_end: Optional[datetime]
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    created_at: datetime
    updated_at: datetime
    features: Optional[PlanFeatures] = None

    class Config:
        from_attributes = True

class LifetimePurchaseResponse(BaseModel):
    """Schema for lifetime purchase response"""
    client_secret: str
    payment_intent_id: str

class InvoiceItem(BaseModel):
    """Schema for invoice items"""
    id: str
    amount_due: float
    currency: str
    status: str
    created: datetime
    invoice_pdf: Optional[str]
    hosted_invoice_url: Optional[str]

class InvoiceList(BaseModel):
    """Schema for list of invoices"""
    invoices: List[InvoiceItem]