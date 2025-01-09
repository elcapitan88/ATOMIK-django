# app/core/tasks/token_refresh.py

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.services.tokens.manager import token_manager
from app.services.broker_token_service import BrokerTokenService
from app.models.broker import BrokerCredentials
from app.core.config import settings
from app.core.brokers.config import TokenConfig
from app.core.brokers.base import BaseBroker

logger = logging.getLogger(__name__)

class TokenRefreshManager:
    def __init__(self):
        self.is_running = False
        self._locks: Dict[str, asyncio.Lock] = {}
        self._refresh_attempts: Dict[str, int] = {}
        self.last_success: Dict[int, datetime] = {}
        self.error_counts: Dict[str, int] = {}
        
        # Use class-level settings from TokenConfig
        self.refresh_interval = TokenConfig.REFRESH_INTERVAL
        self.alert_threshold = TokenConfig.ALERT_THRESHOLD

    def get_broker_config(self, broker_id: str) -> dict:
        """Get token configuration for specific broker"""
        return TokenConfig.get_broker_config(broker_id)

    async def get_lock(self, credential_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific credential"""
        if credential_id not in self._locks:
            self._locks[credential_id] = asyncio.Lock()
        return self._locks[credential_id]

    def _increment_refresh_attempts(self, credential_id: str):
        """Increment refresh attempts counter"""
        self._refresh_attempts[credential_id] = self._refresh_attempts.get(credential_id, 0) + 1
        logger.info(f"Incremented refresh attempts for credential {credential_id} to {self._refresh_attempts[credential_id]}")

    def _reset_refresh_attempts(self, credential_id: str):
        """Reset refresh attempts counter"""
        if credential_id in self._refresh_attempts:
            del self._refresh_attempts[credential_id]
            logger.info(f"Reset refresh attempts for credential {credential_id}")

    async def refresh_token_if_needed(
        self, 
        credential: BrokerCredentials,
        db: Session
    ) -> bool:
        """Refresh token with proper transaction handling"""
        credential_id = str(credential.id)
        broker_config = self.get_broker_config(credential.broker_id)
        lock = await self.get_lock(credential_id)

        try:
            async with asyncio.timeout(30):  # 30 second timeout
                async with lock:
                    # Create new session for this operation
                    new_db = SessionLocal()
                    try:
                        # Get fresh credential instance
                        credential = new_db.query(BrokerCredentials).get(credential.id)
                        if not credential:
                            logger.error(f"Credential {credential_id} not found in database")
                            return False
                        
                        # Check if refresh is needed
                        time_until_expiry = (credential.expires_at - datetime.utcnow()).total_seconds()
                        refresh_threshold = broker_config['REFRESH_THRESHOLD']
                        token_lifetime = broker_config['TOKEN_LIFETIME']
                        
                        logger.info(
                            f"Credential {credential_id} expires in {time_until_expiry:.0f} seconds. "
                            f"Refresh threshold: {refresh_threshold * token_lifetime:.0f} seconds"
                        )

                        if time_until_expiry > (refresh_threshold * token_lifetime):
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
            credential.refresh_fail_count += 1
            credential.last_refresh_attempt = datetime.utcnow()
            credential.last_refresh_error = error
            
            db.commit()
            
            broker_config = self.get_broker_config(credential.broker_id)
            if credential.refresh_fail_count >= broker_config['MAX_RETRY_ATTEMPTS']:
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

    async def refresh_all_tokens(self):
        """Main token refresh loop"""
        while self.is_running:
            db = None
            try:
                db = SessionLocal()
            
            # Get active credentials needing refresh
                credentials = await token_manager.get_active_credentials(db)
                logger.info(f"Checking {len(credentials)} active credentials for refresh")
            
                for credential in credentials:
                    try:
                        # Use token_manager's refresh method instead of our own
                        await token_manager.refresh_token_if_needed(credential, db)
                    except Exception as e:
                        logger.error(f"Error processing credential {credential.id}: {str(e)}")

                logger.info("Completed token refresh cycle")
            
            except Exception as e:
                logger.error(f"Error in refresh cycle: {str(e)}")
            finally:
                if db:
                    db.close()
            
        # Wait for next refresh interval
            await asyncio.sleep(self.refresh_interval)

    async def start(self):
        """Start the token refresh manager"""
        if self.is_running:
            return
            
        self.is_running = True
        logger.info("Starting token refresh manager")
        await self.refresh_all_tokens()

    async def stop(self):
        """Stop the token refresh manager"""
        self.is_running = False
        logger.info("Stopping token refresh manager")

# Create singleton instance
token_refresh_manager = TokenRefreshManager()

# Function to start token refresh task
async def start_token_refresh_task():
   await token_refresh_manager.start()

# Function to stop token refresh task
async def stop_token_refresh_task():
   await token_refresh_manager.stop()