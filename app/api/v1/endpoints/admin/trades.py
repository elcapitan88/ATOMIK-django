from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

from app.db.session import get_db
from app.models.user import User
from app.models.order import Order, OrderStatus
from app.core.security import get_current_user
from app.core.permissions import admin_required

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/stats", response_model=Dict[str, Any])
async def get_trade_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
    period: str = Query("24h", regex="^(1h|6h|24h|7d|30d)$"),
):
    """Get trading statistics"""
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
        
        # Total orders in period
        total_orders = db.query(func.count(Order.id)).filter(
            Order.created_at >= start_time
        ).scalar()
        
        # Orders by status
        status_counts = {}
        for status in OrderStatus:
            count = db.query(func.count(Order.id)).filter(
                Order.created_at >= start_time,
                Order.status == status
            ).scalar()
            status_counts[status.value] = count
        
        # Calculate success rate
        successful_orders = status_counts.get(OrderStatus.FILLED.value, 0)
        failed_orders = status_counts.get(OrderStatus.REJECTED.value, 0) + status_counts.get(OrderStatus.CANCELLED.value, 0) + status_counts.get(OrderStatus.EXPIRED.value, 0)
        
        success_rate = (successful_orders / total_orders * 100) if total_orders > 0 else 0
        
        # Most active symbols
        most_active_symbols = db.query(
            Order.symbol,
            func.count(Order.id).label('order_count')
        ).filter(
            Order.created_at >= start_time
        ).group_by(
            Order.symbol
        ).order_by(
            desc('order_count')
        ).limit(5).all()
        
        formatted_active_symbols = [
            {
                "symbol": symbol,
                "order_count": order_count
            }
            for symbol, order_count in most_active_symbols
        ]
        
        # Recent orders
        recent_orders = db.query(Order).filter(
            Order.created_at >= start_time
        ).order_by(
            Order.created_at.desc()
        ).limit(5).all()
        
        formatted_recent_orders = [
            {
                "id": order.id,
                "broker_order_id": order.broker_order_id,
                "user_id": order.user_id,
                "symbol": order.symbol,
                "side": order.side,
                "order_type": order.order_type,
                "status": order.status,
                "quantity": order.quantity,
                "filled_quantity": order.filled_quantity,
                "created_at": order.created_at
            }
            for order in recent_orders
        ]
        
        return {
            "period": period,
            "total_orders": total_orders,
            "status_counts": status_counts,
            "success_rate": success_rate,
            "most_active_symbols": formatted_active_symbols,
            "recent_orders": formatted_recent_orders
        }
        
    except Exception as e:
        logger.error(f"Error fetching trade stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch trade statistics: {str(e)}"
        )

@router.get("/orders", response_model=Dict[str, Any])
async def get_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    user_id: Optional[int] = None,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    """Get order listings with filtering"""
    try:
        # Base query
        query = db.query(Order)
        
        # Apply filters
        if user_id:
            query = query.filter(Order.user_id == user_id)
            
        if symbol:
            query = query.filter(Order.symbol == symbol)
            
        if status:
            try:
                status_enum = OrderStatus(status)
                query = query.filter(Order.status == status_enum)
            except ValueError:
                # Invalid status - ignore this filter
                pass
            
        if start_date:
            query = query.filter(Order.created_at >= start_date)
            
        if end_date:
            query = query.filter(Order.created_at <= end_date)
            
        # Get total count (for pagination)
        total = query.count()
        
        # Get orders
        orders = query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()
        
        # Format response
        order_data = []
        for order in orders:
            order_dict = {
                "id": order.id,
                "broker_order_id": order.broker_order_id,
                "user_id": order.user_id,
                "strategy_id": order.strategy_id,
                "broker_account_id": order.broker_account_id,
                "symbol": order.symbol,
                "side": order.side,
                "order_type": order.order_type,
                "status": order.status,
                "quantity": order.quantity,
                "filled_quantity": order.filled_quantity,
                "remaining_quantity": order.remaining_quantity,
                "price": order.price,
                "stop_price": order.stop_price,
                "average_fill_price": order.average_fill_price,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
                "filled_at": order.filled_at,
                "cancelled_at": order.cancelled_at,
                "error_message": order.error_message
            }
            
            order_data.append(order_dict)
        
        return {
            "total": total,
            "orders": order_data,
            "skip": skip,
            "limit": limit
        }
        
    except Exception as e:
        logger.error(f"Error fetching orders: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch orders: {str(e)}"
        )