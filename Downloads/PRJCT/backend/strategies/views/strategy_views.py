import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from ..models import ActivatedStrategy, Broker, BrokerAccount, Webhook
from ..brokers.tradovate.models import TradovateAccount

logger = logging.getLogger(__name__)

@login_required
@require_http_methods(["POST"])
def activate_strategy(request):
    try:
        data = json.loads(request.body)
        logger.info(f"Received strategy activation request for user {request.user.id}: {data}")

        # Validate webhook exists and belongs to user
        try:
            webhook = Webhook.objects.get(token=data['webhookToken'], user=request.user)
        except Webhook.DoesNotExist:
            return JsonResponse({'error': 'Invalid webhook token'}, status=400)

        # Check for existing strategy
        existing_query = ActivatedStrategy.objects.filter(
            user=request.user,
            webhook_id=data['webhookToken']
        )

        if data['type'] == 'single':
            existing_query = existing_query.filter(account_id=data['accountId'])
        else:
            existing_query = existing_query.filter(leader_account_id=data['leaderAccountId'])

        if existing_query.exists():
            # If strategy exists, update it instead of creating new
            strategy = existing_query.first()
            
            if data['type'] == 'single':
                strategy.quantity = data['quantity']
                strategy.ticker = data['ticker']
            else:
                strategy.leader_quantity = data['leaderQuantity']
                strategy.follower_quantity = data['followerQuantity']
                strategy.ticker = data['ticker']
                strategy.group_name = data['groupName']
                # Update follower accounts if provided
                if 'followerAccountIds' in data:
                    strategy.follower_accounts.clear()
                    for account_id in data['followerAccountIds']:
                        account = TradovateAccount.objects.get(account_id=account_id)
                        strategy.follower_accounts.add(account)

            strategy.is_active = True
            strategy.save()
            
            response_data = {
                'id': strategy.id,
                'type': strategy.strategy_type,
                'accountId': strategy.account_id,
                'leaderAccountId': strategy.leader_account_id,
                'followerAccountIds': list(strategy.follower_accounts.values_list('account_id', flat=True)),
                'webhookToken': str(strategy.webhook_id),
                'quantity': strategy.quantity,
                'leaderQuantity': strategy.leader_quantity,
                'followerQuantity': strategy.follower_quantity,
                'ticker': strategy.ticker,
                'groupName': strategy.group_name,
                'isActive': strategy.is_active,
                'created_at': strategy.created_at.isoformat(),
                'updated': True  # Flag to indicate this was an update
            }
            
            return JsonResponse(response_data)

        # Get or create Tradovate broker
        try:
            broker = Broker.objects.get(slug='tradovate')
            logger.info(f"Found existing broker: {broker.id} - {broker.name}")
        except Broker.DoesNotExist:
            broker = Broker.objects.create(
                slug='tradovate',
                name='Tradovate',
                is_active=True
            )
            logger.info(f"Created new broker: {broker.id} - {broker.name}")

        with transaction.atomic():
            strategy = ActivatedStrategy.objects.create(
                user=request.user,
                strategy_type=data['type'],
                account_id=data.get('accountId'),
                leader_account_id=data.get('leaderAccountId'),
                webhook_id=data['webhookToken'],
                quantity=data.get('quantity'),
                leader_quantity=data.get('leaderQuantity'),
                follower_quantity=data.get('followerQuantity'),
                ticker=data['ticker'],
                group_name=data.get('groupName'),
                is_active=True
            )

            # Add follower accounts for multiple account strategies
            if data['type'] == 'multiple':
                logger.info(f"Processing multiple account strategy with broker_id: {broker.id}")
                for account_id in data['followerAccountIds']:
                    account = TradovateAccount.objects.get(account_id=account_id)
                    strategy.follower_accounts.add(account)

            response_data = {
                'id': strategy.id,
                'type': strategy.strategy_type,
                'accountId': strategy.account_id,
                'leaderAccountId': strategy.leader_account_id,
                'followerAccountIds': list(strategy.follower_accounts.values_list('account_id', flat=True)),
                'webhookToken': str(strategy.webhook_id),
                'quantity': strategy.quantity,
                'leaderQuantity': strategy.leader_quantity,
                'followerQuantity': strategy.follower_quantity,
                'ticker': strategy.ticker,
                'groupName': strategy.group_name,
                'isActive': strategy.is_active,
                'created_at': strategy.created_at.isoformat()
            }
            
            return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Unexpected error activating strategy: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': str(e),
            'details': "An error occurred while activating the strategy. Please check the broker configuration."
        }, status=500)

@login_required
@require_http_methods(["GET"])
def list_strategies(request):
    """List all strategies for the authenticated user."""
    try:
        strategies = ActivatedStrategy.objects.filter(user=request.user)
        return JsonResponse([{
            'id': strategy.id,
            'type': strategy.strategy_type,
            'accountId': strategy.account_id,
            'leaderAccountId': strategy.leader_account_id,
            'followerAccountIds': list(strategy.follower_accounts.values_list('account_id', flat=True)),
            'webhookToken': strategy.webhook_id,
            'quantity': strategy.quantity,
            'leaderQuantity': strategy.leader_quantity,
            'followerQuantity': strategy.follower_quantity,
            'ticker': strategy.ticker,
            'groupName': strategy.group_name,
            'isActive': strategy.is_active,
            'created_at': strategy.created_at.isoformat()
        } for strategy in strategies], safe=False)
    except Exception as e:
        logger.error(f"Error listing strategies: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Failed to retrieve strategies'}, status=500)

@login_required
@require_http_methods(["POST"])
def toggle_strategy(request, strategy_id):
    """Toggle a strategy's active status."""
    try:
        with transaction.atomic():
            strategy = ActivatedStrategy.objects.get(id=strategy_id, user=request.user)
            strategy.is_active = not strategy.is_active
            strategy.save()
            
            logger.info(f"Strategy {strategy_id} toggled to {strategy.is_active} by user {request.user.id}")
            return JsonResponse({
                'message': 'Strategy toggled successfully',
                'isActive': strategy.is_active
            })
    except ActivatedStrategy.DoesNotExist:
        logger.error(f"Strategy {strategy_id} not found for user {request.user.id}")
        return JsonResponse({'error': 'Strategy not found'}, status=404)
    except Exception as e:
        logger.error(f"Error toggling strategy {strategy_id}: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Failed to toggle strategy'}, status=500)

@login_required
@require_http_methods(["DELETE"])
def delete_strategy(request, strategy_id):
    """Delete a strategy."""
    try:
        with transaction.atomic():
            strategy = ActivatedStrategy.objects.get(id=strategy_id, user=request.user)
            strategy.delete()
            
            logger.info(f"Strategy {strategy_id} deleted by user {request.user.id}")
            return JsonResponse({'message': 'Strategy deleted successfully'})
    except ActivatedStrategy.DoesNotExist:
        logger.error(f"Strategy {strategy_id} not found for user {request.user.id}")
        return JsonResponse({'error': 'Strategy not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting strategy {strategy_id}: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Failed to delete strategy'}, status=500)