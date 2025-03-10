from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

from app.db.session import get_db
from app.models.user import User
from app.models.subscription import Subscription
from app.core.security import get_current_user
from app.core.permissions import admin_required

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/", response_model=Dict[str, Any])
async def get_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
):
    """Get paginated list of users with optional filtering"""
    try:
        # Base query
        query = db.query(User)
        
        # Apply filters
        if search:
            query = query.filter(
                (User.email.ilike(f"%{search}%")) |
                (User.username.ilike(f"%{search}%")) |
                (User.full_name.ilike(f"%{search}%"))
            )
            
        if status == "active":
            query = query.filter(User.is_active == True)
        elif status == "inactive":
            query = query.filter(User.is_active == False)
            
        # Get total count (for pagination)
        total = query.count()
        
        # Get paginated results
        users = query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()
        
        # Format user data with subscription info
        user_data = []
        for user in users:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == user.id
            ).first()
            
            user_dict = {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "is_active": user.is_active,
                "is_superuser": user.is_superuser,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
                "subscription": {
                    "customer_id": subscription.stripe_customer_id if subscription else None,
                } if subscription else None
            }
            
            user_data.append(user_dict)
        
        return {
            "total": total,
            "users": user_data,
            "skip": skip,
            "limit": limit
        }
    
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch users: {str(e)}"
        )

@router.get("/{user_id}", response_model=Dict[str, Any])
async def get_user_details(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
):
    """Get detailed information about a specific user"""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get subscription info
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user.id
        ).first()
        
        # Get counts of related entities
        webhook_count = db.query(user.webhooks).count()
        broker_account_count = db.query(user.broker_accounts).count()
        strategies_count = db.query(user.strategies).count()
        
        # Get recent activity (could be from various tables)
        # This is just a placeholder - you would implement based on your activity tracking
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "is_active": user.is_active,
                "is_superuser": user.is_superuser,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
            },
            "subscription": {
                "customer_id": subscription.stripe_customer_id if subscription else None,
                # You could add more subscription details from Stripe
            } if subscription else None,
            "stats": {
                "webhook_count": webhook_count,
                "broker_account_count": broker_account_count,
                "strategies_count": strategies_count,
            },
            "recent_activity": [] # Placeholder for activity data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch user details: {str(e)}"
        )

@router.post("/{user_id}/toggle-active", response_model=Dict[str, Any])
async def toggle_user_active_status(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_required),
):
    """Toggle a user's active status"""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Don't allow deactivating yourself
        if user.id == current_user.id:
            raise HTTPException(
                status_code=400,
                detail="Cannot modify your own account status"
            )
        
        # Toggle status
        user.is_active = not user.is_active
        user.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {
            "success": True,
            "user_id": user.id,
            "is_active": user.is_active
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling user status: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update user status: {str(e)}"
        )