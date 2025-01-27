from pydantic import BaseModel, UUID4, validator, Field
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum
from decimal import Decimal

class StrategyType(str, Enum):
    """Enumeration of strategy types"""
    SINGLE = "single"
    MULTIPLE = "multiple"

class SingleStrategyCreate(BaseModel):
    """Schema for creating a single account strategy"""
    strategy_type: Literal[StrategyType.SINGLE]
    webhook_id: str = Field(..., description="Webhook token")
    ticker: str = Field(..., min_length=1, max_length=10)
    account_id: str = Field(..., description="Trading account identifier")
    quantity: int = Field(..., gt=0, description="Trading quantity")

    class Config:
        schema_extra = {
            "example": {
                "strategy_type": "single",
                "webhook_id": "123e4567-e89b-12d3-a456-426614174000",
                "ticker": "AAPL",
                "account_id": "12345",
                "quantity": 100
            }
        }

    @validator('ticker')
    def validate_ticker(cls, v):
        if not v.isalnum():
            raise ValueError('Ticker must be alphanumeric')
        return v.upper()

class MultipleStrategyCreate(BaseModel):
    """Schema for creating a multiple account (group) strategy"""
    strategy_type: Literal[StrategyType.MULTIPLE]
    webhook_id: str = Field(..., description="Webhook token")
    ticker: str = Field(..., min_length=1, max_length=10)
    leader_account_id: str = Field(..., description="Leader account identifier")
    leader_quantity: int = Field(..., gt=0)
    follower_account_ids: List[str] = Field(..., min_items=1)
    follower_quantities: List[int] = Field(..., min_items=1)
    group_name: str = Field(..., min_length=1, max_length=100)

    class Config:
        schema_extra = {
            "example": {
                "strategy_type": "multiple",
                "webhook_id": "123e4567-e89b-12d3-a456-426614174000",
                "ticker": "AAPL",
                "leader_account_id": "12345",
                "leader_quantity": 100,
                "follower_quantity": 50,
                "group_name": "My Group Strategy",
                "follower_account_ids": ["67890", "11111"]
            }
        }

    @validator('ticker')
    def validate_ticker(cls, v):
        if not v.isalnum():
            raise ValueError('Ticker must be alphanumeric')
        return v.upper()

    @validator('follower_account_ids')
    def validate_follower_accounts(cls, v, values):
        if 'leader_account_id' in values and values['leader_account_id'] in v:
            raise ValueError('Leader account cannot be in follower accounts')
        if len(set(v)) != len(v):
            raise ValueError('Duplicate follower accounts are not allowed')
        return v
    
    @validator('follower_quantities')
    def validate_quantities(cls, v, values):
        if 'follower_account_ids' in values:
            if len(v) != len(values['follower_account_ids']):
                raise ValueError('Number of quantities must match number of follower accounts')
            if not all(q > 0 for q in v):
                raise ValueError('All quantities must be greater than 0')
        return v

    @validator('group_name')
    def validate_group_name(cls, v):
        if not v.strip():
            raise ValueError('Group name cannot be empty')
        return v.strip()

class StrategyUpdate(BaseModel):
    """Schema for updating an existing strategy"""
    is_active: Optional[bool] = None
    quantity: Optional[int] = Field(None, gt=0)
    leader_quantity: Optional[int] = Field(None, gt=0)
    follower_quantity: Optional[int] = Field(None, gt=0)

    class Config:
        schema_extra = {
            "example": {
                "is_active": True,
                "quantity": 150,
                "leader_quantity": 150,
                "follower_quantity": 75
            }
        }

class StrategyStats(BaseModel):
    """Statistics for a strategy"""
    total_trades: int = Field(default=0, ge=0)
    successful_trades: int = Field(default=0, ge=0)
    failed_trades: int = Field(default=0, ge=0)
    total_pnl: Decimal = Field(default=Decimal('0.00'))
    win_rate: Optional[float] = Field(None, ge=0, le=100)
    average_trade_pnl: Optional[Decimal] = None

    @validator('win_rate', always=True)
    def calculate_win_rate(cls, v, values):
        if 'total_trades' in values and values['total_trades'] > 0:
            return (values['successful_trades'] / values['total_trades']) * 100
        return None

    @validator('average_trade_pnl', always=True)
    def calculate_average_pnl(cls, v, values):
        if 'total_trades' in values and values['total_trades'] > 0:
            return values['total_pnl'] / Decimal(str(values['total_trades']))
        return None

class StrategyInDB(BaseModel):
    """Schema for strategy data as stored in database"""
    id: int
    user_id: int
    strategy_type: StrategyType
    webhook_id: str = Field(..., description="Webhook token")
    ticker: str
    account_id: Optional[str]
    quantity: Optional[int]
    leader_account_id: Optional[str]
    leader_quantity: Optional[int]
    follower_quantity: Optional[int]
    group_name: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_triggered: Optional[datetime]
    stats: Optional[StrategyStats]

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: str(v)
        }

class StrategyResponse(BaseModel):
    """Schema for strategy response to client"""
    id: int
    strategy_type: StrategyType
    webhook_id: str = Field(..., description="Webhook token")
    ticker: str
    is_active: bool
    created_at: datetime
    last_triggered: Optional[datetime]
    stats: Optional[StrategyStats] = None
    
    # Single strategy fields
    account_id: Optional[str] = None
    quantity: Optional[int] = None
    
    # Multiple strategy fields
    leader_account_id: Optional[str] = None
    leader_quantity: Optional[int] = None
    follower_quantity: Optional[int] = None
    group_name: Optional[str] = None
    follower_account_ids: Optional[List[str]] = None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID4: lambda v: str(v),
            Decimal: lambda v: str(v)
        }