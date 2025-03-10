# app/api/v1/endpoints/admin/strategy.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

from app.db.session import get_db
from app.models.user import User
from app.models.strategy import ActivatedStrategy
from app.models.webhook import Webhook
from app.models.broker import BrokerAccount
from app.core.security import get_current_user
from app.core.permissions import admin_required

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/stats", response_model=Dict[str, Any])
async def get_strategy_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
    period: str = Query("24h", regex="^(1h|6h|24h|7d|30d)$"),
):
    """Get strategy usage statistics"""
    try:
        # Calculate time range based on period
        now = datetime.utcnow()
        if period == "1h":
            start_time = now - timedelta(hours=1)
        elif period == "6h":
            start_time = now - timedelta(hours=6)
        elif period == "24h":
            start_time = now - timedelta(hours=24)
        elif period == "7d":
            start_time = now - timedelta(days=7)
        elif period == "30d":
            start_time = now - timedelta(days=30)
        else:
            start_time = now - timedelta(hours=24)  # Default to 24h
        
        # Total strategies count
        total_strategies = db.query(func.count(ActivatedStrategy.id)).scalar()
        
        # Active strategies (triggered in time period)
        active_strategies = db.query(func.count(ActivatedStrategy.id)).filter(
            ActivatedStrategy.last_triggered >= start_time
        ).scalar()
        
        # Strategies by type
        single_strategies = db.query(func.count(ActivatedStrategy.id)).filter(
            ActivatedStrategy.strategy_type == "single"
        ).scalar()
        
        multiple_strategies = db.query(func.count(ActivatedStrategy.id)).filter(
            ActivatedStrategy.strategy_type == "multiple"
        ).scalar()
        
        # Calculate success metrics across all strategies
        total_trades = db.query(func.sum(ActivatedStrategy.total_trades)).scalar() or 0
        successful_trades = db.query(func.sum(ActivatedStrategy.successful_trades)).scalar() or 0
        failed_trades = db.query(func.sum(ActivatedStrategy.failed_trades)).scalar() or 0
        
        # Calculate overall win rate
        win_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Most popular tickers
        popular_tickers = db.query(
            ActivatedStrategy.ticker,
            func.count(ActivatedStrategy.id).label('strategy_count')
        ).group_by(
            ActivatedStrategy.ticker
        ).order_by(
            desc('strategy_count')
        ).limit(10).all()
        
        formatted_popular_tickers = [
            {
                "ticker": ticker,
                "count": count
            }
            for ticker, count in popular_tickers
        ]
        
        # Top performing strategies
        top_strategies = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.total_trades > 0,  # Only include strategies with trades
            ActivatedStrategy.win_rate.isnot(None)  # Only include strategies with calculated win rate
        ).order_by(
            desc(ActivatedStrategy.win_rate),
            desc(ActivatedStrategy.total_trades)
        ).limit(5).all()
        
        formatted_top_strategies = [
            {
                "id": strategy.id,
                "user_id": strategy.user_id,
                "ticker": strategy.ticker,
                "strategy_type": strategy.strategy_type,
                "total_trades": strategy.total_trades,
                "successful_trades": strategy.successful_trades,
                "win_rate": float(strategy.win_rate) if strategy.win_rate else 0,
                "total_pnl": float(strategy.total_pnl) if strategy.total_pnl else 0
            }
            for strategy in top_strategies
        ]
        
        # Recently created strategies
        recent_strategies = db.query(ActivatedStrategy).order_by(
            ActivatedStrategy.created_at.desc()
        ).limit(5).all()
        
        formatted_recent_strategies = [
            {
                "id": strategy.id,
                "user_id": strategy.user_id,
                "ticker": strategy.ticker,
                "strategy_type": strategy.strategy_type,
                "created_at": strategy.created_at,
                "is_active": strategy.is_active
            }
            for strategy in recent_strategies
        ]
        
        return {
            "period": period,
            "total_strategies": total_strategies,
            "active_strategies": active_strategies,
            "strategy_types": {
                "single": single_strategies,
                "multiple": multiple_strategies
            },
            "trade_metrics": {
                "total_trades": total_trades,
                "successful_trades": successful_trades,
                "failed_trades": failed_trades,
                "win_rate": win_rate
            },
            "popular_tickers": formatted_popular_tickers,
            "top_strategies": formatted_top_strategies,
            "recent_strategies": formatted_recent_strategies
        }
        
    except Exception as e:
        logger.error(f"Error fetching strategy stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch strategy statistics: {str(e)}"
        )

