from functools import wraps
from fastapi import HTTPException, Depends, Response
import logging
from typing import Callable, Optional, List
from .config import settings
from app.services.stripe_service import StripeService
from app.services.subscription_service import SubscriptionService
from app.db.session import get_db
from app.core.subscription_tiers import SubscriptionTier
from app.core.security import get_current_user
from app.core.upgrade_prompts import upgrade_exception, UpgradeReason, add_upgrade_headers
from app.services.chat_role_service import is_user_beta_tester as is_user_chat_beta_tester, is_user_admin as is_user_chat_admin, is_user_moderator as is_user_chat_moderator

logger = logging.getLogger(__name__)

def check_subscription(func: Callable):
    """Verify user has an active subscription"""
    @wraps(func)
    async def wrapper(*args, current_user=None, **kwargs):
        if settings.SKIP_SUBSCRIPTION_CHECK:
            logger.debug("Skipping subscription check - Development Mode")
            return await func(*args, current_user=current_user, **kwargs)
        
        try:
            if not current_user or not current_user.subscription:
                raise HTTPException(
                    status_code=403,
                    detail="Active subscription required"
                )

            # Handle lifetime users without Stripe (previous app users)
            if not current_user.subscription.stripe_customer_id:
                if current_user.subscription.status == "active" and current_user.subscription.is_lifetime:
                    logger.info(f"Access granted to non-Stripe lifetime user: {current_user.email}")
                    return await func(*args, current_user=current_user, **kwargs)
                else:
                    raise HTTPException(
                        status_code=403,
                        detail="Your subscription is not active"
                    )

            # Handle Stripe users - check for grace period first
            subscription = current_user.subscription
            
            # Allow access during grace period
            if subscription.is_in_grace_period:
                logger.info(f"Access granted during grace period: {current_user.email}, days left: {subscription.days_left_in_grace_period}")
                return await func(*args, current_user=current_user, **kwargs)
            
            # Check if subscription is suspended
            if subscription.is_suspended:
                raise HTTPException(
                    status_code=403,
                    detail="Your subscription is suspended due to payment failure. Please update your payment method to restore access."
                )
            
            # Standard Stripe verification for non-grace period cases
            stripe_service = StripeService()
            has_active_subscription = await stripe_service.verify_subscription_status(
                subscription.stripe_customer_id
            )

            if not has_active_subscription:
                raise HTTPException(
                    status_code=403,
                    detail="Your subscription is not active"
                )

            return await func(*args, current_user=current_user, **kwargs)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Subscription check error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error verifying subscription"
            )

    return wrapper

