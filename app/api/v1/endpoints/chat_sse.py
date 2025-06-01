# app/api/v1/endpoints/chat_sse.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
import asyncio
import json
from typing import Dict, Set
from datetime import datetime

from app.db.session import get_db
from app.core.security import get_current_user, get_current_user_from_query
from app.models.user import User
from app.models.chat import ChatMessage, ChatReaction, UserChatRole
from app.schemas.chat import ChatEventData

router = APIRouter()

# Global storage for active SSE connections
# In production, consider using Redis for scalability
active_connections: Dict[int, Set[asyncio.Queue]] = {}


class ChatEventManager:
    def __init__(self):
        self.connections: Dict[int, Set[asyncio.Queue]] = {}
    
    async def connect(self, user_id: int) -> asyncio.Queue:
        """Add a new SSE connection for a user"""
        queue = asyncio.Queue()
        
        if user_id not in self.connections:
            self.connections[user_id] = set()
        
        self.connections[user_id].add(queue)
        return queue
    
    async def disconnect(self, user_id: int, queue: asyncio.Queue):
        """Remove an SSE connection for a user"""
        if user_id in self.connections:
            self.connections[user_id].discard(queue)
            if not self.connections[user_id]:
                del self.connections[user_id]
    
    async def broadcast_to_channel(self, channel_id: int, event_type: str, data: dict, db: Session):
        """Broadcast an event to all users who have access to a channel"""
        # For now, broadcast to all connected users
        # TODO: Implement proper channel membership checking
        event = {
            "type": event_type,
            "channel_id": channel_id,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        print(f"🔍 SSE: Broadcasting {event_type} to channel {channel_id}")
        print(f"🔍 SSE: Connected users: {list(self.connections.keys())}")
        print(f"🔍 SSE: Message sender: {data.get('user_id', 'unknown')}")
        
        broadcast_count = 0
        for user_id, queues in self.connections.items():
            for queue in queues.copy():  # Copy to avoid modification during iteration
                try:
                    await queue.put(event)
                    print(f"🔍 SSE: Broadcasting event to user {user_id}: {event_type}")
                    broadcast_count += 1
                except Exception as e:
                    print(f"❌ SSE: Failed to broadcast to user {user_id}: {str(e)}")
                    # Remove broken connections
                    queues.discard(queue)
        
        print(f"🔍 SSE: Broadcast complete - sent to {broadcast_count} connections")
    
    async def broadcast_to_user(self, user_id: int, event_type: str, data: dict):
        """Send an event to a specific user"""
        if user_id in self.connections:
            event = {
                "type": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            for queue in self.connections[user_id].copy():
                try:
                    await queue.put(event)
                except Exception as e:
                    # Remove broken connections
                    self.connections[user_id].discard(queue)


# Global event manager instance
chat_event_manager = ChatEventManager()


@router.get("/events")
async def chat_events_stream(
    request: Request,
    current_user: User = Depends(get_current_user_from_query),
    db: Session = Depends(get_db)
):
    """
    Server-Sent Events endpoint for real-time chat updates
    
    Authentication: Uses query parameter token instead of Authorization header
    Usage: GET /api/v1/chat/events?token=your_jwt_token_here
    
    This endpoint requires authentication via query parameter because browsers
    don't support custom headers for EventSource connections.
    """
    print(f"🔍 SSE: Connection request received from user {current_user.id} ({current_user.email})")
    print(f"🔍 SSE: Request headers: {dict(request.headers)}")
    print(f"🔍 SSE: Client info: {request.client}")
    
    async def event_generator():
        print(f"🔍 SSE: Starting event generator for user {current_user.id}")
        
        # Connect user to the event manager
        queue = await chat_event_manager.connect(current_user.id)
        print(f"🔍 SSE: User {current_user.id} connected to event manager")
        
        # Send initial connection confirmation
        initial_event = {
            "type": "connection_established", 
            "user_id": current_user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        yield f"data: {json.dumps(initial_event)}\n\n"
        print(f"🔍 SSE: Sent initial connection event to user {current_user.id}")
        
        try:
            while True:
                # Check if client is still connected
                if await request.is_disconnected():
                    print(f"🔍 SSE: Client {current_user.id} disconnected")
                    break
                
                try:
                    # Wait for events with a timeout to allow periodic connection checks
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    print(f"🔍 SSE: Broadcasting event to user {current_user.id}: {event.get('type', 'unknown')}")
                    
                    # Format as SSE
                    yield f"data: {json.dumps(event)}\n\n"
                    
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    ping_event = {'type': 'ping', 'timestamp': datetime.utcnow().isoformat()}
                    yield f"data: {json.dumps(ping_event)}\n\n"
                    print(f"🔍 SSE: Sent keepalive ping to user {current_user.id}")
                
        except asyncio.CancelledError:
            print(f"🔍 SSE: Connection cancelled for user {current_user.id}")
        except Exception as e:
            print(f"❌ SSE: Error in event generator for user {current_user.id}: {str(e)}")
        finally:
            # Clean up connection
            await chat_event_manager.disconnect(current_user.id, queue)
            print(f"🔍 SSE: Cleaned up connection for user {current_user.id}")
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
            "X-Accel-Buffering": "no",  # Disable proxy buffering
        }
    )


# Event broadcasting functions (to be called by other endpoints)
async def broadcast_new_message(message: ChatMessage, user_name: str, user_role_color: str, user_profile_picture: str, db: Session):
    """Broadcast a new message event"""
    data = {
        "id": message.id,
        "channel_id": message.channel_id,
        "user_id": message.user_id,
        "user_name": user_name,
        "user_role_color": user_role_color,
        "user_profile_picture": user_profile_picture,
        "content": message.content,
        "reply_to_id": message.reply_to_id,
        "created_at": message.created_at.isoformat(),
        "is_edited": False,
        "reactions": []
    }
    
    await chat_event_manager.broadcast_to_channel(
        message.channel_id, 
        "new_message", 
        data, 
        db
    )


async def broadcast_message_updated(message: ChatMessage, user_name: str, user_role_color: str, user_profile_picture: str, db: Session):
    """Broadcast a message edit event"""
    data = {
        "id": message.id,
        "channel_id": message.channel_id,
        "user_id": message.user_id,
        "user_name": user_name,
        "user_role_color": user_role_color,
        "user_profile_picture": user_profile_picture,
        "content": message.content,
        "reply_to_id": message.reply_to_id,
        "created_at": message.created_at.isoformat(),
        "is_edited": message.is_edited,
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "reactions": []
    }
    
    await chat_event_manager.broadcast_to_channel(
        message.channel_id, 
        "message_updated", 
        data, 
        db
    )


async def broadcast_message_deleted(message_id: int, channel_id: int, db: Session):
    """Broadcast a message deletion event"""
    data = {
        "id": message_id,
        "channel_id": channel_id
    }
    
    await chat_event_manager.broadcast_to_channel(
        channel_id, 
        "message_deleted", 
        data, 
        db
    )


async def broadcast_reaction_added(reaction: ChatReaction, user_name: str, db: Session):
    """Broadcast a reaction added event"""
    data = {
        "message_id": reaction.message_id,
        "user_id": reaction.user_id,
        "user_name": user_name,
        "emoji": reaction.emoji,
        "created_at": reaction.created_at.isoformat()
    }
    
    # Get the message to know which channel to broadcast to
    message = db.query(ChatMessage).filter(ChatMessage.id == reaction.message_id).first()
    if message:
        await chat_event_manager.broadcast_to_channel(
            message.channel_id, 
            "reaction_added", 
            data, 
            db
        )


async def broadcast_reaction_removed(message_id: int, user_id: int, emoji: str, user_name: str, db: Session):
    """Broadcast a reaction removed event"""
    data = {
        "message_id": message_id,
        "user_id": user_id,
        "user_name": user_name,
        "emoji": emoji
    }
    
    # Get the message to know which channel to broadcast to
    message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if message:
        await chat_event_manager.broadcast_to_channel(
            message.channel_id, 
            "reaction_removed", 
            data, 
            db
        )


# Test endpoint for debugging SSE
@router.post("/test-broadcast")
async def test_broadcast(
    message: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Test endpoint to trigger a broadcast event for debugging"""
    test_event = {
        "type": "test_message",
        "data": {
            "message": message,
            "sender": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        }
    }
    
    print(f"🔍 SSE: Manual test broadcast triggered by {current_user.email}: {message}")
    
    # Broadcast to all connected users
    for user_id, queues in chat_event_manager.connections.items():
        for queue in queues.copy():
            try:
                await queue.put(test_event)
                print(f"🔍 SSE: Test event sent to user {user_id}")
            except Exception as e:
                print(f"❌ SSE: Failed to send test event to user {user_id}: {str(e)}")
                queues.discard(queue)
    
    return {
        "message": "Test broadcast sent",
        "connected_users": len(chat_event_manager.connections),
        "total_connections": sum(len(queues) for queues in chat_event_manager.connections.values())
    }


# Export the event manager for use in other modules
__all__ = ["chat_event_manager", "broadcast_new_message", "broadcast_message_updated", 
           "broadcast_message_deleted", "broadcast_reaction_added", "broadcast_reaction_removed"]