# strategies/brokers/tradovate/utils.py

import hmac
import hashlib
import logging
import json
from typing import Dict, Optional, Any, Union
from datetime import datetime, timezone
from decimal import Decimal
import asyncio
import aiohttp
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .constants import KNOWN_CONTRACTS, CONTRACT_SPECS, OrderStatus
from .exceptions import TradovateAPIError, RateLimitExceeded

logger = logging.getLogger(__name__)

def generate_signature(secret_key: str, payload: str) -> str:
    """Generate HMAC signature for API requests."""
    return hmac.new(
        secret_key.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

def parse_tradovate_datetime(timestamp: Union[int, str]) -> datetime:
    """Parse Tradovate datetime format."""
    if isinstance(timestamp, str):
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    return datetime.fromtimestamp(int(timestamp) / 1000.0, tz=timezone.utc)

async def request_with_retry(url: str, headers: Dict, max_retries: int = 3) -> Dict:
    """Make HTTP request with retry logic."""
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    return await response.json()
        except aiohttp.ClientError as e:
            if attempt == max_retries - 1:
                raise TradovateAPIError(f"API request failed after {max_retries} attempts: {str(e)}")
            await asyncio.sleep(1 * (attempt + 1))
            logger.warning(f"Retry attempt {attempt + 1} for URL: {url}")
        except Exception as e:
            raise TradovateAPIError(f"Unexpected error during API request: {str(e)}")

def format_position(position: Dict, account) -> Optional[Dict]:
    """Format position data for frontend consumption."""
    try:
        contract_id = str(position.get('contractId'))
        symbol = KNOWN_CONTRACTS.get(contract_id, f'Contract-{contract_id}')
        specs = CONTRACT_SPECS.get(symbol[:3], {
            'tickSize': Decimal('0.01'),
            'tickValue': Decimal('1.0'),
        })

        net_pos = Decimal(str(position.get('netPos', 0)))
        net_price = Decimal(str(position.get('netPrice', 0)))
        current_price = Decimal(str(position.get('lastPrice', net_price)))

        # Calculate P&L
        if net_pos != 0:
            tick_value = Decimal(str(specs['tickValue']))
            tick_size = Decimal(str(specs['tickSize']))
            price_diff = current_price - net_price
            ticks = abs(price_diff / tick_size)
            pnl = ticks * tick_value * abs(net_pos)
            if (net_pos > 0 and price_diff < 0) or (net_pos < 0 and price_diff > 0):
                pnl = -pnl
        else:
            pnl = Decimal('0')

        return {
            'id': str(position.get('id')),
            'contractId': contract_id,
            'symbol': symbol,
            'side': 'LONG' if net_pos > 0 else 'SHORT',
            'quantity': abs(net_pos),
            'avgPrice': float(net_price),
            'currentPrice': float(current_price),
            'unrealizedPnL': float(pnl),
            'timeEntered': position.get('timestamp'),
            'accountId': account.account_id,
            'contractInfo': {
                'tickValue': float(specs['tickValue']),
                'tickSize': float(specs['tickSize']),
                'name': symbol,
            }
        }

    except Exception as e:
        logger.error(f"Error formatting position: {str(e)}")
        return None

def format_order_status(status: str) -> str:
    """Normalize Tradovate order status."""
    status_map = {
        'Accepted': OrderStatus.PENDING.value,
        'Working': OrderStatus.WORKING.value,
        'Completed': OrderStatus.FILLED.value,
        'Cancelled': OrderStatus.CANCELLED.value,
        'Rejected': OrderStatus.REJECTED.value,
        'Expired': OrderStatus.EXPIRED.value
    }
    return status_map.get(status, OrderStatus.PENDING.value)

def format_price_for_contract(symbol: str, price: Union[float, Decimal]) -> Decimal:
    """Format price according to contract specifications."""
    if symbol not in CONTRACT_SPECS:
        raise ValueError(f"Unknown symbol: {symbol}")

    tick_size = Decimal(str(CONTRACT_SPECS[symbol]['tick_size']))
    price_decimal = Decimal(str(price))
    return (price_decimal / tick_size).quantize(Decimal('1')) * tick_size

def calculate_position_value(symbol: str, quantity: int, price: Decimal) -> Decimal:
    """Calculate total position value."""
    if symbol not in CONTRACT_SPECS:
        raise ValueError(f"Unknown symbol: {symbol}")

    contract = CONTRACT_SPECS[symbol]
    tick_value = Decimal(str(contract['value_per_tick']))
    ticks_per_point = Decimal('4')  # Standard for most futures
    return quantity * price * tick_value * ticks_per_point

def calculate_margin_requirement(symbol: str, quantity: int, is_day_trade: bool = True) -> Decimal:
    """Calculate margin requirement for a position."""
    if symbol not in CONTRACT_SPECS:
        raise ValueError(f"Unknown symbol: {symbol}")

    contract = CONTRACT_SPECS[symbol]
    margin = Decimal(str(contract['margin_day'])) if is_day_trade else Decimal(str(contract['margin_overnight']))
    return margin * Decimal(str(quantity))

def validate_order_parameters(
    symbol: str,
    quantity: Union[int, float, Decimal],
    order_type: str,
    price: Optional[Union[float, Decimal]] = None,
    time_in_force: Optional[str] = None
) -> None:
    """Validate order parameters before submission."""
    if symbol not in CONTRACT_SPECS:
        raise ValidationError(f"Invalid symbol: {symbol}")

    if not isinstance(quantity, (int, float, Decimal)) or quantity <= 0:
        raise ValidationError("Quantity must be a positive number")

    if price is not None:
        try:
            Decimal(str(price))
        except:
            raise ValidationError("Invalid price format")

    if time_in_force and time_in_force not in ['Day', 'GTC', 'IOC', 'FOK']:
        raise ValidationError(f"Invalid time in force: {time_in_force}")

def get_api_url(environment: str) -> str:
    """Get appropriate API URL based on environment."""
    if environment == 'live':
        return settings.TRADOVATE_LIVE_API_URL
    return settings.TRADOVATE_DEMO_API_URL

def get_ws_url(environment: str) -> str:
    """Get appropriate WebSocket URL based on environment."""
    if environment == 'live':
        return settings.TRADOVATE_LIVE_WS_URL
    return settings.TRADOVATE_DEMO_WS_URL

def handle_api_error(response: Any) -> None:
    """Handle Tradovate API error responses."""
    if response.status_code == 429:
        retry_after = int(response.headers.get('Retry-After', 60))
        raise RateLimitExceeded(
            "Rate limit exceeded",
            retry_after=retry_after
        )
    
    try:
        error_data = response.json()
        error_message = error_data.get('errorText', str(response.content))
        raise TradovateAPIError(
            f"API Error ({response.status_code}): {error_message}"
        )
    except json.JSONDecodeError:
        raise TradovateAPIError(
            f"API Error ({response.status_code}): {response.text}"
        )