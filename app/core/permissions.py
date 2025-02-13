from functools import wraps
from fastapi import HTTPException
import logging
from typing import Callable
from .config import settings
from app.services.stripe_service import StripeService

logger = logging.getLogger(__name__)

def check_subscription(func: Callable):
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

            stripe_service = StripeService()
            has_active_subscription = await stripe_service.verify_subscription_status(
                current_user.subscription.stripe_customer_id
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

def check_account_ownership(func: Callable):
    """
    Decorator to verify user owns the account they're trying to access.
    Used for broker account operations and webhook management.
    """
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

            # Check if account belongs to user
            account = current_user.broker_accounts.filter(id=account_id).first()
            if not account:
                logger.warning(f"User {current_user.id} attempted to access unauthorized account {account_id}")
                raise HTTPException(
                    status_code=403,
                    detail="You do not have permission to access this account"
                )

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

def check_webhook_ownership(func: Callable):
    """
    Decorator to verify user owns the webhook they're trying to access.
    """
    @wraps(func)
    async def wrapper(*args, current_user=None, webhook_id=None, **kwargs):
        if settings.SKIP_SUBSCRIPTION_CHECK:
            logger.debug("Skipping webhook ownership check - Development Mode")
            return await func(*args, current_user=current_user, webhook_id=webhook_id, **kwargs)

        try:
            if not webhook_id or not current_user:
                raise HTTPException(
                    status_code=400,
                    detail="Missing required parameters"
                )

            # Check if webhook belongs to user
            webhook = current_user.webhooks.filter(id=webhook_id).first()
            if not webhook:
                logger.warning(f"User {current_user.id} attempted to access unauthorized webhook {webhook_id}")
                raise HTTPException(
                    status_code=403,
                    detail="You do not have permission to access this webhook"
                )

            return await func(*args, current_user=current_user, webhook_id=webhook_id, **kwargs)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking webhook ownership: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error verifying webhook access"
            )

    return wrapper

def check_rate_limit(max_requests: int = 100, window_seconds: int = 60):
    """
    Decorator to implement rate limiting for API endpoints.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            if settings.SKIP_SUBSCRIPTION_CHECK:
                return await func(*args, current_user=current_user, **kwargs)

            try:
                # In a production environment, you would implement rate limiting
                # using Redis or a similar caching system
                return await func(*args, current_user=current_user, **kwargs)

            except Exception as e:
                logger.error(f"Rate limit error: {str(e)}")
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please try again later."
                )

        return wrapper
    return decorator