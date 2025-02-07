# app/schemas/webhook.py
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

class StrategyType(str, Enum):
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    ARBITRAGE = "arbitrage"
    SCALPING = "scalping"

class WebhookPayload(BaseModel):
    action: WebhookAction

class WebhookBase(BaseModel):
    name: Optional[str] = None
    source_type: WebhookSourceType = WebhookSourceType.CUSTOM
    details: Optional[str] = None
    allowed_ips: Optional[str] = None
    max_triggers_per_minute: Optional[int] = Field(default=60, gt=0)
    require_signature: Optional[bool] = True
    max_retries: Optional[int] = Field(default=3, gt=0)
    strategy_type: Optional[StrategyType] = None
    is_shared: Optional[bool] = False

class WebhookCreate(WebhookBase):
    pass

class WebhookUpdate(WebhookBase):
    is_active: Optional[bool] = None

class WebhookSubscriptionBase(BaseModel):
    webhook_id: str
    user_id: int

class WebhookSubscriptionCreate(WebhookSubscriptionBase):
    pass

class WebhookSubscriptionOut(WebhookSubscriptionBase):
    id: int
    subscribed_at: datetime

    class Config:
        from_attributes = True

class WebhookRatingBase(BaseModel):
    rating: int = Field(ge=1, le=5)

    @validator('rating')
    def validate_rating(cls, v):
        if not 1 <= v <= 5:
            raise ValueError('Rating must be between 1 and 5')
        return v

class WebhookRatingCreate(WebhookRatingBase):
    pass

class WebhookRatingOut(WebhookRatingBase):
    id: int
    webhook_id: str
    user_id: int
    rated_at: datetime

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

class WebhookOut(WebhookBase):
    id: int
    token: str  
    user_id: int
    secret_key: str
    is_active: bool
    is_shared: bool = False
    created_at: datetime
    last_triggered: Optional[datetime] = None  
    webhook_url: str
    subscriber_count: Optional[int] = 0
    rating: Optional[float] = 0.0
    username: Optional[str] = None  # Added to include user's username

    class Config:
        from_attributes = True

class WebhookStatistics(BaseModel):
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_processing_time: float
    last_execution: Optional[datetime]
    subscriber_count: int
    average_rating: float

    class Config:
        from_attributes = True

class SharedStrategyOut(WebhookOut):
    author_username: str
    subscriber_count: int
    rating: float
    strategy_details: Optional[str] = None

    class Config:
        from_attributes = True

class WebhookShareUpdate(BaseModel):
    isActive: bool
    description: Optional[str] = None
    strategyType: Optional[StrategyType] = None

    class Config:
        from_attributes = True