def require_tier(minimum_tier: str):
    """
    Decorator to check if user has required subscription tier
    
    Args:
        minimum_tier: Minimum required tier (starter, pro, elite)
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, db=Depends(get_db), current_user=None, response: Response = None, **kwargs):
            if settings.SKIP_SUBSCRIPTION_CHECK:
                logger.debug(f"Skipping tier check for {minimum_tier} - Development Mode")
                return await func(*args, current_user=current_user, db=db, **kwargs)
            
            try:
                # Get subscription tier
                if not current_user or not current_user.subscription:
                    raise HTTPException(
                        status_code=403,
                        detail="Active subscription required"
                    )
                
                user_tier = current_user.subscription.tier
                tier_levels = {
                    "starter": 0,
                    "pro": 1,
                    "elite": 2
                }
                
                if tier_levels.get(user_tier.lower(), -1) < tier_levels.get(minimum_tier.lower(), 0):
                    # Map required tier to reason code
                    reason_mapping = {
                        "pro": UpgradeReason.ADVANCED_FEATURES,
                        "elite": UpgradeReason.ADVANCED_FEATURES
                    }
                    
                    reason = reason_mapping.get(minimum_tier.lower(), UpgradeReason.ADVANCED_FEATURES)
                    
                    # Add upgrade headers if response object available
                    if response:
                        add_upgrade_headers(response, user_tier, reason)
                        
                    # Create exception with standardized upgrade message
                    raise upgrade_exception(
                        reason=reason,
                        current_tier=user_tier,
                        detail=f"This feature requires {minimum_tier.capitalize()} tier or higher"
                    )
                
                return await func(*args, current_user=current_user, db=db, response=response if response else None, **kwargs)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Tier requirement check error: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Error checking subscription tier"
                )
                
        return wrapper
    return decorator

def check_resource_limit(resource_type: str):
    """
    Decorator to check if user can add more of a specific resource
    
    Args:
        resource_type: Type of resource (connected_accounts, active_webhooks, active_strategies)
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, db=Depends(get_db), current_user=None, response: Response = None, **kwargs):
            if settings.SKIP_SUBSCRIPTION_CHECK:
                logger.debug(f"Skipping resource limit check for {resource_type} - Development Mode")
                return await func(*args, current_user=current_user, db=db, **kwargs)
            
            try:
                if not current_user:
                    raise HTTPException(
                        status_code=401,
                        detail="Authentication required"
                    )
                
                # Map resource type to reason code for upgrade messages
                reason_mapping = {
                    "connected_accounts": UpgradeReason.ACCOUNT_LIMIT,
                    "active_webhooks": UpgradeReason.WEBHOOK_LIMIT,
                    "active_strategies": UpgradeReason.STRATEGY_LIMIT,
                }
                reason = reason_mapping.get(resource_type, UpgradeReason.ADVANCED_FEATURES)
                
                # Use subscription service to check resource limits
                subscription_service = SubscriptionService(db)
                can_add, message = subscription_service.can_add_resource(
                    current_user.id, 
                    resource_type
                )
                
                if not can_add:
                    logger.warning(f"Resource limit reached: user {current_user.id}, resource {resource_type}")
                    
                    # Get user's subscription tier
                    user_tier = subscription_service.get_user_tier(current_user.id)
                    
                    # Add upgrade headers if response object available
                    if response:
                        add_upgrade_headers(response, user_tier, reason)
                    
                    # Raise exception with proper upgrade information
                    raise upgrade_exception(
                        reason=reason,
                        current_tier=user_tier,
                        detail=message
                    )
                
                return await func(*args, current_user=current_user, db=db, response=response if response else None, **kwargs)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Resource limit check error: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Error checking resource limits"
                )
                
        return wrapper
    return decorator

def check_feature_access(feature: str):
    """
    Decorator to check if user has access to a specific feature
    
    Args:
        feature: Feature name to check access for
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, db=Depends(get_db), current_user=None, response: Response = None, **kwargs):
            if settings.SKIP_SUBSCRIPTION_CHECK:
                logger.debug(f"Skipping feature access check for {feature} - Development Mode")
                return await func(*args, current_user=current_user, db=db, **kwargs)
            
            try:
                if not current_user:
                    raise HTTPException(
                        status_code=401,
                        detail="Authentication required"
                    )
                
                # Map feature to reason code
                reason_mapping = {
                    "group_strategies_allowed": UpgradeReason.GROUP_STRATEGY,
                    "can_share_webhooks": UpgradeReason.WEBHOOK_SHARING
                }
                reason = reason_mapping.get(feature, UpgradeReason.ADVANCED_FEATURES)
                
                # Use subscription service to check feature access
                subscription_service = SubscriptionService(db)
                has_access, message = subscription_service.is_feature_available(
                    current_user.id, 
                    feature
                )
                
                if not has_access:
                    logger.warning(f"Feature access denied: user {current_user.id}, feature {feature}")
                    
                    # Get user's tier
                    user_tier = subscription_service.get_user_tier(current_user.id)
                    
                    # Add upgrade headers if response object available
                    if response:
                        add_upgrade_headers(response, user_tier, reason)
                    
                    # Raise exception with proper upgrade information
                    raise upgrade_exception(
                        reason=reason,
                        current_tier=user_tier,
                        detail=message
                    )
                
                return await func(*args, current_user=current_user, db=db, response=response if response else None, **kwargs)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Feature access check error: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Error checking feature access"
                )
                
        return wrapper
    return decorator

def check_rate_limit(limit_type: str):
    """
    Decorator to check rate limits based on subscription tier
    
    Args:
        limit_type: Type of rate limit to check (api, webhook)
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, db=Depends(get_db), current_user=None, response: Response = None, **kwargs):
            if settings.SKIP_SUBSCRIPTION_CHECK:
                logger.debug(f"Skipping rate limit check for {limit_type} - Development Mode")
                return await func(*args, current_user=current_user, db=db, **kwargs)
            
            try:
                if not current_user:
                    raise HTTPException(
                        status_code=401,
                        detail="Authentication required"
                    )
                
                # Map limit type to reason code
                reason_mapping = {
                    "api": UpgradeReason.API_RATE_LIMIT,
                    "webhook": UpgradeReason.WEBHOOK_RATE_LIMIT,
                }
                reason = reason_mapping.get(limit_type, UpgradeReason.ADVANCED_FEATURES)
                
                # Get user's tier for rate limit determination
                user_tier = SubscriptionService(db).get_user_tier(current_user.id)
                
                # Check rate limit (basic implementation - replace with actual rate limiter)
                # This is a placeholder - you would use Redis or similar for actual rate limiting
                is_rate_limited = False  # Replace with actual check
                
                if is_rate_limited:
                    logger.warning(f"Rate limit reached: user {current_user.id}, limit {limit_type}")
                    
                    # Add upgrade headers
                    if response:
                        add_upgrade_headers(response, user_tier, reason)
                    
                    # Raise exception with proper upgrade information
                    raise upgrade_exception(
                        reason=reason,
                        current_tier=user_tier
                    )
                
                return await func(*args, current_user=current_user, db=db, response=response if response else None, **kwargs)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Rate limit check error: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Error checking rate limits"
                )
                
        return wrapper
    return decorator


