import json
import logging
from django.core.cache import cache
import requests
from typing import Dict, Any, Optional, Union
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from strategies.models import ActivatedStrategy
from strategies.brokers.tradovate.models import (
    TradovateAccount, 
    TradovateToken, 
    TradovateOrder
)
from strategies.views.utils import WebhookValidationError
from strategies.brokers.tradovate.constants import KNOWN_CONTRACTS, CONTRACT_SPECS

logger = logging.getLogger(__name__)

def process_webhook_payload(webhook, payload: Dict[str, Any]) -> None:
    """
    Process the normalized webhook payload and execute trading actions.
    
    Args:
        webhook: The webhook object that received the payload
        payload: The normalized trading signal payload
    
    Raises:
        WebhookValidationError: If the webhook or strategy validation fails
        Exception: For any other processing errors
    """
    try:
        # Get all active strategies for this webhook
        strategies = ActivatedStrategy.objects.filter(webhook_id=webhook.token, is_active=True)
        
        if not strategies.exists():
            logger.error(f"No active strategy found for webhook {webhook.token}")
            raise WebhookValidationError("No active strategy found for this webhook")

        # Validate payload action
        if 'action' not in payload:
            raise WebhookValidationError("Missing 'action' in payload")
        
        if payload['action'].upper() not in ['BUY', 'SELL']:
            raise WebhookValidationError(f"Invalid action: {payload['action']}. Must be BUY or SELL")

        # Process each strategy
        for strategy in strategies:
            try:
                if strategy.strategy_type == 'single':
                    execute_single_account_trade(strategy, payload)
                else:
                    execute_group_trade(strategy, payload)

                # Update strategy statistics for success
                with transaction.atomic():
                    strategy.last_triggered = timezone.now()
                    strategy.total_trades += 1
                    strategy.successful_trades += 1
                    strategy.save()

                # Broadcast position update via WebSocket
                broadcast_position_updates(strategy.user.id)

            except Exception as e:
                logger.error(f"Error processing strategy {strategy.id}: {str(e)}", exc_info=True)
                # Update strategy statistics for failure
                with transaction.atomic():
                    strategy.last_triggered = timezone.now()
                    strategy.total_trades += 1
                    strategy.failed_trades += 1
                    strategy.save()
                raise

        logger.info(f"Successfully processed webhook for {len(strategies)} strategies")
        
    except Exception as e:
        logger.error(f"Error processing webhook payload: {str(e)}", exc_info=True)
        raise

def broadcast_position_updates(user_id: int) -> None:
    """
    Broadcast updated positions to connected WebSocket clients.
    
    Args:
        user_id: The user ID to broadcast updates to
    """
    try:
        # Get all positions for the user
        positions = get_all_user_positions(user_id)
        
        # Get the channel layer
        channel_layer = get_channel_layer()
        
        # Broadcast to user's group
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {
                "type": "position_update",
                "positions": positions
            }
        )
        logger.info(f"Successfully broadcasted position updates to user {user_id}")
    except Exception as e:
        logger.error(f"Error broadcasting position updates: {str(e)}")

def get_all_user_positions(user_id: int) -> list:
    """
    Get all positions for a user across all active accounts.
    
    Args:
        user_id: The user ID to get positions for
        
    Returns:
        List of formatted position data
    """
    positions = []
    
    try:
        # Get all active accounts for the user
        accounts = TradovateAccount.objects.filter(
            user_id=user_id,
            is_active=True
        )

        for account in accounts:
            try:
                token = TradovateToken.objects.get(
                    user_id=user_id,
                    environment=account.environment
                )

                if not token.is_valid or token.is_expired():
                    continue

                positions_response = get_account_positions(account, token)
                if positions_response:
                    positions.extend(positions_response)

            except Exception as e:
                logger.error(f"Error getting positions for account {account.account_id}: {str(e)}")
                continue

        return positions

    except Exception as e:
        logger.error(f"Error getting all user positions: {str(e)}")
        return []

