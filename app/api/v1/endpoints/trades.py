"""
Trade API endpoints for managing trade data and lifecycle operations.
Provides REST endpoints for accessing live and historical trade data.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.trade import Trade, TradeExecution
from app.services.trade_service import TradeService

logger = logging.getLogger(__name__)

router = APIRouter()

# Response Models
class TradeResponse(BaseModel):
    id: int
    position_id: str
    symbol: str
    side: str
    total_quantity: int
    average_entry_price: float
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    max_unrealized_pnl: Optional[float] = None
    max_adverse_pnl: Optional[float] = None
    status: str
    open_time: datetime
    close_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    strategy_id: Optional[int] = None
    broker_id: str
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None
    tags: Optional[str] = None

    class Config:
        from_attributes = True

class TradeExecutionResponse(BaseModel):
    id: int
    trade_id: int
    broker_account_id: str
    account_role: str
    quantity: int
    execution_price: float
    execution_time: datetime
    realized_pnl: Optional[float] = None
    execution_id: Optional[str] = None
    commission: Optional[float] = None
    fees: Optional[float] = None

    class Config:
        from_attributes = True

class TradeDetailResponse(TradeResponse):
    executions: List[TradeExecutionResponse] = []

class TradePerformanceResponse(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    average_win: float
    average_loss: float
    profit_factor: float
    max_win: float
    max_loss: float
    period_days: int

class TradeListResponse(BaseModel):
    trades: List[TradeResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool

# Request Models
class CloseTradeRequest(BaseModel):
    exit_price: Optional[float] = Field(None, description="Manual exit price override")
    notes: Optional[str] = Field(None, description="Closing notes")

@router.get("/live", response_model=List[TradeResponse])
async def get_live_trades(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all currently open trades for the authenticated user.
    Returns real-time position data as live trades.
    """
    try:
        trade_service = TradeService(db)
        trades = await trade_service.get_live_trades(current_user.id)
        
        return [TradeResponse.from_orm(trade) for trade in trades]
        
    except Exception as e:
        logger.error(f"Error getting live trades for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve live trades")