def check_beta_access(feature_name: Optional[str] = None):
    """
    Decorator to check if user has beta tester access
    
    Args:
        feature_name: Optional specific beta feature name to check
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, db=Depends(get_db), current_user=None, response: Response = None, **kwargs):
            try:
                if not current_user:
                    raise HTTPException(
                        status_code=401,
                        detail="Authentication required"
                    )
                
                # Check if user has beta access via app_role first, then chat roles as fallback
                has_beta_access = (
                    current_user.is_beta_tester() or  # Check app_role first
                    await is_user_chat_admin(db, current_user.id) or  # Chat admin role
                    await is_user_chat_moderator(db, current_user.id) or  # Chat moderator role
                    await is_user_chat_beta_tester(db, current_user.id)  # Chat beta tester role
                )
                
                if not has_beta_access:
                    logger.warning(f"Beta access denied: user {current_user.id}, feature {feature_name}")
                    raise HTTPException(
                        status_code=403,
                        detail="Beta tester access required for this feature"
                    )
                
                return await func(*args, current_user=current_user, db=db, response=response if response else None, **kwargs)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Beta access check error: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Error checking beta access"
                )
                
        return wrapper
    return decorator


async def check_beta_feature_access(db, user_id: int, feature_name: str, user=None) -> bool:
    """
    Check if a user has access to a specific beta feature
    
    Args:
        db: Database session
        user_id: User ID to check
        feature_name: Beta feature name
        user: Optional User object to avoid additional queries
    
    Returns:
        bool: True if user has access, False otherwise
    """
    try:
        # If user object provided, check app_role first
        if user:
            if user.is_beta_tester():  # This includes admin, moderator, beta_tester
                return True
        
        # Fallback to chat roles for backwards compatibility
        if await is_user_chat_admin(db, user_id) or await is_user_chat_moderator(db, user_id):
            return True
        
        # Beta testers have access to beta features
        if await is_user_chat_beta_tester(db, user_id):
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error checking beta feature access: {str(e)}")
        return False


async def get_user_beta_features(db, user_id: int, user=None) -> List[str]:
    """
    Get list of beta features available to a user
    
    Args:
        db: Database session
        user_id: User ID
    
    Returns:
        List[str]: List of available beta feature names
    """
    try:
        # Define available beta features
        all_beta_features = [
            "advanced-analytics",
            "new-dashboard",
            "experimental-trading",
            "ai-insights",
            "advanced-charts"
        ]
        
        # Check if user has beta access
        has_beta_access = await check_beta_feature_access(db, user_id, "", user)
        
        if has_beta_access:
            return all_beta_features
        else:
            return []
            
    except Exception as e:
        logger.error(f"Error getting user beta features: {str(e)}")
        return []


# Beta feature constants
BETA_FEATURES = {
    "ADVANCED_ANALYTICS": "advanced-analytics",
    "NEW_DASHBOARD": "new-dashboard", 
    "EXPERIMENTAL_TRADING": "experimental-trading",
    "AI_INSIGHTS": "ai-insights",
    "ADVANCED_CHARTS": "advanced-charts"
}