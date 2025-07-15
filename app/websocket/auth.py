"""
WebSocket Authentication Helper

Handles JWT token validation for Application WebSocket connections.
Reuses existing authentication infrastructure from the main API.
"""

import logging
from typing import Optional
from fastapi import WebSocketException, status
from jose import JWTError, jwt

from app.core.config import settings
from app.db.base import get_db
from app.models.user import User

logger = logging.getLogger(__name__)


async def get_current_user_websocket(token: str) -> Optional[User]:
    """
    Validate JWT token for WebSocket connection and return user.
    
    This is the WebSocket equivalent of get_current_user() dependency.
    
    Args:
        token: JWT token from WebSocket query parameter
        
    Returns:
        User object if token is valid, None otherwise
        
    Raises:
        WebSocketException: If token is invalid or user not found
    """
    try:
        # Decode JWT token
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        
        email: str = payload.get("sub")
        if email is None:
            logger.warning("🔒 WebSocket auth failed: No email in token")
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid token: no email"
            )
            
    except JWTError as e:
        logger.warning(f"🔒 WebSocket auth failed: JWT error - {e}")
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid token: JWT decode failed"
        )
    
    # Get database session
    db = next(get_db())
    try:
        # Get user from database using email (matching core/security.py pattern)
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            logger.warning(f"🔒 WebSocket auth failed: User {email} not found")
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid token: user not found"
            )
        
        # Check if user is active
        if not user.is_active:
            logger.warning(f"🔒 WebSocket auth failed: User {user.email} is inactive")
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid token: user inactive"
            )
        
        logger.debug(f"✅ WebSocket auth successful for user {user.id} ({user.email})")
        return user
        
    except Exception as e:
        logger.error(f"❌ Database error during WebSocket auth: {e}")
        raise WebSocketException(
            code=status.WS_1011_INTERNAL_ERROR,
            reason="Database error during authentication"
        )
    finally:
        db.close()


async def validate_websocket_permissions(user: User, requested_channels: list = None) -> bool:
    """
    Validate user permissions for WebSocket features.
    
    Args:
        user: Authenticated user
        requested_channels: List of channel IDs user wants to access
        
    Returns:
        bool: True if user has required permissions
    """
    try:
        # Basic permission: user must be active
        if not user.is_active:
            logger.warning(f"🔒 Permission denied: User {user.id} is inactive")
            return False
        
        # TODO: Add subscription-based channel access control
        # For now, all active users can access all channels
        # Future: Check user subscription tier vs channel requirements
        
        # Check if user has chat access (could be subscription-based)
        # For now, all users have chat access
        has_chat_access = True
        
        if not has_chat_access:
            logger.warning(f"🔒 Permission denied: User {user.id} lacks chat access")
            return False
        
        # Log successful permission validation
        logger.debug(f"✅ WebSocket permissions validated for user {user.id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error validating WebSocket permissions: {e}")
        return False


async def get_user_chat_channels(user: User) -> list:
    """
    Get list of chat channels the user has access to.
    
    Args:
        user: Authenticated user
        
    Returns:
        List of channel IDs user can access
    """
    try:
        # Get database session
        db = next(get_db())
        
        try:
            # TODO: Query user's actual channel memberships from database
            # For now, return default channels based on user role/subscription
            
            default_channels = ["general"]  # All users get general channel
            
            # Add channels based on user role (superuser functionality removed)
            
            # Add channels based on subscription tier (future enhancement)
            # if user.subscription_tier in ["pro", "premium"]:
            #     default_channels.extend(["premium-chat", "signals"])
            
            logger.debug(f"📡 User {user.id} has access to channels: {default_channels}")
            return default_channels
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"❌ Error getting user chat channels: {e}")
        return ["general"]  # Fallback to general channel only


class WebSocketTokenValidator:
    """
    Helper class for validating WebSocket tokens with caching.
    
    This can be used for more advanced token validation scenarios.
    """
    
    def __init__(self):
        self._token_cache = {}  # Simple in-memory cache for validated tokens
        self._cache_ttl = 300   # 5 minutes cache TTL
    
    async def validate_token(self, token: str) -> Optional[User]:
        """
        Validate token with optional caching.
        
        Args:
            token: JWT token to validate
            
        Returns:
            User object if valid, None otherwise
        """
        # For now, always validate fresh (no caching)
        # Future enhancement: implement smart caching with TTL
        return await get_current_user_websocket(token)
    
    def clear_cache(self):
        """Clear the token cache."""
        self._token_cache.clear()
        logger.debug("🧹 WebSocket token cache cleared")


# Global token validator instance
websocket_token_validator = WebSocketTokenValidator()


# Backwards compatibility functions
async def authenticate_websocket(token: str) -> User:
    """
    Authenticate WebSocket connection (backwards compatibility).
    
    Args:
        token: JWT token
        
    Returns:
        User object
        
    Raises:
        WebSocketException: If authentication fails
    """
    return await get_current_user_websocket(token)


async def check_websocket_access(user: User, channel_id: str = None) -> bool:
    """
    Check if user has access to WebSocket features (backwards compatibility).
    
    Args:
        user: User to check
        channel_id: Optional specific channel to check
        
    Returns:
        bool: True if access granted
    """
    # Basic access check
    has_access = await validate_websocket_permissions(user)
    
    if not has_access:
        return False
    
    # Channel-specific check
    if channel_id:
        user_channels = await get_user_chat_channels(user)
        return channel_id in user_channels
    
    return True