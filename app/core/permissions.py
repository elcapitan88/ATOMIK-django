from functools import wraps
from fastapi import HTTPException
import logging
from typing import Callable
from .config import settings
from app.models.subscription import SubscriptionTier, SubscriptionStatus

logger = logging.getLogger(__name__)

def check_subscription_feature(required_tier: SubscriptionTier):
    """
    Decorator to check if user has required subscription tier for a feature.
    In development mode (SKIP_SUBSCRIPTION_CHECK=True), all checks are bypassed.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            # Development mode - skip all subscription checks
            if settings.SKIP_SUBSCRIPTION_CHECK:
                logger.debug("Skipping subscription check - Development Mode")
                return await func(*args, current_user=current_user, **kwargs)
            
            try:
                # Production mode - verify subscription
                if not current_user or not current_user.subscription:
                    logger.warning(f"No subscription found for user {current_user.id if current_user else 'unknown'}")
                    raise HTTPException(
                        status_code=403,
                        detail="Active subscription required to access this feature"
                    )

                subscription = current_user.subscription
                
                # Check subscription status
                if subscription.status not in [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]:
                    logger.warning(f"Invalid subscription status: {subscription.status}")
                    raise HTTPException(
                        status_code=403,
                        detail="Your subscription is not active"
                    )

                # Lifetime subscribers have access to all features
                if subscription.tier == SubscriptionTier.LIFETIME:
                    return await func(*args, current_user=current_user, **kwargs)

                # Define tier hierarchy
                tier_levels = {
                    SubscriptionTier.STARTED: 1,
                    SubscriptionTier.PLUS: 2,
                    SubscriptionTier.PRO: 3,
                    SubscriptionTier.LIFETIME: 4
                }

                # Check if user's tier is sufficient
                if tier_levels[subscription.tier] < tier_levels[required_tier]:
                    logger.warning(
                        f"Insufficient subscription tier. Required: {required_tier}, "
                        f"Current: {subscription.tier}"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"This feature requires {required_tier.value} subscription or higher"
                    )

                return await func(*args, current_user=current_user, **kwargs)

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Unexpected error in subscription check: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Error verifying subscription access"
                )

        return wrapper
    return decorator

def check_account_ownership(func: Callable):
    """Decorator to verify user owns the account they're trying to access"""
    @wraps(func)
    async def wrapper(*args, current_user=None, account_id=None, **kwargs):
        if settings.SKIP_SUBSCRIPTION_CHECK:
            logger.debug("Skipping ownership check - Development Mode")
            return await func(*args, current_user=current_user, account_id=account_id, **kwargs)

        try:
            if not account_id or not current_user:
                raise HTTPException(
                    status_code=400,
                    detail="Missing required parameters"
                )

            # Account ownership check would go here
            # This is a placeholder for when you implement account ownership verification
            
            return await func(*args, current_user=current_user, account_id=account_id, **kwargs)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking account ownership: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error verifying account access"
            )

    return wrapper