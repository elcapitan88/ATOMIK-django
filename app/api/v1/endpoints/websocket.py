# Standard library imports
from datetime import datetime
import asyncio
import logging
import json
from enum import Enum
import uuid
from starlette.websockets import WebSocketState
from typing import Dict, Optional, Set, Any, Union

# FastAPI imports
from fastapi import (
    APIRouter, 
    WebSocket, 
    WebSocketDisconnect, 
    Depends, 
    Request,
    Query, 
    HTTPException,
    status
)
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.core.brokers.base import BaseBroker  # Fix for BaseBroker error
from app.websockets.metrics import HeartbeatMetrics  # Fix for HeartbeatMetrics error
from starlette.websockets import WebSocketState  # Fix for WebSocketState error
from fastapi import WebSocket, WebSocketDisconnect

# Local imports
from app.websockets.manager import WebSocketManager
from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.broker import BrokerAccount
from app.core.config import settings
from app.websockets.metrics import HeartbeatMetrics
from app.websockets.manager import websocket_manager
from app.websockets.heartbeat_monitor import heartbeat_monitor
from app.websockets.metrics import HeartbeatMetrics
from app.websockets.websocket_config import WebSocketConfig


logger = logging.getLogger(__name__)
router = APIRouter()

class WebSocketState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"

# Store active connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Dict[str, WebSocket]] = {}
        self.connection_details: Dict[str, Dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket, client_id: str, user_id: Optional[int] = None) -> bool:
        """Handle new WebSocket connection."""
        try:
            # Register with resource manager
            node_id = await self.resource_manager.register_connection(
                websocket.client.host,
                client_id
            )
            
            if not node_id:
                await websocket.close(code=1008)
                return False

            # Accept connection
            connection_id = f"{client_id}_{user_id}" if user_id else client_id
            
            async with self._lock:
                self.active_connections[connection_id] = websocket
                if user_id:
                    if user_id not in self.user_connections:
                        self.user_connections[user_id] = set()
                    self.user_connections[user_id].add(websocket)
                
            logger.info(f"New WebSocket connection: {connection_id}")
            return True

        except Exception as e:
            logger.error(f"Error in connect: {str(e)}")
            return False

    async def disconnect(self, client_id: str):
        """Handle WebSocket disconnection."""
        try:
            async with self._lock:
                # Remove from active connections
                for conn_id in list(self.active_connections.keys()):
                    if conn_id.startswith(f"{client_id}_") or conn_id == client_id:
                        if conn_id in self.active_connections:
                            del self.active_connections[conn_id]
                
                # Remove from user connections
                for user_connections in self.user_connections.values():
                    for websocket in list(user_connections):
                        try:
                            await websocket.close()
                        except:
                            pass
                        user_connections.discard(websocket)

                # Release resources
                await self.resource_manager.load_balancer.release_connection(client_id)
                
                logger.info(f"WebSocket disconnected: {client_id}")

        except Exception as e:
            logger.error(f"Error in disconnect: {str(e)}")

    async def update_heartbeat(self, connection_id: str):
        """Update last heartbeat time for a connection"""
        try:
            if connection_id in self.connection_details:
                self.connection_details[connection_id]["last_heartbeat"] = datetime.utcnow()
                logger.debug(f"Updated heartbeat for connection: {connection_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error updating heartbeat: {str(e)}")
            return False

    def get_connection_count(self, user_id: int) -> int:
        """Get count of active connections for user"""
        return len(self.active_connections.get(user_id, {}))

    async def broadcast_to_user(self, user_id: int, message: dict):
        """Broadcast a message to all user's connections"""
        if user_id in self.active_connections:
            disconnected = []
            for conn_id, websocket in self.active_connections[user_id].items():
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to connection {conn_id}: {str(e)}")
                    disconnected.append(conn_id)
            
            # Clean up disconnected connections
            for conn_id in disconnected:
                await self.disconnect(conn_id)

    def get_connection_count(self, user_id: int) -> int:
        """Get count of active connections for user"""
        return len(self.active_connections.get(user_id, {}))

# Create global connection manager
manager = ConnectionManager()