def get_account_positions(account: TradovateAccount, token: TradovateToken) -> list:
    """
    Get positions for a specific account.
    
    Args:
        account: TradovateAccount instance
        token: TradovateToken instance
        
    Returns:
        List of formatted position data
    """
    try:
        api_url = (
            settings.TRADOVATE_LIVE_API_URL 
            if account.environment == 'live' 
            else settings.TRADOVATE_DEMO_API_URL
        )

        headers = {
            'Authorization': f'Bearer {token.access_token}',
            'Content-Type': 'application/json'
        }

        response = requests.get(
            f"{api_url}/position/list",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        positions = response.json()

        formatted_positions = []
        for position in positions:
            if str(position.get('accountId')) == account.account_id and position.get('netPos', 0) != 0:
                formatted_position = format_position(position, account)
                if formatted_position:
                    formatted_positions.append(formatted_position)

        return formatted_positions

    except Exception as e:
        logger.error(f"Error fetching positions for account {account.account_id}: {str(e)}")
        return []

def format_position(position: Dict, account: TradovateAccount) -> Optional[Dict]:
    """
    Format position data for frontend consumption.
    """
    try:
        contract_id = str(position.get('contractId'))
        symbol = KNOWN_CONTRACTS.get(contract_id, f'Contract-{contract_id}')
        contract_specs = CONTRACT_SPECS.get(symbol, {
            'tickSize': 0.01,
            'tickValue': 1.0,
            'description': 'Unknown Contract'
        })

        net_pos = float(position.get('netPos', 0))
        net_price = float(position.get('netPrice', 0))
        
        tick_value = float(contract_specs['tickValue'])
        tick_size = float(contract_specs['tickSize'])
        
        # Calculate P&L if we have a position
        if net_pos != 0:
            avg_entry = net_price
            current_price = net_price  # Without market data, use net price
            price_diff = current_price - avg_entry
            ticks = abs(price_diff / tick_size)
            pnl = ticks * tick_value * abs(net_pos)
            if (net_pos > 0 and price_diff < 0) or (net_pos < 0 and price_diff > 0):
                pnl = -pnl
        else:
            pnl = 0

        return {
            'id': str(position.get('id')),
            'contractId': contract_id,
            'symbol': symbol,
            'side': 'LONG' if net_pos > 0 else 'SHORT',
            'quantity': abs(net_pos),
            'avgPrice': net_price,
            'currentPrice': net_price,
            'unrealizedPnL': pnl,
            'timeEntered': position.get('timestamp'),
            'accountId': account.account_id,
            'contractInfo': {
                'tickValue': tick_value,
                'tickSize': tick_size,
                'name': symbol,
                'description': contract_specs['description']
            }
        }

    except Exception as e:
        logger.error(f"Error formatting position: {str(e)}")
        return None

def execute_tradovate_order(token: TradovateToken, order_data: Dict[str, Any], strategy: ActivatedStrategy) -> Dict[str, Any]:
    """
    Execute an order through the Tradovate API.
    """
    try:
        headers = {
            'Authorization': f'Bearer {token.access_token}',
            'Content-Type': 'application/json'
        }

        api_url = (
            settings.TRADOVATE_LIVE_API_URL 
            if token.environment == 'live' 
            else settings.TRADOVATE_DEMO_API_URL
        )
        
        logger.info(f"Sending order to Tradovate API: {order_data}")
        
        response = requests.post(
            f"{api_url}/order/placeorder",
            headers=headers,
            json=order_data,
            timeout=10
        )
        
        response_data = response.json()
        logger.info(f"Tradovate API response: {response_data}")
        
        # Create order record
        account = TradovateAccount.objects.get(account_id=order_data['accountId'])
        order_record = TradovateOrder.objects.create(
            account=account,
            strategy=strategy,
            webhook_id=strategy.webhook_id,
            order_type=order_data['orderType'],
            action=order_data['action'],
            symbol=order_data['symbol'],
            quantity=order_data['orderQty'],
            price=order_data.get('price'),
            status='submitted',
            raw_request=order_data,
            raw_response=response_data
        )

        # Check for error response
        if response.status_code != 200 or 'errorText' in response_data:
            error_message = response_data.get('errorText', 'Unknown error')
            logger.error(f"Tradovate API error: {error_message}")
            order_record.status = 'failed'
            order_record.error_message = error_message
            order_record.save()
            raise WebhookValidationError(f"Tradovate API error: {error_message}")
        
        # Update order record with success info
        order_record.tradovate_order_id = response_data['orderId']
        order_record.status = 'working'
        order_record.save()
        
        # Broadcast position update
        broadcast_position_updates(strategy.user.id)
        
        return response_data

    except requests.RequestException as e:
        error_message = f"Tradovate API request error: {str(e)}"
        logger.error(error_message, exc_info=True)
        
        # Create failed order record
        TradovateOrder.objects.create(
            account=account,
            strategy=strategy,
            webhook_id=strategy.webhook_id,
            order_type=order_data['orderType'],
            action=order_data['action'],
            symbol=order_data['symbol'],
            quantity=order_data['orderQty'],
            price=order_data.get('price'),
            status='failed',
            raw_request=order_data,
            raw_response={'error': str(e)},
            error_message=error_message
        )
        
        raise

def execute_single_account_trade(strategy: ActivatedStrategy, payload: Dict[str, Any]) -> None:
    """Execute a trade for a single account strategy."""
    try:
        account = TradovateAccount.objects.get(account_id=strategy.account_id)
        token = TradovateToken.objects.get(
            user=strategy.user,
            environment=account.environment
        )

        if not token.is_valid:
            raise WebhookValidationError(f"Invalid token for account {account.name}")

        order_data = prepare_order_data(strategy, payload)
        response = execute_tradovate_order(token, order_data, strategy)
        
        logger.info(f"Successfully executed trade for strategy {strategy.id}")

        # Broadcast position update
        broadcast_position_updates(strategy.user.id)

    except Exception as e:
        logger.error(f"Error executing single account trade: {str(e)}", exc_info=True)
        raise

def execute_group_trade(strategy: ActivatedStrategy, payload: Dict[str, Any]) -> None:
    """Execute trades for a group strategy."""
    errors = []
    try:
        # Execute leader trade
        leader_strategy_data = {
            **strategy.__dict__,
            'account_id': strategy.leader_account_id,
            'quantity': strategy.leader_quantity
        }
        leader_strategy = ActivatedStrategy(**leader_strategy_data)
        
        logger.info(f"Executing leader trade for strategy {strategy.id}")
        execute_single_account_trade(leader_strategy, payload)

        # Execute follower trades
        for follower_account in strategy.follower_accounts.all():
            follower_strategy_data = {
                **strategy.__dict__,
                'account_id': follower_account.account_id,
                'quantity': strategy.follower_quantity
            }
            follower_strategy = ActivatedStrategy(**follower_strategy_data)
            
            try:
                logger.info(f"Executing follower trade for account {follower_account.account_id}")
                execute_single_account_trade(follower_strategy, payload)
            except Exception as e:
                error_msg = f"Error executing follower trade for account {follower_account.account_id}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)

        if errors:
            raise Exception(f"Some follower trades failed: {'; '.join(errors)}")

        # Broadcast position updates for all accounts
        broadcast_position_updates(strategy.user.id)

    except Exception as e:
        logger.error(f"Error executing group trade: {str(e)}", exc_info=True)
        raise

def prepare_order_data(strategy: ActivatedStrategy, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare order data for Tradovate API.
    
    Args:
        strategy: The strategy object containing trade parameters
        payload: The normalized trading signal payload
    
    Returns:
        Dict containing the formatted order data for Tradovate API
    
    Raises:
        ValidationError: If order parameters are invalid
    """
    try:
        # Validate action
        action = payload['action'].upper()
        if action not in ['BUY', 'SELL']:
            raise ValidationError(f"Invalid action: {action}. Must be BUY or SELL.")

        # Get account information from TradovateAccount
        try:
            account = TradovateAccount.objects.get(account_id=strategy.account_id)
            if not account.is_active:
                raise ValidationError(f"Account {account.name} is not active")
            if account.status != 'active':
                raise ValidationError(f"Account {account.name} status is {account.status}")
        except TradovateAccount.DoesNotExist:
            raise ValidationError(f"Account not found: {strategy.account_id}")

        # Base order data
        order_data = {
            'accountSpec': account.name,
            'accountId': int(account.account_id),
            'action': action.capitalize(),
            'symbol': strategy.ticker,
            'orderQty': abs(strategy.quantity),
            'orderType': 'Market',
            'isAutomated': True,
            'timeInForce': 'GTC'
        }

        # Handle limit orders if price is provided
        if 'price' in payload and payload['price']:
            try:
                price = Decimal(str(payload['price']))
                order_data.update({
                    'orderType': 'Limit',
                    'price': float(price)
                })
            except (TypeError, ValueError, InvalidOperation) as e:
                raise ValidationError(f"Invalid price value: {payload['price']}")

        logger.info(f"Prepared Tradovate order: {order_data}")
        return order_data

    except Exception as e:
        logger.error(f"Error preparing order data: {str(e)}", exc_info=True)
        raise