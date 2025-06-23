
import json
import base64
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

# FastAPI imports
from fastapi import APIRouter, Depends, HTTPException, Request, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, JSONResponse

# SQLAlchemy imports
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

# Third-party imports
import httpx
from pydantic import BaseModel

# Local imports
from ....core.security import get_current_user
from ....core.permissions import check_subscription_feature
from ....db.session import get_db
from ....models.user import User
from ....models.broker import BrokerAccount, BrokerCredentials
from ....models.subscription import SubscriptionTier, SubscriptionStatus
from ....core.brokers.base import BaseBroker
from ....core.brokers.config import BrokerEnvironment, BROKER_CONFIGS
from ....core.config import settings
# Trading WebSocket functionality moved to separate Websocket-Proxy service


__all__ = ['router', 'tradovate_callback'] 

# Initialize router and logger
router = APIRouter()
logger = logging.getLogger(__name__)

# Pydantic models for request validation
class OAuthInitRequest(BaseModel):
    environment: str

class CallbackRequest(BaseModel):
    code: str
    state: Optional[str] = None

@router.post("/connect")
@check_subscription_feature(SubscriptionTier.STARTED)
async def initiate_oauth(
    request: OAuthInitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Initiate the OAuth flow with Tradovate"""
    try:
        # Clean and validate environment
        environment = request.environment.lower()
        logger.info(f"Initiating OAuth flow for environment: {environment}")
        
        if environment not in ['demo', 'live']:
            raise HTTPException(
                status_code=400,
                detail="Invalid environment. Must be 'demo' or 'live'"
            )
        
        # Create state token
        state = base64.urlsafe_b64encode(json.dumps({
            'environment': environment,
            'user_id': current_user.id,
            'timestamp': datetime.utcnow().isoformat(),
            'nonce': str(uuid.uuid4())
        }).encode()).decode()

        logger.info(f"Generated state token for user {current_user.id}")

        # Build OAuth URL
        params = {
            "client_id": settings.TRADOVATE_CLIENT_ID,
            "redirect_uri": settings.TRADOVATE_REDIRECT_URI,
            "response_type": "code",
            "scope": "trading",
            "state": state
        }

        # Get the appropriate auth URL based on environment
        base_auth_url = settings.TRADOVATE_AUTH_URL
        if environment == 'demo':
            base_auth_url = base_auth_url.replace('live', 'demo')

        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        full_auth_url = f"{base_auth_url}?{query_string}"

        logger.info(f"Generated OAuth URL: {full_auth_url}")
        return {"auth_url": full_auth_url, "state": state}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth initiation failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"OAuth initiation failed: {str(e)}"
        )

# app/api/v1/endpoints/tradovate.py

@router.get("/callback")
async def tradovate_callback(
    code: str,
    state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Handle the OAuth callback from Tradovate"""
    logger.info("=== Tradovate OAuth Callback Started ===")
    logger.info(f"Received code: {code}")
    logger.info(f"Received state: {state[:30]}..." if state else "No state received")

    try:
        # Validate state parameter
        if not state:
            logger.error("Missing state parameter")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/dashboard?connection_status=error&message=Missing state parameter",
                status_code=302
            )

        # Decode and validate state token
        try:
            decoded_state = base64.urlsafe_b64decode(state)
            state_data = json.loads(decoded_state.decode())
            
            user_id = state_data.get('user_id')
            environment = state_data.get('environment', 'demo')
            timestamp = datetime.fromisoformat(state_data.get('timestamp'))

            logger.info(f"Decoded state - User ID: {user_id}, Environment: {environment}")

        except Exception as e:
            logger.error(f"State validation failed: {str(e)}")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/dashboard?connection_status=error&message=Invalid state parameter",
                status_code=302
            )

        # Get broker instance
        broker = BaseBroker.get_broker_instance("tradovate", db)
        
        # Process OAuth callback
        result = await broker.process_oauth_callback(code, user_id, environment)
        
        logger.info(f"OAuth callback successful: Connected {len(result['accounts'])} accounts")

        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard?connection_status=success&accounts={len(result['accounts'])}",
            status_code=302
        )

    except Exception as e:
        logger.error(f"OAuth callback processing failed: {str(e)}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard?connection_status=error&message={str(e)}",
            status_code=302
        )
    finally:
        logger.info("=== OAuth Callback Processing Completed ===")

@router.websocket("/ws/{account_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    account_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for real-time trading data"""
    logger.info(f"WebSocket connection attempt for account: {account_id}")
    
    try:
        # Authenticate user
        user = await get_current_user(db=db, token=token)
        if not user:
            logger.warning("WebSocket authentication failed")
            await websocket.close(code=4001)
            return

        # Verify account ownership
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == user.id,
            BrokerAccount.is_active == True
        ).first()

        if not account:
            logger.warning(f"Account verification failed: {account_id}")
            await websocket.close(code=4003)
            return

        logger.info(f"WebSocket connection accepted for account {account_id}")
        await websocket.accept()

        try:
            while True:
                data = await websocket.receive_json()
                # Process websocket data here
                await websocket.send_json({"status": "received", "data": data})
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for account {account_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {str(e)}")
            await websocket.close(code=4000)

    except Exception as e:
        logger.error(f"WebSocket initialization error: {str(e)}")
        try:
            await websocket.close(code=4000)
        except:
            pass

# In endpoints/tradovate.py
@router.get("/routes-debug")
async def debug_routes():
    """Debug endpoint to verify route registration"""
    return {
        "callback_url": settings.TRADOVATE_REDIRECT_URI,
        "registered_routes": {
            "callback": "/api/tradovate/callback",
            "main": "/api/v1/brokers/tradovate"
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/ping")
async def ping_tradovate():
    """Test endpoint to verify routing"""
    return {
        "status": "ok",
        "message": "Tradovate routes are properly registered",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/test")
async def test_endpoint():
    """Test endpoint for debugging"""
    logger.info("Test endpoint called")
    return {
        "status": "ok",
        "message": "Tradovate endpoint is working",
        "timestamp": datetime.utcnow().isoformat()
    }