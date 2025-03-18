from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import logging
from datetime import datetime

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.subscription import Subscription
from app.services.subscription_service import SubscriptionService
from app.core.permissions import check_subscription
from app.core.subscription_tiers import SubscriptionTier

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/status")
@check_subscription
async def get_subscription_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current user's subscription status and resource usage
    """
    try:
        # Get subscription service
        subscription_service = SubscriptionService(db)
        
        # Get user's subscription
        subscription = subscription_service.get_user_subscription(current_user.id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail="No active subscription found"
            )
        
        # Get resource counts
        resource_counts = subscription_service.count_user_resources(current_user.id)
        
        # Get tier limits
        tier = subscription.tier
        tier_info = {
            "connected_accounts": {
                "used": resource_counts["connected_accounts"],
                "limit": subscription_service.get_tier_limit(tier, "connected_accounts"),
                "available": subscription_service.can_add_resource(current_user.id, "connected_accounts")[0]
            },
            "active_webhooks": {
                "used": resource_counts["active_webhooks"],
                "limit": subscription_service.get_tier_limit(tier, "active_webhooks"),
                "available": subscription_service.can_add_resource(current_user.id, "active_webhooks")[0]
            },
            "active_strategies": {
                "used": resource_counts["active_strategies"],
                "limit": subscription_service.get_tier_limit(tier, "active_strategies"),
                "available": subscription_service.can_add_resource(current_user.id, "active_strategies")[0]
            },
            "group_strategies_allowed": subscription_service.is_feature_available(
                current_user.id, 
                "group_strategies_allowed"
            )[0],
            "can_share_webhooks": subscription_service.is_feature_available(
                current_user.id,
                "can_share_webhooks" 
            )[0]
        }
        
        # Format human-readable limits
        human_readable_limits = {}
        for resource, details in tier_info.items():
            if isinstance(details, dict) and "limit" in details:
                if details["limit"] == float('inf'):
                    human_readable_limits[resource] = "Unlimited"
                else:
                    human_readable_limits[resource] = str(details["limit"])
        
        # Get upgrade recommendations
        upgrade_recommendations = subscription_service.get_upgrade_recommendations(current_user.id)
        
        # Build response
        response = {
            "subscription": {
                "id": subscription.id,
                "tier": subscription.tier,
                "status": subscription.status,
                "is_lifetime": subscription.is_lifetime,
                "stripe_customer_id": subscription.stripe_customer_id,
                "stripe_subscription_id": subscription.stripe_subscription_id,
                "created_at": subscription.created_at.isoformat(),
                "updated_at": subscription.updated_at.isoformat() if subscription.updated_at else None
            },
            "resources": resource_counts,
            "limits": tier_info,
            "human_readable_limits": human_readable_limits,
            "next_tier": get_next_tier_info(tier),
            "upgrade_recommendations": upgrade_recommendations
        }
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving subscription status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve subscription status"
        )

@router.get("/tiers")
async def get_subscription_tiers():
    """
    Get information about all available subscription tiers
    """
    try:
        subscription_service = SubscriptionService(None)  # No DB needed for tier comparison
        tier_comparison = subscription_service.get_tier_comparison()
        
        # Add feature highlights for each tier
        feature_highlights = {
            SubscriptionTier.STARTER: [
                "1 connected trading account",
                "1 active webhook",
                "1 active strategy",
                "Basic webhook configurations",
                "Manual trade execution",
                "Community support"
            ],
            SubscriptionTier.PRO: [
                "5 connected trading accounts",
                "5 active webhooks",
                "5 active strategies",
                "Group strategies",
                "Webhook sharing",
                "Advanced webhook configurations",
                "Email & chat support",
                "Higher rate limits"
            ],
            SubscriptionTier.ELITE: [
                "Unlimited connected accounts",
                "Unlimited active webhooks",
                "Unlimited strategies",
                "Unlimited rate limits",
                "Group strategies & webhook sharing",
                "Priority support",
                "Early access to new features"
            ]
        }
        
        # Combine tier info with features
        for tier, info in tier_comparison.items():
            info["highlights"] = feature_highlights.get(tier, [])
        
        return {
            "tiers": tier_comparison,
            "comparison_chart": generate_tier_comparison_chart()
        }
        
    except Exception as e:
        logger.error(f"Error retrieving subscription tiers: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve subscription tiers"
        )

@router.get("/usage-history")
@check_subscription
async def get_usage_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get historical resource usage for the current user
    """
    try:
        # This would typically connect to a resource tracking table that records usage over time
        # For now, we'll return a placeholder with current values
        subscription_service = SubscriptionService(db)
        current_counts = subscription_service.count_user_resources(current_user.id)
        
        # Sync counters to ensure accuracy
        synced_counts = subscription_service.sync_resource_counts(current_user.id)
        
        return {
            "current": {
                "timestamp": datetime.utcnow().isoformat(),
                "resources": synced_counts
            },
            "history": [
                # In the future, this would contain historical snapshots
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "resources": synced_counts
                }
            ],
            "message": "Detailed usage history tracking will be available in a future update."
        }
    except Exception as e:
        logger.error(f"Error retrieving usage history: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve usage history"
        )

