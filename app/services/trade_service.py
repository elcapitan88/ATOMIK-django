"""
Trade Service for managing trade lifecycle and database operations.
Handles conversion of WebSocket position events to persistent trade records.
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from ..models.trade import Trade, TradeExecution
from ..models.strategy import ActivatedStrategy
from ..models.user import User
from ..models.order import Order

logger = logging.getLogger(__name__)


class TradeService:
    """Service for managing trade lifecycle and database operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def create_trade(
        self,
        user_id: int,
        position_data: Dict[str, Any],
        strategy_id: Optional[int] = None
    ) -> Optional[Trade]:
        """
        Create a new trade record from position opened event.
        
        Args:
            user_id: User ID who owns the trade
            position_data: Position data from WebSocket event
            strategy_id: Optional strategy ID for attribution
            
        Returns:
            Created Trade object or None if failed
        """
        try:
            # Extract required fields from position data
            position_id = str(position_data.get('position_id'))
            if not position_id:
                logger.error("No position_id found in position data")
                return None
            
            # Check if trade already exists (prevent duplicates)
            existing_trade = self.db.query(Trade).filter(
                Trade.position_id == position_id
            ).first()
            
            if existing_trade:
                logger.warning(f"Trade already exists for position_id: {position_id}")
                return existing_trade
            
            # Determine strategy attribution
            if not strategy_id:
                strategy_id = await self._determine_strategy_attribution(user_id, position_data)
            
            # Create new trade record
            trade = Trade(
                user_id=user_id,
                strategy_id=strategy_id,
                position_id=position_id,
                broker_id=position_data.get('broker_id', 'unknown'),
                symbol=position_data.get('symbol', ''),
                contract_id=position_data.get('contract_id'),
                side="BUY" if position_data.get('net_pos', 0) > 0 else "SELL",
                total_quantity=abs(position_data.get('net_pos', 0)),
                average_entry_price=Decimal(str(position_data.get('average_price', 0))),
                status="open",
                open_time=datetime.utcnow(),
                broker_data=str(position_data) if position_data else None
            )
            
            self.db.add(trade)
            self.db.commit()
            self.db.refresh(trade)
            
            logger.info(f"Created trade {trade.id} for position {position_id}")
            return trade
            
        except Exception as e:
            logger.error(f"Error creating trade: {str(e)}", exc_info=True)
            self.db.rollback()
            return None
    
    async def update_trade_entry(
        self,
        position_id: str,
        position_data: Dict[str, Any]
    ) -> Optional[Trade]:
        """
        Update existing trade with modified position data (averaging in).
        
        Args:
            position_id: Position ID to find the trade
            position_data: Updated position data from WebSocket
            
        Returns:
            Updated Trade object or None if not found
        """
        try:
            trade = self.db.query(Trade).filter(
                Trade.position_id == position_id,
                Trade.status == "open"
            ).first()
            
            if not trade:
                logger.warning(f"No open trade found for position_id: {position_id}")
                return None
            
            # Update trade with new position data
            new_quantity = abs(position_data.get('net_pos', 0))
            new_avg_price = position_data.get('average_price', 0)
            
            if new_quantity != trade.total_quantity:
                trade.total_quantity = new_quantity
                trade.average_entry_price = Decimal(str(new_avg_price))
                trade.updated_at = datetime.utcnow()
                
                # Update P&L metrics if current price available
                current_pnl = position_data.get('unrealized_pnl', 0)
                if current_pnl is not None:
                    trade.update_pnl_metrics(float(current_pnl))
                
                self.db.commit()
                self.db.refresh(trade)
                
                logger.info(f"Updated trade {trade.id} - new qty: {new_quantity}, avg price: {new_avg_price}")
            
            return trade
            
        except Exception as e:
            logger.error(f"Error updating trade entry: {str(e)}", exc_info=True)
            self.db.rollback()
            return None
    
    async def close_trade(
        self,
        position_id: str,
        position_data: Dict[str, Any]
    ) -> Optional[Trade]:
        """
        Close a trade and calculate final P&L.
        
        Args:
            position_id: Position ID to find the trade
            position_data: Final position data from WebSocket
            
        Returns:
            Closed Trade object or None if not found
        """
        try:
            trade = self.db.query(Trade).filter(
                Trade.position_id == position_id,
                Trade.status == "open"
            ).first()
            
            if not trade:
                logger.warning(f"No open trade found for position_id: {position_id}")
                return None
            
            # Extract final P&L and exit price
            realized_pnl = position_data.get('realized_pnl', 0)
            exit_price = position_data.get('exit_price') or position_data.get('current_price', 0)
            
            # Close the trade
            trade.close_trade(
                exit_price=float(exit_price),
                realized_pnl=float(realized_pnl),
                close_time=datetime.utcnow()
            )
            
            self.db.commit()
            self.db.refresh(trade)
            
            logger.info(f"Closed trade {trade.id} - P&L: {realized_pnl}, Duration: {trade.duration_seconds}s")
            return trade
            
        except Exception as e:
            logger.error(f"Error closing trade: {str(e)}", exc_info=True)
            self.db.rollback()
            return None
    
    async def get_live_trades(self, user_id: int) -> List[Trade]:
        """Get all open trades for a user."""
        try:
            trades = self.db.query(Trade).filter(
                Trade.user_id == user_id,
                Trade.status == "open"
            ).order_by(desc(Trade.open_time)).all()
            
            return trades
            
        except Exception as e:
            logger.error(f"Error getting live trades: {str(e)}")
            return []
    
    async def get_historical_trades(
        self,
        user_id: int,
        symbol: Optional[str] = None,
        strategy_id: Optional[int] = None,
        days_back: Optional[int] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Trade]:
        """
        Get historical (closed) trades with filtering options.
        
        Args:
            user_id: User ID to filter by
            symbol: Optional symbol filter
            strategy_id: Optional strategy filter
            days_back: Optional number of days to look back
            limit: Maximum number of results
            offset: Pagination offset
            
        Returns:
            List of historical trades
        """
        try:
            query = self.db.query(Trade).filter(
                Trade.user_id == user_id,
                Trade.status == "closed"
            )
            
            # Apply filters
            if symbol:
                query = query.filter(Trade.symbol == symbol)
            
            if strategy_id:
                query = query.filter(Trade.strategy_id == strategy_id)
            
            if days_back:
                cutoff_date = datetime.utcnow() - timedelta(days=days_back)
                query = query.filter(Trade.close_time >= cutoff_date)
            
            # Order by most recent first
            trades = query.order_by(desc(Trade.close_time))\
                         .limit(limit)\
                         .offset(offset)\
                         .all()
            
            return trades
            
        except Exception as e:
            logger.error(f"Error getting historical trades: {str(e)}")
            return []
    
    async def get_trade_by_id(self, trade_id: int, user_id: int) -> Optional[Trade]:
        """Get a specific trade by ID with user ownership check."""
        try:
            trade = self.db.query(Trade).filter(
                Trade.id == trade_id,
                Trade.user_id == user_id
            ).first()
            
            return trade
            
        except Exception as e:
            logger.error(f"Error getting trade by ID: {str(e)}")
            return None
    
    async def get_trade_performance_summary(self, user_id: int, days_back: int = 30) -> Dict[str, Any]:
        """Get comprehensive trade performance metrics for a user."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_back)
            
            # Get closed trades in the period
            trades = self.db.query(Trade).filter(
                Trade.user_id == user_id,
                Trade.status == "closed",
                Trade.close_time >= cutoff_date
            ).all()
            
            if not trades:
                return {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0,
                    "total_pnl": 0,
                    "average_win": 0,
                    "average_loss": 0,
                    "profit_factor": 0,
                    "max_win": 0,
                    "max_loss": 0
                }
            
            # Calculate metrics
            total_trades = len(trades)
            winning_trades = [t for t in trades if t.realized_pnl and t.realized_pnl > 0]
            losing_trades = [t for t in trades if t.realized_pnl and t.realized_pnl < 0]
            
            total_pnl = sum(float(t.realized_pnl or 0) for t in trades)
            total_wins = sum(float(t.realized_pnl or 0) for t in winning_trades)
            total_losses = abs(sum(float(t.realized_pnl or 0) for t in losing_trades))
            
            return {
                "total_trades": total_trades,
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "win_rate": (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0,
                "total_pnl": total_pnl,
                "average_win": (total_wins / len(winning_trades)) if winning_trades else 0,
                "average_loss": (total_losses / len(losing_trades)) if losing_trades else 0,
                "profit_factor": (total_wins / total_losses) if total_losses > 0 else float('inf') if total_wins > 0 else 0,
                "max_win": max((float(t.realized_pnl or 0) for t in winning_trades), default=0),
                "max_loss": min((float(t.realized_pnl or 0) for t in losing_trades), default=0),
                "period_days": days_back
            }
            
        except Exception as e:
            logger.error(f"Error calculating performance summary: {str(e)}")
            return {}
    
    async def create_trade_execution(
        self,
        trade_id: int,
        execution_data: Dict[str, Any]
    ) -> Optional[TradeExecution]:
        """Create a trade execution record for network strategies."""
        try:
            execution = TradeExecution(
                trade_id=trade_id,
                broker_account_id=execution_data.get('account_id'),
                account_role=execution_data.get('role', 'follower'),
                quantity=execution_data.get('quantity', 0),
                execution_price=Decimal(str(execution_data.get('price', 0))),
                execution_time=datetime.utcnow(),
                realized_pnl=Decimal(str(execution_data.get('pnl', 0))) if execution_data.get('pnl') else None,
                execution_id=execution_data.get('execution_id'),
                commission=Decimal(str(execution_data.get('commission', 0))) if execution_data.get('commission') else None,
                fees=Decimal(str(execution_data.get('fees', 0))) if execution_data.get('fees') else None,
                broker_data=str(execution_data) if execution_data else None
            )
            
            self.db.add(execution)
            self.db.commit()
            self.db.refresh(execution)
            
            logger.info(f"Created trade execution {execution.id} for trade {trade_id}")
            return execution
            
        except Exception as e:
            logger.error(f"Error creating trade execution: {str(e)}", exc_info=True)
            self.db.rollback()
            return None
    
    async def _determine_strategy_attribution(
        self,
        user_id: int,
        position_data: Dict[str, Any]
    ) -> Optional[int]:
        """
        Determine which strategy should be attributed to this position.
        This is a simplified version - can be enhanced with more sophisticated logic.
        """
        try:
            # Get the most recent active strategy for this user and symbol
            symbol = position_data.get('symbol', '')
            
            strategy = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == user_id,
                ActivatedStrategy.ticker == symbol,
                ActivatedStrategy.is_active == True
            ).order_by(desc(ActivatedStrategy.last_triggered)).first()
            
            if strategy:
                return strategy.id
            
            # Fallback: get any active strategy for this user
            fallback_strategy = self.db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == user_id,
                ActivatedStrategy.is_active == True
            ).order_by(desc(ActivatedStrategy.created_at)).first()
            
            return fallback_strategy.id if fallback_strategy else None
            
        except Exception as e:
            logger.error(f"Error determining strategy attribution: {str(e)}")
            return None