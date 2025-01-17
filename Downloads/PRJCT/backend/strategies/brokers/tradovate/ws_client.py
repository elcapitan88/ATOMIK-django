from typing import Dict, Any, Optional, List
import json
import logging
import asyncio
from decimal import Decimal
from django.utils import timezone
from django.conf import settings

from ..base.client import BaseWebSocketClient
from .models import TradovateAccount, TradovateToken
from .constants import CONTRACT_SPECS, KNOWN_CONTRACTS

logger = logging.getLogger(__name__)

class TradovateWebSocketClient(BaseWebSocketClient):
    """
    Tradovate-specific WebSocket client implementation.
    Handles authentication, message normalization, and Tradovate-specific behaviors.
    """

    def __init__(self, account: TradovateAccount, token: TradovateToken):
        self.account = account
        self.token = token
        
        # Determine WebSocket URL based on environment
        ws_url = (
            settings.TRADOVATE_LIVE_WS_URL 
            if account.environment == 'live' 
            else settings.TRADOVATE_DEMO_WS_URL
        )
        
        super().__init__(
            url=ws_url,
            options={
                'reconnect_attempts': 5,
                'reconnect_interval': 1,
                'heartbeat_interval': 15,
                'connection_timeout': 10
            }
        )

        # Subscription tracking
        self.subscribed_symbols = set()
        self.subscribed_accounts = set()
        self.position_cache = {}
        self.order_cache = {}

    async def authenticate(self) -> None:
        """Implement Tradovate-specific authentication."""
        try:
            auth_message = {
                "op": "authorize",
                "data": {
                    "access_token": self.token.access_token,
                    "md_access_token": self.token.md_access_token
                }
            }
            await self.send_message(auth_message)
            
            # Wait for auth response
            response = await self._wait_for_auth_response()
            if not response.get('success'):
                raise Exception(f"Authentication failed: {response.get('message', 'Unknown error')}")
            
            logger.info(f"Successfully authenticated WebSocket for account {self.account.account_id}")
            
            # Subscribe to account-specific updates after authentication
            await self.subscribe_account_updates()
            
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            raise

    async def _wait_for_auth_response(self) -> Dict:
        """Wait for authentication response with timeout."""
        try:
            message = await asyncio.wait_for(
                self.ws.recv(),
                timeout=10
            )
            return json.loads(message)
        except asyncio.TimeoutError:
            raise Exception("Authentication response timeout")
        except json.JSONDecodeError:
            raise Exception("Invalid authentication response")

    async def subscribe_market_data(self, symbols: List[str]) -> None:
        """Subscribe to market data for specified symbols."""
        try:
            for symbol in symbols:
                if symbol not in self.subscribed_symbols:
                    subscription = {
                        "op": "subscribe",
                        "args": ["md/subscribeQuote", {"symbol": symbol}]
                    }
                    await self.send_message(subscription)
                    self.subscribed_symbols.add(symbol)
                    logger.info(f"Subscribed to market data for {symbol}")
        except Exception as e:
            logger.error(f"Error subscribing to market data: {str(e)}")
            raise

    async def subscribe_account_updates(self) -> None:
        """Subscribe to account-specific updates."""
        try:
            subscription = {
                "op": "subscribe",
                "args": [
                    "user/changes",
                    {
                        "users": True,
                        "accounts": True,
                        "positions": True,
                        "orders": True,
                        "fills": True
                    }
                ]
            }
            await self.send_message(subscription)
            self.subscribed_accounts.add(self.account.account_id)
            logger.info(f"Subscribed to updates for account {self.account.account_id}")
        except Exception as e:
            logger.error(f"Error subscribing to account updates: {str(e)}")
            raise

    def get_message_type(self, message: Dict) -> str:
        """Extract message type from Tradovate message format."""
        return message.get('e', 'unknown')

    async def normalize_message(self, message_type: str, message: Dict) -> Dict:
        """Normalize Tradovate-specific message formats to standard format."""
        try:
            # Call appropriate normalization method based on message type
            normalizers = {
                'market_data': self._normalize_market_data,
                'position': self._normalize_position,
                'order': self._normalize_order,
                'fill': self._normalize_fill,
                'account': self._normalize_account
            }

            normalizer = normalizers.get(message_type)
            if normalizer:
                return await normalizer(message)
            return message

        except Exception as e:
            logger.error(f"Error normalizing {message_type} message: {str(e)}")
            raise

    async def _normalize_market_data(self, data: Dict) -> Dict:
        """Normalize market data message."""
        return {
            'symbol': data.get('symbol'),
            'price': data.get('last'),
            'bid': data.get('bid'),
            'ask': data.get('ask'),
            'volume': data.get('volume'),
            'timestamp': data.get('timestamp'),
            'source': 'tradovate'
        }

    async def _normalize_position(self, data: Dict) -> Dict:
        """Normalize position message."""
        try:
            contract_id = str(data.get('contractId'))
            symbol = KNOWN_CONTRACTS.get(contract_id, f'Contract-{contract_id}')
            specs = CONTRACT_SPECS.get(symbol[:3], {
                'tickSize': Decimal('0.01'),
                'tickValue': Decimal('1.0'),
            })

            net_pos = Decimal(str(data.get('netPos', 0)))
            net_price = Decimal(str(data.get('netPrice', 0)))
            current_price = Decimal(str(data.get('lastPrice', net_price)))

            # Calculate P&L
            price_diff = current_price - net_price
            tick_size = Decimal(str(specs['tickSize']))
            tick_value = Decimal(str(specs['tickValue']))
            
            if net_pos != 0:
                ticks = abs(price_diff / tick_size)
                pnl = ticks * tick_value * abs(net_pos)
                if (net_pos > 0 and price_diff < 0) or (net_pos < 0 and price_diff > 0):
                    pnl = -pnl
            else:
                pnl = Decimal('0')

            normalized = {
                'id': str(data.get('id')),
                'contractId': contract_id,
                'symbol': symbol,
                'side': 'LONG' if net_pos > 0 else 'SHORT',
                'quantity': abs(net_pos),
                'avgPrice': float(net_price),
                'currentPrice': float(current_price),
                'unrealizedPnL': float(pnl),
                'timeEntered': data.get('timestamp'),
                'accountId': self.account.account_id,
                'contractInfo': {
                    'tickValue': float(tick_value),
                    'tickSize': float(tick_size),
                    'name': symbol,
                }
            }

            # Update position cache
            self.position_cache[contract_id] = normalized
            return normalized

        except Exception as e:
            logger.error(f"Error normalizing position data: {str(e)}")
            raise

    async def _normalize_order(self, data: Dict) -> Dict:
        """Normalize order message."""
        order_id = str(data.get('orderId'))
        normalized = {
            'orderId': order_id,
            'status': data.get('status'),
            'symbol': data.get('symbol'),
            'side': data.get('action'),
            'quantity': data.get('orderQty'),
            'filledQuantity': data.get('filledQty', 0),
            'price': data.get('price'),
            'orderType': data.get('orderType'),
            'timestamp': data.get('timestamp'),
            'accountId': self.account.account_id,
            'source': 'tradovate'
        }
        
        # Update order cache
        self.order_cache[order_id] = normalized
        return normalized

    async def _normalize_fill(self, data: Dict) -> Dict:
        """Normalize fill message."""
        return {
            'fillId': str(data.get('id')),
            'orderId': str(data.get('orderId')),
            'symbol': data.get('symbol'),
            'side': data.get('action'),
            'quantity': data.get('qty'),
            'price': data.get('price'),
            'timestamp': data.get('timestamp'),
            'accountId': self.account.account_id,
            'source': 'tradovate'
        }

    async def _normalize_account(self, data: Dict) -> Dict:
        """Normalize account message."""
        return {
            'accountId': self.account.account_id,
            'balance': data.get('cashBalance'),
            'availableMargin': data.get('availableForTrade'),
            'marginUsed': data.get('marginUsed'),
            'timestamp': data.get('timestamp'),
            'source': 'tradovate'
        }

    async def cleanup(self) -> None:
        """Cleanup Tradovate-specific resources."""
        try:
            # Unsubscribe from market data
            for symbol in self.subscribed_symbols:
                try:
                    await self.send_message({
                        "op": "unsubscribe",
                        "args": ["md/unsubscribeQuote", {"symbol": symbol}]
                    })
                except Exception as e:
                    logger.error(f"Error unsubscribing from {symbol}: {str(e)}")

            # Clear caches
            self.position_cache.clear()
            self.order_cache.clear()
            self.subscribed_symbols.clear()
            self.subscribed_accounts.clear()

            # Call parent cleanup
            await super().cleanup()

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            raise

    def is_subscribed(self, symbol: str) -> bool:
        """Check if subscribed to a symbol."""
        return symbol in self.subscribed_symbols

    def get_position(self, contract_id: str) -> Optional[Dict]:
        """Get cached position data."""
        return self.position_cache.get(contract_id)

    def get_order(self, order_id: str) -> Optional[Dict]:
        """Get cached order data."""
        return self.order_cache.get(order_id)