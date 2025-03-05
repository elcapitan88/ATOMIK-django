from typing import Dict, List, Optional, Any
import asyncio
from datetime import datetime, timedelta
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError

from app.models.broker import BrokerCredentials, BrokerAccount
from app.core.brokers.base import BaseBroker
from app.core.config import settings
from app.db.session import SessionLocal
from fastapi import HTTPException
from app.core.brokers.config import TokenConfig

logger = logging.getLogger(__name__)



class TokenManager:
    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._refresh_attempts: Dict[str, int] = {}
        self.LOCK_TIMEOUT = 30

    async def get_lock(self, credential_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific credential"""
        if credential_id not in self._locks:
            self._locks[credential_id] = asyncio.Lock()
        return self._locks[credential_id]

    def _get_refresh_attempts(self, credential_id: str) -> int:
        """Get current refresh attempts for a credential"""
        return self._refresh_attempts.get(credential_id, 0)

    def _increment_refresh_attempts(self, credential_id: str):
        """Increment refresh attempts counter"""
        self._refresh_attempts[credential_id] = self._get_refresh_attempts(credential_id) + 1
        logger.info(f"Incremented refresh attempts for credential {credential_id} to {self._refresh_attempts[credential_id]}")

    def _reset_refresh_attempts(self, credential_id: str):
        """Reset refresh attempts counter"""
        if credential_id in self._refresh_attempts:
            del self._refresh_attempts[credential_id]
            logger.info(f"Reset refresh attempts for credential {credential_id}")

    async def get_active_credentials(self, db: Session) -> list[BrokerCredentials]:
        try:
            current_time = datetime.utcnow()
            
            credentials = (
                db.query(BrokerCredentials)
                .join(BrokerAccount)
                .filter(
                    BrokerCredentials.is_valid == True,
                    BrokerAccount.is_active == True,
                    BrokerAccount.deleted_at.is_(None)
                )
                .all()
            )
            
            credentials_to_refresh = []
            for credential in credentials:
                broker_config = TokenConfig.get_broker_config(credential.broker_id)
                
                # Get reference time (last refresh or creation time)
                reference_time = credential.last_refresh_attempt or credential.created_at
                
                # Calculate time until refresh
                token_lifetime = broker_config['TOKEN_LIFETIME']
                refresh_threshold = broker_config['REFRESH_THRESHOLD']
                refresh_at = token_lifetime * refresh_threshold
                
                time_used = (current_time - reference_time).total_seconds()
                time_until_refresh = refresh_at - time_used
                
                logger.info(
                    f"Credential {credential.id}: "
                    f"Time until refresh: {time_until_refresh:.0f} seconds "
                    f"(Will refresh after {refresh_at:.0f} seconds of use)"
                )
                
                # Check if we should refresh
                if time_used >= refresh_at:
                    credentials_to_refresh.append(credential)
                    logger.info(
                        f"Queuing credential {credential.id} for refresh "
                        f"(Used for {time_used:.0f} seconds, "
                        f"Refresh threshold: {refresh_at:.0f} seconds)"
                    )
            
            return credentials_to_refresh
                
        except Exception as e:
            logger.error(f"Error getting active credentials: {str(e)}")
            return []

    async def refresh_token_if_needed(self, credential: BrokerCredentials, db: Session) -> bool:
        """Refresh token with proper transaction handling"""
        credential_id = str(credential.id)
        broker_config = TokenConfig.get_broker_config(credential.broker_id)
        lock = await self.get_lock(credential_id)

        try:
            # Define the task that will run inside the lock
            async def locked_task():
                # Create new session for this operation
                new_db = SessionLocal()
                local_credential = None  # Initialize the variable to prevent reference errors
                try:
                    # Get fresh credential instance
                    local_credential = new_db.query(BrokerCredentials).get(credential.id)
                    if not local_credential:
                        logger.error(f"Credential {credential_id} not found in database")
                        return False
                    
                    # Check if refresh is needed
                    time_until_expiry = (local_credential.expires_at - datetime.utcnow()).total_seconds()
                    refresh_threshold = broker_config['REFRESH_THRESHOLD']
                    token_lifetime = broker_config['TOKEN_LIFETIME']
                    
                    logger.info(
                        f"Credential {credential_id} expires in {time_until_expiry:.0f} seconds. "
                        f"Refresh threshold: {refresh_threshold * token_lifetime:.0f} seconds"
                    )

                    if time_until_expiry > (refresh_threshold * token_lifetime):
                        return True

                    if self._refresh_attempts.get(credential_id, 0) >= broker_config['MAX_RETRY_ATTEMPTS']:
                        await self._handle_max_retries_exceeded(local_credential, new_db)
                        return False

                    logger.info(f"Attempting to refresh token for credential {credential_id}")
                    broker = BaseBroker.get_broker_instance(local_credential.broker_id, new_db)
                    refreshed_credential = await broker.refresh_credentials(local_credential)
                    
                    if refreshed_credential and refreshed_credential.is_valid:
                        local_credential.access_token = refreshed_credential.access_token
                        local_credential.refresh_token = refreshed_credential.refresh_token
                        local_credential.expires_at = refreshed_credential.expires_at
                        local_credential.is_valid = True
                        local_credential.refresh_fail_count = 0
                        local_credential.last_refresh_attempt = datetime.utcnow()
                        local_credential.last_refresh_error = None
                        
                        new_db.commit()
                        self._reset_refresh_attempts(credential_id)
                        logger.info(f"Successfully refreshed token for credential {credential_id}")
                        await self._notify_refresh_success(local_credential)
                        return True
                    else:
                        raise ValueError("Invalid response from broker refresh")

                except Exception as e:
                    new_db.rollback()
                    self._increment_refresh_attempts(credential_id)
                    # Use local_credential only if it was successfully initialized
                    if local_credential:
                        await self._handle_refresh_error(local_credential, str(e), new_db)
                    else:
                        logger.error(f"Refresh error for credential {credential_id} that couldn't be loaded: {str(e)}")
                    logger.error(f"Failed to refresh token: {str(e)}")
                    return False
                finally:
                    new_db.close()

            # Execute the task with a timeout
            return await asyncio.wait_for(locked_task(), timeout=self.LOCK_TIMEOUT)

        except asyncio.TimeoutError:
            logger.error(f"Lock acquisition timeout for credential {credential_id}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in token refresh: {str(e)}")
            return False

    async def _handle_max_retries_exceeded(self, credential: BrokerCredentials, db: Session):
        """Handle case when max refresh retries are exceeded"""
        logger.error(f"Max refresh attempts exceeded for credential {credential.id}")
        
        try:
            credential.is_valid = False
            credential.error_message = "Max refresh attempts exceeded"
            
            # Deactivate associated account
            if credential.account:
                credential.account.is_active = False
                credential.account.status = "token_expired"
            
            db.commit()
            await self._notify_token_expiration(credential)
                
        except Exception as e:
            logger.error(f"Error handling max retries: {str(e)}")

    async def _handle_refresh_error(self, credential: BrokerCredentials, error: str, db: Session):
        """Handle refresh error and update credential status"""
        try:
            if not credential:
                logger.error(f"Cannot handle refresh error: credential is None")
                return
                
            credential.refresh_fail_count = (credential.refresh_fail_count or 0) + 1
            credential.last_refresh_error = error
            credential.last_refresh_attempt = datetime.utcnow()
            
            db.commit()
            
            if credential.refresh_fail_count >= TokenConfig.get_broker_config(credential.broker_id)['MAX_RETRY_ATTEMPTS']:
                await self._handle_max_retries_exceeded(credential, db)
            else:
                await self._notify_refresh_error(credential, error)
                
        except Exception as e:
            logger.error(f"Error handling refresh error: {str(e)}")

    async def validate_token(self, credential: BrokerCredentials) -> bool:
        """Validate if a token is still valid"""
        try:
            if not credential:
                logger.error("Cannot validate null credential")
                return False
                
            # Check if token is marked as invalid
            if not credential.is_valid:
                return False
                
            # Check if token is expired
            if credential.expires_at and credential.expires_at <= datetime.utcnow():
                logger.info(f"Token expired for credential {credential.id}")
                return False
                
            # If has access token and isn't expired, it's valid
            return True
        except Exception as e:
            logger.error(f"Error validating token for credential {credential.id}: {str(e)}")
            return False

    async def _notify_refresh_success(self, credential: BrokerCredentials):
        """Notify successful token refresh"""
        logger.info(f"Token refreshed successfully for credential {credential.id}")

    async def _notify_refresh_error(self, credential: BrokerCredentials, error: str):
        """Notify token refresh error"""
        logger.warning(f"Token refresh failed for credential {credential.id}: {error}")

    async def _notify_token_expiration(self, credential: BrokerCredentials):
        """Notify token expiration"""
        logger.error(f"Token expired for credential {credential.id}")

# Create singleton instance
token_manager = TokenManager()