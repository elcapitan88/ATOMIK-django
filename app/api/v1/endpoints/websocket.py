from fastapi import APIRouter, WebSocket, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from datetime import datetime
import logging
from typing import Optional, Dict, Any

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.broker import BrokerAccount
from app.websockets.manager import websocket_manager
from app.websockets.heartbeat_monitor import heartbeat_monitor
from app.websockets.metrics import HeartbeatMetrics

logger = logging.getLogger(__name__)
router = APIRouter()

async def validate_ws_token(token: str, db: Session) -> Optional[User]:
    """Validate WebSocket token and return associated user"""
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        email = payload.get("sub")
        if not email:
            return None
            
        user = db.query(User).filter(User.email == email).first()
        return user
    except JWTError:
        return None
    except Exception as e:
        logger.error(f"Token validation error: {str(e)}")
        return None

async def verify_account_access(user_id: int, account_id: str, db: Session) -> Optional[BrokerAccount]:
    """Verify user has access to the specified account"""
    try:
        account = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == user_id,
            BrokerAccount.account_id == account_id,
            BrokerAccount.is_active == True,
            BrokerAccount.deleted_at.is_(None)
        ).first()
        return account
    except Exception as e:
        logger.error(f"Account verification error: {str(e)}")
        return None

@router.websocket("/tradovate/{account_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    account_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for real-time trading data"""
    try:
        logger.info(f"WebSocket connection attempt for account: {account_id}")
        
        # Validate token first
        user = await validate_ws_token(token, db)
        if not user:
            logger.error(f"Invalid token for account {account_id}")
            await websocket.close(code=4001)
            return

        # Accept the connection
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for account: {account_id}")

        try:
            while True:
                # Wait for messages
                message = await websocket.receive_json()
                logger.debug(f"Received message from {account_id}: {message}")
                
                # Process message and send response
                response = await websocket_manager.process_message(account_id, message)
                if response:
                    await websocket.send_json(response)

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for account: {account_id}")
        except Exception as e:
            logger.error(f"Error processing messages for {account_id}: {str(e)}")
            await websocket.close(code=4000)
    
    except Exception as e:
        logger.error(f"WebSocket error for account {account_id}: {str(e)}")
        if websocket.client_state.connected:
            await websocket.close(code=4000)
    finally:
        await websocket_manager.disconnect(account_id)
        logger.info(f"WebSocket connection cleanup completed for account: {account_id}")

@router.get("/health")
async def websocket_health():
    """Health check endpoint for WebSocket service"""
    try:
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {
                "websocket_manager": websocket_manager.get_status(),
                "heartbeat_monitor": heartbeat_monitor.get_health_status()
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WebSocket service health check failed"
        )

@router.get("/status/{account_id}")
async def get_connection_status(
    account_id: str,
    db: Session = Depends(get_db)
):
    """Get WebSocket connection status for an account"""
    try:
        connection_info = websocket_manager.get_connection_info(account_id)
        if not connection_info:
            raise HTTPException(status_code=404, detail="Connection not found")

        return {
            "status": "ok",
            "account_id": account_id,
            "connection": connection_info,
            "heartbeat": heartbeat_monitor.get_connection_stats(account_id)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting connection status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))