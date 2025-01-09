from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import base64
import requests
from datetime import datetime, timedelta
import json
import logging
import uuid

from fastapi.responses import RedirectResponse
from ....db.session import get_db
from ....core.security import get_current_user
from ....models.user import User
from ....models.broker import BrokerAccount, BrokerCredentials
from ....core.config import settings
from ....core.brokers.base import BaseBroker
from typing import Dict, List, Optional, Any 

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/initiate-oauth")
async def initiate_oauth(
    environment: str = "demo",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Initiate the OAuth flow with Tradovate"""
    try:
        state = base64.urlsafe_b64encode(json.dumps({
            'environment': environment,
            'user_id': current_user.id,
            'timestamp': datetime.utcnow().isoformat(),
            'nonce': str(uuid.uuid4())
        }).encode()).decode()

        # Use the auth URL directly from settings
        auth_url = settings.TRADOVATE_AUTH_URL

        params = {
            "client_id": settings.TRADOVATE_CLIENT_ID,
            "redirect_uri": settings.TRADOVATE_REDIRECT_URI,
            "response_type": "code",
            "scope": "trading",
            "state": state
        }

        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        full_auth_url = f"{auth_url}?{query_string}"

        return {"auth_url": full_auth_url}

    except Exception as e:
        logger.error(f"OAuth initiation failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"OAuth initiation failed: {str(e)}"
        )

@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str | None = None,
    db: Session = Depends(get_db)
):
    """Handle Tradovate OAuth callback"""
    try:
        logger.info("Starting OAuth callback process")
        logger.info(f"Received authorization code: {code[:10]}...")

        if not state:
            logger.error("Missing state parameter")
            raise HTTPException(status_code=400, detail="Missing state parameter")

        # Decode state
        try:
            # Clean up state string (handle potential URL encoding)
            state = state.replace(' ', '+')
            if '%3D' in state:
                state = state.replace('%3D', '=')
            padding = 4 - (len(state) % 4)
            if padding != 4:
                state = state + ('=' * padding)

            state_data = json.loads(base64.urlsafe_b64decode(state).decode())
            environment = state_data.get('environment', 'demo')
            user_id = state_data.get('user_id')
            
            logger.info(f"Decoded state data - Environment: {environment}, User ID: {user_id}")
        except Exception as e:
            logger.error(f"Error decoding state: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid state parameter")

        # Get broker instance
        broker = BaseBroker.get_broker_instance("tradovate", db)
        
        # Process OAuth callback using broker implementation
        result = await broker.process_oauth_callback(code, user_id, environment)
        
        logger.info(f"OAuth callback processed successfully: {result}")

        # Redirect to frontend with success
        redirect_url = f"{settings.FRONTEND_URL}/dashboard"
        logger.info(f"Redirecting to: {redirect_url}")
        return RedirectResponse(url=redirect_url)

    except HTTPException as he:
        logger.error(f"HTTP Exception in callback: {str(he)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in callback: {str(e)}")
        error_url = f"{settings.FRONTEND_URL}/dashboard?error={str(e)}"
        return RedirectResponse(url=error_url)

