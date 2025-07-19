# app/core/upgrade_prompts.py
"""
Centralized module for handling subscription upgrade prompts and messaging.
This ensures consistent upgrade messaging throughout the application.
"""
from typing import Dict, Any, Optional, Tuple
from fastapi import HTTPException, Response
from app.core.config import settings

# Base URL for pricing page
PRICING_URL = f"{settings.FRONTEND_URL}/pricing"

# Define common upgrade reasons with consistent naming
class UpgradeReason:
    ACCOUNT_LIMIT = "account_limit"
    WEBHOOK_LIMIT = "webhook_limit"
    STRATEGY_LIMIT = "strategy_limit"
    GROUP_STRATEGY = "group_strategy"
    WEBHOOK_SHARING = "webhook_sharing"
    ADVANCED_FEATURES = "advanced_features"
    API_RATE_LIMIT = "api_rate_limit"
    WEBHOOK_RATE_LIMIT = "webhook_rate_limit"

# Define tier details for quick reference
TIER_DETAILS = {
    "starter": {
        "name": "Starter",
        "accounts": "1",
        "webhooks": "1",
        "strategies": "1",
        "group_strategies": False,
        "webhook_sharing": False,
        "webhook_rate": "60/min",
        "api_rate": "100/min",
    },
    "pro": {
        "name": "Pro",
        "accounts": "5",
        "webhooks": "5",
        "strategies": "5", 
        "group_strategies": True,
        "webhook_sharing": True,
        "webhook_rate": "300/min",
        "api_rate": "500/min",
        "price_monthly": "$49/month",
        "price_yearly": "$468/year ($39/month)",
    },
    "elite": {
        "name": "Elite",
        "accounts": "Unlimited",
        "webhooks": "Unlimited",
        "strategies": "Unlimited",
        "group_strategies": True,
        "webhook_sharing": True,
        "webhook_rate": "Unlimited",
        "api_rate": "Unlimited",
        "price_monthly": "$89/month",
        "price_yearly": "$828/year ($69/month)",
        "price_lifetime": "$1,990 (one-time payment)"
    }
}

# Upgrade messages by reason
UPGRADE_MESSAGES = {
    UpgradeReason.ACCOUNT_LIMIT: {
        "starter": "You've reached the maximum number of connected accounts (1) for your Legacy Free plan. Upgrade to Starter to connect up to 5 accounts, or Pro for unlimited accounts.",
        "pro": "You've reached the maximum number of connected accounts (5) for your Starter plan. Upgrade to Pro for unlimited accounts.",
    },
    UpgradeReason.WEBHOOK_LIMIT: {
        "starter": "You've reached the maximum number of webhooks (1) for your Legacy Free plan. Upgrade to Starter for up to 5 webhooks, or Pro for unlimited webhooks.",
        "pro": "You've reached the maximum number of webhooks (5) for your Starter plan. Upgrade to Pro for unlimited webhooks.",
    },
    UpgradeReason.STRATEGY_LIMIT: {
        "starter": "You've reached the maximum number of strategies (1) for your Legacy Free plan. Upgrade to Starter for up to 5 strategies, or Pro for unlimited strategies.",
        "pro": "You've reached the maximum number of strategies (5) for your Starter plan. Upgrade to Pro for unlimited strategies.",
    },
    UpgradeReason.GROUP_STRATEGY: {
        "starter": "Group strategies are only available in Starter and Pro plans. Upgrade to access this feature.",
    },
    UpgradeReason.WEBHOOK_SHARING: {
        "starter": "Webhook sharing is only available in Starter and Pro plans. Upgrade to access this feature.",
    },
    UpgradeReason.WEBHOOK_RATE_LIMIT: {
        "starter": "You've exceeded the webhook rate limit for your Starter tier (60/min). Upgrade to Pro (300/min) or Elite (unlimited) for higher limits.",
        "pro": "You've exceeded the webhook rate limit for your Pro tier (300/min). Upgrade to Elite for unlimited webhook processing.",
    },
    UpgradeReason.API_RATE_LIMIT: {
        "starter": "You've exceeded the API rate limit for your Starter tier (100/min). Upgrade to Pro (500/min) or Elite (unlimited) for higher limits.",
        "pro": "You've exceeded the API rate limit for your Pro tier (500/min). Upgrade to Elite for unlimited API access.",
    },
    UpgradeReason.ADVANCED_FEATURES: {
        "starter": "Advanced features like this are only available in Pro and Elite tiers. Upgrade to access more features.",
    }
}

