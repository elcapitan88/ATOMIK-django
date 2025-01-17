# Django imports
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.conf import settings

# Rest framework imports
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework import status

# Python standard library imports
import json
import logging
import requests
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, List, Union
import base64
import asyncio
from urllib.parse import urlencode

# Local imports
from strategies.models import Broker
from .models import TradovateAccount, TradovateToken
from .constants import (
    CONTRACT_SPECS, 
    KNOWN_CONTRACTS,
    TRADOVATE_LIVE_EXCHANGE_URL,
    TRADOVATE_DEMO_EXCHANGE_URL,
    TRADOVATE_LIVE_API_URL,
    TRADOVATE_DEMO_API_URL
)
from .exceptions import TradovateAPIError, RateLimitExceeded
from .utils import format_position
from ..base.exceptions import (
    WebSocketError,
    WebSocketConnectionError,
    WebSocketAuthenticationError,
    WebSocketMessageError
)

# Set up logger
logger = logging.getLogger(__name__)


@csrf_exempt
@login_required  # Add login_required decorator
def initiate_oauth(request):
    """Initialize OAuth flow with Tradovate"""
    logger.info("initiate_oauth view called")
    
    if request.method == 'POST':
        logger.info("Received POST request for initiate_oauth")
        try:
            # Log authentication status
            logger.info(f"User authentication status: {request.user.is_authenticated}")
            logger.info(f"User ID: {request.user.id}")
            logger.info(f"Username: {request.user.username}")

            data = json.loads(request.body)
            environment = data.get('environment', 'demo')
            logger.info(f"Initiating OAuth for environment: {environment}")

            # Create state with environment and user ID
            state_data = {
                'environment': environment,
                'user_id': request.user.id
            }
            state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

            # Build OAuth parameters
            params = {
                "client_id": settings.TRADOVATE_CLIENT_ID,
                "redirect_uri": settings.TRADOVATE_REDIRECT_URI,
                "response_type": "code",
                "scope": "trading",
                "state": state
            }

            # Build complete authorization URL
            auth_url = settings.TRADOVATE_AUTH_URL
            if environment == 'demo':
                auth_url = auth_url.replace('live', 'demo')
            
            full_auth_url = f"{auth_url}?{urlencode(params)}"
            logger.info(f"Constructed auth_url: {full_auth_url}")

            return JsonResponse({'auth_url': full_auth_url})
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request body: {str(e)}")
            return JsonResponse({'error': 'Invalid JSON format'}, status=400)
        except Exception as e:
            logger.error(f"Unexpected error in initiate_oauth: {str(e)}", exc_info=True)
            return JsonResponse({'error': str(e)}, status=500)
    
    logger.info("Received non-POST request for initiate_oauth")
    return JsonResponse({'error': 'Invalid request method'}, status=405)

