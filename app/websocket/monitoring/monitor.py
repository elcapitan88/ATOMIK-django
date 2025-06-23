"""
Application WebSocket Monitoring

Simplified monitoring for Application WebSocket connections focused on 
chat and UI events rather than high-frequency trading data.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import logging
import asyncio
from enum import Enum
from collections import defaultdict, deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events to monitor"""
    CONNECTION = "connection"
    DISCONNECTION = "disconnection"
    MESSAGE = "message"
    REACTION = "reaction"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


@dataclass
class MonitorEvent:
    """Individual monitoring event"""
    event_type: EventType
    user_id: str
    channel_id: Optional[str]
    timestamp: datetime
    metadata: Dict[str, Any]


class AppWebSocketMonitor:
    """Monitor for Application WebSocket system"""
    
    def __init__(self, max_events: int = 1000):
        self.max_events = max_events
        self.events: deque = deque(maxlen=max_events)
        self.stats = {
            "connections": 0,
            "disconnections": 0,
            "messages": 0,
            "reactions": 0,
            "errors": 0,
            "heartbeats": 0
        }
        
        # Real-time tracking
        self.active_connections: Dict[str, datetime] = {}
        self.channel_activity: Dict[str, List[datetime]] = defaultdict(list)
        self.error_counts: Dict[str, int] = defaultdict(int)
        
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the monitoring service"""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("🔍 Application WebSocket Monitor started")

    async def stop(self):
        """Stop the monitoring service"""
        self._running = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("🔍 Application WebSocket Monitor stopped")

    def record_event(
        self, 
        event_type: EventType, 
        user_id: str, 
        channel_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Record a monitoring event"""
        event = MonitorEvent(
            event_type=event_type,
            user_id=user_id,
            channel_id=channel_id,
            timestamp=datetime.utcnow(),
            metadata=metadata or {}
        )
        
        self.events.append(event)
        self._update_stats(event)

    def _update_stats(self, event: MonitorEvent):
        """Update internal statistics"""
        if event.event_type == EventType.CONNECTION:
            self.stats["connections"] += 1
            self.active_connections[event.user_id] = event.timestamp
            
        elif event.event_type == EventType.DISCONNECTION:
            self.stats["disconnections"] += 1
            self.active_connections.pop(event.user_id, None)
            
        elif event.event_type == EventType.MESSAGE:
            self.stats["messages"] += 1
            if event.channel_id:
                self.channel_activity[event.channel_id].append(event.timestamp)
                
        elif event.event_type == EventType.REACTION:
            self.stats["reactions"] += 1
            
        elif event.event_type == EventType.ERROR:
            self.stats["errors"] += 1
            error_type = event.metadata.get("error_type", "unknown")
            self.error_counts[error_type] += 1
            
        elif event.event_type == EventType.HEARTBEAT:
            self.stats["heartbeats"] += 1

    def get_active_connections_count(self) -> int:
        """Get current number of active connections"""
        return len(self.active_connections)

    def get_channel_activity(self, channel_id: str, minutes: int = 60) -> int:
        """Get message count for a channel in the last N minutes"""
        if channel_id not in self.channel_activity:
            return 0
        
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        return len([
            timestamp for timestamp in self.channel_activity[channel_id]
            if timestamp > cutoff
        ])

    def get_error_summary(self, hours: int = 24) -> Dict[str, int]:
        """Get error summary for the last N hours"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        recent_errors = defaultdict(int)
        
        for event in self.events:
            if (event.event_type == EventType.ERROR and 
                event.timestamp > cutoff):
                error_type = event.metadata.get("error_type", "unknown")
                recent_errors[error_type] += 1
        
        return dict(recent_errors)

    def get_connection_duration(self, user_id: str) -> Optional[float]:
        """Get connection duration for a user in seconds"""
        if user_id not in self.active_connections:
            return None
        
        return (datetime.utcnow() - self.active_connections[user_id]).total_seconds()

    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health metrics"""
        now = datetime.utcnow()
        
        # Calculate rates (events per minute in last hour)
        one_hour_ago = now - timedelta(hours=1)
        recent_events = [e for e in self.events if e.timestamp > one_hour_ago]
        
        event_counts = defaultdict(int)
        for event in recent_events:
            event_counts[event.event_type.value] += 1
        
        # Calculate average connection duration
        avg_connection_duration = 0
        if self.active_connections:
            durations = [
                (now - conn_time).total_seconds()
                for conn_time in self.active_connections.values()
            ]
            avg_connection_duration = sum(durations) / len(durations)
        
        return {
            "timestamp": now.isoformat(),
            "active_connections": len(self.active_connections),
            "total_stats": self.stats.copy(),
            "hourly_rates": {
                event_type: count for event_type, count in event_counts.items()
            },
            "avg_connection_duration_seconds": avg_connection_duration,
            "top_errors": dict(list(self.error_counts.items())[:5]),
            "monitoring": {
                "total_events_tracked": len(self.events),
                "running": self._running
            }
        }

    def get_channel_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all channels"""
        channel_stats = {}
        
        for channel_id in self.channel_activity:
            # Get activity for different time periods
            stats = {
                "messages_last_hour": self.get_channel_activity(channel_id, 60),
                "messages_last_day": self.get_channel_activity(channel_id, 60 * 24),
                "total_messages": len(self.channel_activity[channel_id]),
            }
            
            # Get active users in channel (from recent events)
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent_users = set()
            for event in self.events:
                if (event.channel_id == channel_id and 
                    event.timestamp > one_hour_ago and
                    event.event_type in [EventType.MESSAGE, EventType.REACTION]):
                    recent_users.add(event.user_id)
            
            stats["active_users_last_hour"] = len(recent_users)
            channel_stats[channel_id] = stats
        
        return channel_stats

    async def _cleanup_loop(self):
        """Background cleanup task"""
        while self._running:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                await self._cleanup_old_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error in monitoring cleanup loop: {e}")

    async def _cleanup_old_data(self):
        """Clean up old monitoring data"""
        # Clean up old channel activity (keep last 7 days)
        cutoff = datetime.utcnow() - timedelta(days=7)
        
        for channel_id in list(self.channel_activity.keys()):
            # Keep only recent timestamps
            recent_activity = [
                timestamp for timestamp in self.channel_activity[channel_id]
                if timestamp > cutoff
            ]
            
            if recent_activity:
                self.channel_activity[channel_id] = recent_activity
            else:
                # Remove empty channels
                del self.channel_activity[channel_id]
        
        # Clean up stale connections (should be handled by WebSocket manager)
        stale_cutoff = datetime.utcnow() - timedelta(hours=24)
        stale_users = [
            user_id for user_id, conn_time in self.active_connections.items()
            if conn_time < stale_cutoff
        ]
        
        for user_id in stale_users:
            del self.active_connections[user_id]
            
        if stale_users:
            logger.info(f"🧹 Monitor cleaned up {len(stale_users)} stale connection records")


# Global monitor instance
app_websocket_monitor = AppWebSocketMonitor()