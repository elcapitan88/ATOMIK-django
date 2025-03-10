from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

from app.db.session import get_db
from app.models.user import User
from app.models.webhook import Webhook, WebhookLog
from app.core.security import get_current_user
from app.core.permissions import admin_required

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/stats", response_model=Dict[str, Any])
async def get_webhook_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
    period: str = Query("24h", regex="^(1h|6h|24h|7d|30d)$"),
):
    """Get webhook usage statistics"""
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
        
        # Total webhook count
        total_webhooks = db.query(func.count(Webhook.id)).scalar()
        
        # Active webhooks (used in time period)
        active_webhooks = db.query(func.count(Webhook.id)).filter(
            Webhook.last_triggered >= start_time
        ).scalar()
        
        # Total invocations in time period
        total_invocations = db.query(func.count(WebhookLog.id)).filter(
            WebhookLog.triggered_at >= start_time
        ).scalar()
        
        # Successful vs failed invocations
        successful_invocations = db.query(func.count(WebhookLog.id)).filter(
            WebhookLog.triggered_at >= start_time,
            WebhookLog.success == True
        ).scalar()
        
        failed_invocations = db.query(func.count(WebhookLog.id)).filter(
            WebhookLog.triggered_at >= start_time,
            WebhookLog.success == False
        ).scalar()
        
        # Average processing time
        avg_processing_time = db.query(func.avg(WebhookLog.processing_time)).filter(
            WebhookLog.triggered_at >= start_time,
            WebhookLog.processing_time.isnot(None)
        ).scalar() or 0
        
        # Most active webhooks
        most_active_webhooks = db.query(
            Webhook.id,
            Webhook.name,
            Webhook.token,
            func.count(WebhookLog.id).label('invocation_count')
        ).join(
            WebhookLog, WebhookLog.webhook_id == Webhook.id
        ).filter(
            WebhookLog.triggered_at >= start_time
        ).group_by(
            Webhook.id
        ).order_by(
            desc('invocation_count')
        ).limit(5).all()
        
        formatted_active_webhooks = [
            {
                "id": webhook.id,
                "name": webhook.name or "Unnamed Webhook",
                "token": webhook.token,
                "invocation_count": invocation_count
            }
            for webhook, invocation_count in most_active_webhooks
        ]
        
        # Recent errors
        recent_errors = db.query(WebhookLog).filter(
            WebhookLog.triggered_at >= start_time,
            WebhookLog.success == False
        ).order_by(
            WebhookLog.triggered_at.desc()
        ).limit(5).all()
        
        formatted_recent_errors = [
            {
                "id": log.id,
                "webhook_id": log.webhook_id,
                "triggered_at": log.triggered_at,
                "error_message": log.error_message,
                "ip_address": log.ip_address
            }
            for log in recent_errors
        ]
        
        return {
            "period": period,
            "total_webhooks": total_webhooks,
            "active_webhooks": active_webhooks,
            "total_invocations": total_invocations,
            "successful_invocations": successful_invocations,
            "failed_invocations": failed_invocations,
            "error_rate": (failed_invocations / total_invocations * 100) if total_invocations > 0 else 0,
            "avg_processing_time": avg_processing_time,
            "most_active_webhooks": formatted_active_webhooks,
            "recent_errors": formatted_recent_errors
        }
        
    except Exception as e:
        logger.error(f"Error fetching webhook stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch webhook statistics: {str(e)}"
        )

@router.get("/logs", response_model=Dict[str, Any])
async def get_webhook_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    webhook_token: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    """Get webhook invocation logs with filtering"""
    try:
        # Build query with joins
        query = db.query(WebhookLog).join(
            Webhook, WebhookLog.webhook_id == Webhook.id
        )
        
        # Apply filters
        if webhook_token:
            query = query.filter(Webhook.token == webhook_token)
            
        if status == "success":
            query = query.filter(WebhookLog.success == True)
        elif status == "error":
            query = query.filter(WebhookLog.success == False)
            
        if start_date:
            query = query.filter(WebhookLog.triggered_at >= start_date)
            
        if end_date:
            query = query.filter(WebhookLog.triggered_at <= end_date)
            
        # Get total count (for pagination)
        total = query.count()
        
        # Get logs with webhook info
        logs = query.order_by(WebhookLog.triggered_at.desc()).offset(skip).limit(limit).all()
        
        # Format response
        log_data = []
        for log in logs:
            webhook = db.query(Webhook).filter(Webhook.id == log.webhook_id).first()
            
            log_dict = {
                "id": log.id,
                "webhook_id": log.webhook_id,
                "webhook_name": webhook.name if webhook else "Unknown",
                "webhook_token": webhook.token if webhook else "Unknown",
                "triggered_at": log.triggered_at,
                "success": log.success,
                "processing_time": log.processing_time,
                "ip_address": log.ip_address,
                "error_message": log.error_message,
            }
            
            log_data.append(log_dict)
        
        return {
            "total": total,
            "logs": log_data,
            "skip": skip,
            "limit": limit
        }
        
    except Exception as e:
        logger.error(f"Error fetching webhook logs: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch webhook logs: {str(e)}"
        )