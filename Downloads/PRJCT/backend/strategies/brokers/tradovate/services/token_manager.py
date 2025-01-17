# strategies/brokers/tradovate/services/token_manager.py

from django.conf import settings
from django.db import transaction
import logging
from typing import Optional
from asgiref.sync import sync_to_async
from ..models import TradovateToken
import requests

logger = logging.getLogger(__name__)

class TradovateTokenManager:
    def __init__(self):
        self.refresh_threshold = 0.9  # Refresh at 90% of token lifetime
    
    def get_valid_token(self, user_id: int, environment: str) -> Optional[TradovateToken]:
        """Get a valid token, refreshing if necessary"""
        try:
            token = TradovateToken.objects.get(
                user_id=user_id,
                environment=environment,
                is_valid=True
            )
            
            if token.is_token_expired():
                if self.refresh_token(token):
                    return token
                return None
                
            return token
            
        except TradovateToken.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Error getting valid token: {str(e)}")
            return None

    def refresh_token(self, token: TradovateToken) -> bool:
        """Refresh a token"""
        try:
            with transaction.atomic():
                exchange_url = (
                    settings.TRADOVATE_LIVE_EXCHANGE_URL 
                    if token.environment == 'live' 
                    else settings.TRADOVATE_DEMO_EXCHANGE_URL
                )

                response = requests.post(
                    f"{exchange_url}/auth/refresh",
                    headers={
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    json={'refreshToken': token.refresh_token},
                    auth=(settings.TRADOVATE_CLIENT_ID, settings.TRADOVATE_CLIENT_SECRET),
                    timeout=10
                )
                
                if response.status_code != 200:
                    raise Exception(f"Token refresh failed: {response.text}")

                data = response.json()
                
                # Update token data
                token.access_token = data.get('accessToken', data.get('access_token'))
                if 'refreshToken' in data or 'refresh_token' in data:
                    token.refresh_token = data.get('refreshToken', data.get('refresh_token'))
                if 'mdAccessToken' in data or 'md_access_token' in data:
                    token.md_access_token = data.get('mdAccessToken', data.get('md_access_token'))
                    
                token.last_refreshed = timezone.now()
                token.is_valid = True
                token.save()
                
                logger.info(f"Successfully refreshed token for user {token.user_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to refresh token: {str(e)}")
            token.is_valid = False
            token.save()
            return False

    def check_and_refresh_tokens(self):
        """Check and refresh all expired tokens"""
        tokens = TradovateToken.objects.filter(is_valid=True)
        for token in tokens:
            if token.is_token_expired():
                self.refresh_token(token)