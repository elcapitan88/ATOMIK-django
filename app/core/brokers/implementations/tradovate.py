from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import requests
import logging
import json
from sqlalchemy.exc import IntegrityError
import aiohttp
import base64
import asyncio
import traceback
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..base import BaseBroker, AuthenticationError, ConnectionError, OrderError
from ..config import BrokerEnvironment
from ....models.broker import BrokerAccount, BrokerCredentials
from ....models.user import User
from ....models.webhook import Webhook
from ....models.strategy import ActivatedStrategy
from ....core.config import settings

logger = logging.getLogger(__name__)

class TradovateBroker(BaseBroker):
    """Tradovate broker implementation"""
    
    def __init__(self, broker_id: str, db: Session):
        super().__init__(broker_id, db)
        self.api_urls = {
            'demo': settings.TRADOVATE_DEMO_API_URL,
            'live': settings.TRADOVATE_LIVE_API_URL
        }
        self.ws_urls = {
            'demo': settings.TRADOVATE_DEMO_WS_URL,
            'live': settings.TRADOVATE_LIVE_WS_URL
        }

    async def _make_request(
        self, 
        method: str, 
        url: str, 
        data: Optional[dict | str] = None, 
        headers: Optional[dict] = None
    ) -> Any:
        """Make HTTP request to Tradovate API"""
        try:
            async with aiohttp.ClientSession() as session:
                request_kwargs = {
                    'method': method,
                    'url': url,
                    'headers': headers or {}
                }

                if data:
                    # Always send JSON data
                    request_kwargs['json'] = data if isinstance(data, dict) else json.loads(data)

                async with session.request(**request_kwargs) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Request failed - Status: {response.status}, URL: {url}, Error: {error_text}")
                        raise AuthenticationError(f"Request failed with status {response.status}: {error_text}")
                    
                    return await response.json()

        except aiohttp.ClientError as e:
            logger.error(f"HTTP request failed: {str(e)}")
            raise AuthenticationError(f"HTTP request failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in request: {str(e)}")
            raise AuthenticationError(f"Request error: {str(e)}")



    def _validate_token_response(self, tokens: dict) -> bool:
        """Validate token response has required fields"""
        required_fields = ['access_token', 'expires_in']  
    
        for field in required_fields:
            if not tokens.get(field):
                logger.error(f"Missing required field in token response: {field}")
                return False
            
        if not isinstance(tokens['expires_in'], (int, float)):
            logger.error("Invalid expires_in value")
            return False
        
        return True

    async def _exchange_code_for_tokens(self, code: str, environment: str) -> dict:
        """Exchange authorization code for tokens"""
        exchange_url = (
            settings.TRADOVATE_LIVE_EXCHANGE_URL 
            if environment == 'live'  # Just use the environment parameter directly
            else settings.TRADOVATE_DEMO_EXCHANGE_URL
        )

        try:
            response = requests.post(
                exchange_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.TRADOVATE_REDIRECT_URI,
                    "client_id": settings.TRADOVATE_CLIENT_ID,
                    "client_secret": settings.TRADOVATE_CLIENT_SECRET,
                },
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )

            if response.status_code != 200:
                logger.error(f"Token exchange failed with status {response.status_code}")
                logger.error(f"Response: {response.text}")
                raise AuthenticationError(
                    f"Token exchange failed: {response.text}"
                )

            tokens = response.json()
            
            if not self._validate_token_response(tokens):
                raise AuthenticationError("Invalid token response from Tradovate")

            return tokens

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error during token exchange: {str(e)}")
            raise AuthenticationError("Failed to connect to Tradovate authentication service")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse token response: {str(e)}")
            raise AuthenticationError("Invalid response from Tradovate authentication service")

    async def initialize_api_key(
        self,
        user: User,
        environment: str,
        credentials: Dict[str, Any]
) -> Dict[str, Any]:
        """Initialize API key connection - Not supported for Tradovate"""
        raise NotImplementedError("Tradovate does not support API key authentication")

    async def initialize_oauth(
        self,
        user: User,
        environment: str
    ) -> Dict[str, Any]:
        """Initialize OAuth flow for Tradovate"""
        try:
            # Generate state token
            state = self.generate_state_token(user.id, environment)

            # Build OAuth URL
            base_url = settings.TRADOVATE_AUTH_URL
            if environment == 'demo':
                base_url = base_url.replace('live', 'demo')

            params = {
                "client_id": settings.TRADOVATE_CLIENT_ID,
                "redirect_uri": settings.TRADOVATE_REDIRECT_URI,
                "response_type": "code",
                "scope": "trading",
                "state": state
            }

            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            auth_url = f"{base_url}?{query_string}"

            return {
                "auth_url": auth_url,
                "broker_id": self.broker_id,
                "environment": environment
            }

        except Exception as e:
            logger.error(f"OAuth initialization failed: {str(e)}")
            raise

    async def authenticate(self, credentials: Dict[str, Any]) -> BrokerCredentials:
        """
        Authenticate with Tradovate
    
        Args:
            credentials (Dict[str, Any]): Dictionary containing environment and code
        
        Returns:
            BrokerCredentials: New credentials object with access token
        
        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            environment = credentials.get('environment', 'demo')
            exchange_url = f"{self.api_urls[environment]}/auth/token"

        # Prepare request data
            request_data = {
                "grant_type": "refresh_token",
                "access_token": credentials.access_token,
                "client_id": settings.TRADOVATE_CLIENT_ID,
                "client_secret": settings.TRADOVATE_CLIENT_SECRET
            }

            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',  # Changed content type
                'Accept': 'application/json'
            }

        # Make request using our _make_request helper
            response = await self._make_request(
                'POST',
                exchange_url,
                data=json.dumps(request_data),
                headers=headers
            )

        # Validate response
            if not response or 'accessToken' not in response:
                raise AuthenticationError("Invalid response from Tradovate authentication")

        # Get current time for consistent timestamps
            current_time = datetime.utcnow()
            expiry_time = current_time + timedelta(seconds=response.get('expiresIn', 4800))

        # Create new credentials with properly initialized fields
            new_credentials = BrokerCredentials(
                broker_id=self.broker_id,
                credential_type='oauth',
                access_token=response['accessToken'],
                expires_at=expiry_time,
                is_valid=True,
                created_at=current_time,
                updated_at=current_time,
                last_refresh_attempt=current_time,  # Initialize the last refresh attempt
                refresh_fail_count=0,
                last_refresh_error=None,
                error_message=None
            )

            logger.info(
                f"Created new credentials for {self.broker_id}:\n"
                f"Access Token: {response['accessToken'][:20]}...\n"
                f"Expires In: {response.get('expiresIn')}\n"
                f"Created At: {current_time}\n"
                f"Expires At: {expiry_time}"
            )

            return new_credentials

        except AuthenticationError as auth_e:
            logger.error(f"Authentication error: {str(auth_e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {str(e)}\n"
                    f"Traceback: {traceback.format_exc()}")
            raise AuthenticationError(f"Authentication failed: {str(e)}")
           

    async def process_oauth_callback(self, code: str, user_id: int, environment: str) -> Dict[str, Any]:
        """Process OAuth callback from Tradovate"""
        try:
            tokens = await self._exchange_code_for_tokens(code, environment)
            logger.info("Processing OAuth callback tokens")

            # Create credentials
            credentials = BrokerCredentials(
                broker_id=self.broker_id,
                credential_type='oauth',
                access_token=tokens.get('access_token'),
                expires_at=datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 4800)),
                is_valid=True,
                last_refresh_attempt=datetime.utcnow(),
                refresh_fail_count=0,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            self.db.add(credentials)

            # Fetch accounts using new credentials
            api_url = settings.TRADOVATE_LIVE_API_URL if environment == 'live' else settings.TRADOVATE_DEMO_API_URL
            headers = {
                "Authorization": f"Bearer {credentials.access_token}",
                "Content-Type": "application/json"
            }

            accounts_response = requests.get(f"{api_url}/account/list", headers=headers)
            if accounts_response.status_code != 200:
                raise ConnectionError(f"Failed to fetch accounts: {accounts_response.text}")

            accounts_data = accounts_response.json()
            stored_accounts = []

            for account_info in accounts_data:
                # Check for existing account
                existing_account = self.db.query(BrokerAccount).filter(
                    BrokerAccount.user_id == user_id,
                    BrokerAccount.account_id == str(account_info.get('id')),
                    BrokerAccount.broker_id == self.broker_id,
                    BrokerAccount.environment == environment
                ).first()

                if existing_account:
                    logger.info(f"Updating existing account: {existing_account.account_id}")
                    # Update existing account
                    existing_account.name = account_info.get('name')
                    existing_account.is_active = True
                    existing_account.status = 'active'
                    existing_account.error_message = None
                    existing_account.last_connected = datetime.utcnow()
                    existing_account.updated_at = datetime.utcnow()
                    existing_account.deleted_at = None
                    existing_account.is_deleted = False
                    
                    # Update credentials
                    if existing_account.credentials:
                        self.db.delete(existing_account.credentials)
                    existing_account.credentials = credentials
                    
                    stored_accounts.append(existing_account)
                else:
                    logger.info(f"Creating new account for user {user_id}")
                    # Create new account
                    new_account = BrokerAccount(
                        user_id=user_id,
                        broker_id=self.broker_id,
                        account_id=str(account_info.get('id')),
                        name=account_info.get('name'),
                        environment=environment,
                        status='active',
                        is_active=True,
                        last_connected=datetime.utcnow()
                    )
                    self.db.add(new_account)
                    new_account.credentials = credentials
                    stored_accounts.append(new_account)

            try:
                self.db.commit()
                logger.info(f"Successfully stored/updated {len(stored_accounts)} accounts")
            except IntegrityError as e:
                self.db.rollback()
                logger.error(f"Database integrity error: {str(e)}")
                raise HTTPException(
                    status_code=400,
                    detail="Account already exists for this user"
                )
            except Exception as e:
                self.db.rollback()
                logger.error(f"Database error: {str(e)}")
                raise

            return {
                "status": "success",
                "accounts": [
                    {
                        "account_id": acc.account_id,
                        "name": acc.name,
                        "environment": acc.environment
                    } for acc in stored_accounts
                ]
            }

        except Exception as e:
            logger.error(f"OAuth callback processing failed: {str(e)}")
            raise


    async def validate_credentials(self, credentials: BrokerCredentials) -> bool:
        """Validate stored credentials"""
        try:
            if not credentials.is_valid:
                return False

            if credentials.expires_at <= datetime.utcnow():
                return False

            # Test credentials with a simple API call
            headers = {
                "Authorization": f"Bearer {credentials.access_token}"
            }
            response = requests.get(
                f"{self.api_urls[credentials.account.environment]}/user/userinfo",
                headers=headers
            )

            return response.status_code == 200

        except Exception as e:
            logger.error(f"Credential validation failed: {str(e)}")
            return False


    async def connect_account(
        self,
        user: User,
        account_id: str,
        environment: BrokerEnvironment,
        credentials: Optional[Dict[str, Any]] = None
    ) -> BrokerAccount:
        """Connect to a Tradovate account"""
        try:
            # Check if account already exists
            existing_account = await self.check_account_exists(
                user.id, account_id, environment.value
            )

            if existing_account:
                if existing_account.is_active:
                    raise ConnectionError("Account already connected")
                account = existing_account
                account.is_active = True
            else:
                account = BrokerAccount(
                    user_id=user.id,
                    broker_id=self.broker_id,
                    account_id=account_id,
                    environment=environment.value,
                    name=f"Tradovate {environment.value.capitalize()} Account",
                    status='connecting'
                )
                self.db.add(account)

            if credentials:
                # Get account information
                auth_response = await self.authenticate(credentials)
                account_info = await self._get_account_info(account_id, auth_response)

                # Update account with retrieved information
                account.name = account_info.get('name', account.name)

            account.status = 'active'
            account.last_connected = datetime.utcnow()
            account.error_message = None

            self.db.commit()
            return account

        except Exception as e:
            if 'account' in locals():
                account.status = 'error'
                account.error_message = str(e)
                account.is_active = False
                self.db.commit()
            raise ConnectionError(f"Account connection failed: {str(e)}")
        

    async def refresh_credentials(self, credentials: BrokerCredentials) -> BrokerCredentials:
        """
        Refresh access token for Tradovate using the renewAccessToken endpoint
    
        Args:
            credentials (BrokerCredentials): The current credentials to refresh
    
        Returns:
            BrokerCredentials: Updated credentials with new access token
    
        Raises:
            AuthenticationError: If token refresh fails
        """
        try:
            if not credentials or not credentials.access_token:
                raise AuthenticationError("Invalid credentials provided for refresh")

        # Construct the URL using the environment-specific base URL
            
            exchange_url = (
                settings.TRADOVATE_LIVE_RENEW_TOKEN_URL 
                if credentials.account.environment == 'live' 
                else settings.TRADOVATE_DEMO_RENEW_TOKEN_URL
            )

            logger.info(
                f"Initiating token refresh for credential {credentials.id} "
                f"Environment: {credentials.account.environment} "
                f"URL: {exchange_url}"
                f"Attempting to refresh with token: {credentials.access_token[:30]}..."
            )

        # Prepare the request data according to Tradovate's specifications
            request_data = {
                "accessToken": credentials.access_token
            }

            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': f'Bearer {credentials.access_token}'
            }

        # Make the request with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await self._make_request(
                        'POST',
                        exchange_url,
                        headers=headers
                    )

                # Log successful response for debugging
                    logger.info(f"Token refresh response: {response}")

                    if not response:
                        raise AuthenticationError("Empty response received from Tradovate")
                
                    if 'accessToken' not in response:
                        raise AuthenticationError(
                            f"Invalid response format. Expected 'accessToken', got: {list(response.keys())}"
                        )
                
                    if 'accessToken' not in response:
                        raise AuthenticationError("Response missing 'accessToken' field")
                    if 'expirationTime' not in response:
                        raise AuthenticationError("Response missing 'expirationTime' field")

                # Update credential using Tradovate's returned values
                    credentials.access_token = response['accessToken']
                    credentials.expires_at = datetime.fromisoformat(response['expirationTime'].replace('Z', '+00:00'))
                    credentials.is_valid = True
                    credentials.refresh_fail_count = 0
                    credentials.last_refresh_attempt = datetime.utcnow()  # Update last refresh timestamp
                    credentials.last_refresh_error = None

                    self.db.commit()
            
                    logger.info(
                        f"Successfully refreshed token for credential {credentials.id}. "
                        f"New token expires at {credentials.expires_at}"
                    )

                    return credentials

                except Exception as e:
                    if attempt == max_retries - 1:  # Last attempt
                        raise
                    logger.warning(
                        f"Refresh attempt {attempt + 1} failed for credential {credentials.id}: {str(e)}. "
                        "Retrying..."
                    )
                    await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff

        except AuthenticationError as auth_e:
            logger.error(
                f"Authentication error refreshing token for credential {credentials.id}: {str(auth_e)}"
            )
            credentials.refresh_fail_count = (credentials.refresh_fail_count or 0) + 1
            credentials.last_refresh_error = str(auth_e)
            credentials.last_refresh_attempt = datetime.utcnow()
            raise

        except Exception as e:
            logger.error(
                f"Unexpected error refreshing token for credential {credentials.id}: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            credentials.refresh_fail_count = (credentials.refresh_fail_count or 0) + 1
            credentials.last_refresh_error = str(e)
            credentials.last_refresh_attempt = datetime.utcnow()
            raise AuthenticationError(f"Token refresh failed: {str(e)}")
        
        except Exception as e:
            self.db.rollback()  # Add rollback on error
            logger.error(f"Failed to refresh token: {str(e)}")
            raise

    async def fetch_accounts(self, user: User) -> List[Dict[str, Any]]:
        """Fetch Tradovate accounts for a user"""
        try:
            accounts = self.db.query(BrokerAccount).filter(
                BrokerAccount.user_id == user.id,
                BrokerAccount.broker_id == self.broker_id,
                BrokerAccount.is_active == True,
                BrokerAccount.deleted_at.is_(None)
            ).all()

            formatted_accounts = []
            for account in accounts:
                # Get account balance if credentials are valid
                balance = 0.0
                if account.credentials and account.credentials.is_valid:
                    try:
                        status = await self.get_account_status(account)
                        balance = status.get("balance", 0.0)
                    except Exception as e:
                        logger.warning(f"Failed to fetch balance for account {account.id}: {str(e)}")

                formatted_accounts.append({
                    "account_id": account.account_id,
                    "name": account.name,
                    "environment": account.environment,
                    "status": account.status,
                    "balance": balance,
                    "active": account.is_active,
                    "is_token_expired": not account.credentials.is_valid if account.credentials else True,
                    "last_connected": account.last_connected,
                    "broker": "tradovate"
                })

            return formatted_accounts

        except Exception as e:
            logger.error(f"Error fetching Tradovate accounts: {str(e)}")
            raise

    async def get_account_status(self, account: BrokerAccount) -> Dict[str, Any]:
        """Get account status and information"""
        try:
            api_url = self.api_urls[account.environment]
            headers = self._get_auth_headers(account.credentials)
            
            response = requests.get(
                f"{api_url}/account/status",
                headers=headers
            )
            
            if response.status_code != 200:
                raise ConnectionError(f"Failed to get account status: {response.text}")
                
            return response.json()
        except Exception as e:
            logger.error(f"Error getting account status: {str(e)}")
            raise

    async def get_positions(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """Get current positions for an account"""
        try:
            api_url = self.api_urls[account.environment]
            headers = self._get_auth_headers(account.credentials)
            
            response = requests.get(
                f"{api_url}/position/list",
                headers=headers
            )
            
            if response.status_code != 200:
                raise ConnectionError(f"Failed to get positions: {response.text}")
                
            return response.json()
        except Exception as e:
            logger.error(f"Error getting positions: {str(e)}")
            raise

    async def get_orders(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """Get orders for an account"""
        try:
            api_url = self.api_urls[account.environment]
            headers = self._get_auth_headers(account.credentials)
            
            response = requests.get(
                f"{api_url}/order/list",
                headers=headers
            )
            
            if response.status_code != 200:
                raise ConnectionError(f"Failed to get orders: {response.text}")
                
            return response.json()
        except Exception as e:
            logger.error(f"Error getting orders: {str(e)}")
            raise

    async def place_order(self, account: BrokerAccount, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Place a trading order"""
        try:
            api_url = self.api_urls[account.environment]
            headers = self._get_auth_headers(account.credentials)
            
            response = requests.post(
                f"{api_url}/order/placeOrder",
                headers=headers,
                json=order_data
            )
            
            if response.status_code != 200:
                raise OrderError(f"Failed to place order: {response.text}")
                
            return response.json()
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            raise

    async def cancel_order(self, account: BrokerAccount, order_id: str) -> bool:
        """Cancel an order"""
        try:
            api_url = self.api_urls[account.environment]
            headers = self._get_auth_headers(account.credentials)
            
            response = requests.post(
                f"{api_url}/order/cancelOrder",
                headers=headers,
                json={"orderId": order_id}
            )
            
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error cancelling order: {str(e)}")
            raise

    async def disconnect_account(self, account: BrokerAccount) -> bool:
        """Disconnect a trading account"""
        try:
            # Mark account as inactive
            account.is_active = False
            account.status = "disconnected"
            account.error_message = None
            self.db.commit()
            
            return True
        except Exception as e:
            logger.error(f"Error disconnecting account: {str(e)}")
            raise

    def _get_auth_headers(self, credentials: BrokerCredentials) -> Dict[str, str]:
        """Get authentication headers for API requests"""
        return {
            "Authorization": f"Bearer {credentials.access_token}",
            "Content-Type": "application/json"
        }