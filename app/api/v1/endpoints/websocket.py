# app/api/v1/endpoints/websocket.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Optional, List
import logging
import json
from datetime import datetime
from jose import jwt, JWTError

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.broker import BrokerAccount
from app.models.websocket import WebSocketConnection
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Store active connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict] = {}
        self.connection_details: Dict[str, Dict] = {}

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
    connection_id = None
    
    try:
        logger.info(f"WebSocket connection attempt for account: {account_id}")
        logger.info(f"Received token (first 50 chars): {token[:50]}...")

        # Token validation and user lookup
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            if not email:
                logger.error("Invalid token: no email claim")
                await websocket.close(code=4001)
                return

            user = db.query(User).filter(User.email == email).first()
            if not user:
                logger.error(f"User not found for email: {email}")
                await websocket.close(code=4001)
                return

            # Verify account
            account = db.query(BrokerAccount).filter(
                BrokerAccount.account_id == account_id,
                BrokerAccount.user_id == user.id,
                BrokerAccount.is_active == True
            ).first()

            if not account:
                logger.error(f"Account verification failed for {account_id}")
                await websocket.close(code=4003)
                return

            # Accept connection
            await websocket.accept()
            logger.info(f"WebSocket connection accepted for account {account_id}")

            # Generate connection ID and store connection
            connection_id = f"{user.id}:{account_id}:{datetime.utcnow().timestamp()}"
            success = await manager.connect(
                websocket=websocket,
                connection_id=connection_id,
                user_id=user.id,
                account_id=account_id
            )

            if not success:
                logger.error("Failed to store connection")
                await websocket.close(code=4000)
                return

            # Main message loop
            while True:
                message = await websocket.receive_json()
                logger.info(f"Received message for account {account_id}: {message}")
                
                if message.get('type') == 'heartbeat':
                    logger.info(f"Processing heartbeat for account {account_id}")
                    await manager.update_heartbeat(connection_id)
                    await websocket.send_json({
                        'type': 'heartbeat',
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    logger.info(f"Sent heartbeat response to account {account_id}") 
                    continue

                # Process other messages here
                logger.info(f"Received message: {message}")

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for account {account_id}")
            if connection_id:
                await manager.disconnect(connection_id)
        except JWTError as e:
            logger.error(f"Token validation failed: {str(e)}")
            await websocket.close(code=4001)
            return
            
    except Exception as e:
        logger.error(f"Unexpected WebSocket error: {str(e)}")
        if connection_id:
            await manager.disconnect(connection_id)
        try:
            await websocket.close(code=4000)
        except:
            pass

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