@router.get("/list", response_model=Dict[str, Any])
async def list_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    user_id: Optional[int] = None,
    ticker: Optional[str] = None,
    strategy_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    sort_by: str = "created_at",
    sort_desc: bool = True
):
    """Get paginated list of strategies with filtering"""
    try:
        # Base query
        query = db.query(ActivatedStrategy)
        
        # Apply filters
        if user_id:
            query = query.filter(ActivatedStrategy.user_id == user_id)
            
        if ticker:
            query = query.filter(ActivatedStrategy.ticker == ticker)
            
        if strategy_type:
            query = query.filter(ActivatedStrategy.strategy_type == strategy_type)
            
        if is_active is not None:
            query = query.filter(ActivatedStrategy.is_active == is_active)
            
        # Get total count (for pagination)
        total = query.count()
        
        # Apply sorting
        if sort_by == "win_rate":
            order_func = desc(ActivatedStrategy.win_rate) if sort_desc else ActivatedStrategy.win_rate
        elif sort_by == "total_trades":
            order_func = desc(ActivatedStrategy.total_trades) if sort_desc else ActivatedStrategy.total_trades
        elif sort_by == "total_pnl":
            order_func = desc(ActivatedStrategy.total_pnl) if sort_desc else ActivatedStrategy.total_pnl
        else:  # Default to created_at
            order_func = desc(ActivatedStrategy.created_at) if sort_desc else ActivatedStrategy.created_at
            
        query = query.order_by(order_func)
        
        # Apply pagination
        strategies = query.offset(skip).limit(limit).all()
        
        # Format response
        strategy_data = []
        for strategy in strategies:
            # Get user info
            user = db.query(User).filter(User.id == strategy.user_id).first()
            
            # Get webhook info if available
            webhook = None
            if strategy.webhook_id:
                webhook = db.query(Webhook).filter(Webhook.token == strategy.webhook_id).first()
            
            # For single strategies, get account info
            account = None
            if strategy.strategy_type == "single" and strategy.account_id:
                account = db.query(BrokerAccount).filter(
                    BrokerAccount.account_id == strategy.account_id
                ).first()
                
            # Format strategy data
            strategy_dict = {
                "id": strategy.id,
                "user_id": strategy.user_id,
                "username": user.username if user else "Unknown",
                "strategy_type": strategy.strategy_type,
                "ticker": strategy.ticker,
                "is_active": strategy.is_active,
                "created_at": strategy.created_at,
                "last_triggered": strategy.last_triggered,
                "total_trades": strategy.total_trades,
                "successful_trades": strategy.successful_trades,
                "failed_trades": strategy.failed_trades,
                "win_rate": float(strategy.win_rate) if strategy.win_rate else None,
                "total_pnl": float(strategy.total_pnl) if strategy.total_pnl else None,
                "webhook": {
                    "id": webhook.id,
                    "name": webhook.name,
                    "source_type": webhook.source_type
                } if webhook else None
            }
            
            # Add type-specific fields
            if strategy.strategy_type == "single":
                strategy_dict.update({
                    "account_id": strategy.account_id,
                    "quantity": strategy.quantity,
                    "broker_id": account.broker_id if account else None,
                    "environment": account.environment if account else None
                })
            else:  # multiple
                strategy_dict.update({
                    "leader_account_id": strategy.leader_account_id,
                    "leader_quantity": strategy.leader_quantity,
                    "group_name": strategy.group_name,
                    "follower_count": len(strategy.get_follower_accounts()) if hasattr(strategy, 'get_follower_accounts') else 0
                })
                
            strategy_data.append(strategy_dict)
                
        return {
            "total": total,
            "strategies": strategy_data,
            "skip": skip,
            "limit": limit
        }
        
    except Exception as e:
        logger.error(f"Error listing strategies: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list strategies: {str(e)}"
        )

