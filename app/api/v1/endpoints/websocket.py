from fastapi import APIRouter, WebSocket, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from datetime import datetime
import logging
import json
import asyncio
from typing import Optional, Dict, Any, List

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState
from app.models.broker import BrokerAccount
from app.websockets.manager import websocket_manager
from app.websockets.heartbeat_monitor import heartbeat_monitor
from app.websockets.metrics import HeartbeatMetrics
from app.websockets.types.messages import (
    WSMessageType, 
    WSSyncRequest, 
    WSAccountState, 
    WSSubscriptionRequest,
    WSErrorMessage,
    ErrorCode,
    SubscriptionAction,
    parse_ws_message
)

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

async def handle_sync_request(
    websocket: WebSocket,
    message: WSSyncRequest,
    account: BrokerAccount
) -> None:
    """Handle account sync request"""
    try:
        # Validate endpoints requested
        valid_endpoints = {'user', 'account', 'position', 'order'}
        requested_endpoints = set(message.endpoints)
        
        if not requested_endpoints.issubset(valid_endpoints):
            invalid_endpoints = requested_endpoints - valid_endpoints
            error_msg = f"Invalid endpoints requested: {invalid_endpoints}"
            await websocket.send_json(
                WSErrorMessage(
                    code=ErrorCode.INVALID_MESSAGE,
                    message=error_msg
                ).dict()
            )
            return

        # Initialize account state
        account_state = await websocket_manager.get_account_state(account.account_id)
        if account_state:
            await websocket.send_json(account_state.dict())
        else:
            await websocket.send_json(
                WSErrorMessage(
                    code=ErrorCode.SYNC_FAILED,
                    message="Failed to get account state"
                ).dict()
            )

    except Exception as e:
        logger.error(f"Error handling sync request: {str(e)}")
        await websocket.send_json(
            WSErrorMessage(
                code=ErrorCode.SYNC_FAILED,
                message="Internal error during sync"
            ).dict()
        )

async def handle_subscription_request(
    websocket: WebSocket,
    message: WSSubscriptionRequest,
    account: BrokerAccount
) -> None:
    """Handle subscription request"""
    try:
        if message.action == SubscriptionAction.SUBSCRIBE:
            # Subscribe to requested endpoints
            success = await websocket_manager.subscribe_account(
                account.account_id,
                message.endpoints
            )
            if success:
                await websocket.send_json({
                    "type": WSMessageType.SUBSCRIPTION,
                    "success": True,
                    "account_id": account.account_id,
                    "endpoints": message.endpoints
                })
            else:
                await websocket.send_json(
                    WSErrorMessage(
                        code=ErrorCode.SUBSCRIPTION_FAILED,
                        message="Failed to subscribe to endpoints"
                    ).dict()
                )
                
        elif message.action == SubscriptionAction.UNSUBSCRIBE:
            # Unsubscribe from endpoints
            await websocket_manager.unsubscribe_account(
                account.account_id,
                message.endpoints
            )
            await websocket.send_json({
                "type": WSMessageType.SUBSCRIPTION,
                "success": True,
                "account_id": account.account_id,
                "endpoints": message.endpoints
            })

    except Exception as e:
        logger.error(f"Error handling subscription request: {str(e)}")
        await websocket.send_json(
            WSErrorMessage(
                code=ErrorCode.SUBSCRIPTION_FAILED,
                message="Internal error during subscription"
            ).dict()
        )

#@router.websocket("/tradovate/{account_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    account_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for trading accounts"""
    metrics = HeartbeatMetrics()
    
    try:
        # Validate token and get user
        user = await validate_ws_token(token, db)
        if not user:
            logger.warning(f"Invalid token for WebSocket connection: {account_id}")
            await websocket.close(code=4001)
            return

        # Verify account access
        account = await verify_account_access(user.id, account_id, db)
        if not account:
            logger.warning(f"Invalid account access: {account_id} for user {user.id}")
            await websocket.close(code=4003)
            return

        # Accept connection and initialize monitoring
        await websocket.accept()
        await websocket_manager.connect(websocket, account_id, user.id)
        await heartbeat_monitor.start_monitoring(websocket, account_id, metrics)
        
        logger.info(f"WebSocket connection established for account {account_id}")

        try:
            while True:
                try:
                    # Receive message with timeout
                    data = await websocket.receive_text()
                    
                    # Handle heartbeat message
                    if data == '[]':
                        await heartbeat_monitor.process_heartbeat(account_id)
                        continue

                    # Log raw message received
                    logger.info(f"Raw message received for account {account_id}: {data}")

                    # Process non-heartbeat messages
                    try:
                        message_data = json.loads(data)
                        logger.info(f"Parsed JSON for account {account_id}: {message_data}")
                        
                        # Check message type before parsing
                        message_type = message_data.get('type')
                        logger.info(f"Processing message type: {message_type}")

                        # Parse and process message
                        try:
                            message = parse_ws_message(message_data)
                            logger.info(f"Successfully parsed message of type: {message.type}")

                            # Handle sync request
                            if isinstance(message, WSSyncRequest):
                                logger.info(f"Processing sync request for account {account_id}")
                                await handle_sync_request(websocket, message, account)
                            
                            # Handle subscription request
                            elif isinstance(message, WSSubscriptionRequest):
                                logger.info(f"Processing subscription request for account {account_id}")
                                await handle_subscription_request(websocket, message, account)
                            
                            # Handle other messages
                            else:
                                logger.info(f"Processing message via manager for account {account_id}")
                                await websocket_manager.process_message(account_id, message_data)

                        except ValueError as parse_error:
                            logger.error(f"Message parsing error for {account_id}: {str(parse_error)}")
                            error_msg = WSErrorMessage(
                                code=ErrorCode.INVALID_MESSAGE,
                                message=f"Invalid message format: {str(parse_error)}"
                            )
                            await websocket.send_json(error_msg.dict())
                            continue

                    except json.JSONDecodeError as json_error:
                        logger.error(f"Invalid JSON received from {account_id}: {data}")
                        error_msg = WSErrorMessage(
                            code=ErrorCode.INVALID_MESSAGE,
                            message="Invalid JSON format"
                        )
                        await websocket.send_json(error_msg.dict())
                        continue

                except WebSocketDisconnect:
                    logger.info(f"Client disconnected normally: {account_id}")
                    break
                except Exception as e:
                    logger.error(f"Error receiving message from {account_id}: {str(e)}")
                    break

        finally:
            # Cleanup on connection end
            await websocket_manager.disconnect(account_id)
            await heartbeat_monitor.stop_monitoring(account_id)
            logger.info(f"WebSocket connection closed for account {account_id}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected normally: {account_id}")
        
    except Exception as e:
        logger.error(f"WebSocket error for {account_id}: {str(e)}")
        error_details = await handle_websocket_error(e, websocket, account_id)
        logger.error(f"Error details: {error_details}")
        
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=4000)
    
    finally:
        # Ensure everything is cleaned up
        try:
            await websocket_manager.disconnect(account_id)
            await heartbeat_monitor.stop_monitoring(account_id)
        except Exception as cleanup_error:
            logger.error(f"Error during cleanup for {account_id}: {str(cleanup_error)}")



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