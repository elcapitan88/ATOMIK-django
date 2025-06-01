# app/api/v1/endpoints/chat_sse.py
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
import asyncio
import json
from typing import Dict, Set, Any, List
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
        self.connection_metadata: Dict[int, Dict[str, Any]] = {}  # Track connection info
        self.last_heartbeat: Dict[int, datetime] = {}  # Track last activity
        self.message_queue: Dict[int, List[Dict[str, Any]]] = {}  # Queue messages for offline users
        self.max_queue_size = 50  # Maximum messages to queue per user
    
    async def connect(self, user_id: int, client_info: str = "unknown") -> asyncio.Queue:
        """Add a new SSE connection for a user"""
        queue = asyncio.Queue()
        connection_time = datetime.utcnow()
        
        if user_id not in self.connections:
            self.connections[user_id] = set()
            self.connection_metadata[user_id] = {}
            print(f"🔍 SSE: First connection for user {user_id}")
        
        self.connections[user_id].add(queue)
        self.connection_metadata[user_id][id(queue)] = {
            "connected_at": connection_time,
            "client_info": client_info,
            "message_count": 0
        }
        self.last_heartbeat[user_id] = connection_time
        
        print(f"🔍 SSE: New connection added for user {user_id}. Total connections: {len(self.connections[user_id])}")
        print(f"🔍 SSE: Global connection count: {sum(len(queues) for queues in self.connections.values())}")
        
        # Send any queued messages to the newly connected user
        await self._send_queued_messages(user_id, queue)
        
        return queue
    
    async def disconnect(self, user_id: int, queue: asyncio.Queue):
        """Remove an SSE connection for a user"""
        if user_id in self.connections:
            self.connections[user_id].discard(queue)
            
            # Clean up metadata
            if user_id in self.connection_metadata:
                queue_id = id(queue)
                if queue_id in self.connection_metadata[user_id]:
                    connection_info = self.connection_metadata[user_id][queue_id]
                    duration = datetime.utcnow() - connection_info["connected_at"]
                    print(f"🔍 SSE: Connection for user {user_id} lasted {duration.total_seconds():.1f}s, sent {connection_info['message_count']} messages")
                    del self.connection_metadata[user_id][queue_id]
            
            if not self.connections[user_id]:
                print(f"🔍 SSE: All connections removed for user {user_id}")
                del self.connections[user_id]
                if user_id in self.connection_metadata:
                    del self.connection_metadata[user_id]
                if user_id in self.last_heartbeat:
                    del self.last_heartbeat[user_id]
            else:
                print(f"🔍 SSE: Connection removed for user {user_id}. Remaining connections: {len(self.connections[user_id])}")
    
    async def _send_queued_messages(self, user_id: int, queue: asyncio.Queue):
        """Send any queued messages to a newly connected user"""
        if user_id in self.message_queue and self.message_queue[user_id]:
            queued_messages = self.message_queue[user_id].copy()
            print(f"🔍 SSE: Sending {len(queued_messages)} queued messages to user {user_id}")
            
            for message in queued_messages:
                try:
                    await asyncio.wait_for(queue.put(message), timeout=2.0)
                    print(f"✅ SSE: Sent queued message to user {user_id}: {message.get('type', 'unknown')}")
                except Exception as e:
                    print(f"❌ SSE: Failed to send queued message to user {user_id}: {str(e)}")
                    break
            
            # Clear the queue after successful delivery
            self.message_queue[user_id] = []
            print(f"🔍 SSE: Cleared message queue for user {user_id}")
    
    async def _queue_message_for_user(self, user_id: int, event: dict):
        """Queue a message for a user who is currently offline"""
        if user_id not in self.message_queue:
            self.message_queue[user_id] = []
        
        # Add to queue with size limit
        self.message_queue[user_id].append(event)
        if len(self.message_queue[user_id]) > self.max_queue_size:
            # Remove oldest message
            removed = self.message_queue[user_id].pop(0)
            print(f"🔄 SSE: Queue full for user {user_id}, removed oldest message: {removed.get('type', 'unknown')}")
        
        print(f"📬 SSE: Queued message for offline user {user_id}. Queue size: {len(self.message_queue[user_id])}")
    
    async def _get_channel_members(self, channel_id: int, db: Session) -> List[int]:
        """Get list of user IDs who should receive messages from this channel"""
        # For now, return all users with admin or beta_tester roles
        # TODO: Implement proper channel membership when that feature is added
        from app.models.user import User
        
        try:
            # Get all users with admin or beta_tester app_role
            users = db.query(User).filter(
                User.app_role.in_(['admin', 'beta_tester'])
            ).all()
            
            user_ids = [user.id for user in users]
            print(f"🔍 SSE: Found {len(user_ids)} potential channel members: {user_ids}")
            return user_ids
        except Exception as e:
            print(f"❌ SSE: Error getting channel members: {str(e)}")
            return []
    
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
        print(f"🔍 SSE: Total connections: {sum(len(queues) for queues in self.connections.values())}")
        print(f"🔍 SSE: Message sender: {data.get('user_id', 'unknown')}")
        
        # Log detailed connection info
        for user_id, queues in self.connections.items():
            last_hb = self.last_heartbeat.get(user_id, datetime.utcnow())
            time_since_hb = datetime.utcnow() - last_hb
            print(f"🔍 SSE: User {user_id}: {len(queues)} connections, last heartbeat {time_since_hb.total_seconds():.1f}s ago")
        
        # Get potential recipients first, even if no one is currently connected
        potential_recipients = await self._get_channel_members(channel_id, db)
        print(f"🔍 SSE: Potential recipients for channel {channel_id}: {potential_recipients}")
        
        # If no users are connected, we can still queue messages for offline users
        if not self.connections:
            print(f"⚠️ SSE: No users currently connected for {event_type}")
            print(f"📬 SSE: Will queue message for offline users: {data.get('content', 'unknown content')}")
            
            # Queue for all potential recipients
            queued_count = 0
            for user_id in potential_recipients:
                await self._queue_message_for_user(user_id, {
                    "type": event_type,
                    "channel_id": channel_id,
                    "data": data,
                    "timestamp": datetime.utcnow().isoformat()
                })
                queued_count += 1
            
            print(f"📬 SSE: Queued message for {queued_count} offline users")
            return
        
        # Proactively clean up stale connections before broadcasting
        cleaned_count = await self.cleanup_stale_connections(max_age_seconds=180)  # 3 minutes
        if cleaned_count > 0:
            print(f"🧹 SSE: Auto-cleaned {cleaned_count} stale connections before broadcast")
        
        broadcast_count = 0
        failed_connections = []
        queued_count = 0
        
        for user_id, queues in list(self.connections.items()):  # Create list to avoid modification during iteration
            user_broadcast_count = 0
            print(f"🔍 SSE: Attempting to broadcast to user {user_id} with {len(queues)} connections")
            
            for queue in list(queues):  # Create list copy
                try:
                    # Add timeout to prevent hanging
                    await asyncio.wait_for(queue.put(event), timeout=5.0)
                    
                    # Update metadata
                    queue_id = id(queue)
                    if user_id in self.connection_metadata and queue_id in self.connection_metadata[user_id]:
                        self.connection_metadata[user_id][queue_id]["message_count"] += 1
                    
                    # Update heartbeat
                    self.last_heartbeat[user_id] = datetime.utcnow()
                    
                    print(f"✅ SSE: Successfully sent {event_type} to user {user_id}")
                    broadcast_count += 1
                    user_broadcast_count += 1
                except asyncio.TimeoutError:
                    print(f"⏰ SSE: Timeout broadcasting to user {user_id} - connection may be stale")
                    failed_connections.append((user_id, queue))
                    queues.discard(queue)
                except Exception as e:
                    print(f"❌ SSE: Failed to broadcast to user {user_id}: {str(e)}")
                    failed_connections.append((user_id, queue))
                    queues.discard(queue)
            
            print(f"🔍 SSE: Broadcast to user {user_id} complete: {user_broadcast_count} successful")
            
            # If user has no working connections, remove them entirely
            if not queues:
                print(f"❌ SSE: Removing user {user_id} - no working connections")
                del self.connections[user_id]
                if user_id in self.connection_metadata:
                    del self.connection_metadata[user_id]
                if user_id in self.last_heartbeat:
                    del self.last_heartbeat[user_id]
        
        # Clean up failed connections
        for user_id, queue in failed_connections:
            if user_id in self.connections:
                self.connections[user_id].discard(queue)
                # Clean up metadata for failed connection
                queue_id = id(queue)
                if user_id in self.connection_metadata and queue_id in self.connection_metadata[user_id]:
                    del self.connection_metadata[user_id][queue_id]
        
        # Queue messages for offline users who should receive them
        for user_id in potential_recipients:
            if user_id not in self.connections:
                await self._queue_message_for_user(user_id, event)
                queued_count += 1
        
        print(f"🔍 SSE: Broadcast summary - sent to {broadcast_count} connections, {len(failed_connections)} failed, {queued_count} queued for offline users")
        
        # Alert if broadcast failed completely AND no messages were queued
        if broadcast_count == 0 and queued_count == 0:
            print(f"🚨 SSE: ALERT - Message broadcast failed completely! No recipients received: {data.get('content', 'unknown')}")
        elif broadcast_count == 0 and queued_count > 0:
            print(f"📬 SSE: No active connections, but queued message for {queued_count} offline users")
    
    async def broadcast_to_user(self, user_id: int, event_type: str, data: dict):
        """Send an event to a specific user"""
        if user_id in self.connections:
            event = {
                "type": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            successful_sends = 0
            for queue in self.connections[user_id].copy():
                try:
                    await asyncio.wait_for(queue.put(event), timeout=5.0)
                    successful_sends += 1
                    
                    # Update metadata
                    queue_id = id(queue)
                    if user_id in self.connection_metadata and queue_id in self.connection_metadata[user_id]:
                        self.connection_metadata[user_id][queue_id]["message_count"] += 1
                    
                    self.last_heartbeat[user_id] = datetime.utcnow()
                except Exception as e:
                    print(f"❌ SSE: Failed to send to user {user_id}: {str(e)}")
                    self.connections[user_id].discard(queue)
                    
                    # Clean up metadata
                    queue_id = id(queue)
                    if user_id in self.connection_metadata and queue_id in self.connection_metadata[user_id]:
                        del self.connection_metadata[user_id][queue_id]
            
            print(f"🔍 SSE: Direct broadcast to user {user_id}: {successful_sends} successful sends")
            
            # Clean up user if no connections remain
            if not self.connections[user_id]:
                del self.connections[user_id]
                if user_id in self.connection_metadata:
                    del self.connection_metadata[user_id]
                if user_id in self.last_heartbeat:
                    del self.last_heartbeat[user_id]
    
    async def cleanup_stale_connections(self, max_age_seconds: int = 300):
        """Remove connections that haven't been active for too long"""
        now = datetime.utcnow()
        stale_users = []
        
        for user_id, last_heartbeat in list(self.last_heartbeat.items()):
            time_since_heartbeat = now - last_heartbeat
            if time_since_heartbeat.total_seconds() > max_age_seconds:
                print(f"🧹 SSE: Cleaning up stale connection for user {user_id} (inactive for {time_since_heartbeat.total_seconds():.1f}s)")
                stale_users.append(user_id)
        
        for user_id in stale_users:
            if user_id in self.connections:
                del self.connections[user_id]
            if user_id in self.connection_metadata:
                del self.connection_metadata[user_id]
            if user_id in self.last_heartbeat:
                del self.last_heartbeat[user_id]
        
        if stale_users:
            print(f"🧹 SSE: Cleaned up {len(stale_users)} stale connections")
        
        return len(stale_users)
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get detailed connection statistics"""
        total_connections = sum(len(queues) for queues in self.connections.values())
        now = datetime.utcnow()
        
        stats = {
            "total_users": len(self.connections),
            "total_connections": total_connections,
            "users": {},
            "health_summary": {
                "healthy": 0,
                "stale_warning": 0,
                "stale_critical": 0
            }
        }
        
        for user_id, queues in self.connections.items():
            last_hb = self.last_heartbeat.get(user_id, now)
            time_since_hb = now - last_hb
            seconds_since_hb = time_since_hb.total_seconds()
            
            # Determine health status
            if seconds_since_hb < 60:  # < 1 min
                health = "healthy"
                stats["health_summary"]["healthy"] += 1
            elif seconds_since_hb < 180:  # < 3 min
                health = "stale_warning"
                stats["health_summary"]["stale_warning"] += 1
            else:  # >= 3 min
                health = "stale_critical"
                stats["health_summary"]["stale_critical"] += 1
            
            stats["users"][user_id] = {
                "connections": len(queues),
                "last_heartbeat_seconds_ago": seconds_since_hb,
                "health": health,
                "metadata": self.connection_metadata.get(user_id, {}),
                "queued_messages": len(self.message_queue.get(user_id, []))
            }
        
        # Add queue statistics
        stats["message_queues"] = {
            "total_queued_users": len([uid for uid, queue in self.message_queue.items() if queue]),
            "total_queued_messages": sum(len(queue) for queue in self.message_queue.values()),
            "queue_details": {
                user_id: len(queue) for user_id, queue in self.message_queue.items() if queue
            }
        }
        
        return stats


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
    client_info = f"{request.client.host if request.client else 'unknown'}:{request.client.port if request.client else 'unknown'}"
    user_agent = request.headers.get('user-agent', 'unknown')
    print(f"🔍 SSE: Connection request received from user {current_user.id} ({current_user.email})")
    print(f"🔍 SSE: Client info: {client_info}, User-Agent: {user_agent}")
    print(f"🔍 SSE: Request headers: {dict(request.headers)}")
    
    async def event_generator():
        print(f"🔍 SSE: Starting event generator for user {current_user.id}")
        
        # Connect user to the event manager
        queue = await chat_event_manager.connect(current_user.id, client_info)
        print(f"🔍 SSE: User {current_user.id} connected to event manager")
        print(f"🔍 SSE: Current global connections: {sum(len(queues) for queues in chat_event_manager.connections.values())}")
        
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
                    
                    # Format as SSE with explicit flush
                    data = f"data: {json.dumps(event)}\n\n"
                    yield data
                    
                    # Force a small delay to prevent rapid disconnections
                    await asyncio.sleep(0.1)
                    
                except asyncio.TimeoutError:
                    # Send keepalive ping and update heartbeat
                    ping_event = {'type': 'ping', 'timestamp': datetime.utcnow().isoformat()}
                    yield f"data: {json.dumps(ping_event)}\n\n"
                    chat_event_manager.last_heartbeat[current_user.id] = datetime.utcnow()
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
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
            "Access-Control-Allow-Credentials": "true",
            "X-Accel-Buffering": "no",  # Disable proxy buffering
            "Transfer-Encoding": "chunked",
            "Content-Type": "text/event-stream; charset=utf-8",
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


# Connection health and diagnostic endpoints
@router.get("/connection-stats")
async def get_connection_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed connection statistics for debugging"""
    if not current_user.is_admin():
        # Allow beta testers and moderators to see basic stats
        from app.services.chat_role_service import is_user_admin, is_user_moderator, is_user_beta_tester
        if not (await is_user_admin(db, current_user.id) or 
                await is_user_moderator(db, current_user.id) or 
                await is_user_beta_tester(db, current_user.id)):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    stats = chat_event_manager.get_connection_stats()
    return {
        "connection_stats": stats,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.post("/cleanup-stale-connections")
async def cleanup_stale_connections(
    max_age_seconds: int = 300,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger cleanup of stale connections"""
    if not current_user.is_admin():
        from app.services.chat_role_service import is_user_admin, is_user_moderator
        if not (await is_user_admin(db, current_user.id) or await is_user_moderator(db, current_user.id)):
            raise HTTPException(status_code=403, detail="Only admins and moderators can trigger cleanup")
    
    cleaned_count = await chat_event_manager.cleanup_stale_connections(max_age_seconds)
    return {
        "message": f"Cleaned up {cleaned_count} stale connections",
        "cleaned_connections": cleaned_count,
        "max_age_seconds": max_age_seconds,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/health")
async def sse_health_check():
    """Quick health check for SSE system"""
    stats = chat_event_manager.get_connection_stats()
    
    return {
        "status": "healthy",
        "total_users": stats["total_users"],
        "total_connections": stats["total_connections"],
        "health_summary": stats["health_summary"],
        "timestamp": datetime.utcnow().isoformat()
    }


# Export the event manager for use in other modules
__all__ = ["chat_event_manager", "broadcast_new_message", "broadcast_message_updated", 
           "broadcast_message_deleted", "broadcast_reaction_added", "broadcast_reaction_removed"]