async def validate_ws_token(token: str, db: Session) -> Optional[User]:
    """Validate WebSocket token"""
    try:
        logger.info("Starting WebSocket token validation...")
        logger.info(f"Received token (first 20 chars): {token[:20]}")
        logger.info(f"Using SECRET_KEY (first 10 chars): {settings.SECRET_KEY[:10]}")
        logger.info(f"Using ALGORITHM: {settings.ALGORITHM}")

        # Decode token
        try:
            payload = jwt.decode(
                token, 
                settings.SECRET_KEY, 
                algorithms=[settings.ALGORITHM]
            )
            logger.info(f"Token decoded successfully. Payload: {payload}")
            
            email: str = payload.get("sub")
            if not email:
                logger.error("No email claim (sub) found in token")
                return None
                
            logger.info(f"Looking for user with email: {email}")
            user = db.query(User).filter(User.email == email).first()
            
            if user:
                logger.info(f"User found: ID={user.id}, email={email}")
                return user
            else:
                logger.error(f"No user found for email: {email}")
                return None

        except JWTError as jwt_error:
            logger.error(f"JWT decode error: {str(jwt_error)}")
            # Instead of returning None, let's raise the exception to match get_current_user behavior
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )

    except Exception as e:
        logger.error(f"Token validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )
    
async def get_websocket_manager(websocket: WebSocket):
    """
    Modified to work with WebSocket endpoints
    """
    try:
        app = websocket.app
        if not hasattr(app.state, "websocket_manager"):
            logger.error("WebSocket manager not found in application state")
            await websocket.close(code=1011)
            raise HTTPException(
                status_code=500,
                detail="WebSocket manager not initialized"
            )

        manager = app.state.websocket_manager
        
        # Ensure manager is initialized
        if not getattr(manager, '_initialized', False):
            initialized = await manager.initialize()
            if not initialized:
                logger.error("Failed to initialize WebSocket manager")
                await websocket.close(code=1011)
                raise HTTPException(
                    status_code=500,
                    detail="Failed to initialize WebSocket manager"
                )
            
        return manager
        
    except Exception as e:
        logger.error(f"Error getting WebSocket manager: {str(e)}")
        await websocket.close(code=1011)
        raise HTTPException(
            status_code=500,
            detail="WebSocket system unavailable"
        )
    
@router.websocket("/tradovate/{account_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    account_id: str,
    token: str = Query(...),
    manager: WebSocketManager = Depends(get_websocket_manager),
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for real-time trading data"""
    try:
        # Validate token BEFORE accepting connection
        user = await validate_ws_token(token, db)
        if not user:
            await websocket.close(code=4001)
            return

        # Verify account BEFORE accepting connection
        account = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == user.id,
            BrokerAccount.account_id == account_id,
            BrokerAccount.is_active == True,
            BrokerAccount.deleted_at.is_(None)
        ).first()

        if not account:
            await websocket.close(code=4003)
            return

        # Initialize connection with manager (this will handle accepting)
        success = await manager.connect(
            websocket=websocket,
            client_id=account_id
        )

        if not success:
            await websocket.close(code=4000)
            return

        # Message loop
        try:
            while True:
                data = await websocket.receive_json()
                if data.get('type') == 'heartbeat':
                    await manager.update_heartbeat(account_id)
                    await websocket.send_json({
                        "type": "heartbeat_ack",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                else:
                    await websocket.send_json({
                        "type": "echo",
                        "data": data,
                        "timestamp": datetime.utcnow().isoformat()
                    })

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected normally: {account_id}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected during setup: {account_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        await manager.disconnect(account_id)
        logger.info(f"Cleaned up WebSocket connection for account {account_id}")

async def get_account_data(account_id: str, db: Session) -> Optional[Dict[str, Any]]:
    """Get latest account data with positions and balances"""
    try:
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.is_active == True
        ).first()

        if not account:
            return None

        # Get broker instance
        broker = BaseBroker.get_broker_instance(account.broker_id, db)
        
        # Fetch latest account status
        status = await broker.get_account_status(account)
        positions = await broker.get_positions(account)

        return {
            "account_id": account_id,
            "status": status,
            "positions": positions,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting account data: {str(e)}")
        return None

async def monitor_connection_health(
    websocket: WebSocket,
    account_id: str,
    metrics: HeartbeatMetrics
) -> None:
    """Monitor overall connection health"""
    while True:
        try:
            await asyncio.sleep(WebSocketConfig.HEARTBEAT['CLEANUP_INTERVAL'] / 1000)
            
            if websocket.client_state == WebSocketState.DISCONNECTED:
                break
                
            health_metrics = metrics.get_metrics()
            if health_metrics['healthScore'] < 0.5:
                logger.warning(f"Poor connection health detected for account {account_id}: {health_metrics}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error monitoring connection health for account {account_id}: {str(e)}")
            await asyncio.sleep(5)  # Wait before retrying

@router.get("/health")
async def websocket_health():
    """Health check endpoint for WebSocket service"""
    try:
        return {
            "status": "healthy",
            "websocket_manager": websocket_manager.get_health_status(),
            "heartbeat_monitor": heartbeat_monitor.get_health_status(),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WebSocket service health check failed"
        )

async def get_account_data(account_id: str, db: Session) -> dict:
    """Get latest account data"""
    try:
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.is_active == True
        ).first()

        if account:
            return {
                "accountId": account.account_id,
                "balance": float(account.balance or 0),
                "totalPnL": float(account.total_pnl or 0),
                "dayPnL": float(account.today_pnl or 0),
                "openPositionsPnL": float(account.open_pnl or 0)
            }
        return None
    except Exception as e:
        logger.error(f"Error getting account data: {e}")
        return None

@router.get("/status/{account_id}")
async def get_connection_status(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get WebSocket connection status for an account"""
    try:
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == current_user.id
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
            
        active_connections = manager.get_connection_count(current_user.id)
        
        return {
            "account_id": account_id,
            "is_connected": active_connections > 0,
            "active_connections": active_connections,
            "account_status": {
                "is_active": account.is_active,
                "has_valid_credentials": account.credentials.is_valid if account.credentials else False
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting connection status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
# In app/api/v1/endpoints/websocket.py

@router.get("/test")  # Note: this will be accessible at /api/v1/ws/test
async def test_ws_auth(
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """Test endpoint to verify WebSocket authentication logic"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            return {
                "token_valid": False,
                "error": "User not found",
                "decoded_payload": payload
            }
        
        # Also check for any active broker accounts
        accounts = db.query(BrokerAccount).filter(
            BrokerAccount.user_id == user.id,
            BrokerAccount.is_active == True
        ).all()
        
        return {
            "token_valid": True,
            "user": user.email,
            "decoded_payload": payload,
            "accounts": [
                {
                    "account_id": acc.account_id,
                    "broker_id": acc.broker_id,
                    "status": acc.status
                } for acc in accounts
            ]
        }
    except Exception as e:
        return {
            "token_valid": False,
            "error": str(e)
        }