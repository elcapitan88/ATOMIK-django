from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, Numeric, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from ..db.base_class import Base


class Trade(Base):
    """Model for storing trade records from position lifecycle events."""
    __tablename__ = "trades"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # User and Strategy Association
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    strategy_id = Column(Integer, ForeignKey("activated_strategies.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Position Identification
    position_id = Column(String(50), nullable=False, unique=True, index=True)  # Unique constraint to prevent duplicates
    broker_id = Column(String(50), nullable=False, index=True)  # e.g., "tradovate"
    
    # Instrument Details
    symbol = Column(String(20), nullable=False, index=True)  # e.g., "MES", "NQ"
    contract_id = Column(Integer, nullable=True)  # Broker-specific contract ID
    
    # Trade Direction and Sizing
    side = Column(String(10), nullable=False)  # "BUY" or "SELL"
    total_quantity = Column(Integer, nullable=False)  # Total position size
    
    # Pricing Information
    average_entry_price = Column(Numeric(12, 4), nullable=False)  # Average fill price
    exit_price = Column(Numeric(12, 4), nullable=True)  # Exit price when closed
    
    # P&L Tracking
    realized_pnl = Column(Numeric(12, 2), nullable=True)  # Final P&L when closed
    max_unrealized_pnl = Column(Numeric(12, 2), nullable=True)  # Peak unrealized profit
    max_adverse_pnl = Column(Numeric(12, 2), nullable=True)  # Maximum unrealized loss
    
    # Trade Lifecycle
    status = Column(String(20), nullable=False, default="open", index=True)  # "open", "closed", "partially_closed"
    open_time = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    close_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)  # Trade duration in seconds
    
    # Risk Management
    stop_loss_price = Column(Numeric(12, 4), nullable=True)
    take_profit_price = Column(Numeric(12, 4), nullable=True)
    
    # Additional Metadata
    broker_data = Column(Text, nullable=True)  # JSON string for broker-specific data
    notes = Column(Text, nullable=True)
    tags = Column(String(500), nullable=True)  # Comma-separated tags
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="trades")
    strategy = relationship("ActivatedStrategy", back_populates="trades")
    executions = relationship("TradeExecution", back_populates="trade", cascade="all, delete-orphan")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_trades_user_strategy', 'user_id', 'strategy_id'),
        Index('idx_trades_symbol_time', 'symbol', 'open_time'),
        Index('idx_trades_status_time', 'status', 'open_time'),
        Index('idx_trades_user_time', 'user_id', 'open_time'),
    )
    
    def update_pnl_metrics(self, current_unrealized_pnl: float) -> None:
        """Update P&L tracking metrics during trade lifecycle."""
        try:
            current_pnl = Decimal(str(current_unrealized_pnl))
            
            # Update max unrealized profit
            if self.max_unrealized_pnl is None or current_pnl > self.max_unrealized_pnl:
                self.max_unrealized_pnl = current_pnl
            
            # Update max adverse (loss) - track most negative value
            if self.max_adverse_pnl is None or current_pnl < self.max_adverse_pnl:
                self.max_adverse_pnl = current_pnl
                
        except (ValueError, TypeError) as e:
            # Log error but don't raise to prevent disrupting trade flow
            pass
    
    def close_trade(self, exit_price: float, realized_pnl: float, close_time: Optional[datetime] = None) -> None:
        """Close the trade and calculate final metrics."""
        self.exit_price = Decimal(str(exit_price))
        self.realized_pnl = Decimal(str(realized_pnl))
        self.close_time = close_time or datetime.utcnow()
        self.status = "closed"
        
        # Calculate duration
        if self.open_time and self.close_time:
            duration = self.close_time - self.open_time
            self.duration_seconds = int(duration.total_seconds())
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive trade performance data."""
        return {
            'trade_id': self.id,
            'position_id': self.position_id,
            'symbol': self.symbol,
            'side': self.side,
            'quantity': self.total_quantity,
            'entry_price': float(self.average_entry_price),
            'exit_price': float(self.exit_price) if self.exit_price else None,
            'realized_pnl': float(self.realized_pnl) if self.realized_pnl else None,
            'max_unrealized_pnl': float(self.max_unrealized_pnl) if self.max_unrealized_pnl else None,
            'max_adverse_pnl': float(self.max_adverse_pnl) if self.max_adverse_pnl else None,
            'status': self.status,
            'open_time': self.open_time.isoformat() if self.open_time else None,
            'close_time': self.close_time.isoformat() if self.close_time else None,
            'duration_seconds': self.duration_seconds,
            'strategy_id': self.strategy_id,
            'broker_id': self.broker_id
        }
    
    def is_profitable(self) -> Optional[bool]:
        """Check if trade is profitable. Returns None if trade is still open."""
        if self.status != "closed" or self.realized_pnl is None:
            return None
        return self.realized_pnl > 0
    
    def __str__(self):
        return f"Trade {self.id} - {self.symbol} {self.side} {self.total_quantity} @ {self.average_entry_price}"
    
    def __repr__(self):
        return f"<Trade(id={self.id}, symbol={self.symbol}, side={self.side}, status={self.status})>"


class TradeExecution(Base):
    """Model for tracking individual account executions within a trade (for network strategies)."""
    __tablename__ = "trade_executions"
    
    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Trade Association
    trade_id = Column(Integer, ForeignKey("trades.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Account Details
    broker_account_id = Column(String, ForeignKey("broker_accounts.account_id", ondelete="CASCADE"), nullable=False)
    account_role = Column(String(20), nullable=False)  # "leader", "follower"
    
    # Execution Details
    quantity = Column(Integer, nullable=False)  # Account-specific quantity
    execution_price = Column(Numeric(12, 4), nullable=False)  # Account-specific fill price
    execution_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # P&L for this specific execution
    realized_pnl = Column(Numeric(12, 2), nullable=True)  # P&L for this account
    
    # Broker-specific execution data
    execution_id = Column(String(100), nullable=True)  # Broker's execution ID
    commission = Column(Numeric(8, 2), nullable=True)
    fees = Column(Numeric(8, 2), nullable=True)
    
    # Metadata
    broker_data = Column(Text, nullable=True)  # JSON string for broker-specific data
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    trade = relationship("Trade", back_populates="executions")
    broker_account = relationship("BrokerAccount")
    
    # Indexes
    __table_args__ = (
        Index('idx_executions_trade_account', 'trade_id', 'broker_account_id'),
        Index('idx_executions_time', 'execution_time'),
    )
    
    def get_net_pnl(self) -> Optional[Decimal]:
        """Get net P&L after commissions and fees."""
        if self.realized_pnl is None:
            return None
            
        net_pnl = self.realized_pnl
        if self.commission:
            net_pnl -= self.commission
        if self.fees:
            net_pnl -= self.fees
            
        return net_pnl
    
    def __str__(self):
        return f"Execution {self.id} - Account {self.broker_account_id} ({self.account_role}): {self.quantity} @ {self.execution_price}"
    
    def __repr__(self):
        return f"<TradeExecution(id={self.id}, trade_id={self.trade_id}, account={self.broker_account_id})>"