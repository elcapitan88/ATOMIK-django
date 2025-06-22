"""
Application WebSocket Endpoint

⚠️ IMPORTANT: This is for APPLICATION WebSocket (chat, notifications, UI events)
NOT for trading data! Trading WebSocket is in /Websocket-Proxy/

Handles:
- Chat messages
- Emoji reactions  
- Typing indicators
- System notifications
- UI events
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from sqlalchemy.orm import Session

from app.websocket.auth import get_current_user_websocket, get_user_chat_channels
from app.websocket.manager import app_websocket_manager
from app.db.base import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/{user_id}")
async def application_websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(..., description="JWT authentication token")
):
    """
    Application WebSocket endpoint for real-time communication.
    
    Handles:
    - Chat messages (send/receive)
    - Emoji reactions (add/remove)
    - Typing indicators
    - System notifications
    - Connection management
    
    URL: /api/v1/chat/ws/{user_id}?token={jwt_token}
    
    Args:
        websocket: FastAPI WebSocket connection
        user_id: User's unique identifier (must match token)
        token: JWT authentication token
    """
    current_user = None
    
    try:
        # Authenticate user
        current_user = await get_current_user_websocket(token)
        
        if not current_user or str(current_user.id) != user_id:
            logger.warning(f"🔒 WebSocket auth failed: Token user mismatch for {user_id}")
            await websocket.close(code=4001, reason="Unauthorized")
            return
        
        # Get user's chat channels
        user_channels = await get_user_chat_channels(current_user)
        
        # Connect to Application WebSocket Manager
        success = await app_websocket_manager.connect(
            websocket=websocket,
            user_id=str(current_user.id),
            user_channels=user_channels
        )
        
        if not success:
            logger.error(f"❌ Failed to connect user {user_id} to WebSocket manager")
            await websocket.close(code=4000, reason="Connection failed")
            return
        
        logger.info(f"🔗 User {current_user.email} connected to Application WebSocket")
        
        # Main message loop
        while True:
            try:
                # Receive message from client
                data = await websocket.receive_text()
                message_data = json.loads(data)
                
                # Handle the message
                await handle_application_websocket_message(
                    message_data=message_data,
                    user=current_user,
                    websocket=websocket
                )
                
            except WebSocketDisconnect:
                logger.info(f"🔌 User {current_user.email} disconnected from WebSocket")
                break
                
            except json.JSONDecodeError:
                logger.warning(f"📨 Invalid JSON from user {user_id}")
                await app_websocket_manager.send_to_user(str(current_user.id), {
                    "type": "error",
                    "message": "Invalid message format",
                    "timestamp": datetime.utcnow().isoformat()
                })
                
            except Exception as e:
                logger.error(f"❌ Error handling WebSocket message from {user_id}: {e}")
                await app_websocket_manager.send_to_user(str(current_user.id), {
                    "type": "error", 
                    "message": "Message processing failed",
                    "timestamp": datetime.utcnow().isoformat()
                })
    
    except Exception as e:
        logger.error(f"❌ WebSocket connection error for user {user_id}: {e}")
        if websocket.application_state.CONNECTED:
            await websocket.close(code=4000, reason="Connection error")
    
    finally:
        # Clean up connection
        if current_user:
            await app_websocket_manager.disconnect(
                str(current_user.id), 
                "WebSocket endpoint cleanup"
            )


async def handle_application_websocket_message(
    message_data: Dict[str, Any],
    user: User,
    websocket: WebSocket
) -> None:
    """
    Handle incoming WebSocket messages from clients.
    
    Message Types:
    - send_message: Send a chat message
    - add_reaction: Add emoji reaction to message
    - remove_reaction: Remove emoji reaction
    - typing: Send typing indicator
    - ping: Connection health check
    
    Args:
        message_data: Parsed JSON message from client
        user: Authenticated user
        websocket: WebSocket connection
    """
    message_type = message_data.get("type")
    user_id = str(user.id)
    
    try:
        if message_type == "send_message":
            await handle_send_message(message_data, user)
            
        elif message_type == "add_reaction":
            await handle_add_reaction(message_data, user)
            
        elif message_type == "remove_reaction":
            await handle_remove_reaction(message_data, user)
            
        elif message_type == "typing":
            await handle_typing_indicator(message_data, user)
            
        elif message_type == "ping":
            await app_websocket_manager.handle_ping(user_id)
            
        elif message_type == "subscribe_channel":
            await handle_channel_subscription(message_data, user)
            
        elif message_type == "unsubscribe_channel":
            await handle_channel_unsubscription(message_data, user)
            
        else:
            logger.warning(f"📨 Unknown message type '{message_type}' from user {user_id}")
            await app_websocket_manager.send_to_user(user_id, {
                "type": "error",
                "message": f"Unknown message type: {message_type}",
                "timestamp": datetime.utcnow().isoformat()
            })
            
    except Exception as e:
        logger.error(f"❌ Error handling {message_type} from user {user_id}: {e}")
        await app_websocket_manager.send_to_user(user_id, {
            "type": "error",
            "message": f"Failed to process {message_type}",
            "timestamp": datetime.utcnow().isoformat()
        })


async def handle_send_message(message_data: Dict[str, Any], user: User) -> None:
    """
    Handle sending a chat message via WebSocket.
    
    Args:
        message_data: Message data from client
        user: Authenticated user
    """
    try:
        channel_id = message_data.get("channel_id")
        content = message_data.get("content")
        reply_to_id = message_data.get("reply_to_id")
        
        if not channel_id or not content:
            raise ValueError("Missing channel_id or content")
        
        # TODO: For full implementation, add chat message database models and CRUD operations
        # For now, we'll just broadcast the message for real-time communication
        
        # Generate a temporary message ID (in future, this would come from database)
        message_id = f"msg_{datetime.utcnow().timestamp()}"
        
        # Prepare message for broadcast
        broadcast_message = {
            "type": "new_message",
            "data": {
                "id": message_id,
                "channel_id": channel_id,
                "user_id": str(user.id),
                "username": user.username or user.email,
                "content": content.strip(),
                "created_at": datetime.utcnow().isoformat(),
                "reply_to_id": reply_to_id,
                "is_edited": False,
                "reactions": []
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Broadcast to channel
        await app_websocket_manager.broadcast_to_channel(
            channel_id=channel_id,
            message=broadcast_message
        )
        
        logger.debug(f"💬 Message sent by {user.email} to channel {channel_id}")
            
    except Exception as e:
        logger.error(f"❌ Error sending message: {e}")
        await app_websocket_manager.send_to_user(str(user.id), {
            "type": "message_error",
            "message": "Failed to send message",
            "timestamp": datetime.utcnow().isoformat()
        })


async def handle_add_reaction(message_data: Dict[str, Any], user: User) -> None:
    """
    Handle adding an emoji reaction via WebSocket.
    
    Args:
        message_data: Reaction data from client
        user: Authenticated user
    """
    try:
        message_id = message_data.get("message_id")
        emoji = message_data.get("emoji")
        
        if not message_id or not emoji:
            raise ValueError("Missing message_id or emoji")
        
        # TODO: For full implementation, add reaction database models and CRUD operations
        # For now, we'll just broadcast the reaction for real-time communication
        
        # Prepare reaction for broadcast (assuming general channel for now)
        broadcast_message = {
            "type": "reaction_added",
            "data": {
                "message_id": str(message_id),
                "channel_id": "general",  # TODO: Get actual channel from message in database
                "emoji": emoji,
                "user_id": str(user.id),
                "username": user.username or user.email
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Broadcast to channel
        await app_websocket_manager.broadcast_to_channel(
            channel_id="general",
            message=broadcast_message
        )
        
        logger.debug(f"👍 Reaction {emoji} added by {user.email} to message {message_id}")
            
    except Exception as e:
        logger.error(f"❌ Error adding reaction: {e}")
        await app_websocket_manager.send_to_user(str(user.id), {
            "type": "reaction_error",
            "message": "Failed to add reaction", 
            "timestamp": datetime.utcnow().isoformat()
        })


async def handle_remove_reaction(message_data: Dict[str, Any], user: User) -> None:
    """
    Handle removing an emoji reaction via WebSocket.
    
    Args:
        message_data: Reaction data from client
        user: Authenticated user
    """
    try:
        message_id = message_data.get("message_id")
        emoji = message_data.get("emoji")
        
        if not message_id or not emoji:
            raise ValueError("Missing message_id or emoji")
        
        # TODO: For full implementation, add reaction database models and CRUD operations
        # For now, we'll just broadcast the reaction removal for real-time communication
        
        # Prepare removal for broadcast (assuming general channel for now)
        broadcast_message = {
            "type": "reaction_removed",
            "data": {
                "message_id": str(message_id),
                "channel_id": "general",  # TODO: Get actual channel from message in database
                "emoji": emoji,
                "user_id": str(user.id),
                "username": user.username or user.email
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Broadcast to channel
        await app_websocket_manager.broadcast_to_channel(
            channel_id="general",
            message=broadcast_message
        )
        
        logger.debug(f"👎 Reaction {emoji} removed by {user.email} from message {message_id}")
            
    except Exception as e:
        logger.error(f"❌ Error removing reaction: {e}")
        await app_websocket_manager.send_to_user(str(user.id), {
            "type": "reaction_error",
            "message": "Failed to remove reaction",
            "timestamp": datetime.utcnow().isoformat()
        })


async def handle_typing_indicator(message_data: Dict[str, Any], user: User) -> None:
    """
    Handle typing indicator via WebSocket.
    
    Args:
        message_data: Typing data from client
        user: Authenticated user
    """
    try:
        channel_id = message_data.get("channel_id")
        
        if not channel_id:
            raise ValueError("Missing channel_id")
        
        # Prepare typing indicator for broadcast
        broadcast_message = {
            "type": "user_typing",
            "data": {
                "channel_id": channel_id,
                "user_id": str(user.id),
                "username": user.username or user.email
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Broadcast to channel (exclude the typing user)
        await app_websocket_manager.broadcast_to_channel(
            channel_id=channel_id,
            message=broadcast_message,
            exclude_user=str(user.id)
        )
        
        logger.debug(f"⌨️ Typing indicator from {user.email} in channel {channel_id}")
        
    except Exception as e:
        logger.error(f"❌ Error handling typing indicator: {e}")


async def handle_channel_subscription(message_data: Dict[str, Any], user: User) -> None:
    """
    Handle channel subscription via WebSocket.
    
    Args:
        message_data: Subscription data from client
        user: Authenticated user
    """
    try:
        channel_id = message_data.get("channel_id")
        
        if not channel_id:
            raise ValueError("Missing channel_id")
        
        # Subscribe user to channel
        success = await app_websocket_manager.subscribe_to_channel(
            user_id=str(user.id),
            channel_id=channel_id
        )
        
        if success:
            await app_websocket_manager.send_to_user(str(user.id), {
                "type": "channel_subscribed",
                "data": {"channel_id": channel_id},
                "timestamp": datetime.utcnow().isoformat()
            })
            
            logger.debug(f"📡 User {user.email} subscribed to channel {channel_id}")
        
    except Exception as e:
        logger.error(f"❌ Error subscribing to channel: {e}")


async def handle_channel_unsubscription(message_data: Dict[str, Any], user: User) -> None:
    """
    Handle channel unsubscription via WebSocket.
    
    Args:
        message_data: Unsubscription data from client
        user: Authenticated user
    """
    try:
        channel_id = message_data.get("channel_id")
        
        if not channel_id:
            raise ValueError("Missing channel_id")
        
        # Unsubscribe user from channel
        success = await app_websocket_manager.unsubscribe_from_channel(
            user_id=str(user.id),
            channel_id=channel_id
        )
        
        if success:
            await app_websocket_manager.send_to_user(str(user.id), {
                "type": "channel_unsubscribed",
                "data": {"channel_id": channel_id},
                "timestamp": datetime.utcnow().isoformat()
            })
            
            logger.debug(f"📡 User {user.email} unsubscribed from channel {channel_id}")
        
    except Exception as e:
        logger.error(f"❌ Error unsubscribing from channel: {e}")


@router.get("/ws/stats")
async def get_websocket_stats():
    """
    Get current WebSocket connection statistics.
    
    Returns:
        Dict with connection stats
    """
    try:
        stats = app_websocket_manager.get_connection_stats()
        return {
            "status": "success",
            "data": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Error getting WebSocket stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")


@router.post("/ws/cleanup")
async def cleanup_stale_connections():
    """
    Manually trigger cleanup of stale WebSocket connections.
    
    Returns:
        Number of connections cleaned up
    """
    try:
        cleaned_up = await app_websocket_manager.cleanup_stale_connections()
        return {
            "status": "success",
            "message": f"Cleaned up {cleaned_up} stale connections",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Error cleaning up connections: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup connections")