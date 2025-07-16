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


class TradovateOrderType:
    Market = "Market"
    Limit = "Limit"
    Stop = "Stop"
    StopLimit = "StopLimit"

class TradovateOrderAction:
    Buy = "Buy"
    Sell = "Sell"

class TradovateTimeInForce:
    Day = "Day"
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK" 

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
        data: Optional[Dict[str, Any] | str] = None, 
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Make HTTP request to Tradovate API"""
        try:
            async with aiohttp.ClientSession() as session:
                request_kwargs = {
                    'method': method,
                    'url': url,
                    'headers': headers or {},
                }

                if params:
                    request_kwargs['params'] = params

                if data:
                    request_kwargs['json'] = data if isinstance(data, dict) else json.loads(data)

                logger.debug(f"Making request to {url}")

                async with session.request(**request_kwargs) as response:
                    response_text = await response.text()
                    
                    if response.status != 200:
                        raise ConnectionError(f"Request failed with status {response.status}: {response_text}")
                    
                    return json.loads(response_text) if response_text else None

        except Exception as e:
            logger.error(f"Request error: {str(e)}")
            raise

    def _validate_token_response(self, tokens: dict) -> bool:
        """Validate token response has required fields"""
        # Log the entire response structure to debug
        logger.debug(f"Token response keys: {list(tokens.keys())}")
        
        # Check both camelCase (Tradovate style) and snake_case (standard OAuth) field names
        access_token_field = None
        expires_field = None
        
        if 'accessToken' in tokens:
            access_token_field = 'accessToken'
            expires_field = 'expiresIn'
        elif 'access_token' in tokens:
            access_token_field = 'access_token'
            expires_field = 'expires_in'
        else:
            logger.error(f"Could not find access token in response. Available fields: {list(tokens.keys())}")
            return False
        
        # Validate token exists
        if not tokens.get(access_token_field):
            logger.error(f"Missing or empty {access_token_field} in token response")
            return False
            
        # Validate expiration exists and is numeric
        if expires_field not in tokens or not isinstance(tokens.get(expires_field), (int, float)):
            # If expiration is missing but we have a token, still proceed
            logger.warning(f"Missing or invalid {expires_field}, using default expiration")
        
        return True

    async def _exchange_code_for_tokens(self, code: str, environment: str) -> dict:
        """Exchange authorization code for tokens"""
        exchange_url = (
            settings.TRADOVATE_LIVE_EXCHANGE_URL 
            if environment == 'live'
            else settings.TRADOVATE_DEMO_EXCHANGE_URL
        )

        try:
            logger.info(f"Exchanging auth code for tokens at URL: {exchange_url}")
            logger.info(f"Using redirect URI: {settings.TRADOVATE_REDIRECT_URI}")
            
            # Keep track of the code (without revealing the full value)
            code_sample = f"{code[:5]}...{code[-5:]}" if len(code) > 10 else "***"
            logger.info(f"Using auth code: {code_sample}")
            
            # Method 1: Standard form-encoded POST with client ID and secret in body
            form_data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.TRADOVATE_REDIRECT_URI,
                "client_id": settings.TRADOVATE_CLIENT_ID,
                "client_secret": settings.TRADOVATE_CLIENT_SECRET,
            }
            
            logger.info(f"Using form parameters: {[k for k in form_data.keys()]}")
            
            response = requests.post(
                exchange_url,
                data=form_data,  # This sends as application/x-www-form-urlencoded
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )

            # Try alternate auth method if first fails
            if response.status_code != 200 or ('error' in response.json()):
                logger.warning("First auth method failed, trying alternative with Basic Auth")
                
                # Method 2: Try with client ID and secret in Authorization header
                response = requests.post(
                    exchange_url,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": settings.TRADOVATE_REDIRECT_URI
                    },
                    auth=(settings.TRADOVATE_CLIENT_ID, settings.TRADOVATE_CLIENT_SECRET),
                    headers={
                        'Content-Type': 'application/x-www-form-urlencoded'
                    }
                )

            # Log the full request and response for debugging
            auth_request_info = {
                "url": exchange_url,
                "method": "POST",
                "headers": {k: "REDACTED" if k.lower() in ["authorization", "cookie"] else v 
                            for k, v in response.request.headers.items()},
                "params": form_data.keys(),
            }
            logger.info(f"Auth request details: {auth_request_info}")

            # Log detailed response information
            logger.info(f"Token exchange response status: {response.status_code}")
            logger.info(f"Response headers: {response.headers}")
            
            # Always log the response body for OAuth errors
            try:
                response_body = response.json()
                logger.info(f"Response body (keys): {list(response_body.keys())}")
                if 'error' in response_body:
                    logger.error(f"OAuth Error: {response_body.get('error')} - {response_body.get('error_description')}")
            except:
                logger.error(f"Could not parse response as JSON. Raw response: {response.text[:500]}")
            
            if response.status_code != 200:
                logger.error(f"Token exchange failed with status {response.status_code}")
                raise AuthenticationError(
                    f"Token exchange failed: {response.text}"
                )

            try:
                tokens = response.json()
                # Handle OAuth error responses
                if 'error' in tokens:
                    error_msg = tokens.get('error', 'unknown_error')
                    error_desc = tokens.get('error_description', 'No description provided')
                    logger.error(f"OAuth Error: {error_msg} - {error_desc}")
                    
                    # Specific guidance based on error
                    if 'invalid_grant' in error_msg:
                        error_desc += " (The authorization code may have expired or already been used)"
                    elif 'redirect_uri_mismatch' in error_msg or error_desc:
                        error_desc += f" (Check that {settings.TRADOVATE_REDIRECT_URI} matches exactly what's registered with Tradovate)"
                    
                    raise AuthenticationError(f"OAuth error: {error_msg} - {error_desc}")
                
                # Log token response structure
                logger.info(f"Token response contains fields: {list(tokens.keys())}")
                
                # For debugging, log field values lengths without revealing content
                token_info = {}
                for key in tokens.keys():
                    if isinstance(tokens[key], str):
                        token_info[key] = f"[{len(tokens[key])} chars]"
                    else:
                        token_info[key] = str(tokens[key])
                logger.info(f"Token values info: {token_info}")
                
                if not self._validate_token_response(tokens):
                    raise AuthenticationError("Invalid token response from Tradovate")

                return tokens
                
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to parse token response as JSON: {response.text}")
                raise AuthenticationError(f"Invalid JSON response: {str(json_err)}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error during token exchange: {str(e)}")
            raise AuthenticationError("Failed to connect to Tradovate authentication service")

    async def _get_account_info(self, account_id: str, credentials: BrokerCredentials, environment: str = None) -> Dict[str, Any]:
        """Get account information using credentials"""
        try:
            # Determine environment - either from credentials or passed parameter
            env = environment
            if hasattr(credentials, 'account') and credentials.account and credentials.account.environment:
                env = credentials.account.environment
            
            if not env:
                env = 'demo'  # Default to demo if environment not specified
                
            api_url = self.api_urls[env]
            headers = self._get_auth_headers(credentials)
            
            logger.info(f"Fetching account info for account ID: {account_id}, environment: {env}")
            
            # Try to get account by ID first
            response = await self._make_request(
                'GET',
                f"{api_url}/account/find",
                params={"id": int(account_id)},
                headers=headers
            )
            
            if not response:
                logger.warning(f"Could not find account by ID {account_id}, trying alternative methods")
                # Try to find by name if ID search fails
                accounts_response = await self._make_request(
                    'GET',
                    f"{api_url}/account/list",
                    headers=headers
                )
                
                if accounts_response:
                    # Find account in the list
                    for acc in accounts_response:
                        if str(acc.get('id')) == account_id:
                            return acc
                            
                raise ConnectionError(f"Could not find account information for account ID: {account_id}")
                
            return response
        except Exception as e:
            logger.error(f"Error fetching account info: {str(e)}")
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
            

            access_token = tokens.get('accessToken') or tokens.get('access_token')
            # Get expiration using either naming convention, default to 80 minutes if missing
            expires_in = tokens.get('expiresIn') or tokens.get('expires_in', 4800)

            if not access_token:
                raise AuthenticationError("Could not find access token in response")

            # Create credentials
            credentials = BrokerCredentials(
                broker_id=self.broker_id,
                credential_type='oauth',
                access_token=access_token,
                expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
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

                # Create new credentials for EACH account
                credentials = BrokerCredentials(
                    broker_id=self.broker_id,
                    credential_type='oauth',
                    access_token=access_token,
                    expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
                    is_valid=True,
                    last_refresh_attempt=datetime.utcnow(),
                    refresh_fail_count=0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                self.db.add(credentials)

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
        """
        Validate if stored credentials are valid
        
        This method only checks if the token is marked as valid in the database
        and has not expired. It does NOT attempt to refresh the token as that
        is now handled by the token-refresh-service.
        
        Args:
            credentials: The credentials to validate
            
        Returns:
            bool: True if credentials are valid, False otherwise
        """
        try:
            if not credentials or not credentials.is_valid:
                return False

            # Check if token is expired
            if credentials.expires_at and credentials.expires_at <= datetime.utcnow():
                logger.info(f"Token expired for credential {credentials.id}")
                return False
                
            # If has access token and isn't expired, it's valid
            return True
            
        except Exception as e:
            logger.error(f"Error validating token: {str(e)}")
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

            # If credentials are provided, try to get account information
            if credentials:
                try:
                    # Get account information
                    auth_response = await self.authenticate(credentials)
                    account_info = await self._get_account_info(account_id, auth_response, environment.value)

                    # Update account with retrieved information if available
                    if account_info and account_info.get('name'):
                        account.name = account_info.get('name')
                except Exception as e:
                    logger.warning(f"Could not retrieve account info: {str(e)}")
                    # Continue with default name if account info retrieval fails

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
            # First, verify credentials are valid (without attempting refresh)
            if not account.credentials:
                logger.warning(f"No credentials found for account {account.account_id}")
                return {
                    "status": "disconnected",
                    "account_id": account.account_id,
                    "name": account.name,
                    "balance": 0.0,
                    "available_margin": 0.0,
                    "day_pnl": 0.0,
                    "timestamp": datetime.utcnow().isoformat(),
                    "error": "No credentials found. Please reconnect your account."
                }
                
            if not account.credentials.is_valid:
                logger.warning(f"Invalid credentials for account {account.account_id}")
                return {
                    "status": "token_expired",
                    "account_id": account.account_id,
                    "name": account.name,
                    "balance": 0.0,
                    "available_margin": 0.0,
                    "day_pnl": 0.0,
                    "timestamp": datetime.utcnow().isoformat(),
                    "error": "Your authentication token has expired. The system will automatically refresh it soon. If this persists, please reconnect your account."
                }
                
            # Check if token is expired
            if account.credentials.expires_at and account.credentials.expires_at <= datetime.utcnow():
                logger.warning(f"Expired token for account {account.account_id}")
                return {
                    "status": "token_expired",
                    "account_id": account.account_id,
                    "name": account.name,
                    "balance": 0.0,
                    
                    "available_margin": 0.0,
                    "day_pnl": 0.0,
                    "timestamp": datetime.utcnow().isoformat(),
                    "error": "Your authentication token has expired. The system will automatically refresh it soon. If this persists, please reconnect your account."
                }

            # If credentials are valid, proceed with API requests
            api_url = self.api_urls[account.environment]
            headers = self._get_auth_headers(account.credentials)
            
            logger.info(f"""
            Checking account status:
            Account Name (accountSpec): {account.name}
            Account ID: {account.account_id}
            Environment: {account.environment}
            API URL: {api_url}
            """)

            # Get account details using the name (accountSpec)
            account_response = await self._make_request(
                'GET',
                f"{api_url}/account/find",
                params={"name": account.name},  # Query by name which is accountSpec
                headers=headers
            )
            
            if not account_response:
                raise ConnectionError("Empty account response from Tradovate API")

            # Get cash balance using accountId
            cash_response = await self._make_request(
                'GET',
                f"{api_url}/cashBalance/find",
                params={"accountId": int(account.account_id)},
                headers=headers
            )

            # Get P&L info using accountId
            pnl_response = await self._make_request(
                'GET',
                f"{api_url}/account/getDayPnL",
                params={"accountId": int(account.account_id)},
                headers=headers
            )

            # Combine all information
            return {
                "status": "active",
                "account_id": str(account_response.get('id')),
                "name": account_response.get('name', ''),
                "balance": float(cash_response.get('cashBalance', 0)) if cash_response else 0.0,
                "available_margin": float(cash_response.get('availableForTrading', 0)) if cash_response else 0.0,
                "day_pnl": float(pnl_response.get('pnl', 0)) if pnl_response else 0.0,
                "timestamp": datetime.utcnow().isoformat()
            }

        except ConnectionError as ce:
            logger.error(f"""
            Connection error getting account status:
            Account ID: {account.account_id}
            Account Name: {account.name}
            Error: {str(ce)}
            """)
            
            # Check if this might be a token issue
            if "401" in str(ce) or "unauthorized" in str(ce).lower() or "authentication" in str(ce).lower():
                # Mark credentials as invalid to trigger refresh by service
                if account.credentials:
                    account.credentials.is_valid = False
                    self.db.commit()
                    logger.info(f"Marked credentials as invalid for account {account.account_id} to trigger refresh")
                
                return {
                    "status": "connection_error",
                    "account_id": account.account_id,
                    "name": account.name,
                    "error": "Authentication error. Your token will be automatically refreshed. If this persists, please reconnect your account.",
                    "timestamp": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "status": "connection_error",
                    "account_id": account.account_id,
                    "name": account.name,
                    "error": f"Failed to connect to Tradovate: {str(ce)}",
                    "timestamp": datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"""
            Failed to get account status:
            Account ID: {account.account_id}
            Account Name: {account.name}
            Error: {str(e)}
            """)
            
            return {
                "status": "error",
                "account_id": account.account_id,
                "name": account.name,
                "error": f"Error retrieving account status: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }

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
        try:
            api_url = self.api_urls[account.environment]
            headers = self._get_auth_headers(account.credentials)

            # Log incoming order data
            logger.info(f"Incoming order data to place_order: {json.dumps(order_data, indent=2)}")

            tradovate_order = {
                "accountSpec": account.name,
                "accountId": int(account.account_id),
                "symbol": order_data["symbol"],
                "orderQty": order_data["quantity"],
                "orderType": "Market",  # Hardcode for now to debug
                "action": order_data["side"].capitalize(),
                "timeInForce": "GTC",
                "isAutomated": False
            }

            # Log the exact payload being sent to Tradovate
            logger.info(f"Sending to Tradovate API: {json.dumps(tradovate_order, indent=2)}")

            # Store raw response before any transformation
            raw_response = await self._make_request(
                'POST',
                f"{api_url}/order/placeOrder",
                data=tradovate_order,
                headers=headers
            )

            # Log raw response immediately
            logger.info(f"Raw Tradovate API Response: {json.dumps(raw_response, indent=2)}")

            # Then transform for our normalized response
            normalized_response = {
                "order_id": str(raw_response.get('orderId')),
                "status": raw_response.get('orderStatus', 'pending'),
                "filled_quantity": raw_response.get('filledQty', 0),
                "remaining_quantity": raw_response.get('remainingQty', order_data["quantity"]),
                "average_price": raw_response.get('avgFillPrice'),
                "timestamp": datetime.utcnow().isoformat(),
                "raw_response": raw_response  # Include full raw response
            }

            logger.info(f"Normalized response: {json.dumps(normalized_response, indent=2)}")

            if raw_response.get('orderId'):
                order_id = str(raw_response.get('orderId'))
                from app.services.trading_service import order_monitoring_service
                await order_monitoring_service.add_order(
                    order_id=order_id,
                    account=account,
                    user_id=account.user_id,
                    order_data=order_data  # Pass the original order data
                )

            return normalized_response

        except Exception as e:
            logger.error(f"""
            Order placement failed:
            Error: {str(e)}
            Account: {account.name} ({account.account_id})
            Order Data: {json.dumps(order_data, indent=2)}
            Traceback: {traceback.format_exc()}
            """)
            raise OrderError(f"Failed to place order: {str(e)}")

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

    async def get_order_status(self, account: BrokerAccount, order_id: str) -> Dict[str, Any]:
        """Get the current status of an order"""
        try:
            # Validate credentials
            if not account.credentials or not account.credentials.is_valid:
                raise AuthenticationError("Invalid or expired credentials")
            
            api_url = self.api_urls[account.environment]
            headers = self._get_auth_headers(account.credentials)
            
            # Make request to get order details
            response = await self._make_request(
                'GET',
                f"{api_url}/order/get",
                params={"orderId": int(order_id)},
                headers=headers
            )
            
            if not response:
                raise ConnectionError(f"Empty response when fetching order {order_id}")
            
            # Check for error response
            if "failureReason" in response or "failureText" in response:
                logger.warning(f"Error response for order {order_id}: {response}")
                return {
                    "order_id": str(order_id),
                    "status": "error",
                    "error_message": response.get("failureText", "Unknown error"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "raw_response": response
                }
            
            # Map Tradovate order status to our standardized format
            status_mapping = {
                "Pending": "pending",
                "Working": "working", 
                "Completed": "filled",
                "Canceled": "cancelled",
                "Rejected": "rejected",
                "Expired": "expired"
            }
            
            # Normalize the response with complete information
            normalized_response = {
                "order_id": str(order_id),
                "status": status_mapping.get(response.get("orderStatus", ""), "unknown"),
                "filled_quantity": response.get("filledQuantity", 0),
                "remaining_quantity": response.get("remainingQuantity", 0),
                "average_price": response.get("avgFillPrice"),
                "timestamp": datetime.utcnow().isoformat(),
                "raw_response": response
            }
            
            return normalized_response
            
        except Exception as e:
            logger.error(f"Error getting order status for {order_id}: {str(e)}")
            # Return an error response rather than raising, to help monitoring service continue
            return {
                "order_id": str(order_id),
                "status": "error",
                "error_message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

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
    
    async def close_all_positions_for_accounts(self, accounts: List[BrokerAccount]) -> Dict[str, List[Dict[str, Any]]]:
        """Close all open positions across multiple accounts"""
        try:
            results = {}
            
            for account in accounts:
                try:
                    # Get positions for this account
                    positions = await self.get_positions(account)
                    
                    if not positions:
                        logger.info(f"No open positions found for account {account.account_id}")
                        results[account.account_id] = []
                        continue

                    account_results = []
                    for position in positions:
                        try:
                            # Determine closing order details
                            closing_side = "SELL" if position.get("quantity", 0) > 0 else "BUY"
                            quantity = abs(position.get("quantity", 0))
                            
                            # Prepare order data
                            order_data = {
                                "account_id": account.account_id,
                                "symbol": position.get("symbol"),
                                "quantity": quantity,
                                "side": closing_side,
                                "type": "MARKET",
                                "time_in_force": "GTC"
                            }

                            # Place closing order
                            result = await self.place_order(account, order_data)
                            account_results.append({
                                "position": position,
                                "close_order": result,
                                "status": "success"
                            })

                        except Exception as e:
                            logger.error(f"Error closing position {position}: {str(e)}")
                            account_results.append({
                                "position": position,
                                "error": str(e),
                                "status": "failed"
                            })

                    results[account.account_id] = account_results

                except Exception as e:
                    logger.error(f"Error processing account {account.account_id}: {str(e)}")
                    results[account.account_id] = [{
                        "error": str(e),
                        "status": "failed"
                    }]

            return results

        except Exception as e:
            logger.error(f"Error in close_all_positions_for_accounts: {str(e)}")
            raise OrderError(f"Failed to close positions across accounts: {str(e)}")

    # Abstract method implementations required by BaseBroker
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

    async def initialize_api_key(
        self,
        user: User,
        environment: str,
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize API key connection - Not supported for Tradovate"""
        raise NotImplementedError("Tradovate does not support API key authentication")

    async def refresh_credentials(self, credentials: BrokerCredentials) -> BrokerCredentials:
        """
        Refresh Tradovate credentials by delegating to the token-refresh-service.
        
        This method serves as a compatibility layer for the abstract BaseBroker interface.
        Actual token refresh operations are handled by the dedicated token-refresh-service
        which runs as a separate microservice and automatically refreshes tokens before expiration.
        
        Args:
            credentials: The broker credentials to refresh
            
        Returns:
            BrokerCredentials: The refreshed credentials
            
        Raises:
            AuthenticationError: If credentials are invalid or refresh fails
        """
        try:
            logger.info(f"Refresh credentials requested for Tradovate account {credentials.id}")
            
            # Validate current credentials first
            if not await self.validate_credentials(credentials):
                # Check if token is expired
                if credentials.expires_at and credentials.expires_at <= datetime.utcnow():
                    logger.warning(f"Token expired for Tradovate account {credentials.id}")
                    
                    # Update credential status to indicate refresh is needed
                    credentials.is_valid = False
                    credentials.last_refresh_error = "Token expired - refresh handled by token-refresh-service"
                    self.db.commit()
                    
                    raise AuthenticationError(
                        "Token has expired. The token-refresh-service will automatically refresh it. "
                        "Please retry your request in a few moments."
                    )
                else:
                    logger.error(f"Invalid credentials for Tradovate account {credentials.id}")
                    raise AuthenticationError("Invalid credentials cannot be refreshed")
            
            # Token is valid, return as-is
            # The token-refresh-service handles proactive refresh based on expiration thresholds
            logger.info(f"Credentials are valid for Tradovate account {credentials.id}")
            return credentials
            
        except AuthenticationError:
            # Re-raise authentication errors as-is
            raise
        except Exception as e:
            logger.error(f"Unexpected error in refresh_credentials for Tradovate account {credentials.id}: {str(e)}")
            raise AuthenticationError(f"Credential refresh failed: {str(e)}")