@csrf_exempt
def oauth_callback(request):
    """Handle OAuth callback from Tradovate."""
    logger.info("Received OAuth callback")
    code = request.GET.get('code')
    state = request.GET.get('state')

    if not code:
        logger.error("No code provided in OAuth callback")
        return redirect(f"{settings.FRONTEND_URL}/auth?error=No authorization code provided")

    try:
        # Decode state parameter
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state).decode())
            user_id = state_data.get('user_id')
            environment = state_data.get('environment', 'demo')
            logger.info(f"Decoded state data - user_id: {user_id}, environment: {environment}")
        except Exception as e:
            logger.error(f"Error decoding state parameter: {str(e)}")
            return redirect(f"{settings.FRONTEND_URL}/auth?error=Invalid state parameter")

        # Get user from state
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
            logger.info(f"Found user {user.username} from state parameter")
        except User.DoesNotExist:
            logger.error(f"User {user_id} not found")
            return redirect(f"{settings.FRONTEND_URL}/auth?error=User not found")

        # Choose URLs based on environment
        exchange_url = (
            settings.TRADOVATE_LIVE_EXCHANGE_URL 
            if environment == 'live' 
            else settings.TRADOVATE_DEMO_EXCHANGE_URL
        )
        api_url = (
            settings.TRADOVATE_LIVE_API_URL 
            if environment == 'live' 
            else settings.TRADOVATE_DEMO_API_URL
        )

        # Exchange code for tokens
        try:
            logger.info(f"Exchanging code for token at {exchange_url}")
            payload = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.TRADOVATE_REDIRECT_URI,
            }
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            }

            response = requests.post(
                exchange_url,
                data=payload,
                headers=headers,
                auth=(settings.TRADOVATE_CLIENT_ID, settings.TRADOVATE_CLIENT_SECRET),
                timeout=10
            )
            response.raise_for_status()
            tokens = response.json()
            logger.info(f"Token exchange response status: {response.status_code}")
        except requests.RequestException as e:
            logger.error(f"Token exchange failed: {str(e)}")
            return redirect(f"{settings.FRONTEND_URL}/auth?error=Failed to exchange token")

        try:
            with transaction.atomic():
                # Create or get broker first within transaction
                broker = Broker.objects.select_for_update().get_or_create(
                    slug='tradovate',
                    defaults={
                        'name': 'Tradovate',
                        'is_active': True
                    }
                )[0]
                
                logger.debug(f"Using broker: {broker.id} - {broker.slug}")

                # Create or update token
                token, created = TradovateToken.objects.update_or_create(
                    user=user,
                    environment=environment,
                    defaults={
                        'access_token': tokens.get('accessToken', tokens.get('access_token', '')),
                        'refresh_token': tokens.get('refreshToken', tokens.get('refresh_token', '')),
                        'md_access_token': tokens.get('mdAccessToken', tokens.get('md_access_token', '')),
                        'expires_in': tokens.get('expiresIn', tokens.get('expires_in', 4800)),
                        'created_at': timezone.now(),
                        'last_refreshed': timezone.now(),
                        'is_valid': True,
                        'error_count': 0,
                        'last_error': None
                    }
                )
                
                logger.info(f"Token {'created' if created else 'updated'} for user: {user.username}")

                # Set up API headers
                api_headers = {
                    'Authorization': f'Bearer {token.access_token}',
                    'Content-Type': 'application/json'
                }

                # Fetch accounts and balances
                account_response = requests.get(
                    f"{api_url}/account/list",
                    headers=api_headers,
                    timeout=10
                )
                account_response.raise_for_status()
                accounts = account_response.json()

                balance_response = requests.get(
                    f"{api_url}/cashBalance/list",
                    headers=api_headers,
                    timeout=10
                )
                balance_response.raise_for_status()
                balances = balance_response.json()

                # Map balances to accounts
                balance_map = {str(balance['accountId']): balance for balance in balances}
                logger.info(f"Received {len(accounts)} accounts from Tradovate")

                # Process accounts
                saved_accounts = []
                for account in accounts:
                    account_id = str(account['id'])
                    balance_info = balance_map.get(account_id, {})
                    
                    logger.debug(f"Processing account {account_id} with broker_id: {broker.id}")
                    
                    tradovate_account, created = TradovateAccount.objects.update_or_create(
                        user=user,
                        broker=broker,
                        account_id=account_id,
                        environment=environment,
                        defaults={
                            'name': account.get('name', 'Tradovate Account'),
                            'nickname': account.get('nickname'),
                            'is_active': True,
                            'status': 'active',
                            'balance': balance_info.get('cashBalance', 0),
                            'available_margin': balance_info.get('availableForTrade', 0),
                            'margin_used': balance_info.get('marginUsed', 0),
                            'last_connected': timezone.now(),
                            'error_message': None
                        }
                    )

                    saved_accounts.append({
                        'account_id': tradovate_account.account_id,
                        'name': tradovate_account.name,
                        'nickname': tradovate_account.nickname,
                        'active': tradovate_account.is_active,
                        'environment': tradovate_account.environment,
                        'balance': float(tradovate_account.balance or 0),
                        'available_margin': float(tradovate_account.available_margin or 0)
                    })

                # Generate JWT token
                jwt_token = str(AccessToken.for_user(user))

                # Build success response
                success_params = {
                    'auth_success': 'true',
                    'access_token': jwt_token,
                    'accounts': json.dumps(saved_accounts),
                    'environment': environment
                }

                success_url = f"{settings.FRONTEND_URL}/dashboard?{urlencode(success_params)}"
                logger.info(f"OAuth flow completed successfully for user {user.username}")
                return HttpResponseRedirect(success_url)

        except IntegrityError as e:
            logger.error(f"Database integrity error: {str(e)}", exc_info=True)
            logger.error(f"Broker details - ID: {getattr(broker, 'id', None)}, Exists: {Broker.objects.filter(slug='tradovate').exists()}")
            return redirect(f"{settings.FRONTEND_URL}/auth?error=Database integrity error")

        except Exception as e:
            logger.error(f"Error processing accounts: {str(e)}", exc_info=True)
            return redirect(f"{settings.FRONTEND_URL}/auth?error=Failed to process accounts")

    except Exception as e:
        logger.error(f"Unexpected error during OAuth callback: {str(e)}", exc_info=True)
        return redirect(f"{settings.FRONTEND_URL}/auth?error=An unexpected error occurred")

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def fetch_accounts(request):
    """Fetch and update Tradovate accounts for the authenticated user."""
    
    # Add caching to prevent frequent refetching
    cache_key = f'tradovate_accounts_{request.user.id}'
    cached_data = cache.get(cache_key)
    if cached_data:
        return Response(cached_data)

    logger.info(f"Fetching accounts for user {request.user.username}")
    
    try:
        with transaction.atomic():
            all_accounts = []
            tokens = TradovateToken.objects.filter(
                user=request.user,
                is_valid=True
            ).select_related('user')

            if not tokens.exists():
                logger.info(f"No tokens found for user {request.user.username}")
                return Response([], status=status.HTTP_200_OK)

            # Get or create Tradovate broker
            broker = Broker.objects.get_or_create(
                slug='tradovate',
                defaults={'name': 'Tradovate'}
            )[0]

            for token in tokens:
                try:
                    # Handle token refresh
                    if token.is_expired():
                        token = refresh_tradovate_token(token)
                        if not token or not token.is_valid:
                            continue

                    api_url = (
                        settings.TRADOVATE_LIVE_API_URL 
                        if token.environment == 'live' 
                        else settings.TRADOVATE_DEMO_API_URL
                    )

                    headers = {
                        'Authorization': f'Bearer {token.access_token}',
                        'Content-Type': 'application/json'
                    }

                    # Make synchronous requests
                    account_response = requests.get(
                        f"{api_url}/account/list",
                        headers=headers,
                        timeout=10
                    )
                    account_response.raise_for_status()
                    
                    balance_response = requests.get(
                        f"{api_url}/cashBalance/list",
                        headers=headers,
                        timeout=10
                    )
                    balance_response.raise_for_status()

                    accounts_data = account_response.json()
                    balances_data = balance_response.json()
                    balance_map = {str(b['accountId']): b for b in balances_data}

                    # Process accounts
                    for account in accounts_data:
                        account_id = str(account['id'])
                        balance_info = balance_map.get(account_id, {})
                        
                        tradovate_account, _ = TradovateAccount.objects.update_or_create(
                            user=request.user,
                            broker=broker,
                            account_id=account_id,
                            environment=token.environment,
                            defaults={
                                'name': account.get('name', 'Tradovate Account'),
                                'nickname': account.get('nickname'),
                                'is_active': True,
                                'status': 'active',
                                'balance': balance_info.get('cashBalance', 0),
                                'available_margin': balance_info.get('availableForTrade', 0),
                                'margin_used': balance_info.get('marginUsed', 0),
                                'last_connected': timezone.now()
                            }
                        )

                        all_accounts.append({
                            'account_id': tradovate_account.account_id,
                            'name': tradovate_account.name,
                            'nickname': tradovate_account.nickname,
                            'active': tradovate_account.is_active,
                            'environment': tradovate_account.environment,
                            'balance': float(tradovate_account.balance or 0),
                            'available_margin': float(tradovate_account.available_margin or 0)
                        })

                except Exception as e:
                    logger.error(f"Error processing token for {token.environment}: {str(e)}")
                    continue

            # Cache the results
            cache.set(cache_key, all_accounts, timeout=30)  # Cache for 30 seconds
            return Response(all_accounts)

    except Exception as e:
        logger.error(f"Unexpected error during account fetch: {str(e)}", exc_info=True)
        return Response({
            'error': 'Failed to fetch accounts',
            'detail': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def refresh_tradovate_token(token: TradovateToken) -> TradovateToken:
    """Helper function to refresh a Tradovate access token."""
    if not token.refresh_token:
        raise ValueError("No refresh token available")

    try:
        exchange_url = (
            settings.TRADOVATE_LIVE_EXCHANGE_URL 
            if token.environment == 'live' 
            else settings.TRADOVATE_DEMO_EXCHANGE_URL
        )

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        response = requests.post(
            f"{exchange_url}/auth/refresh",
            headers=headers,
            auth=(settings.TRADOVATE_CLIENT_ID, settings.TRADOVATE_CLIENT_SECRET),
            json={'refreshToken': token.refresh_token},
            timeout=10
        )
        
        response.raise_for_status()
        new_tokens = response.json()

        with transaction.atomic():
            token.access_token = new_tokens['access_token']
            if 'refresh_token' in new_tokens:
                token.refresh_token = new_tokens['refresh_token']
            if 'md_access_token' in new_tokens:
                token.md_access_token = new_tokens['md_access_token']
            token.last_refreshed = timezone.now()
            token.is_valid = True
            token.error_count = 0
            token.last_error = None
            token.save()

        logger.info(f"Successfully refreshed token for user {token.user.id}")
        return token

    except requests.RequestException as e:
        error_msg = f"Failed to refresh token: {str(e)}"
        logger.error(error_msg)
        token.mark_invalid(error_msg)
        raise TradovateAPIError(error_msg)

    except Exception as e:
        error_msg = f"Unexpected error during token refresh: {str(e)}"
        logger.error(error_msg, exc_info=True)
        token.mark_invalid(error_msg)
        raise
    
# Helper function used by fetch_accounts
def refresh_tradovate_token(token):
    """Refresh a Tradovate access token."""
    if not token.refresh_token:
        raise ValueError("No refresh token available")

    try:
        exchange_url = (
            settings.TRADOVATE_LIVE_EXCHANGE_URL 
            if token.environment == 'live' 
            else settings.TRADOVATE_DEMO_EXCHANGE_URL
        )

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        response = requests.post(
            f"{exchange_url}/auth/refresh",
            headers=headers,
            auth=(settings.TRADOVATE_CLIENT_ID, settings.TRADOVATE_CLIENT_SECRET),
            json={'refreshToken': token.refresh_token},
            timeout=10
        )
        
        response.raise_for_status()
        new_tokens = response.json()

        with transaction.atomic():
            token.access_token = new_tokens['access_token']
            if 'refresh_token' in new_tokens:
                token.refresh_token = new_tokens['refresh_token']
            if 'md_access_token' in new_tokens:
                token.md_access_token = new_tokens['md_access_token']
            token.last_refreshed = timezone.now()
            token.is_valid = True
            token.error_count = 0
            token.last_error = None
            token.save()

        logger.info(f"Successfully refreshed token for user {token.user.id}")
        return token

    except Exception as e:
        error_msg = f"Failed to refresh token: {str(e)}"
        logger.error(error_msg)
        token.mark_invalid(error_msg)
        raise

@csrf_exempt
@login_required
def toggle_account_status(request, account_id):
    """Toggle account active status"""
    try:
        account = TradovateAccount.objects.get(
            user=request.user,
            account_id=account_id
        )
        
        new_status = 'active' if account.status == 'inactive' else 'inactive'
        account.status = new_status
        account.save()
        
        logger.info(f"Account {account_id} status toggled to {new_status}")
        return JsonResponse({
            'message': f'Account status updated to {new_status}',
            'status': new_status
        })
    except TradovateAccount.DoesNotExist:
        logger.error(f"Account {account_id} not found")
        return JsonResponse({'error': 'Account not found'}, status=404)
    except Exception as e:
        logger.error(f"Error toggling account status: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["DELETE"])
def remove_account(request, account_id):
    """Remove Tradovate account and associated token"""
    logger.info(f"Attempting to remove account with ID: {account_id}")
    try:
        with transaction.atomic():
            account = TradovateAccount.objects.get(account_id=account_id, user=request.user)
            environment = account.environment
            account.delete()
            
            # Also remove the token for this environment
            TradovateToken.objects.filter(user=request.user, environment=environment).delete()
            
            logger.info(f"Successfully removed account with ID: {account_id} and associated token")
            return JsonResponse({'message': 'Account and associated token successfully removed'})
            
    except TradovateAccount.DoesNotExist:
        logger.error(f"Account with ID {account_id} not found")
        return JsonResponse({'error': 'Account not found'}, status=404)
    except Exception as e:
        logger.error(f"Error removing account {account_id}: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

def refresh_tradovate_token(token):
    """Refresh a Tradovate access token."""
    if not token.refresh_token:
        raise ValueError("No refresh token available")

    try:
        exchange_url = (
            settings.TRADOVATE_LIVE_EXCHANGE_URL 
            if token.environment == 'live' 
            else settings.TRADOVATE_DEMO_EXCHANGE_URL
        )

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        response = requests.post(
            f"{exchange_url}/auth/refresh",
            headers=headers,
            auth=(settings.TRADOVATE_CLIENT_ID, settings.TRADOVATE_CLIENT_SECRET),
            json={'refreshToken': token.refresh_token},
            timeout=10
        )
        
        response.raise_for_status()
        new_tokens = response.json()

        with transaction.atomic():
            token.access_token = new_tokens['access_token']
            if 'refresh_token' in new_tokens:
                token.refresh_token = new_tokens['refresh_token']
            if 'md_access_token' in new_tokens:
                token.md_access_token = new_tokens['md_access_token']
            token.last_refreshed = timezone.now()
            token.is_valid = True
            token.error_count = 0
            token.last_error = None
            token.save()

        logger.info(f"Successfully refreshed token for user {token.user.id}")
        return token

    except requests.RequestException as e:
        error_msg = f"Failed to refresh token: {str(e)}"
        logger.error(error_msg)
        token.mark_invalid(error_msg)
        raise ValueError(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error during token refresh: {str(e)}"
        logger.error(error_msg, exc_info=True)
        token.mark_invalid(error_msg)
        raise
        
@csrf_exempt
@login_required
def get_account_orders(request, account_id):
    """Get current and recent orders for a specific account"""
    try:
        account = TradovateAccount.objects.get(
            user=request.user,
            account_id=account_id
        )

        token = TradovateToken.objects.get(
            user=request.user,
            environment=account.environment
        )

        if token.needs_refresh():
            token = refresh_tradovate_token(token)

        api_url = (
            settings.TRADOVATE_LIVE_API_URL 
            if account.environment == 'live' 
            else settings.TRADOVATE_DEMO_API_URL
        )

        headers = token.get_authorization_header()
        headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

        # Fetch orders
        response = requests.get(
            f"{api_url}/order/list",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        orders = response.json()

        # Filter orders for this account
        account_orders = [
            order for order in orders 
            if str(order.get('accountId')) == account_id
        ]

        # Sort orders by timestamp descending
        account_orders.sort(
            key=lambda x: x.get('timestamp', 0),
            reverse=True
        )

        return JsonResponse({
            'account_id': account_id,
            'orders': account_orders
        })

    except TradovateAccount.DoesNotExist:
        return JsonResponse({'error': 'Account not found'}, status=404)
    except TradovateToken.DoesNotExist:
        return JsonResponse({'error': 'Token not found'}, status=404)
    except requests.RequestException as e:
        logger.error(f"Error fetching orders: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
    except Exception as e:
        logger.error(f"Unexpected error fetching orders: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
    
@login_required
def get_positions(request, account_id=None):
    """
    Get positions for either a specific account or all active accounts.
    
    Args:
        request: HTTP request object
        account_id: Optional specific account ID to fetch positions for
    
    Returns:
        JsonResponse containing:
            - positions: List of formatted position data
            - count: Number of positions
            - timestamp: Server timestamp
    """
    logger.info(f"Fetching positions for user {request.user.username}" + 
                (f" account {account_id}" if account_id else " all accounts"))
    
    try:
        # Build base query for active accounts
        accounts = TradovateAccount.objects.filter(
            user=request.user,
            is_active=True,
            status='active'
        ).select_related('broker')

        # Filter by account_id if provided
        if account_id:
            accounts = accounts.filter(account_id=account_id)

        if not accounts.exists():
            logger.info(f"No active accounts found for filter: {account_id if account_id else 'all'}")
            return JsonResponse({
                'positions': [],
                'count': 0,
                'timestamp': timezone.now().isoformat()
            })

        all_positions = []
        processed_accounts = []
        skipped_accounts = []

        for account in accounts:
            try:
                # Get valid token for this account's environment
                token = TradovateToken.objects.get(
                    user=request.user,
                    environment=account.environment,
                    is_valid=True
                )

                if token.is_expired():
                    logger.warning(f"Token expired for account {account.account_id}")
                    try:
                        token = refresh_tradovate_token(token)
                    except Exception as e:
                        logger.error(f"Failed to refresh token for account {account.account_id}: {str(e)}")
                        skipped_accounts.append({
                            'account_id': account.account_id,
                            'reason': 'Token refresh failed'
                        })
                        continue

                api_url = (
                    settings.TRADOVATE_LIVE_API_URL 
                    if account.environment == 'live' 
                    else settings.TRADOVATE_DEMO_API_URL
                )

                headers = {
                    'Authorization': f'Bearer {token.access_token}',
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }

                # Fetch positions from Tradovate API
                response = requests.get(
                    f"{api_url}/position/list",
                    headers=headers,
                    timeout=10
                )
                response.raise_for_status()
                positions = response.json()

                # Format positions
                account_positions = []
                for position in positions:
                    if str(position.get('accountId')) == account.account_id and position.get('netPos', 0) != 0:
                        formatted_position = format_position(position, account)
                        if formatted_position:
                            account_positions.append(formatted_position)

                all_positions.extend(account_positions)
                processed_accounts.append({
                    'account_id': account.account_id,
                    'positions_count': len(account_positions)
                })

                logger.info(f"Successfully fetched {len(account_positions)} positions for account {account.account_id}")

            except TradovateToken.DoesNotExist:
                logger.warning(f"No valid token found for account {account.account_id}")
                skipped_accounts.append({
                    'account_id': account.account_id,
                    'reason': 'No valid token'
                })
                continue

            except requests.RequestException as e:
                logger.error(f"API request failed for account {account.account_id}: {str(e)}")
                skipped_accounts.append({
                    'account_id': account.account_id,
                    'reason': 'API request failed'
                })
                continue

            except Exception as e:
                logger.error(f"Error processing account {account.account_id}: {str(e)}", exc_info=True)
                skipped_accounts.append({
                    'account_id': account.account_id,
                    'reason': 'Processing error'
                })
                continue

        # Prepare response
        response_data = {
            'positions': all_positions,
            'count': len(all_positions),
            'timestamp': timezone.now().isoformat(),
            'metadata': {
                'processed_accounts': processed_accounts,
                'skipped_accounts': skipped_accounts,
                'total_accounts': len(accounts),
                'successful_accounts': len(processed_accounts)
            }
        }

        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Unexpected error in get_positions: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': 'An unexpected error occurred while fetching positions',
            'detail': str(e)
        }, status=500)

def format_position(position, account):
    """
    Format position data for response.
    
    Args:
        position: Raw position data from Tradovate
        account: TradovateAccount instance
        
    Returns:
        Formatted position dictionary or None if formatting fails
    """
    try:
        contract_id = str(position.get('contractId'))
        symbol = KNOWN_CONTRACTS.get(contract_id, f'Contract-{contract_id}')
        specs = CONTRACT_SPECS.get(symbol[:3], {
            'tickSize': 0.01,
            'tickValue': 1.0,
        })

        net_pos = float(position.get('netPos', 0))
        net_price = float(position.get('netPrice', 0))
        
        # Calculate P&L if we have the necessary data
        pnl = 0
        current_price = float(position.get('lastPrice', net_price))
        if net_pos != 0:
            tick_value = float(specs['tickValue'])
            tick_size = float(specs['tickSize'])
            price_diff = current_price - net_price
            ticks = abs(price_diff / tick_size)
            pnl = ticks * tick_value * abs(net_pos)
            if (net_pos > 0 and price_diff < 0) or (net_pos < 0 and price_diff > 0):
                pnl = -pnl

        return {
            'id': str(position.get('id')),
            'contractId': contract_id,
            'symbol': symbol,
            'side': 'LONG' if net_pos > 0 else 'SHORT',
            'quantity': abs(net_pos),
            'avgPrice': net_price,
            'currentPrice': current_price,
            'unrealizedPnL': round(pnl, 2),
            'timeEntered': position.get('timestamp'),
            'accountId': account.account_id,
            'environment': account.environment,
            'contractInfo': {
                'tickValue': float(specs['tickValue']),
                'tickSize': float(specs['tickSize']),
                'name': symbol,
            }
        }
    except Exception as e:
        logger.error(f"Error formatting position: {str(e)}")
        return None