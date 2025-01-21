# Standard library imports
from datetime import datetime
import asyncio
import logging
import json
import uuid
from starlette.websockets import WebSocketState
from typing import Dict, Optional, Set, Any, Union

# FastAPI imports
from fastapi import (
    APIRouter, 
    WebSocket, 
    WebSocketDisconnect, 
    Depends, 
    Query, 
    HTTPException,
    status
)
from sqlalchemy.orm import Session
from jose import jwt, JWTError

# Local imports
from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.broker import BrokerAccount
from app.core.config import settings
from app.websockets.manager import websocket_manager
from app.websockets.heartbeat_monitor import heartbeat_monitor
from app.websockets.metrics import HeartbeatMetrics
from ....websockets.websocket_config import WebSocketConfig 


logger = logging.getLogger(__name__)
router = APIRouter()


# Store active connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Dict[str, WebSocket]] = {}
        self.connection_details: Dict[str, Dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket, connection_id: str, user_id: int, account_id: str) -> bool:
        """Store a websocket connection"""
        try:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = {}
                
            self.active_connections[user_id][connection_id] = websocket
            self.connection_details[connection_id] = {
                "user_id": user_id,
                "account_id": account_id,
                "connected_at": datetime.utcnow(),
                "last_heartbeat": datetime.utcnow()
            }
            
            logger.info(f"New connection stored: {connection_id}")
            return True
        except Exception as e:
            logger.error(f"Error storing connection: {str(e)}")
            return False

    async def disconnect(self, connection_id: str):
        """Remove a websocket connection"""
        try:
            if connection_id in self.connection_details:
                user_id = self.connection_details[connection_id]["user_id"]
                
                # Close WebSocket if it exists
                if user_id in self.active_connections and connection_id in self.active_connections[user_id]:
                    ws = self.active_connections[user_id][connection_id]
                    if ws:
                        await ws.close()
                    
                    # Clean up connections
                    self.active_connections[user_id].pop(connection_id, None)
                    if not self.active_connections[user_id]:
                        self.active_connections.pop(user_id, None)
                
                # Remove connection details
                self.connection_details.pop(connection_id, None)
                logger.info(f"Connection removed: {connection_id}")
        except Exception as e:
            logger.error(f"Error during disconnect: {str(e)}")

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
    

@router.websocket("/tradovate/{account_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    account_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for real-time trading data"""
    # Initialize resources
    metrics = HeartbeatMetrics()
    cleanup_tasks: Set[asyncio.Task] = set()
    heartbeat_task = None
    monitoring_task = None

    logger.info(f"WebSocket connection request for account {account_id}")

    try:
        # Token validation and authentication
        user = await validate_ws_token(token, db)
        if not user:
            logger.error(f"WebSocket authentication failed for account {account_id}")
            await websocket.close(code=4001)
            return

        # Verify account ownership
        account = db.query(BrokerAccount).filter(
            BrokerAccount.account_id == account_id,
            BrokerAccount.user_id == user.id,
            BrokerAccount.is_active == True
        ).first()

        if not account:
            logger.error(f"Account verification failed: {account_id}")
            await websocket.close(code=4003)
            return

        # Accept connection
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for account {account_id}")

        # Initialize WebSocket manager connection
        success = await websocket_manager.connect(websocket, account_id, user.id)
        if not success:
            raise Exception(f"Failed to initialize connection manager for account {account_id}")

        # Start monitoring tasks
        heartbeat_task = asyncio.create_task(
            heartbeat_monitor.start_monitoring(websocket, account_id, metrics)
        )
        cleanup_tasks.add(heartbeat_task)
        logger.info(f"Started heartbeat monitoring for account {account_id}")

        # Start connection monitoring
        monitoring_task = asyncio.create_task(
            monitor_connection_health(websocket, account_id, metrics)
        )
        cleanup_tasks.add(monitoring_task)

        try:
            # Main message loop
            while True:
                try:
                    message = await websocket.receive_json()
                    logger.debug(f"Received message: {message}") 
                    
                    # Handle heartbeat acknowledgments
                    if message.get('type') == 'heartbeat_ack':
                        logger.info(f"Routing heartbeat ack to monitor: {message}")
                        await heartbeat_monitor.process_heartbeat_ack(account_id, message)
                        continue

                    # Process other messages
                    await websocket_manager.handle_message(account_id, message)

                except WebSocketDisconnect:
                    logger.info(f"Client disconnected: {account_id}")
                    break
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")
                    if websocket.client_state != WebSocketState.DISCONNECTED:
                        await websocket.send_json({
                            "type": "error",
                            "message": str(e)
                        })

        except Exception as e:
            logger.error(f"Error in message loop: {str(e)}")
            raise

    except Exception as e:
        logger.error(f"WebSocket error for account {account_id}: {str(e)}")
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close(code=4000)

    finally:
        logger.info(f"Cleaning up connection for account {account_id}")
        
        # Cancel all cleanup tasks
        for task in cleanup_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Stop heartbeat monitoring
        if heartbeat_task and not heartbeat_task.done():
            await heartbeat_monitor.stop_monitoring(account_id)
            logger.info(f"Stopped heartbeat monitoring for account {account_id}")

        # Stop other monitoring
        if monitoring_task and not monitoring_task.done():
            monitoring_task.cancel()
            try:
                await monitoring_task
            except asyncio.CancelledError:
                pass

        # Disconnect from manager
        await websocket_manager.disconnect(account_id)

        # Log final statistics
        duration = (datetime.utcnow() - metrics.lastHeartbeat).total_seconds() if metrics.lastHeartbeat else 0
        logger.info(
            f"Connection statistics for {account_id}: "
            f"Duration={duration:.1f}s, "
            f"Messages={metrics.totalHeartbeats}, "
            f"Heartbeats={metrics.totalHeartbeats}"
        )
        
        logger.info(f"Cleaned up WebSocket connection for account {account_id}")

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