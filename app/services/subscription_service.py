# app/services/subscription_service.py
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
import logging

from app.core.subscription_tiers import (
    SubscriptionTier, 
    get_tier_limit, 
    check_resource_limit, 
    is_feature_allowed
)
from app.models.subscription import Subscription
from app.models.broker import BrokerAccount
from app.models.webhook import Webhook
from app.models.strategy import ActivatedStrategy
from app.models.user import User

logger = logging.getLogger(__name__)

class SubscriptionService:
    """Service for handling subscription tier limits and features"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_user_subscription(self, user_id: int) -> Optional[Subscription]:
        """Get a user's subscription"""
        return self.db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).first()
    
    def get_user_tier(self, user_id: int) -> str:
        """Get a user's subscription tier"""
        subscription = self.get_user_subscription(user_id)
        if not subscription:
            # Default to starter tier if no subscription found
            return SubscriptionTier.STARTER
        return subscription.tier
    
    def count_user_resources(self, user_id: int) -> Dict[str, int]:
        """
        Count all resources currently used by a user
        Uses stored counters when available for better performance
        
        Returns:
            Dict with counts of connected_accounts, active_webhooks, and active_strategies
        """
        # Try to get counts from subscription first
        subscription = self.get_user_subscription(user_id)
        
        if subscription and all(counter is not None for counter in [
            subscription.connected_accounts_count,
            subscription.active_webhooks_count,
            subscription.active_strategies_count
        ]):
            # Use stored counters if available
            return {
                "connected_accounts": subscription.connected_accounts_count,
                "active_webhooks": subscription.active_webhooks_count,
                "active_strategies": subscription.active_strategies_count
            }
        
        # Fall back to counting from database if counters aren't available
        connected_accounts = self.db.query(func.count(BrokerAccount.id)).filter(
            BrokerAccount.user_id == user_id,
            BrokerAccount.is_active == True,
            BrokerAccount.is_deleted == False
        ).scalar() or 0
        
        active_webhooks = self.db.query(func.count(Webhook.id)).filter(
            Webhook.user_id == user_id,
            Webhook.is_active == True
        ).scalar() or 0
        
        active_strategies = self.db.query(func.count(ActivatedStrategy.id)).filter(
            ActivatedStrategy.user_id == user_id,
            ActivatedStrategy.is_active == True
        ).scalar() or 0
        
        # If subscription exists but counters aren't set, update them
        if subscription:
            subscription.connected_accounts_count = connected_accounts
            subscription.active_webhooks_count = active_webhooks
            subscription.active_strategies_count = active_strategies
            self.db.commit()
        
        return {
            "connected_accounts": connected_accounts,
            "active_webhooks": active_webhooks,
            "active_strategies": active_strategies
        }
    
    def can_add_resource(self, user_id: int, resource: str) -> Tuple[bool, str]:
        """
        Check if a user can add a new resource based on their subscription tier
        
        Args:
            user_id: User ID
            resource: Resource type (connected_accounts, active_webhooks, active_strategies)
            
        Returns:
            Tuple of (allowed: bool, message: str)
        """
        tier = self.get_user_tier(user_id)
        resources = self.count_user_resources(user_id)
        
        current_count = resources.get(resource, 0)
        limit = get_tier_limit(tier, resource)
        
        # Check if unlimited
        if limit == float('inf'):
            return True, f"Allowed ({tier} tier has unlimited {resource})"
        
        # Check if under limit
        if current_count < limit:
            return True, f"Allowed ({current_count + 1}/{limit} {resource})"
        
        # Generate upgrade message based on resource type
        upgrade_messages = {
            "connected_accounts": f"You've reached the maximum number of connected accounts ({limit}) for your {tier} tier. Please upgrade to add more accounts.",
            "active_webhooks": f"You've reached the maximum number of active webhooks ({limit}) for your {tier} tier. Please upgrade to add more webhooks.",
            "active_strategies": f"You've reached the maximum number of active strategies ({limit}) for your {tier} tier. Please upgrade to add more strategies."
        }
        
        return False, upgrade_messages.get(
            resource, 
            f"Upgrade required: {current_count}/{limit} {resource} (maximum for {tier} tier)"
        )
    
    def get_tier_limit(self, tier: str, resource: str) -> int:
        """Get the resource limit for a specific tier"""
        try:
            return get_tier_limit(tier, resource)
        except ValueError:
            logger.error(f"Invalid resource type {resource} or tier {tier}")
            return 0
    
    def is_feature_available(self, user_id: int, feature: str) -> Tuple[bool, str]:
        """
        Check if a feature is available for a user's subscription tier
        
        Args:
            user_id: User ID
            feature: Feature name to check
            
        Returns:
            Tuple of (allowed: bool, message: str)
        """
        tier = self.get_user_tier(user_id)
        allowed = is_feature_allowed(tier, feature)
        
        if allowed:
            return True, f"Feature '{feature}' is available on your {tier} plan"
        
        # Determine required tier for this feature
        required_tier = None
        for t in [SubscriptionTier.STARTER, SubscriptionTier.PRO, SubscriptionTier.ELITE]:
            if is_feature_allowed(t, feature):
                required_tier = t
                break
        
        if required_tier:
            return False, f"Feature '{feature}' requires {required_tier} tier or higher"
        else:
            return False, f"Feature '{feature}' is not available on your {tier} plan"

    def get_tier_comparison(self) -> Dict[str, Dict[str, Any]]:
        """
        Get a comparison of all subscription tiers
        
        Returns:
            Dict with tier information and features
        """
        return {
            SubscriptionTier.STARTER: {
                "name": "Starter",
                "connected_accounts": get_tier_limit(SubscriptionTier.STARTER, "connected_accounts"),
                "active_webhooks": get_tier_limit(SubscriptionTier.STARTER, "active_webhooks"),
                "active_strategies": get_tier_limit(SubscriptionTier.STARTER, "active_strategies"),
                "group_strategies": is_feature_allowed(SubscriptionTier.STARTER, "group_strategies_allowed"),
                "can_share_webhooks": is_feature_allowed(SubscriptionTier.STARTER, "can_share_webhooks"),
                "api_rate_limit": "100/min",
                "webhook_rate_limit": "60/min"
            },
            SubscriptionTier.PRO: {
                "name": "Pro",
                "connected_accounts": get_tier_limit(SubscriptionTier.PRO, "connected_accounts"),
                "active_webhooks": get_tier_limit(SubscriptionTier.PRO, "active_webhooks"),
                "active_strategies": get_tier_limit(SubscriptionTier.PRO, "active_strategies"),
                "group_strategies": is_feature_allowed(SubscriptionTier.PRO, "group_strategies_allowed"),
                "can_share_webhooks": is_feature_allowed(SubscriptionTier.PRO, "can_share_webhooks"),
                "api_rate_limit": "500/min",
                "webhook_rate_limit": "300/min",
                "price_monthly": "$49/month",
                "price_yearly": "$468/year ($39/month)"
            },
            SubscriptionTier.ELITE: {
                "name": "Elite",
                "connected_accounts": "Unlimited",
                "active_webhooks": "Unlimited",
                "active_strategies": "Unlimited",
                "group_strategies": is_feature_allowed(SubscriptionTier.ELITE, "group_strategies_allowed"),
                "can_share_webhooks": is_feature_allowed(SubscriptionTier.ELITE, "can_share_webhooks"),
                "api_rate_limit": "Unlimited",
                "webhook_rate_limit": "Unlimited",
                "price_monthly": "$89/month",
                "price_yearly": "$828/year ($69/month)",
                "price_lifetime": "$1,990 (one-time payment)"
            }
        }
        
    def sync_resource_counts(self, user_id: int) -> Dict[str, int]:
        """
        Synchronize resource counts for a user and update subscription record
        
        Args:
            user_id: User ID to sync counts for
            
        Returns:
            Dict with updated resource counts
        """
        try:
            # Get actual counts from database
            connected_accounts = self.db.query(func.count(BrokerAccount.id)).filter(
                BrokerAccount.user_id == user_id,
                BrokerAccount.is_active == True,
                BrokerAccount.is_deleted == False
            ).scalar() or 0
            
            active_webhooks = self.db.query(func.count(Webhook.id)).filter(
                Webhook.user_id == user_id,
                Webhook.is_active == True
            ).scalar() or 0
            
            active_strategies = self.db.query(func.count(ActivatedStrategy.id)).filter(
                ActivatedStrategy.user_id == user_id,
                ActivatedStrategy.is_active == True
            ).scalar() or 0
            
            # Get subscription and update counts
            subscription = self.get_user_subscription(user_id)
            if subscription:
                subscription.connected_accounts_count = connected_accounts
                subscription.active_webhooks_count = active_webhooks
                subscription.active_strategies_count = active_strategies
                self.db.commit()
                
            # Return updated counts
            return {
                "connected_accounts": connected_accounts,
                "active_webhooks": active_webhooks,
                "active_strategies": active_strategies
            }
            
        except Exception as e:
            logger.error(f"Error syncing resource counts for user {user_id}: {str(e)}")
            self.db.rollback()
            raise
            
    def get_upgrade_recommendations(self, user_id: int) -> Dict[str, Any]:
        """
        Get upgrade recommendations for a user based on their current usage
        
        Args:
            user_id: User ID to get recommendations for
            
        Returns:
            Dict with upgrade recommendations
        """
        tier = self.get_user_tier(user_id)
        if tier == SubscriptionTier.ELITE:
            return {"recommendations": [], "message": "You are already on the highest tier."}
            
        # Get current resource usage
        resources = self.count_user_resources(user_id)
        
        # Get current tier limits
        current_limits = {
            "connected_accounts": get_tier_limit(tier, "connected_accounts"),
            "active_webhooks": get_tier_limit(tier, "active_webhooks"),
            "active_strategies": get_tier_limit(tier, "active_strategies")
        }
        
        # Check which resources are approaching limits (80% or more)
        approaching_limits = []
        for resource, count in resources.items():
            limit = current_limits.get(resource, float('inf'))
            if limit != float('inf') and count >= 0.8 * limit:
                approaching_limits.append({
                    "resource": resource,
                    "current": count,
                    "limit": limit,
                    "percentage": round((count / limit) * 100, 1)
                })
                
        # Check if user might need group strategies
        needs_group_strategies = self.db.query(func.count(ActivatedStrategy.id)).filter(
            ActivatedStrategy.user_id == user_id
        ).scalar() > 2  # If user has more than 2 strategies, might need groups
        
        # Get next tier
        next_tier = SubscriptionTier.PRO if tier == SubscriptionTier.STARTER else SubscriptionTier.ELITE
        
        # Generate recommendations
        recommendations = []
        
        if approaching_limits:
            recommendations.append({
                "type": "resource_limits",
                "message": f"You're approaching resource limits on your {tier} plan.",
                "resources": approaching_limits,
                "recommendation": f"Upgrade to {next_tier} for higher limits."
            })
            
        if needs_group_strategies and tier == SubscriptionTier.STARTER:
            recommendations.append({
                "type": "group_strategies",
                "message": "Your trading pattern suggests you could benefit from group strategies.",
                "recommendation": "Upgrade to Pro tier to enable group strategies."
            })
            
        return {
            "current_tier": tier,
            "next_tier": next_tier,
            "recommendations": recommendations,
            "upgrade_url": f"/pricing?from={tier}&to={next_tier}"
        }