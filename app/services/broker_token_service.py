from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import logging
from typing import Optional

from app.models.broker import BrokerCredentials
from app.services.tokens.manager import token_manager  # Updated import path

logger = logging.getLogger(__name__)

class BrokerTokenService:
    def __init__(self, db: Session):
        self.db = db

    async def validate_token(self, credentials: BrokerCredentials) -> bool:
        """Validate if token is still valid"""
        try:
            return await token_manager.validate_token(credentials)
        except Exception as e:
            logger.error(f"Error validating token: {str(e)}")
            return False

    async def refresh_token_if_needed(self, credentials: BrokerCredentials) -> bool:
        """Refresh token if needed"""
        try:
            return await token_manager.refresh_token_if_needed(credentials, self.db)
        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            return False

    async def invalidate_token(self, credentials: BrokerCredentials):
        """Invalidate a token"""
        try:
            credentials.is_valid = False
            credentials.error_message = "Token manually invalidated"
            self.db.commit()
            logger.info(f"Token invalidated for credential {credentials.id}")
        except Exception as e:
            logger.error(f"Error invalidating token: {str(e)}")
            self.db.rollback()
            raise

    async def get_token_status(self, credentials: BrokerCredentials) -> dict:
        """Get detailed token status"""
        return {
            "is_valid": credentials.is_valid,
            "updated_at": credentials.updated_at,
            "expires_at": credentials.expires_at,
            "refresh_fail_count": credentials.refresh_fail_count,
            "last_refresh_error": credentials.last_refresh_error,
            "needs_refresh": not await self.validate_token(credentials)
        }