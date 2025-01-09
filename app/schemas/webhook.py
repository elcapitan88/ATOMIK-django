from pydantic import BaseModel, UUID4, validator, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

class WebhookAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class WebhookSourceType(str, Enum):
    TRADINGVIEW = "tradingview"
    TRENDSPIDER = "trendspider"
    CUSTOM = "custom"

class WebhookPayload(BaseModel):
    strategy: str = Field(..., min_length=1)
    action: WebhookAction
    symbol: str = Field(..., min_length=1, max_length=10)
    price: Optional[float] = Field(None, gt=0)
    quantity: Optional[float] = Field(None, gt=0)

class WebhookBase(BaseModel):
    name: Optional[str] = None
    source_type: WebhookSourceType = WebhookSourceType.CUSTOM
    details: Optional[str] = None
    allowed_ips: Optional[str] = None
    max_triggers_per_minute: Optional[int] = Field(default=60, gt=0)
    require_signature: Optional[bool] = True
    max_retries: Optional[int] = Field(default=3, gt=0)

class WebhookCreate(WebhookBase):
    pass

class WebhookUpdate(WebhookBase):
    is_active: Optional[bool] = None

class WebhookOut(WebhookBase):
    id: int
    token: str  
    user_id: int
    secret_key: str
    is_active: bool
    created_at: datetime
    last_triggered: Optional[datetime] = None  
    webhook_url: str

    class Config:
        from_attributes = True

class WebhookLogBase(BaseModel):
    success: bool
    payload: str
    error_message: Optional[str] = None
    ip_address: Optional[str] = None
    processing_time: Optional[float] = None

class WebhookLogCreate(WebhookLogBase):
    webhook_id: int

class WebhookLogOut(WebhookLogBase):
    id: int
    webhook_id: int
    triggered_at: datetime

    class Config:
        from_attributes = True