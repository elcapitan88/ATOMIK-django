# app/services/broker_token_service.py
from datetime import datetime
from sqlalchemy.orm import Session
import logging
from typing import Optional, Dict, Any

from app.models.broker import BrokerCredentials

logger = logging.getLogger(__name__)

class BrokerTokenService:
    """
    Service for broker token validation.
    
    Note: Token refresh is now handled by the standalone token-refresh-service.
    This service focuses solely on token validation and manual invalidation.
    """
    
    def __init__(self, db: Session):
        self.db = db

    async def validate_token(self, credentials: BrokerCredentials) -> bool:
        """
        Check if a token is valid based on expiration time and is_valid flag
        
        This method only checks if the token is valid according to local data.
        Token refreshing is handled by the token-refresh-service.
        
        Args:
            credentials: The broker credentials to validate
            
        Returns:
            bool: True if the token is valid, False otherwise
        """
        try:
            if not credentials:
                logger.warning("Null credentials provided to validate_token")
                return False
                
            # Check if token is marked as invalid
            if not credentials.is_valid:
                return False
                
            # Check if token is expired
            if credentials.expires_at <= datetime.utcnow():
                logger.info(f"Token expired for credential {credentials.id}")
                return False
                
            # If has access token, is marked valid, and isn't expired, it's valid
            return True
            
        except Exception as e:
            logger.error(f"Error validating token: {str(e)}")
            return False

    async def invalidate_token(self, credentials: BrokerCredentials):
        """
        Manually invalidate a token
        
        This should ONLY be used when a broker account is being explicitly
        disconnected by the user or when required for security reasons.
        Note: User logout should NOT trigger token invalidation - broker connections
        should persist regardless of user login status.
        """
        try:
            credentials.is_valid = False
            credentials.error_message = "Token manually invalidated"
            self.db.commit()
            logger.info(f"Token invalidated for credential {credentials.id}")
        except Exception as e:
            logger.error(f"Error invalidating token: {str(e)}")
            self.db.rollback()
            raise

    async def get_token_status(self, credentials: BrokerCredentials) -> Dict[str, Any]:
        """
        Get detailed token status information
        
        Returns status information about the token for display or debugging purposes.
        """
        if not credentials:
            return {
                "is_valid": False,
                "error": "No credentials provided"
            }
            
        return {
            "is_valid": credentials.is_valid,
            "updated_at": credentials.updated_at,
            "expires_at": credentials.expires_at,
            "refresh_fail_count": credentials.refresh_fail_count,
            "last_refresh_error": credentials.last_refresh_error,
            "refresh_handled_by": "token-refresh-service"  # Indicate the new architecture
        }