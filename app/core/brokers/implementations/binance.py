from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import hashlib
import hmac
import logging
import json
import time
import aiohttp
import asyncio
from urllib.parse import urlencode
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..base import BaseBroker, AuthenticationError, ConnectionError, OrderError
from ..config import BrokerEnvironment
from ....models.broker import BrokerAccount, BrokerCredentials
from ....models.user import User
from ....core.config import settings

logger = logging.getLogger(__name__)


class BinanceOrderType:
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"


class BinanceOrderSide:
    BUY = "BUY"
    SELL = "SELL"


class BinanceTimeInForce:
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill


class BinanceMarketType:
    SPOT = "spot"
    FUTURES = "futures"


class BinanceBroker(BaseBroker):
    """Binance broker implementation"""
    
    def __init__(self, broker_id: str, db: Session):
        super().__init__(broker_id, db)
        
        # Set API URLs based on broker type
        if broker_id == 'binanceus':
            self.api_urls = {
                'live': 'https://api.binance.us'
            }
            self.ws_urls = {
                'live': 'wss://stream.binance.us:9443'
            }
        else:  # binance global
            self.api_urls = {
                'live': 'https://api.binance.com'
            }
            self.ws_urls = {
                'live': 'wss://stream.binance.com:9443'
            }
    
    def _get_signature(self, query_string: str, secret_key: str) -> str:
        """Generate HMAC-SHA256 signature for Binance API"""
        return hmac.new(
            secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _prepare_headers(self, api_key: str) -> Dict[str, str]:
        """Prepare headers for Binance API requests"""
        return {
            'X-MBX-APIKEY': api_key,
            'Content-Type': 'application/json'
        }
    
    def _prepare_signed_params(self, params: Dict[str, Any], secret_key: str) -> str:
        """Prepare signed parameters for Binance API"""
        params['timestamp'] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = self._get_signature(query_string, secret_key)
        return f"{query_string}&signature={signature}"
    
    async def authenticate(self, credentials: Dict[str, Any]) -> BrokerCredentials:
        """Authenticate with Binance API using API key and secret"""
        api_key = credentials.get('api_key')
        secret_key = credentials.get('secret_key')
        
        if not api_key or not secret_key:
            raise AuthenticationError("API key and secret key are required")
        
        try:
            # Test the API key by making a request to account endpoint
            headers = self._prepare_headers(api_key)
            params = {'timestamp': int(time.time() * 1000)}
            query_string = self._prepare_signed_params(params, secret_key)
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_urls['live']}/api/v3/account?{query_string}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        account_info = await response.json()
                        logger.info("Successfully authenticated with Binance")
                        
                        # Create and return credentials object
                        return BrokerCredentials(
                            broker_id=self.broker_id,
                            credential_type='api_key',
                            access_token=api_key,
                            refresh_token=secret_key,  # Store secret in refresh_token field
                            expires_at=datetime.utcnow() + timedelta(days=365),  # API keys don't expire
                            metadata={'account_type': account_info.get('accountType', 'SPOT')}
                        )
                    else:
                        error_data = await response.json()
                        raise AuthenticationError(f"Authentication failed: {error_data.get('msg', 'Unknown error')}")
                        
        except aiohttp.ClientError as e:
            logger.error(f"Network error during Binance authentication: {e}")
            raise ConnectionError(f"Failed to connect to Binance: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during Binance authentication: {e}")
            raise AuthenticationError(f"Authentication failed: {e}")
    
    async def validate_credentials(self, credentials: BrokerCredentials) -> bool:
        """Validate stored Binance credentials"""
        try:
            api_key = credentials.access_token
            secret_key = credentials.refresh_token
            
            if not api_key or not secret_key:
                return False
            
            headers = self._prepare_headers(api_key)
            params = {'timestamp': int(time.time() * 1000)}
            query_string = self._prepare_signed_params(params, secret_key)
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_urls['live']}/api/v3/account?{query_string}"
                async with session.get(url, headers=headers) as response:
                    return response.status == 200
                    
        except Exception as e:
            logger.error(f"Error validating Binance credentials: {e}")
            return False
    
    async def refresh_credentials(self, credentials: BrokerCredentials) -> BrokerCredentials:
        """Refresh Binance credentials (API keys don't need refreshing)"""
        # API keys don't expire, so just validate and return the same credentials
        if await self.validate_credentials(credentials):
            return credentials
        else:
            raise AuthenticationError("Invalid credentials cannot be refreshed")
    
    async def connect_account(
        self,
        user: User,
        account_id: str,
        environment: BrokerEnvironment,
        credentials: Optional[Dict[str, Any]] = None
    ) -> BrokerAccount:
        """Connect to a Binance trading account"""
        try:
            if not credentials:
                raise ValueError("API credentials are required for Binance")
            
            # Authenticate first
            broker_credentials = await self.authenticate(credentials)
            
            # Get account info
            account_info = await self._get_account_info(
                broker_credentials.access_token,
                broker_credentials.refresh_token
            )
            
            # Create broker account
            broker_account = BrokerAccount(
                user_id=user.id,
                broker_id=self.broker_id,
                account_id=account_id or f"binance_{user.id}_{int(time.time())}",
                environment=environment.value,
                status='active',
                balance=float(account_info.get('totalWalletBalance', 0)),
                active=True,
                has_credentials=True,
                metadata={
                    'account_type': account_info.get('accountType', 'SPOT'),
                    'permissions': account_info.get('permissions', []),
                    'can_trade': account_info.get('canTrade', False),
                    'can_withdraw': account_info.get('canWithdraw', False),
                    'can_deposit': account_info.get('canDeposit', False)
                }
            )
            
            # Set relationship
            broker_credentials.account_id = broker_account.id
            
            # Save to database
            self.db.add(broker_account)
            self.db.add(broker_credentials)
            self.db.commit()
            
            logger.info(f"Successfully connected Binance account for user {user.id}")
            return broker_account
            
        except Exception as e:
            logger.error(f"Error connecting Binance account: {e}")
            self.db.rollback()
            raise ConnectionError(f"Failed to connect account: {e}")
    
    async def disconnect_account(self, account: BrokerAccount) -> bool:
        """Disconnect a Binance trading account"""
        try:
            # Update account status
            account.status = 'inactive'
            account.active = False
            
            # Remove credentials
            credentials = self.db.query(BrokerCredentials).filter(
                BrokerCredentials.account_id == account.id
            ).first()
            
            if credentials:
                self.db.delete(credentials)
            
            self.db.commit()
            logger.info(f"Successfully disconnected Binance account {account.account_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error disconnecting Binance account: {e}")
            self.db.rollback()
            return False
    
    async def fetch_accounts(self, user: User) -> List[Dict[str, Any]]:
        """Fetch all Binance accounts for a user"""
        try:
            accounts = self.db.query(BrokerAccount).filter(
                BrokerAccount.user_id == user.id,
                BrokerAccount.broker_id.in_(['binance', 'binanceus'])
            ).all()
            
            result = []
            for account in accounts:
                result.append({
                    'account_id': account.account_id,
                    'broker_id': account.broker_id,
                    'name': f"Binance {account.metadata.get('account_type', 'SPOT')}",
                    'environment': account.environment,
                    'status': account.status,
                    'balance': account.balance,
                    'active': account.active,
                    'has_credentials': account.has_credentials,
                    'last_connected': account.updated_at.isoformat() if account.updated_at else None,
                    'metadata': account.metadata
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching Binance accounts: {e}")
            raise ConnectionError(f"Failed to fetch accounts: {e}")
    
    async def get_account_status(self, account: BrokerAccount) -> Dict[str, Any]:
        """Get Binance account status and information"""
        try:
            credentials = self._get_account_credentials(account)
            account_info = await self._get_account_info(
                credentials.access_token,
                credentials.refresh_token
            )
            
            return {
                'account_id': account.account_id,
                'status': 'active' if account_info.get('canTrade') else 'inactive',
                'balance': float(account_info.get('totalWalletBalance', 0)),
                'permissions': account_info.get('permissions', []),
                'account_type': account_info.get('accountType', 'SPOT'),
                'can_trade': account_info.get('canTrade', False),
                'can_withdraw': account_info.get('canWithdraw', False),
                'can_deposit': account_info.get('canDeposit', False),
                'maker_commission': account_info.get('makerCommission', 0),
                'taker_commission': account_info.get('takerCommission', 0)
            }
            
        except Exception as e:
            logger.error(f"Error getting Binance account status: {e}")
            raise ConnectionError(f"Failed to get account status: {e}")
    
    async def get_positions(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """Get current positions for a Binance account"""
        try:
            credentials = self._get_account_credentials(account)
            
            # For spot accounts, positions are represented as balances
            if account.metadata.get('account_type') == 'SPOT':
                return await self._get_spot_balances(
                    credentials.access_token,
                    credentials.refresh_token
                )
            else:
                # For futures accounts, get actual positions
                return await self._get_futures_positions(
                    credentials.access_token,
                    credentials.refresh_token
                )
                
        except Exception as e:
            logger.error(f"Error getting Binance positions: {e}")
            raise ConnectionError(f"Failed to get positions: {e}")
    
    async def get_orders(self, account: BrokerAccount) -> List[Dict[str, Any]]:
        """Get orders for a Binance account"""
        try:
            credentials = self._get_account_credentials(account)
            
            headers = self._prepare_headers(credentials.access_token)
            params = {'timestamp': int(time.time() * 1000)}
            query_string = self._prepare_signed_params(params, credentials.refresh_token)
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_urls['live']}/api/v3/openOrders?{query_string}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        orders = await response.json()
                        return self._transform_orders(orders)
                    else:
                        error_data = await response.json()
                        raise ConnectionError(f"Failed to get orders: {error_data.get('msg', 'Unknown error')}")
                        
        except Exception as e:
            logger.error(f"Error getting Binance orders: {e}")
            raise ConnectionError(f"Failed to get orders: {e}")
    
    async def place_order(
        self,
        account: BrokerAccount,
        order_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Place a trading order on Binance"""
        try:
            credentials = self._get_account_credentials(account)
            
            # Prepare order parameters
            params = {
                'symbol': order_data['symbol'],
                'side': order_data['side'],
                'type': order_data['type'],
                'quantity': order_data['quantity'],
                'timestamp': int(time.time() * 1000)
            }
            
            # Add optional parameters
            if 'price' in order_data:
                params['price'] = order_data['price']
            if 'timeInForce' in order_data:
                params['timeInForce'] = order_data['timeInForce']
            if 'stopPrice' in order_data:
                params['stopPrice'] = order_data['stopPrice']
            
            headers = self._prepare_headers(credentials.access_token)
            query_string = self._prepare_signed_params(params, credentials.refresh_token)
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_urls['live']}/api/v3/order"
                async with session.post(url, headers=headers, data=query_string) as response:
                    if response.status == 200:
                        order_result = await response.json()
                        return self._transform_order_result(order_result)
                    else:
                        error_data = await response.json()
                        raise OrderError(f"Failed to place order: {error_data.get('msg', 'Unknown error')}")
                        
        except Exception as e:
            logger.error(f"Error placing Binance order: {e}")
            raise OrderError(f"Failed to place order: {e}")
    
    async def cancel_order(
        self,
        account: BrokerAccount,
        order_id: str
    ) -> bool:
        """Cancel an order on Binance"""
        try:
            credentials = self._get_account_credentials(account)
            
            params = {
                'symbol': order_id.split('_')[0] if '_' in order_id else '',  # Extract symbol from order_id
                'orderId': order_id,
                'timestamp': int(time.time() * 1000)
            }
            
            headers = self._prepare_headers(credentials.access_token)
            query_string = self._prepare_signed_params(params, credentials.refresh_token)
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_urls['live']}/api/v3/order"
                async with session.delete(url, headers=headers, data=query_string) as response:
                    return response.status == 200
                    
        except Exception as e:
            logger.error(f"Error canceling Binance order: {e}")
            return False
    
    async def initialize_oauth(
        self,
        user: User,
        environment: str
    ) -> Dict[str, Any]:
        """Binance doesn't use OAuth, raise NotImplementedError"""
        raise NotImplementedError("Binance uses API key authentication, not OAuth")
    
    async def initialize_api_key(
        self,
        user: User,
        environment: str,
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize API key connection for Binance"""
        try:
            api_key_data = credentials.get('apiKey', '')
            
            if ':' not in api_key_data:
                raise ValueError("API key must be in format: key:secret")
            
            api_key, secret_key = api_key_data.split(':', 1)
            
            # Test the credentials
            auth_creds = await self.authenticate({
                'api_key': api_key,
                'secret_key': secret_key
            })
            
            # Create account
            account = await self.connect_account(
                user=user,
                account_id=f"{self.broker_id}_{user.id}_{int(time.time())}",
                environment=BrokerEnvironment.LIVE,
                credentials={'api_key': api_key, 'secret_key': secret_key}
            )
            
            return {
                'success': True,
                'account_id': account.account_id,
                'message': 'API key connection successful'
            }
            
        except Exception as e:
            logger.error(f"Error initializing Binance API key: {e}")
            raise ConnectionError(f"Failed to initialize API key: {e}")
    
    # Helper methods
    def _get_account_credentials(self, account: BrokerAccount) -> BrokerCredentials:
        """Get credentials for an account"""
        credentials = self.db.query(BrokerCredentials).filter(
            BrokerCredentials.account_id == account.id
        ).first()
        
        if not credentials:
            raise AuthenticationError("No credentials found for account")
        
        return credentials
    
    async def _get_account_info(self, api_key: str, secret_key: str) -> Dict[str, Any]:
        """Get account information from Binance"""
        headers = self._prepare_headers(api_key)
        params = {'timestamp': int(time.time() * 1000)}
        query_string = self._prepare_signed_params(params, secret_key)
        
        async with aiohttp.ClientSession() as session:
            url = f"{self.api_urls['live']}/api/v3/account?{query_string}"
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_data = await response.json()
                    raise ConnectionError(f"Failed to get account info: {error_data.get('msg', 'Unknown error')}")
    
    async def _get_spot_balances(self, api_key: str, secret_key: str) -> List[Dict[str, Any]]:
        """Get spot trading balances"""
        account_info = await self._get_account_info(api_key, secret_key)
        
        positions = []
        for balance in account_info.get('balances', []):
            free_balance = float(balance['free'])
            locked_balance = float(balance['locked'])
            total_balance = free_balance + locked_balance
            
            if total_balance > 0:  # Only include assets with balance
                positions.append({
                    'symbol': balance['asset'],
                    'quantity': total_balance,
                    'free': free_balance,
                    'locked': locked_balance,
                    'position_type': 'SPOT'
                })
        
        return positions
    
    async def _get_futures_positions(self, api_key: str, secret_key: str) -> List[Dict[str, Any]]:
        """Get futures trading positions"""
        # This would require futures API implementation
        # For now, return empty list
        return []
    
    def _transform_orders(self, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform Binance orders to standard format"""
        transformed = []
        for order in orders:
            transformed.append({
                'order_id': order['orderId'],
                'symbol': order['symbol'],
                'side': order['side'],
                'type': order['type'],
                'quantity': float(order['origQty']),
                'price': float(order['price']) if order['price'] != '0.00000000' else None,
                'status': order['status'],
                'time_in_force': order['timeInForce'],
                'created_at': datetime.fromtimestamp(order['time'] / 1000).isoformat(),
                'updated_at': datetime.fromtimestamp(order['updateTime'] / 1000).isoformat()
            })
        return transformed
    
    def _transform_order_result(self, order_result: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Binance order result to standard format"""
        return {
            'order_id': order_result['orderId'],
            'client_order_id': order_result['clientOrderId'],
            'symbol': order_result['symbol'],
            'side': order_result['side'],
            'type': order_result['type'],
            'quantity': float(order_result['origQty']),
            'price': float(order_result['price']) if order_result['price'] != '0.00000000' else None,
            'status': order_result['status'],
            'time_in_force': order_result['timeInForce'],
            'created_at': datetime.fromtimestamp(order_result['transactTime'] / 1000).isoformat()
        }


# Factory function to create appropriate broker instance
def create_binance_broker(broker_id: str, db: Session) -> BinanceBroker:
    """Create a Binance broker instance"""
    return BinanceBroker(broker_id, db)