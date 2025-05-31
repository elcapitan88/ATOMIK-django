# app/core/subscription_tiers.py
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

class SubscriptionTier(str, Enum):
    """Enumeration of available subscription tiers"""
    STARTER = "starter"  # This will now be for grandfathered free users only
    PRO = "pro"         # This becomes the new "Starter" tier (with old Pro features)
    ELITE = "elite"     # This becomes the new "Pro" tier (with old Elite features)

# Define resource limits for each tier
TIER_LIMITS = {
    SubscriptionTier.STARTER: {
        "connected_accounts": 1,
        "active_webhooks": 1,
        "active_strategies": 1,
        "group_strategies_allowed": False,
        "can_share_webhooks": False,
    },
    SubscriptionTier.PRO: {  # Now the new "Starter" tier with old Pro limits
        "connected_accounts": 5,
        "active_webhooks": 5, 
        "active_strategies": 5,
        "group_strategies_allowed": True,
        "can_share_webhooks": True,
    },
    SubscriptionTier.ELITE: {  # Now the new "Pro" tier with old Elite limits
        "connected_accounts": float('inf'),  # Unlimited
        "active_webhooks": float('inf'),     # Unlimited
        "active_strategies": float('inf'),   # Unlimited
        "group_strategies_allowed": True,
        "can_share_webhooks": True,
    }
}

# Marketing name mapping for the new structure
TIER_DISPLAY_NAMES = {
    SubscriptionTier.STARTER: "Legacy Free",  # For grandfathered users
    SubscriptionTier.PRO: "Starter",          # New display name
    SubscriptionTier.ELITE: "Pro"             # New display name
}

def get_tier_limit(tier: str, resource: str) -> int:
    """
    Get the resource limit for a specific subscription tier
    
    Args:
        tier: Subscription tier (starter, pro, elite)
        resource: Resource type (connected_accounts, active_webhooks, etc.)
        
    Returns:
        int: Resource limit number (float('inf') for unlimited)
    """
    tier_enum = SubscriptionTier(tier.lower()) if isinstance(tier, str) else tier
    
    if tier_enum not in TIER_LIMITS:
        raise ValueError(f"Unknown subscription tier: {tier}")
        
    if resource not in TIER_LIMITS[tier_enum]:
        raise ValueError(f"Unknown resource type: {resource}")
        
    return TIER_LIMITS[tier_enum][resource]

def is_feature_allowed(tier: str, feature: str) -> bool:
    """
    Check if a feature is allowed for a specific subscription tier
    
    Args:
        tier: Subscription tier (starter, pro, elite)
        feature: Feature to check
        
    Returns:
        bool: True if the feature is allowed, False otherwise
    """
    tier_enum = SubscriptionTier(tier.lower()) if isinstance(tier, str) else tier
    
    if tier_enum not in TIER_LIMITS:
        raise ValueError(f"Unknown subscription tier: {tier}")
        
    if feature not in TIER_LIMITS[tier_enum]:
        raise ValueError(f"Unknown feature: {feature}")
        
    return TIER_LIMITS[tier_enum][feature]

def check_resource_limit(tier: str, resource: str, current_count: int) -> bool:
    """
    Check if adding another resource would exceed the tier's limit
    
    Args:
        tier: Subscription tier (starter, pro, elite)
        resource: Resource type to check
        current_count: Current number of resources in use
        
    Returns:
        bool: True if adding another resource is allowed, False otherwise
    """
    limit = get_tier_limit(tier, resource)
    
    # Special case for unlimited resources
    if limit == float('inf'):
        return True
        
    return current_count < limit

def is_in_trial_period(subscription_created_at: datetime) -> bool:
    """
    Check if a subscription is still in the trial period
    
    Args:
        subscription_created_at: When the subscription was created
        
    Returns:
        bool: True if in trial period, False otherwise
    """
    if not subscription_created_at:
        return False
        
    trial_end_date = subscription_created_at + timedelta(days=14)
    return datetime.utcnow() <= trial_end_date

def get_tier_display_name(tier: str) -> str:
    """
    Get the marketing display name for a tier
    
    Args:
        tier: Internal tier name (starter, pro, elite)
        
    Returns:
        str: Display name for the tier
    """
    tier_enum = SubscriptionTier(tier.lower()) if isinstance(tier, str) else tier
    return TIER_DISPLAY_NAMES.get(tier_enum, tier)