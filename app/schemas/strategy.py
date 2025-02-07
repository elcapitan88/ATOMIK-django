from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Union, Literal
from datetime import datetime
from decimal import Decimal
from enum import Enum

class StrategyType(str, Enum):
    """Enumeration of strategy types"""
    SINGLE = "single"
    MULTIPLE = "multiple"

from pydantic import BaseModel, Field, validator, ConfigDict
from typing import Optional
from decimal import Decimal

class StrategyStats(BaseModel):
    """
    Statistics model for tracking strategy performance metrics
    """
    model_config = ConfigDict(
        from_attributes=True,  # Allow ORM model parsing
        json_encoders={Decimal: str}  # Handle Decimal serialization
    )

    # Core metrics
    total_trades: int = Field(
        default=0,
        ge=0,
        description="Total number of trades executed"
    )
    successful_trades: int = Field(
        default=0,
        ge=0,
        description="Number of profitable trades"
    )
    failed_trades: int = Field(
        default=0,
        ge=0,
        description="Number of unprofitable trades"
    )
    total_pnl: Decimal = Field(
        default=Decimal('0.00'),
        description="Total profit and loss"
    )
    
    # Calculated metrics
    win_rate: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Percentage of successful trades"
    )
    average_trade_pnl: Optional[Decimal] = Field(
        None,
        description="Average profit/loss per trade"
    )
    
    # Advanced metrics
    max_drawdown: Optional[Decimal] = Field(
        None,
        description="Maximum observed drawdown"
    )
    sharpe_ratio: Optional[float] = Field(
        None,
        description="Risk-adjusted return metric"
    )
    risk_reward_ratio: Optional[float] = Field(
        None,
        ge=0,
        description="Average risk/reward ratio"
    )
    average_win: Optional[Decimal] = Field(
        None,
        description="Average profit on winning trades"
    )
    average_loss: Optional[Decimal] = Field(
        None,
        description="Average loss on losing trades"
    )
    longest_win_streak: Optional[int] = Field(
        None,
        ge=0,
        description="Longest consecutive winning trades"
    )
    longest_loss_streak: Optional[int] = Field(
        None,
        ge=0,
        description="Longest consecutive losing trades"
    )

    @validator('win_rate', always=True)
    def calculate_win_rate(cls, v, values):
        """Calculate win rate if not provided"""
        if v is not None:
            return v
        if values.get('total_trades', 0) > 0:
            return (values.get('successful_trades', 0) / values['total_trades']) * 100
        return None

    @validator('average_trade_pnl', always=True)
    def calculate_average_pnl(cls, v, values):
        """Calculate average trade PnL if not provided"""
        if v is not None:
            return v
        if values.get('total_trades', 0) > 0:
            return values.get('total_pnl', Decimal('0')) / Decimal(str(values['total_trades']))
        return None

    def dict(self, *args, **kwargs):
        """Convert model to dictionary with proper float conversion"""
        d = super().dict(*args, **kwargs)
        # Convert Decimal values to float for JSON serialization
        decimal_fields = [
            'total_pnl', 'average_trade_pnl', 'max_drawdown',
            'average_win', 'average_loss'
        ]
        for field in decimal_fields:
            if field in d and d[field] is not None:
                d[field] = float(d[field])
        return d

    def update_from_trade(self, is_successful: bool, pnl: Decimal):
        """Update statistics with new trade result"""
        self.total_trades += 1
        if is_successful:
            self.successful_trades += 1
        else:
            self.failed_trades += 1
        
        self.total_pnl += pnl
        
        # Recalculate derived metrics
        if self.total_trades > 0:
            self.win_rate = (self.successful_trades / self.total_trades) * 100
            self.average_trade_pnl = self.total_pnl / Decimal(str(self.total_trades))

    @classmethod
    def create_empty(cls):
        """Create an empty stats instance with default values"""
        return cls(
            total_trades=0,
            successful_trades=0,
            failed_trades=0,
            total_pnl=Decimal('0.00'),
            win_rate=None,
            average_trade_pnl=None
        )
    
    def reset(self):
        """Reset all statistics to default values"""
        self.total_trades = 0
        self.successful_trades = 0
        self.failed_trades = 0
        self.total_pnl = Decimal('0.00')
        self.win_rate = None
        self.average_trade_pnl = None
        self.max_drawdown = None
        self.sharpe_ratio = None
        self.risk_reward_ratio = None
        self.average_win = None
        self.average_loss = None
        self.longest_win_streak = None
        self.longest_loss_streak = None

    def to_summary_dict(self):
        """Return a simplified dictionary with core metrics"""
        return {
            "total_trades": self.total_trades,
            "successful_trades": self.successful_trades,
            "failed_trades": self.failed_trades,
            "total_pnl": float(self.total_pnl),
            "win_rate": self.win_rate,
            "average_trade_pnl": float(self.average_trade_pnl) if self.average_trade_pnl else None
        }

