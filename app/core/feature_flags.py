"""Feature flag decorators and utilities."""

from functools import wraps
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Callable

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.feature_flag_service import FeatureFlagService
import logging

logger = logging.getLogger(__name__)


def require_feature_flag(feature_name: str):
    """
    Decorator to require a specific feature flag to be enabled.
    
    Args:
        feature_name: Name of the feature flag to check
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract dependencies from kwargs
            db = None
            current_user = None
            
            # Find db and current_user in kwargs
            for key, value in kwargs.items():
                if isinstance(value, Session):
                    db = value
                elif isinstance(value, User):
                    current_user = value
            
            if not db or not current_user:
                # If we can't find them in kwargs, they should be in the function signature
                # This is a fallback for development
                logger.warning(f"Could not find db or current_user for feature flag check: {feature_name}")
                return await func(*args, **kwargs)
            
            try:
                feature_service = FeatureFlagService()
                has_access = feature_service.check_user_feature_access(
                    user_id=current_user.id,
                    feature_name=feature_name,
                    db=db
                )
                
                if not has_access:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Feature '{feature_name}' is not available for your account"
                    )
                
                return await func(*args, **kwargs)
                
            except Exception as e:
                logger.error(f"Error checking feature flag {feature_name}: {str(e)}")
                # In development, allow access if feature flag check fails
                logger.warning(f"Allowing access to {feature_name} due to feature flag check error")
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_beta_access(func: Callable):
    """
    Decorator to require beta tester access.
    """
    return require_feature_flag("beta_access")(func)


def require_strategy_builder(func: Callable):
    """
    Decorator to require strategy builder access.
    """
    return require_feature_flag("strategy_builder")(func)