@router.get("/historical", response_model=TradeListResponse)
async def get_historical_trades(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    strategy_id: Optional[int] = Query(None, description="Filter by strategy ID"),
    days_back: Optional[int] = Query(30, description="Number of days to look back"),
    profitable_only: Optional[bool] = Query(None, description="Show only profitable trades"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get historical (closed) trades with filtering and pagination.
    Supports filtering by symbol, strategy, profitability, and date range.
    """
    try:
        trade_service = TradeService(db)
        offset = (page - 1) * per_page
        
        # Get filtered trades
        trades = await trade_service.get_historical_trades(
            user_id=current_user.id,
            symbol=symbol,
            strategy_id=strategy_id,
            days_back=days_back,
            limit=per_page,
            offset=offset
        )
        
        # Apply profitability filter if requested
        if profitable_only is not None:
            if profitable_only:
                trades = [t for t in trades if t.realized_pnl and t.realized_pnl > 0]
            else:
                trades = [t for t in trades if t.realized_pnl and t.realized_pnl <= 0]
        
        # Get total count for pagination (simplified - would need optimization for production)
        all_trades = await trade_service.get_historical_trades(
            user_id=current_user.id,
            symbol=symbol,
            strategy_id=strategy_id,
            days_back=days_back,
            limit=1000,  # Large limit to get total count
            offset=0
        )
        
        if profitable_only is not None:
            if profitable_only:
                all_trades = [t for t in all_trades if t.realized_pnl and t.realized_pnl > 0]
            else:
                all_trades = [t for t in all_trades if t.realized_pnl and t.realized_pnl <= 0]
        
        total = len(all_trades)
        
        return TradeListResponse(
            trades=[TradeResponse.from_orm(trade) for trade in trades],
            total=total,
            page=page,
            per_page=per_page,
            has_next=offset + per_page < total,
            has_prev=page > 1
        )
        
    except Exception as e:
        logger.error(f"Error getting historical trades for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve historical trades")

@router.get("/{trade_id}", response_model=TradeDetailResponse)
async def get_trade_detail(
    trade_id: int = Path(..., description="Trade ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific trade, including executions.
    Shows individual account breakdowns for network strategies.
    """
    try:
        trade_service = TradeService(db)
        trade = await trade_service.get_trade_by_id(trade_id, current_user.id)
        
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        
        # Build detailed response with executions
        trade_dict = TradeResponse.from_orm(trade).dict()
        trade_dict['executions'] = [
            TradeExecutionResponse.from_orm(execution) 
            for execution in trade.executions
        ]
        
        return TradeDetailResponse(**trade_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trade {trade_id} for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve trade details")

@router.post("/{trade_id}/close", response_model=TradeResponse)
async def manually_close_trade(
    trade_id: int = Path(..., description="Trade ID to close"),
    request: CloseTradeRequest = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually close a trade with optional exit price override.
    Used for manual trade closure outside of WebSocket position events.
    """
    try:
        trade_service = TradeService(db)
        trade = await trade_service.get_trade_by_id(trade_id, current_user.id)
        
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        
        if trade.status != "open":
            raise HTTPException(status_code=400, detail="Trade is not open")
        
        # Prepare position data for closure
        position_data = {
            'exit_price': request.exit_price if request and request.exit_price else trade.average_entry_price,
            'realized_pnl': 0,  # Would need current price calculation for real P&L
            'current_price': request.exit_price if request and request.exit_price else trade.average_entry_price
        }
        
        # Close the trade
        closed_trade = await trade_service.close_trade(trade.position_id, position_data)
        
        if not closed_trade:
            raise HTTPException(status_code=500, detail="Failed to close trade")
        
        # Add notes if provided
        if request and request.notes:
            closed_trade.notes = request.notes
            db.commit()
            db.refresh(closed_trade)
        
        logger.info(f"Manually closed trade {trade_id} for user {current_user.id}")
        return TradeResponse.from_orm(closed_trade)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error manually closing trade {trade_id} for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to close trade")

@router.get("/performance/summary", response_model=TradePerformanceResponse)
async def get_performance_summary(
    days_back: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive trading performance metrics for the specified period.
    Includes win rate, P&L statistics, and risk metrics.
    """
    try:
        trade_service = TradeService(db)
        performance = await trade_service.get_trade_performance_summary(
            current_user.id, 
            days_back
        )
        
        if not performance:
            # Return empty performance if no data
            performance = {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "average_win": 0,
                "average_loss": 0,
                "profit_factor": 0,
                "max_win": 0,
                "max_loss": 0,
                "period_days": days_back
            }
        
        return TradePerformanceResponse(**performance)
        
    except Exception as e:
        logger.error(f"Error getting performance summary for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve performance summary")

@router.get("/symbols/list", response_model=List[str])
async def get_traded_symbols(
    days_back: Optional[int] = Query(30, description="Number of days to look back"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get list of symbols that the user has traded in the specified period.
    Used for symbol filtering dropdown in UI.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back) if days_back else None
        
        query = db.query(Trade.symbol).filter(Trade.user_id == current_user.id).distinct()
        
        if cutoff_date:
            query = query.filter(Trade.open_time >= cutoff_date)
        
        symbols = [row[0] for row in query.all()]
        return sorted(symbols)
        
    except Exception as e:
        logger.error(f"Error getting traded symbols for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve traded symbols")

@router.get("/strategies/list", response_model=List[Dict[str, Any]])
async def get_trade_strategies(
    days_back: Optional[int] = Query(30, description="Number of days to look back"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get list of strategies that have generated trades in the specified period.
    Used for strategy filtering dropdown in UI.
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back) if days_back else None
        
        query = db.query(Trade.strategy_id).filter(
            Trade.user_id == current_user.id,
            Trade.strategy_id.isnot(None)
        ).distinct()
        
        if cutoff_date:
            query = query.filter(Trade.open_time >= cutoff_date)
        
        strategy_ids = [row[0] for row in query.all()]
        
        # Get strategy details (would need to join with strategy table for names)
        strategies = []
        for strategy_id in strategy_ids:
            strategies.append({
                "id": strategy_id,
                "name": f"Strategy {strategy_id}"  # Placeholder - would get real name from strategy table
            })
        
        return strategies
        
    except Exception as e:
        logger.error(f"Error getting trade strategies for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve trade strategies")