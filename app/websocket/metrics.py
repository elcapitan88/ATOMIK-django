"""
Application WebSocket Metrics

Performance and health metrics for the Application WebSocket system.
Adapted from trading WebSocket but focused on chat/UI event metrics.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import deque


class ConnectionMetrics:
    """Metrics for individual WebSocket connections"""
    
    def __init__(self):
        self.connected_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.messages_sent = 0
        self.messages_received = 0
        self.heartbeats_sent = 0
        self.heartbeats_received = 0
        self.errors = 0
        self._lock = asyncio.Lock()

    async def record_activity(self, activity_type: str):
        """Record user activity"""
        async with self._lock:
            self.last_activity = datetime.utcnow()
            
            if activity_type == "message_sent":
                self.messages_sent += 1
            elif activity_type == "message_received":
                self.messages_received += 1
            elif activity_type == "heartbeat_sent":
                self.heartbeats_sent += 1
            elif activity_type == "heartbeat_received":
                self.heartbeats_received += 1
            elif activity_type == "error":
                self.errors += 1

    def get_connection_duration(self) -> float:
        """Get connection duration in seconds"""
        return (datetime.utcnow() - self.connected_at).total_seconds()

    def is_idle(self, idle_timeout_seconds: int = 300) -> bool:
        """Check if connection is idle"""
        idle_time = (datetime.utcnow() - self.last_activity).total_seconds()
        return idle_time > idle_timeout_seconds

    def to_dict(self) -> Dict:
        """Convert metrics to dictionary"""
        return {
            "connected_at": self.connected_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "connection_duration_seconds": self.get_connection_duration(),
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "heartbeats_sent": self.heartbeats_sent,
            "heartbeats_received": self.heartbeats_received,
            "errors": self.errors
        }


class ChannelMetrics:
    """Metrics for chat channels"""
    
    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self.created_at = datetime.utcnow()
        self.total_messages = 0
        self.total_reactions = 0
        self.unique_users = set()
        self.peak_concurrent_users = 0
        self.message_history = deque(maxlen=100)  # Keep last 100 message timestamps
        self._lock = asyncio.Lock()

    async def record_message(self, user_id: str):
        """Record a message in this channel"""
        async with self._lock:
            self.total_messages += 1
            self.unique_users.add(user_id)
            self.message_history.append(datetime.utcnow())

    async def record_reaction(self, user_id: str):
        """Record a reaction in this channel"""
        async with self._lock:
            self.total_reactions += 1
            self.unique_users.add(user_id)

    async def update_concurrent_users(self, current_count: int):
        """Update peak concurrent users"""
        async with self._lock:
            if current_count > self.peak_concurrent_users:
                self.peak_concurrent_users = current_count

    def get_messages_per_minute(self) -> float:
        """Calculate messages per minute in last hour"""
        if not self.message_history:
            return 0.0
        
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_messages = [
            msg_time for msg_time in self.message_history 
            if msg_time > one_hour_ago
        ]
        
        if not recent_messages:
            return 0.0
        
        # Calculate rate based on time span of messages
        time_span = (recent_messages[-1] - recent_messages[0]).total_seconds() / 60
        return len(recent_messages) / max(time_span, 1)

    def to_dict(self) -> Dict:
        """Convert metrics to dictionary"""
        return {
            "channel_id": self.channel_id,
            "created_at": self.created_at.isoformat(),
            "total_messages": self.total_messages,
            "total_reactions": self.total_reactions,
            "unique_users": len(self.unique_users),
            "peak_concurrent_users": self.peak_concurrent_users,
            "messages_per_minute": self.get_messages_per_minute(),
            "recent_activity": len([
                msg_time for msg_time in self.message_history
                if msg_time > datetime.utcnow() - timedelta(minutes=10)
            ])
        }


class AppWebSocketMetrics:
    """Global metrics for the Application WebSocket system"""
    
    def __init__(self):
        self.started_at = datetime.utcnow()
        self.total_connections = 0
        self.total_disconnections = 0
        self.total_messages = 0
        self.total_errors = 0
        
        # Active metrics
        self.connection_metrics: Dict[str, ConnectionMetrics] = {}
        self.channel_metrics: Dict[str, ChannelMetrics] = {}
        
        # Rate tracking
        self.message_rate_history = deque(maxlen=60)  # Last 60 minutes
        self._lock = asyncio.Lock()
        
        # Rate tracking task will be started during initialization
        self._rate_task: Optional[asyncio.Task] = None

    async def start_rate_tracking(self):
        """Start the rate tracking background task"""
        if self._rate_task is None:
            self._rate_task = asyncio.create_task(self._track_rates())

    async def record_connection(self, user_id: str):
        """Record a new connection"""
        async with self._lock:
            self.total_connections += 1
            self.connection_metrics[user_id] = ConnectionMetrics()

    async def record_disconnection(self, user_id: str):
        """Record a disconnection"""
        async with self._lock:
            self.total_disconnections += 1
            # Keep metrics for a short time for analysis
            if user_id in self.connection_metrics:
                # Could store in historical metrics here
                pass

    async def record_message(self, user_id: str, channel_id: str):
        """Record a message"""
        async with self._lock:
            self.total_messages += 1
            
            # Update connection metrics
            if user_id in self.connection_metrics:
                await self.connection_metrics[user_id].record_activity("message_sent")
            
            # Update channel metrics
            if channel_id not in self.channel_metrics:
                self.channel_metrics[channel_id] = ChannelMetrics(channel_id)
            await self.channel_metrics[channel_id].record_message(user_id)

    async def record_error(self, user_id: Optional[str] = None):
        """Record an error"""
        async with self._lock:
            self.total_errors += 1
            
            if user_id and user_id in self.connection_metrics:
                await self.connection_metrics[user_id].record_activity("error")

    async def get_system_stats(self) -> Dict:
        """Get overall system statistics"""
        async with self._lock:
            active_connections = len(self.connection_metrics)
            uptime = (datetime.utcnow() - self.started_at).total_seconds()
            
            # Calculate average messages per minute
            messages_per_minute = 0.0
            if self.message_rate_history:
                messages_per_minute = sum(self.message_rate_history) / len(self.message_rate_history)
            
            return {
                "system": {
                    "started_at": self.started_at.isoformat(),
                    "uptime_seconds": uptime,
                    "total_connections": self.total_connections,
                    "total_disconnections": self.total_disconnections,
                    "active_connections": active_connections,
                    "total_messages": self.total_messages,
                    "total_errors": self.total_errors,
                    "messages_per_minute": messages_per_minute
                },
                "channels": {
                    channel_id: metrics.to_dict() 
                    for channel_id, metrics in self.channel_metrics.items()
                },
                "active_connections": len(self.connection_metrics)
            }

    async def cleanup_stale_metrics(self, max_age_hours: int = 24):
        """Clean up old metrics"""
        async with self._lock:
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
            
            # Clean up connection metrics for disconnected users
            stale_users = []
            for user_id, metrics in self.connection_metrics.items():
                if metrics.last_activity < cutoff_time:
                    stale_users.append(user_id)
            
            for user_id in stale_users:
                del self.connection_metrics[user_id]

    async def _track_rates(self):
        """Background task to track message rates"""
        while True:
            try:
                await asyncio.sleep(60)  # Every minute
                
                # Count messages in the last minute from all channels
                one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
                recent_messages = 0
                
                for channel_metrics in self.channel_metrics.values():
                    recent_messages += len([
                        msg_time for msg_time in channel_metrics.message_history
                        if msg_time > one_minute_ago
                    ])
                
                self.message_rate_history.append(recent_messages)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but continue
                pass

    async def shutdown(self):
        """Shutdown metrics collection"""
        if self._rate_task and not self._rate_task.done():
            self._rate_task.cancel()
            try:
                await self._rate_task
            except asyncio.CancelledError:
                pass