@router.get("/{strategy_id}", response_model=Dict[str, Any])
async def get_strategy_details(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required)
):
    """Get detailed information about a specific strategy"""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
            
        # Get user
        user = db.query(User).filter(User.id == strategy.user_id).first()
        
        # Get webhook
        webhook = None
        if strategy.webhook_id:
            webhook = db.query(Webhook).filter(Webhook.token == strategy.webhook_id).first()
        
        # Get related accounts
        accounts = []
        if strategy.strategy_type == "single" and strategy.account_id:
            account = db.query(BrokerAccount).filter(
                BrokerAccount.account_id == strategy.account_id
            ).first()
            if account:
                accounts.append({
                    "account_id": account.account_id,
                    "name": account.name,
                    "broker_id": account.broker_id,
                    "environment": account.environment,
                    "role": "primary"
                })
        elif strategy.strategy_type == "multiple":
            # Leader account
            if strategy.leader_account_id:
                leader = db.query(BrokerAccount).filter(
                    BrokerAccount.account_id == strategy.leader_account_id
                ).first()
                if leader:
                    accounts.append({
                        "account_id": leader.account_id,
                        "name": leader.name,
                        "broker_id": leader.broker_id,
                        "environment": leader.environment,
                        "role": "leader",
                        "quantity": strategy.leader_quantity
                    })
            
            # Follower accounts
            if hasattr(strategy, 'get_follower_accounts'):
                for follower in strategy.get_follower_accounts():
                    follower_account = db.query(BrokerAccount).filter(
                        BrokerAccount.account_id == follower['account_id']
                    ).first()
                    if follower_account:
                        accounts.append({
                            "account_id": follower_account.account_id,
                            "name": follower_account.name,
                            "broker_id": follower_account.broker_id,
                            "environment": follower_account.environment,
                            "role": "follower",
                            "quantity": follower['quantity']
                        })
        
        # Format response
        strategy_details = {
            "id": strategy.id,
            "user": {
                "id": user.id if user else None,
                "username": user.username if user else "Unknown",
                "email": user.email if user else "Unknown"
            },
            "strategy_type": strategy.strategy_type,
            "ticker": strategy.ticker,
            "is_active": strategy.is_active,
            "created_at": strategy.created_at,
            "last_triggered": strategy.last_triggered,
            
            # Performance metrics
            "metrics": {
                "total_trades": strategy.total_trades,
                "successful_trades": strategy.successful_trades,
                "failed_trades": strategy.failed_trades,
                "win_rate": float(strategy.win_rate) if strategy.win_rate else None,
                "total_pnl": float(strategy.total_pnl) if strategy.total_pnl else None,
                "max_drawdown": float(strategy.max_drawdown) if hasattr(strategy, 'max_drawdown') and strategy.max_drawdown else None,
                "sharpe_ratio": float(strategy.sharpe_ratio) if hasattr(strategy, 'sharpe_ratio') and strategy.sharpe_ratio else None,
            },
            
            # Webhook information
            "webhook": {
                "id": webhook.id,
                "token": webhook.token,
                "name": webhook.name,
                "source_type": webhook.source_type,
                "last_triggered": webhook.last_triggered
            } if webhook else None,
            
            # Accounts
            "accounts": accounts,
            
            # Type-specific fields
            "details": {
                "group_name": strategy.group_name if strategy.strategy_type == "multiple" else None,
                "quantity": strategy.quantity if strategy.strategy_type == "single" else None,
            }
        }
        
        # Get risk management settings if available
        if hasattr(strategy, 'get_risk_parameters'):
            strategy_details["risk_management"] = strategy.get_risk_parameters()
            
        return strategy_details
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get strategy details: {str(e)}"
        )

@router.post("/{strategy_id}/toggle", response_model=Dict[str, Any])
async def toggle_strategy_status(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required)
):
    """Toggle a strategy's active status"""
    try:
        strategy = db.query(ActivatedStrategy).filter(
            ActivatedStrategy.id == strategy_id
        ).first()
        
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
            
        # Toggle status
        strategy.is_active = not strategy.is_active
        db.commit()
        
        return {
            "id": strategy.id,
            "is_active": strategy.is_active,
            "message": f"Strategy {'activated' if strategy.is_active else 'deactivated'} successfully"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling strategy status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to toggle strategy status: {str(e)}"
        )