from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
import logging
from datetime import datetime, timedelta

from app.core.subscription_tiers import (
    SubscriptionTier, 
    get_tier_limit, 
    check_resource_limit, 
    is_feature_allowed,
    get_tier_display_name
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
        
        # Use proper upgrade prompt system for consistent messaging
        from app.core.upgrade_prompts import get_upgrade_message, UpgradeReason
        
        reason_mapping = {
            "connected_accounts": UpgradeReason.ACCOUNT_LIMIT,
            "active_webhooks": UpgradeReason.WEBHOOK_LIMIT,
            "active_strategies": UpgradeReason.STRATEGY_LIMIT,
        }
        
        reason = reason_mapping.get(resource, UpgradeReason.ADVANCED_FEATURES)
        message = get_upgrade_message(reason, tier)
        
        return False, message
    
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
        Get a comparison of available subscription tiers
        
        Returns:
            Dict with tier information and features
        """
        return {
            # Using internal tier IDs but with updated display names, limits, and prices
            "pro": {  # Internal tier ID (was Pro, now displayed as "Starter")
                "name": "Starter",  # New display name
                "connected_accounts": get_tier_limit(SubscriptionTier.PRO, "connected_accounts"),
                "active_webhooks": get_tier_limit(SubscriptionTier.PRO, "active_webhooks"),
                "active_strategies": get_tier_limit(SubscriptionTier.PRO, "active_strategies"),
                "group_strategies": is_feature_allowed(SubscriptionTier.PRO, "group_strategies_allowed"),
                "can_share_webhooks": is_feature_allowed(SubscriptionTier.PRO, "can_share_webhooks"),
                "api_rate_limit": "500/min",
                "webhook_rate_limit": "300/min",
                "price_monthly": "$49/month",
                "price_yearly": "$468/year ($39/month)",
                "has_trial": "14-day free trial"
            },
            "elite": {  # Internal tier ID (was Elite, now displayed as "Pro")
                "name": "Pro",  # New display name
                "connected_accounts": "Unlimited",
                "active_webhooks": "Unlimited",
                "active_strategies": "Unlimited",
                "group_strategies": is_feature_allowed(SubscriptionTier.ELITE, "group_strategies_allowed"),
                "can_share_webhooks": is_feature_allowed(SubscriptionTier.ELITE, "can_share_webhooks"),
                "api_rate_limit": "Unlimited",
                "webhook_rate_limit": "Unlimited",
                "price_monthly": "$89/month",
                "price_yearly": "$828/year ($69/month)",
                "price_lifetime": "$1,990 (one-time payment)",
                "has_trial": "14-day free trial"
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
    
    def create_trial_subscription(self, user_id: int, tier: str = "pro") -> Subscription:
        """
        Create a new subscription with a trial period
        
        Args:
            user_id: User ID to create subscription for
            tier: Tier to create ("pro" for new Starter, "elite" for new Pro)
            
        Returns:
            Subscription: The created subscription
        """
        # Check if user already has a subscription
        existing = self.get_user_subscription(user_id)
        if existing:
            return existing
            
        # Create new subscription with trial period
        subscription = Subscription(
            user_id=user_id,
            tier=tier,
            status="trialing",
            is_in_trial=True,
            trial_ends_at=datetime.utcnow() + timedelta(days=14),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        self.db.add(subscription)
        self.db.commit()
        logger.info(f"Created trial subscription for user ID {user_id}, tier: {tier}")
        
        return subscription
    
    def check_and_handle_trial_expiration(self, subscription: Subscription) -> None:
        """
        Check if a trial has expired and handle appropriately
        
        Args:
            subscription: Subscription to check
        """
        if not subscription.is_in_trial:
            return
            
        if not subscription.is_trial_active:
            # Trial has expired
            if subscription.stripe_subscription_id:
                # They have a Stripe subscription, so they've converted - update status
                subscription.is_in_trial = False
                subscription.status = "active"
                subscription.trial_converted = True
            else:
                # No Stripe subscription - mark as inactive
                subscription.status = "inactive"
                subscription.is_in_trial = False
            
            self.db.commit()
            logger.info(f"Trial expired for subscription ID {subscription.id}, status: {subscription.status}")
    
    def mark_as_legacy_free(self, user_id: int) -> None:
        """
        Mark a user as a grandfathered free user
        
        Args:
            user_id: User ID to mark
        """
        subscription = self.get_user_subscription(user_id)
        if subscription and subscription.tier == "starter":
            subscription.is_legacy_free = True
            subscription.status = "active"
            self.db.commit()
            logger.info(f"Marked user ID {user_id} as legacy free user")
    
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
        
        # Determine next tier to recommend based on internal tier ID
        next_tier = None
        next_tier_display_name = None
        if tier == SubscriptionTier.STARTER:
            next_tier = SubscriptionTier.PRO
            next_tier_display_name = "Starter"
        elif tier == SubscriptionTier.PRO:
            next_tier = SubscriptionTier.ELITE
            next_tier_display_name = "Pro"
        
        # Generate recommendations
        recommendations = []
        
        if approaching_limits:
            recommendations.append({
                "type": "resource_limits",
                "message": f"You're approaching resource limits on your current plan.",
                "resources": approaching_limits,
                "recommendation": f"Upgrade to {next_tier_display_name} for higher limits."
            })
        
        return {
            "current_tier": tier,
            "current_tier_display": get_tier_display_name(tier),
            "next_tier": next_tier,
            "next_tier_display": next_tier_display_name,
            "recommendations": recommendations,
            "upgrade_url": f"/pricing?from={tier}&to={next_tier}"
        }