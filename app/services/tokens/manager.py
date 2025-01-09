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
        self.LOCK_TIMEOUT = 30  # Lock timeout in seconds

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
        """Get all active credentials that need checking"""
        try:
            current_time = datetime.utcnow()
        
        # Debug logging
            all_credentials = db.query(BrokerCredentials).all()
            logger.info(f"Total credentials in database: {len(all_credentials)}")
            logger.info(f"Credentials details: {[{
                'id': c.id,
                'broker_id': c.broker_id,
                'is_valid': c.is_valid,
                'expires_at': c.expires_at
            } for c in all_credentials]}")
        
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
            
                # Get the reference time - either last_refresh_attempt or created_at
                reference_time = credential.last_refresh_attempt
                if reference_time is None:
                # If no refresh attempt yet, use token creation time
                    reference_time = datetime.utcnow() - timedelta(seconds=1)  # Force a refresh
                
            # Calculate time used
                token_age = (current_time - reference_time).total_seconds()
                refresh_threshold = broker_config['TOKEN_LIFETIME'] * broker_config['REFRESH_THRESHOLD']
            
                logger.info(
                    f"Credential {credential.id}: "
                    f"Token age: {token_age:.0f}s, "
                    f"Will refresh after {refresh_threshold:.0f}s of use"
                )
            
            # Check if we've used the token for longer than our threshold
                if token_age >= refresh_threshold:
                    credentials_to_refresh.append(credential)
                    logger.info(
                        f"Queuing credential {credential.id} for refresh "
                        f"(used for {token_age:.0f}s)"
                    )
            
            logger.info(f"Checking {len(credentials_to_refresh)} active credentials for refresh")
            return credentials_to_refresh
            
        except Exception as e:
            logger.error(f"Error getting active credentials: {str(e)}")
            return []

    async def refresh_token_if_needed(
        self, 
        credential: BrokerCredentials,
        db: Session
    ) -> bool:
        """Refresh token with proper transaction handling"""
        credential_id = str(credential.id)
        broker_config = TokenConfig.get_broker_config(credential.broker_id)
        lock = await self.get_lock(credential_id)

        try:
            async with asyncio.timeout(self.LOCK_TIMEOUT):
                async with lock:
                    # Create new session for this operation
                    new_db = SessionLocal()
                    try:
                        # Get fresh credential instance
                        credential = new_db.query(BrokerCredentials).get(credential.id)
                        if not credential:
                            logger.error(f"Credential {credential_id} not found")
                            return False

                        # Calculate how long the token has been used
                        token_age = (datetime.utcnow() - credential.last_refresh_attempt).total_seconds()
                        refresh_threshold = broker_config['TOKEN_LIFETIME'] * broker_config['REFRESH_THRESHOLD']

                        logger.info(
                            f"Checking credential {credential_id}: "
                            f"Used for {token_age:.0f}s, "
                            f"Will refresh after {refresh_threshold:.0f}s of use"
                        )

                        # Only refresh if we've used it longer than threshold
                        if token_age < refresh_threshold:
                            logger.debug(f"No refresh needed yet for credential {credential_id}")
                            return True

                        if self._refresh_attempts.get(credential_id, 0) >= broker_config['MAX_RETRY_ATTEMPTS']:
                            await self._handle_max_retries_exceeded(credential, new_db)
                            return False

                        logger.info(f"Attempting to refresh token for credential {credential_id}")
                        broker = BaseBroker.get_broker_instance(credential.broker_id, new_db)
                        refreshed_credential = await broker.refresh_credentials(credential)
                        
                        if refreshed_credential and refreshed_credential.is_valid:
                            credential.access_token = refreshed_credential.access_token
                            credential.refresh_token = refreshed_credential.refresh_token
                            credential.expires_at = refreshed_credential.expires_at
                            credential.is_valid = True
                            credential.refresh_fail_count = 0
                            credential.last_refresh_attempt = datetime.utcnow()
                            credential.last_refresh_error = None
                            
                            new_db.commit()
                            self._reset_refresh_attempts(credential_id)
                            logger.info(f"Successfully refreshed token for credential {credential_id}")
                            await self._notify_refresh_success(credential)
                            return True
                        else:
                            raise ValueError("Invalid response from broker refresh")

                    except Exception as e:
                        new_db.rollback()
                        self._increment_refresh_attempts(credential_id)
                        await self._handle_refresh_error(credential, str(e), new_db)
                        logger.error(f"Failed to refresh token: {str(e)}")
                        return False
                    finally:
                        new_db.close()

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