from django.urls import path
from . import views

app_name = 'tradovate'

urlpatterns = [
    # OAuth endpoints
    path('initiate-oauth/', 
        views.initiate_oauth, 
        name='initiate_oauth'
    ),
    path('callback/', 
        views.oauth_callback, 
        name='oauth_callback'
    ),

    # Account management endpoints
    path('fetch-accounts/', 
        views.fetch_accounts, 
        name='fetch_accounts'
    ),
    path('remove-account/<str:account_id>/', 
        views.remove_account, 
        name='remove_account'
    ),
    path('toggle-account/<str:account_id>/', 
        views.toggle_account_status, 
        name='toggle_account_status'
    ),

    # Trading data endpoints
    path('positions/', 
        views.get_positions, 
        name='positions'
    ),
    path('positions/<str:account_id>/', 
        views.get_positions, 
        name='account_positions'
    ),
    path('get-account-orders/<str:account_id>/', 
        views.get_account_orders, 
        name='account_orders'
    ),

    # Token management
    path('refresh-token/', 
        views.refresh_tradovate_token, 
        name='refresh_token'
    ),
]

# API Documentation
"""
Tradovate API Endpoints
======================

OAuth Flow
---------
POST /initiate-oauth/
    Initialize OAuth flow with Tradovate
    Query params: 
        - environment: 'demo' or 'live'
    Returns: 
        - auth_url: URL to redirect user for authentication

GET /callback/
    OAuth callback handler
    Query params:
        - code: OAuth authorization code
        - state: Environment state (demo/live)
    Returns:
        - Redirects to frontend with account info

Account Management
----------------
GET /fetch-accounts/
    Fetch all connected Tradovate accounts
    Returns:
        - List of account objects with details

DELETE /remove-account/<account_id>/
    Remove a connected trading account
    Returns:
        - Success/error message

POST /toggle-account/<account_id>/
    Toggle account active status
    Returns:
        - Updated account status

Trading Data
-----------
GET /positions/
    Get positions for all active accounts
    Returns:
        - List of positions across all accounts
        - Metadata about processed accounts

GET /positions/<account_id>/
    Get positions for specific account
    Returns:
        - List of positions for specified account
        - Account metadata

GET /get-account-orders/<account_id>/
    Get orders for specific account
    Returns:
        - List of orders with details

Token Management
--------------
POST /refresh-token/
    Refresh Tradovate access token
    Returns:
        - New token information

Authentication
-------------
All endpoints except OAuth callback require JWT authentication
via Bearer token in Authorization header.

Error Responses
-------------
{
    "error": "Error description",
    "detail": "Additional error details",
    "timestamp": "2024-12-10T12:00:00Z"
}

Response Format
-------------
{
    "data": {}, // Response data
    "count": 0, // Number of items (if applicable)
    "timestamp": "2024-12-10T12:00:00Z",
    "metadata": {} // Additional response metadata
}
"""