def get_upgrade_message(reason: str, current_tier: str) -> str:
    """
    Get the appropriate upgrade message based on reason and current tier.
    
    Args:
        reason: The reason code for the upgrade prompt
        current_tier: User's current subscription tier
        
    Returns:
        str: The formatted upgrade message
    """
    # If tier not found, default to starter
    if current_tier not in ["starter", "pro", "elite"]:
        current_tier = "starter"
    
    # Elite tier doesn't need upgrade messages
    if current_tier == "elite":
        return "You already have the highest tier (Elite)."
    
    # Get message for reason and tier
    tier_messages = UPGRADE_MESSAGES.get(reason, {})
    message = tier_messages.get(current_tier)
    
    # Default message if specific one not found
    if not message:
        next_tier = "Pro" if current_tier == "starter" else "Elite"
        message = f"This feature or limit requires a higher tier. Please upgrade to {next_tier} to access it."
    
    return message

def get_next_tier(current_tier: str) -> Optional[str]:
    """Get the next tier up from the current one"""
    if current_tier == "starter":
        return "pro"
    elif current_tier == "pro":
        return "elite"
    return None

def build_upgrade_response(
    reason: str,
    current_tier: str,
    status_code: int = 403,
    add_headers: bool = True
) -> Dict[str, Any]:
    """
    Build a standardized upgrade response.
    
    Args:
        reason: The reason code for the upgrade prompt
        current_tier: User's current subscription tier
        status_code: HTTP status code to use
        add_headers: Whether to add upgrade headers
        
    Returns:
        dict: Response body with upgrade information
    """
    message = get_upgrade_message(reason, current_tier)
    next_tier = get_next_tier(current_tier)
    
    response = {
        "detail": message,
        "error_code": "subscription_limit",
        "reason": reason,
        "current_tier": current_tier,
        "upgrade_url": f"{PRICING_URL}?from={current_tier}&to={next_tier}" if next_tier else None,
    }
    
    # Add comparison between current tier and recommended next tier
    if next_tier:
        response["tier_comparison"] = {
            "current": TIER_DETAILS.get(current_tier, {}),
            "recommended": TIER_DETAILS.get(next_tier, {})
        }
    
    return response

def upgrade_exception(
    reason: str,
    current_tier: str,
    detail: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None
) -> HTTPException:
    """
    Create an HTTPException with upgrade information.
    
    Args:
        reason: The reason code for the upgrade prompt
        current_tier: User's current subscription tier
        detail: Optional custom message
        headers: Additional headers to include
        
    Returns:
        HTTPException: Exception with upgrade information
    """
    message = detail or get_upgrade_message(reason, current_tier)
    next_tier = get_next_tier(current_tier)
    
    error_headers = headers or {}
    if next_tier:
        error_headers.update({
            "X-Upgrade-Required": "true",
            "X-Current-Tier": current_tier,
            "X-Recommended-Tier": next_tier,
            "X-Upgrade-Reason": reason,
            "X-Upgrade-URL": f"{PRICING_URL}?from={current_tier}&to={next_tier}"
        })
    
    return HTTPException(
        status_code=403,
        detail=message,
        headers=error_headers
    )

def add_upgrade_headers(response: Response, current_tier: str, reason: str) -> None:
    """
    Add upgrade-related headers to a FastAPI response.
    
    Args:
        response: FastAPI Response object
        current_tier: User's current subscription tier
        reason: Reason for the upgrade prompt
    """
    next_tier = get_next_tier(current_tier)
    if next_tier:
        response.headers["X-Upgrade-Required"] = "true"
        response.headers["X-Current-Tier"] = current_tier
        response.headers["X-Recommended-Tier"] = next_tier
        response.headers["X-Upgrade-Reason"] = reason
        response.headers["X-Upgrade-URL"] = f"{PRICING_URL}?from={current_tier}&to={next_tier}"