class SingleStrategyCreate(BaseModel):
    """Schema for creating a single account strategy"""
    strategy_type: Literal[StrategyType.SINGLE]
    webhook_id: str = Field(..., description="Webhook token")
    ticker: str = Field(..., min_length=1, max_length=10)
    account_id: str = Field(..., description="Trading account identifier")
    quantity: int = Field(..., gt=0, description="Trading quantity")

    @validator('ticker')
    def validate_ticker(cls, v):
        if not v.isalnum():
            raise ValueError('Ticker must be alphanumeric')
        return v.upper()

    class Config:
        schema_extra = {
            "example": {
                "strategy_type": "single",
                "webhook_id": "123e4567-e89b-12d3-a456-426614174000",
                "ticker": "ES",
                "account_id": "TV12345",
                "quantity": 1
            }
        }

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

    class Config:
        schema_extra = {
            "example": {
                "strategy_type": "multiple",
                "webhook_id": "123e4567-e89b-12d3-a456-426614174000",
                "ticker": "ES",
                "leader_account_id": "TV12345",
                "leader_quantity": 1,
                "follower_account_ids": ["TV67890", "TV11111"],
                "follower_quantities": [1, 1],
                "group_name": "My Group Strategy"
            }
        }

class StrategyUpdate(BaseModel):
    """Schema for updating an existing strategy"""
    is_active: Optional[bool] = None
    quantity: Optional[int] = Field(None, gt=0)
    leader_quantity: Optional[int] = Field(None, gt=0)
    follower_quantities: Optional[List[int]] = Field(None, min_items=1)

    @validator('follower_quantities')
    def validate_quantities(cls, v):
        if v is not None and not all(q > 0 for q in v):
            raise ValueError('All quantities must be greater than 0')
        return v

    class Config:
        schema_extra = {
            "example": {
                "is_active": True,
                "quantity": 2,
                "leader_quantity": 2,
                "follower_quantities": [1, 1]
            }
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
    
    # Webhook details
    webhook: Optional[dict] = Field(None, example={
        "name": "TradingView Alert",
        "source_type": "tradingview"
    })
    
    # Stats
    stats: Optional[dict] = Field(None, example={
        "total_trades": 0,
        "successful_trades": 0,
        "failed_trades": 0,
        "total_pnl": "0.00",
        "win_rate": None,
        "average_trade_pnl": None
    })
    
    # Single strategy fields
    account_id: Optional[str] = Field(None, description="Trading account identifier")
    quantity: Optional[int] = Field(None, description="Trading quantity")
    broker_account: Optional[dict] = Field(None, example={
        "account_id": "TV12345",
        "name": "Trading Account 1",
        "broker_id": "tradovate"
    })
    
    # Multiple strategy fields
    leader_account_id: Optional[str] = Field(None, description="Leader account identifier")
    leader_quantity: Optional[int] = Field(None, description="Leader trading quantity")
    group_name: Optional[str] = Field(None, description="Group strategy name")
    leader_broker_account: Optional[dict] = Field(None, example={
        "account_id": "TV12345",
        "name": "Leader Account",
        "broker_id": "tradovate"
    })
    follower_accounts: Optional[List[dict]] = Field(None, example=[{
        "account_id": "TV67890",
        "quantity": 1
    }])
    
    @validator('webhook_id')
    def validate_webhook_id(cls, v):
        if not v:
            raise ValueError('webhook_id cannot be empty')
        return v

    @validator('ticker')
    def validate_ticker(cls, v):
        if not v:
            raise ValueError('ticker cannot be empty')
        return v.upper()

    @validator('stats', pre=True)
    def ensure_stats_dict(cls, v):
        if v is None:
            return {
                "total_trades": 0,
                "successful_trades": 0,
                "failed_trades": 0,
                "total_pnl": "0.00",
                "win_rate": None,
                "average_trade_pnl": None
            }
        return v

    @validator('group_name')
    def validate_group_name(cls, v, values):
        if values.get('strategy_type') == StrategyType.MULTIPLE and not v:
            raise ValueError('group_name is required for multiple strategies')
        return v

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: str(v)
        }

class StrategyInDB(BaseModel):
    """Schema for strategy data as stored in database"""
    id: int
    user_id: int
    strategy_type: StrategyType
    webhook_id: str
    ticker: str
    account_id: Optional[str]
    quantity: Optional[int]
    leader_account_id: Optional[str]
    leader_quantity: Optional[int]
    follower_quantities: Optional[List[int]]
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