"""
Application WebSocket Manager

⚠️ IMPORTANT: This is for APPLICATION WebSocket (chat, notifications, UI events)
NOT for trading data! Trading WebSocket is in /Websocket-Proxy/

Purpose: Chat messages, emoji reactions, typing indicators, system notifications
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Set, List, Optional, Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class AppWebSocketManager:
    """
    Manages Application WebSocket connections for chat, notifications, and UI events.
    
    Features:
    - User connection tracking
    - Channel subscription management
    - Message broadcasting
    - Connection health monitoring
    - Future-ready for message bus integration
    """
    
    def __init__(self):
        # Active connections: user_id -> websocket
        self.active_connections: Dict[str, WebSocket] = {}
        
        # Channel subscriptions: channel_id -> set of user_ids
        self.channel_subscriptions: Dict[str, Set[str]] = {}
        
        # User channel memberships: user_id -> set of channel_ids
        self.user_channels: Dict[str, Set[str]] = {}
        
        # Connection metadata
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Message acknowledgment tracking
        self.pending_acks: Dict[str, Dict[str, Any]] = {}
        
        logger.info("🗨️ Application WebSocket Manager initialized")
    
    async def connect(self, websocket: WebSocket, user_id: str, user_channels: List[str] = None) -> bool:
        """
        Connect a user to the Application WebSocket.
        
        Args:
            websocket: FastAPI WebSocket connection
            user_id: User's unique identifier
            user_channels: List of channel IDs user should be subscribed to
            
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            await websocket.accept()
            
            # Close existing connection if user reconnects
            if user_id in self.active_connections:
                await self.disconnect(user_id, reason="New connection from same user")
            
            # Store connection
            self.active_connections[user_id] = websocket
            
            # Initialize user channels
            if user_channels:
                self.user_channels[user_id] = set(user_channels)
                # Subscribe to channels
                for channel_id in user_channels:
                    await self.subscribe_to_channel(user_id, channel_id)
            else:
                self.user_channels[user_id] = set()
            
            # Store connection metadata
            self.connection_metadata[user_id] = {
                "connected_at": datetime.utcnow(),
                "last_ping": datetime.utcnow(),
                "message_count": 0,
                "status": "connected"
            }
            
            logger.info(f"✅ User {user_id} connected to Application WebSocket")
            
            # Send connection confirmation
            await self.send_to_user(user_id, {
                "type": "connection_established",
                "timestamp": datetime.utcnow().isoformat(),
                "channels": list(user_channels) if user_channels else []
            })
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect user {user_id}: {e}")
            return False
    
    async def disconnect(self, user_id: str, reason: str = "User disconnected") -> bool:
        """
        Disconnect a user from the Application WebSocket.
        
        Args:
            user_id: User's unique identifier
            reason: Reason for disconnection
            
        Returns:
            bool: True if disconnection successful
        """
        try:
            # Remove from channel subscriptions
            if user_id in self.user_channels:
                for channel_id in self.user_channels[user_id].copy():
                    await self.unsubscribe_from_channel(user_id, channel_id)
            
            # Close WebSocket connection
            if user_id in self.active_connections:
                websocket = self.active_connections[user_id]
                try:
                    await websocket.close(code=1000, reason=reason)
                except:
                    pass  # Connection might already be closed
                del self.active_connections[user_id]
            
            # Clean up metadata
            self.connection_metadata.pop(user_id, None)
            self.user_channels.pop(user_id, None)
            self.pending_acks.pop(user_id, None)
            
            logger.info(f"👋 User {user_id} disconnected: {reason}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error disconnecting user {user_id}: {e}")
            return False
    
    async def subscribe_to_channel(self, user_id: str, channel_id: str) -> bool:
        """
        Subscribe a user to a channel for receiving messages.
        
        Args:
            user_id: User's unique identifier
            channel_id: Channel to subscribe to
            
        Returns:
            bool: True if subscription successful
        """
        try:
            # Add to channel subscriptions
            if channel_id not in self.channel_subscriptions:
                self.channel_subscriptions[channel_id] = set()
            self.channel_subscriptions[channel_id].add(user_id)
            
            # Add to user's channels
            if user_id not in self.user_channels:
                self.user_channels[user_id] = set()
            self.user_channels[user_id].add(channel_id)
            
            logger.debug(f"📡 User {user_id} subscribed to channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error subscribing user {user_id} to channel {channel_id}: {e}")
            return False
    
    async def unsubscribe_from_channel(self, user_id: str, channel_id: str) -> bool:
        """
        Unsubscribe a user from a channel.
        
        Args:
            user_id: User's unique identifier
            channel_id: Channel to unsubscribe from
            
        Returns:
            bool: True if unsubscription successful
        """
        try:
            # Remove from channel subscriptions
            if channel_id in self.channel_subscriptions:
                self.channel_subscriptions[channel_id].discard(user_id)
                # Clean up empty channel subscriptions
                if not self.channel_subscriptions[channel_id]:
                    del self.channel_subscriptions[channel_id]
            
            # Remove from user's channels
            if user_id in self.user_channels:
                self.user_channels[user_id].discard(channel_id)
            
            logger.debug(f"📡 User {user_id} unsubscribed from channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error unsubscribing user {user_id} from channel {channel_id}: {e}")
            return False
    
    async def send_to_user(self, user_id: str, message: Dict[str, Any]) -> bool:
        """
        Send a message to a specific user.
        
        Args:
            user_id: Target user's unique identifier
            message: Message to send
            
        Returns:
            bool: True if message sent successfully
        """
        if user_id not in self.active_connections:
            logger.debug(f"📤 User {user_id} not connected, message queued")
            return False
        
        try:
            websocket = self.active_connections[user_id]
            await websocket.send_text(json.dumps(message))
            
            # Update message count
            if user_id in self.connection_metadata:
                self.connection_metadata[user_id]["message_count"] += 1
            
            logger.debug(f"📤 Sent message to user {user_id}: {message.get('type', 'unknown')}")
            return True
            
        except WebSocketDisconnect:
            logger.info(f"🔌 User {user_id} disconnected during message send")
            await self.disconnect(user_id, "Connection lost during send")
            return False
        except Exception as e:
            logger.error(f"❌ Error sending message to user {user_id}: {e}")
            return False
    
    async def broadcast_to_channel(self, channel_id: str, message: Dict[str, Any], exclude_user: str = None) -> int:
        """
        Broadcast a message to all users in a channel.
        
        Args:
            channel_id: Target channel ID
            message: Message to broadcast
            exclude_user: Optional user ID to exclude from broadcast
            
        Returns:
            int: Number of users who received the message
        """
        if channel_id not in self.channel_subscriptions:
            logger.debug(f"📡 No subscribers for channel {channel_id}")
            return 0
        
        subscribers = self.channel_subscriptions[channel_id].copy()
        if exclude_user:
            subscribers.discard(exclude_user)
        
        successful_sends = 0
        failed_users = []
        
        for user_id in subscribers:
            success = await self.send_to_user(user_id, message)
            if success:
                successful_sends += 1
            else:
                failed_users.append(user_id)
        
        # Clean up failed connections
        for user_id in failed_users:
            await self.disconnect(user_id, "Failed to receive broadcast message")
        
        logger.debug(f"📡 Broadcast to channel {channel_id}: {successful_sends}/{len(subscribers)} successful")
        return successful_sends
    
    async def broadcast_to_all(self, message: Dict[str, Any], exclude_user: str = None) -> int:
        """
        Broadcast a message to all connected users.
        
        Args:
            message: Message to broadcast
            exclude_user: Optional user ID to exclude from broadcast
            
        Returns:
            int: Number of users who received the message
        """
        users = list(self.active_connections.keys())
        if exclude_user:
            users = [u for u in users if u != exclude_user]
        
        successful_sends = 0
        for user_id in users:
            success = await self.send_to_user(user_id, message)
            if success:
                successful_sends += 1
        
        logger.info(f"📡 Global broadcast: {successful_sends}/{len(users)} successful")
        return successful_sends
    
    async def handle_ping(self, user_id: str) -> bool:
        """
        Handle ping from client for connection health.
        
        Args:
            user_id: User sending the ping
            
        Returns:
            bool: True if pong sent successfully
        """
        if user_id in self.connection_metadata:
            self.connection_metadata[user_id]["last_ping"] = datetime.utcnow()
        
        return await self.send_to_user(user_id, {
            "type": "pong",
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """
        Get current connection statistics.
        
        Returns:
            Dict with connection statistics
        """
        total_connections = len(self.active_connections)
        total_channels = len(self.channel_subscriptions)
        total_subscriptions = sum(len(subs) for subs in self.channel_subscriptions.values())
        
        return {
            "total_connections": total_connections,
            "total_channels": total_channels,
            "total_subscriptions": total_subscriptions,
            "channels": {
                channel_id: len(subscribers) 
                for channel_id, subscribers in self.channel_subscriptions.items()
            },
            "uptime_seconds": (datetime.utcnow() - datetime.utcnow()).total_seconds() if self.active_connections else 0
        }
    
    def is_user_connected(self, user_id: str) -> bool:
        """
        Check if a user is currently connected.
        
        Args:
            user_id: User to check
            
        Returns:
            bool: True if user is connected
        """
        return user_id in self.active_connections
    
    def get_user_channels(self, user_id: str) -> List[str]:
        """
        Get list of channels a user is subscribed to.
        
        Args:
            user_id: User to check
            
        Returns:
            List of channel IDs
        """
        return list(self.user_channels.get(user_id, set()))
    
    async def cleanup_stale_connections(self, max_age_minutes: int = 60) -> int:
        """
        Clean up connections that haven't pinged recently.
        
        Args:
            max_age_minutes: Maximum age before connection is considered stale
            
        Returns:
            int: Number of connections cleaned up
        """
        now = datetime.utcnow()
        stale_users = []
        
        for user_id, metadata in self.connection_metadata.items():
            last_ping = metadata.get("last_ping", metadata.get("connected_at"))
            age_minutes = (now - last_ping).total_seconds() / 60
            
            if age_minutes > max_age_minutes:
                stale_users.append(user_id)
        
        # Clean up stale connections
        for user_id in stale_users:
            await self.disconnect(user_id, f"Stale connection (>{max_age_minutes}min)")
        
        if stale_users:
            logger.info(f"🧹 Cleaned up {len(stale_users)} stale connections")
        
        return len(stale_users)


# Global instance for the application
app_websocket_manager = AppWebSocketManager()