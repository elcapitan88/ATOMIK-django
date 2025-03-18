# app/core/subscription_tiers.py
from enum import Enum
from typing import Dict, Any, Optional

class SubscriptionTier(str, Enum):
    """Enumeration of available subscription tiers"""
    STARTER = "starter"
    PRO = "pro"  
    ELITE = "elite"

# Define resource limits for each tier
TIER_LIMITS = {
    SubscriptionTier.STARTER: {
        "connected_accounts": 1,
        "active_webhooks": 1,
        "active_strategies": 1,
        "group_strategies_allowed": False,
        "can_share_webhooks": False,
    },
    SubscriptionTier.PRO: {
        "connected_accounts": 5,
        "active_webhooks": 5, 
        "active_strategies": 5,
        "group_strategies_allowed": True,
        "can_share_webhooks": True,
    },
    SubscriptionTier.ELITE: {
        "connected_accounts": float('inf'),  # Unlimited
        "active_webhooks": float('inf'),     # Unlimited
        "active_strategies": float('inf'),   # Unlimited
        "group_strategies_allowed": True,
        "can_share_webhooks": True,
    }
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