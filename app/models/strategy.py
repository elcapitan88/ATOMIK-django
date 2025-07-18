from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, Numeric, Table, UniqueConstraint
from sqlalchemy.orm import relationship, attribute_mapped_collection, backref
from datetime import datetime
import uuid
import logging
from typing import List, Optional, Dict, Any, Union
from decimal import Decimal
from ..db.base_class import Base
from .user import User
import json
from .broker import BrokerAccount

logger = logging.getLogger(__name__)

# Association table for strategy followers with quantities
strategy_follower_quantities = Table(
    'strategy_follower_quantities',
    Base.metadata,
    Column('strategy_id', Integer, ForeignKey('activated_strategies.id', ondelete="CASCADE")),
    Column('account_id', String, ForeignKey('broker_accounts.account_id', ondelete="CASCADE")),
    Column('quantity', Integer, nullable=False),
    UniqueConstraint('strategy_id', 'account_id', name='unique_strategy_follower')
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
    webhook_id = Column(String(64), ForeignKey("webhooks.token"), index=True)
    ticker = Column(String(10), nullable=False)

    # Single Strategy Fields
    account_id = Column(String, ForeignKey("broker_accounts.account_id", ondelete="CASCADE"))
    quantity = Column(Integer, nullable=True)

    # Multiple Strategy Fields
    leader_account_id = Column(String, ForeignKey("broker_accounts.account_id"), nullable=True)
    leader_quantity = Column(Integer, nullable=True)
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
    webhook = relationship(
        "Webhook",
        primaryjoin="ActivatedStrategy.webhook_id == Webhook.token",
        foreign_keys=[webhook_id],  # Add this line
        back_populates="strategies"
    )

    
    # Updated relationship for followers with quantities
    follower_accounts_with_quantities = relationship(
        "BrokerAccount",
        secondary=strategy_follower_quantities,
        backref="following_strategies_with_quantities",
        lazy="joined"  # This ensures quantities are loaded with the query
    )
    
    orders = relationship("Order", back_populates="strategy", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="strategy", cascade="all, delete-orphan")
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.webhook_id = str(uuid.uuid4()) if 'webhook_id' not in kwargs else kwargs['webhook_id']

    def add_follower_with_quantity(self, account: BrokerAccount, quantity: int) -> None:
        """Helper method to add a follower with its quantity
        
        Args:
            account (BrokerAccount): The follower account to add
            quantity (int): The quantity for this follower
            
        Raises:
            ValueError: If account is already a follower or if quantity is invalid
            TypeError: If invalid account type is provided
        """
        try:
            # Input validation
            if not isinstance(account, BrokerAccount):
                raise TypeError("account must be a BrokerAccount instance")
                
            if not isinstance(quantity, int) or quantity <= 0:
                raise ValueError("quantity must be a positive integer")
                
            # Check if account is leader account
            if account.id == self.leader_account_id:
                raise ValueError("Leader account cannot be added as a follower")
            
            # Check if account is already a follower
            existing = self.follower_accounts_with_quantities.get(account.id)
            if existing is not None:
                raise ValueError(f"Account {account.id} is already a follower")

            # Create the insert statement for the association table
            insert_stmt = strategy_follower_quantities.insert().values(
                strategy_id=self.id,
                account_id=account.id,
                quantity=quantity
            )
            
            return insert_stmt

        except Exception as e:
            logger.error(f"Error adding follower account {account.id}: {str(e)}")
            raise ValueError(f"Failed to add follower account: {str(e)}")

    def update_follower_quantity(self, account: BrokerAccount, quantity: int) -> None:
        """Update the quantity for a specific follower account."""
        if account.id not in self.follower_accounts_with_quantities:
            raise ValueError("Account is not a follower of this strategy")
        
        # Update the quantity in the association table
        stmt = strategy_follower_quantities.update().where(
            strategy_follower_quantities.c.strategy_id == self.id,
            strategy_follower_quantities.c.account_id == account.id
        ).values(quantity=quantity)
        # Note: This needs to be executed within a session
        return stmt

    def remove_follower(self, account: BrokerAccount) -> None:
        """Remove a follower account from the strategy."""
        if account.id not in self.follower_accounts_with_quantities:
            raise ValueError("Account is not a follower of this strategy")
        
        # Remove from the follower accounts
        stmt = strategy_follower_quantities.delete().where(
            strategy_follower_quantities.c.strategy_id == self.id,
            strategy_follower_quantities.c.account_id == account.id
        )
        # Note: This needs to be executed within a session
        return stmt

    def get_follower_quantities(self) -> Dict[int, int]:
        """Get a dictionary of follower account IDs and their quantities."""
        return {
            account_id: relationship['quantity']
            for account_id, relationship in self.follower_accounts_with_quantities.items()
        }
    
    def validate_follower_accounts(self) -> bool:
        """Validate follower accounts and their quantities"""
        try:
            for follower_id in self.follower_accounts_with_quantities:
                if not self.follower_accounts_with_quantities.get(follower_id):
                    logger.error(f"Missing quantity data for follower {follower_id}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error validating follower accounts: {str(e)}")
            return False

    def update_stats(self, trade_result: bool, pnl: Optional[float] = 0) -> None:
        """Update strategy statistics after a trade."""
        try:
            self.total_trades = (self.total_trades or 0) + 1
            if trade_result:
                self.successful_trades = (self.successful_trades or 0) + 1
            else:
                self.failed_trades = (self.failed_trades or 0) + 1
            
            if pnl is not None:
                self.total_pnl = (self.total_pnl or Decimal('0')) + Decimal(str(pnl))
            
            if self.total_trades > 0:
                self.win_rate = Decimal(str(self.successful_trades / self.total_trades * 100))
        except Exception as e:
            logger.error(f"Error updating strategy stats: {str(e)}")

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

    def get_broker_settings(self) -> dict:
        """Get broker-specific settings as a dictionary."""
        if self.broker_settings:
            try:
                return json.loads(self.broker_settings)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def get_follower_accounts(self) -> List[dict]:
        follower_data = []
        try:
            # Convert account_id to string when querying
            for follower_account in self.follower_accounts_with_quantities:
                follower_data.append({
                    'account_id': str(follower_account.account_id),  # Ensure string type
                    'quantity': self.get_follower_quantity(follower_account.account_id)
                })
            return follower_data
        except Exception as e:
            logger.error(f"Error getting follower accounts for strategy {self.id}: {str(e)}")
            return []

    def get_follower_quantity(self, account_id: Union[int, str]) -> int:
        """
        Get the quantity for a specific follower account
        """
        try:
            # Convert account_id to string
            account_id_str = str(account_id)
            
            result = self._sa_instance_state.session.query(strategy_follower_quantities).filter_by(
                strategy_id=self.id,
                account_id=account_id_str  # Use string version
            ).first()
            
            if result:
                return result.quantity
            return 0
        except Exception as e:
            self._sa_instance_state.session.rollback()  # Roll back on error
            logger.error(f"Error getting follower quantity: {str(e)}")
            return 0

    def __str__(self):
        return f"Strategy {self.id} - {self.ticker} ({self.strategy_type})"

    def __repr__(self):
        return f"<ActivatedStrategy(id={self.id}, type={self.strategy_type}, ticker={self.ticker})>"