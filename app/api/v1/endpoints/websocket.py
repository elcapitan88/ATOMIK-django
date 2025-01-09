from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import logging
from datetime import datetime
import json

from ....db.session import get_db
from ....core.security import get_current_user
from ....websockets.manager import websocket_manager
from ....models.user import User
from ....models.websocket import WebSocketConnection, MessageCategory

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/trade")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    broker: str = Query(default="tradovate"),
    environment: str = Query(default="demo"),
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for real-time trading updates"""
    try:
        # Authenticate user
        user = await get_current_user(db=db, token=token)
        if not user:
            await websocket.close(code=4001, reason="Authentication failed")
            return

        # Accept the WebSocket connection
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for user {user.id}")

        # Let the manager handle the connection and messaging
        await websocket_manager.handle_websocket(
            websocket=websocket,
            user=user,
            broker=broker,
            db=db
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user.id if user else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        try:
            await websocket.close(code=4000, reason=str(e))
        except:
            pass

async def process_message(
    websocket: WebSocket,
    user: User,
    message: Dict[str, Any],
    db: Session
) -> None:
    """Process incoming WebSocket messages"""
    try:
        message_type = message.get('type')

        if message_type == MessageCategory.MARKET_DATA:
            await handle_market_data_message(websocket, user, message)
        elif message_type == MessageCategory.ORDER_UPDATE:
            await handle_order_message(websocket, user, message, db)
        elif message_type == MessageCategory.HEARTBEAT:
            await handle_heartbeat(websocket)
        else:
            await websocket.send_json({
                'type': MessageCategory.ERROR,
                'message': f'Unsupported message type: {message_type}',
                'timestamp': datetime.utcnow().isoformat()
            })

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        await websocket.send_json({
            'type': MessageCategory.ERROR,
            'message': 'Internal server error',
            'timestamp': datetime.utcnow().isoformat()
        })

async def handle_market_data_message(
    websocket: WebSocket,
    user: User,
    message: Dict[str, Any]
) -> None:
    """Handle market data subscription messages"""
    action = message.get('action')
    symbols = message.get('symbols', [])

    if not symbols:
        await websocket.send_json({
            'type': MessageCategory.ERROR,
            'message': 'No symbols provided',
            'timestamp': datetime.utcnow().isoformat()
        })
        return

    if action == 'subscribe':
        # Validate symbols
        valid_symbols = [s for s in symbols if is_valid_symbol(s)]
        if valid_symbols:
            await websocket_manager.subscribe(user.id, valid_symbols)
            await websocket.send_json({
                'type': 'subscription_success',
                'symbols': valid_symbols,
                'timestamp': datetime.utcnow().isoformat()
            })
    elif action == 'unsubscribe':
        await websocket_manager.unsubscribe(user.id, symbols)
        await websocket.send_json({
            'type': 'unsubscription_success',
            'symbols': symbols,
            'timestamp': datetime.utcnow().isoformat()
        })

async def handle_order_message(
    websocket: WebSocket,
    user: User,
    message: Dict[str, Any],
    db: Session
) -> None:
    """Handle order-related messages"""
    order_data = validate_order_request(message)
    if not order_data:
        await websocket.send_json({
            'type': MessageCategory.ERROR,
            'message': 'Invalid order request',
            'timestamp': datetime.utcnow().isoformat()
        })
        return

    # Process order through broker (placeholder)
    response = {
        'type': MessageCategory.ORDER_UPDATE,
        'order_id': str(datetime.utcnow().timestamp()),
        'status': 'received',
        'timestamp': datetime.utcnow().isoformat()
    }
    await websocket.send_json(response)

async def handle_heartbeat(websocket: WebSocket) -> None:
    """Handle heartbeat messages"""
    await websocket.send_json({
        'type': MessageCategory.HEARTBEAT,
        'timestamp': datetime.utcnow().isoformat()
    })

def validate_order_request(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate order request data"""
    required_fields = {'symbol', 'action', 'quantity'}
    if not all(field in message for field in required_fields):
        return None

    if not is_valid_symbol(message['symbol']):
        return None

    if message['action'] not in {'BUY', 'SELL'}:
        return None

    try:
        quantity = float(message['quantity'])
        if quantity <= 0:
            return None
    except (ValueError, TypeError):
        return None

    return {
        'symbol': message['symbol'].upper(),
        'action': message['action'],
        'quantity': quantity,
        'order_type': message.get('order_type', 'MARKET'),
        'price': message.get('price'),
        'stop_price': message.get('stop_price')
    }

def is_valid_symbol(symbol: str) -> bool:
    """Validate trading symbol"""
    if not symbol:
        return False
    
    valid_symbols = {'ES', 'NQ', 'CL', 'GC', 'SI', 'ZB', 'RTY', 'YM'}
    return symbol.upper() in valid_symbols

@router.get("/connections")
async def get_active_connections(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get active WebSocket connections for the current user"""
    try:
        connections = db.query(WebSocketConnection).filter(
            WebSocketConnection.user_id == current_user.id,
            WebSocketConnection.is_active == True
        ).all()

        return {
            "active_connections": [
                {
                    "client_id": conn.client_id,
                    "broker": conn.broker,
                    "environment": conn.environment,
                    "connected_at": conn.connected_at.isoformat(),
                    "last_heartbeat": conn.last_heartbeat.isoformat() if conn.last_heartbeat else None
                }
                for conn in connections
            ],
            "total_connections": len(connections)
        }
    except Exception as e:
        logger.error(f"Error getting connections: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve connections"
        )