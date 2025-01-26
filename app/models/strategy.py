from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, Numeric, Table
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from typing import List, Optional
from decimal import Decimal
from ..db.base_class import Base
from .user import User
import json
from .broker import BrokerAccount

# Association table for strategy followers
strategy_followers = Table(
    'strategy_followers',
    Base.metadata,
    Column('strategy_id', Integer, ForeignKey('activated_strategies.id')),
    Column('account_id', Integer, ForeignKey('broker_accounts.id'))
)

class ActivatedStrategy(Base):
    """Model for storing activated trading strategies."""
    __tablename__ = "activated_strategies"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # User Reference
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))

    # Strategy Type and Configuration
    strategy_type = Column(String(20), nullable=False)  # 'single' or 'multiple'
    webhook_id = Column(String(64), index=True)
    ticker = Column(String(10), nullable=False)

    # Single Strategy Fields
    account_id = Column(Integer, ForeignKey("broker_accounts.id"), nullable=True)
    quantity = Column(Integer, nullable=True)

    # Multiple Strategy Fields
    leader_account_id = Column(Integer, ForeignKey("broker_accounts.id"), nullable=True)
    leader_quantity = Column(Integer, nullable=True)
    follower_quantity = Column(Integer, nullable=True)
    group_name = Column(String(100), nullable=True)

    # Status and Timestamps
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_triggered = Column(DateTime, nullable=True)

    # Strategy Performance Stats
    total_trades = Column(Integer, default=0)
    successful_trades = Column(Integer, default=0)
    failed_trades = Column(Integer, default=0)
    total_pnl = Column(Numeric(10, 2), default=0)
    max_drawdown = Column(Numeric(10, 2), nullable=True)
    win_rate = Column(Numeric(5, 2), nullable=True)
    average_win = Column(Numeric(10, 2), nullable=True)
    average_loss = Column(Numeric(10, 2), nullable=True)
    risk_reward_ratio = Column(Numeric(5, 2), nullable=True)
    sharpe_ratio = Column(Numeric(5, 2), nullable=True)

    # Risk Management
    max_position_size = Column(Integer, nullable=True)
    stop_loss_percent = Column(Numeric(5, 2), nullable=True)
    take_profit_percent = Column(Numeric(5, 2), nullable=True)
    max_daily_loss = Column(Numeric(10, 2), nullable=True)
    max_drawdown_limit = Column(Numeric(5, 2), nullable=True)

    # Additional Settings
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)  # Comma-separated tags
    custom_settings = Column(Text, nullable=True)  # JSON string for custom settings

    # Broker Settings
    broker_id = Column(String(50), nullable=True)  # Identifier for the broker
    broker_settings = Column(Text, nullable=True)  # JSON string for broker-specific settings

    # Relationships
    user = relationship("User", back_populates="strategies")
    follower_accounts = relationship(
        "BrokerAccount",
        secondary=strategy_followers,
        backref="following_strategies"
    )
    trades = relationship("Order", back_populates="strategy", cascade="all, delete-orphan")
    broker_account = relationship(
        "BrokerAccount",
        foreign_keys=[account_id],
        backref="strategies"
    )
    leader_broker_account = relationship(
        "BrokerAccount",
        foreign_keys=[leader_account_id],
        backref="leader_strategies"
    )
    class Config:
        orm_mode = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.webhook_id = str(uuid.uuid4()) if 'webhook_id' not in kwargs else kwargs['webhook_id']

    def update_stats(self, trade_result: bool, pnl: float) -> None:
        """Update strategy statistics after a trade."""
        self.total_trades += 1
        if trade_result:
            self.successful_trades += 1
        else:
            self.failed_trades += 1
        
        self.total_pnl += pnl
        
        if self.total_trades > 0:
            self.win_rate = (self.successful_trades / self.total_trades) * 100

    def get_performance_metrics(self) -> dict:
        """Get comprehensive performance metrics."""
        return {
            'total_trades': self.total_trades,
            'successful_trades': self.successful_trades,
            'failed_trades': self.failed_trades,
            'win_rate': float(self.win_rate) if self.win_rate else 0,
            'total_pnl': float(self.total_pnl),
            'average_win': float(self.average_win) if self.average_win else 0,
            'average_loss': float(self.average_loss) if self.average_loss else 0,
            'risk_reward_ratio': float(self.risk_reward_ratio) if self.risk_reward_ratio else 0,
            'max_drawdown': float(self.max_drawdown) if self.max_drawdown else 0,
            'sharpe_ratio': float(self.sharpe_ratio) if self.sharpe_ratio else 0
        }

    def get_risk_parameters(self) -> dict:
        """Get risk management parameters."""
        return {
            'max_position_size': self.max_position_size,
            'stop_loss_percent': float(self.stop_loss_percent) if self.stop_loss_percent else None,
            'take_profit_percent': float(self.take_profit_percent) if self.take_profit_percent else None,
            'max_daily_loss': float(self.max_daily_loss) if self.max_daily_loss else None,
            'max_drawdown_limit': float(self.max_drawdown_limit) if self.max_drawdown_limit else None
        }

    def is_within_risk_limits(self, position_size: int, potential_loss: float) -> bool:
        """Check if a trade is within risk management parameters."""
        if self.max_position_size and position_size > self.max_position_size:
            return False
            
        if self.max_daily_loss and potential_loss > float(self.max_daily_loss):
            return False
            
        return True

    def get_tags(self) -> List[str]:
        """Get strategy tags as a list."""
        return [tag.strip() for tag in self.tags.split(',')] if self.tags else []

    def get_broker_settings(self) -> dict:
        """Get broker-specific settings as a dictionary."""
        if self.broker_settings:
            try:
                return json.loads(self.broker_settings)
            except json.JSONDecodeError:
                return {}
        return {}

    def __str__(self):
        return f"Strategy {self.id} - {self.ticker} ({self.strategy_type})"

    def __repr__(self):
        return f"<ActivatedStrategy(id={self.id}, type={self.strategy_type}, ticker={self.ticker})>"