@router.post("/sync-resources")
@check_subscription
async def synchronize_resource_counts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually synchronize resource counts with actual data
    """
    try:
        subscription_service = SubscriptionService(db)
        updated_counts = subscription_service.sync_resource_counts(current_user.id)
        
        return {
            "status": "success",
            "message": "Resource counts synchronized successfully",
            "counts": updated_counts
        }
    except Exception as e:
        logger.error(f"Error synchronizing resource counts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to synchronize resource counts"
        )

def get_next_tier_info(current_tier: str) -> Dict[str, Any]:
    """Get info about the next tier up from current tier"""
    if current_tier == SubscriptionTier.ELITE:
        return None
        
    next_tier = None
    if current_tier == SubscriptionTier.STARTER:
        next_tier = SubscriptionTier.PRO
    elif current_tier == SubscriptionTier.PRO:
        next_tier = SubscriptionTier.ELITE
        
    if next_tier:
        return {
            "tier": next_tier,
            "upgrade_benefits": get_upgrade_benefits(current_tier, next_tier)
        }
    
    return None

def get_upgrade_benefits(current_tier: str, next_tier: str) -> List[str]:
    """Get list of benefits when upgrading from current tier to next tier"""
    if current_tier == SubscriptionTier.STARTER and next_tier == SubscriptionTier.PRO:
        return [
            "Increase connected accounts from 1 to 5",
            "Increase active webhooks from 1 to 5",
            "Increase active strategies from 1 to 5",
            "Unlock group strategy functionality",
            "Enable webhook sharing",
            "Higher API rate limits (500/min vs 100/min)",
            "Faster webhook processing (300/min vs 60/min)"
        ]
    elif current_tier == SubscriptionTier.PRO and next_tier == SubscriptionTier.ELITE:
        return [
            "Unlimited connected accounts",
            "Unlimited active webhooks",
            "Unlimited active strategies",
            "Unlimited API rate limits",
            "Priority support",
            "Unlimited webhook processing"
        ]
    return []

def generate_tier_comparison_chart() -> Dict[str, Dict[str, Any]]:
    """Generate a comparison chart for subscription tiers"""
    return {
        "columns": ["Feature", "Starter", "Pro", "Elite"],
        "rows": [
            {
                "Feature": "Connected Accounts",
                "Starter": "1",
                "Pro": "5",
                "Elite": "Unlimited"
            },
            {
                "Feature": "Active Webhooks",
                "Starter": "1",
                "Pro": "5",
                "Elite": "Unlimited"
            },
            {
                "Feature": "Active Strategies",
                "Starter": "1",
                "Pro": "5",
                "Elite": "Unlimited"
            },
            {
                "Feature": "Group Strategies",
                "Starter": "❌",
                "Pro": "✅",
                "Elite": "✅"
            },
            {
                "Feature": "Webhook Sharing",
                "Starter": "❌",
                "Pro": "✅",
                "Elite": "✅"
            },
            {
                "Feature": "API Rate Limit",
                "Starter": "100/min",
                "Pro": "500/min",
                "Elite": "Unlimited"
            },
            {
                "Feature": "Webhook Processing",
                "Starter": "60/min",
                "Pro": "300/min",
                "Elite": "Unlimited"
            },
            {
                "Feature": "Priority Support",
                "Starter": "❌",
                "Pro": "❌",
                "Elite": "✅"
            }
        ]
    }