# app/websockets/metrics.py
import asyncio
from datetime import datetime

class HeartbeatMetrics:
    def __init__(self):
        self.totalHeartbeats = 0
        self.missedHeartbeats = 0
        self.averageLatency = 0
        self.lastSuccessful = datetime.utcnow()
        self.lastHeartbeat = datetime.utcnow()
        self.reconnectionAttempts = 0
        self._lock = asyncio.Lock()

    async def record_heartbeat(self):
        """Record a successful heartbeat"""
        async with self._lock:
            self.totalHeartbeats += 1
            self.lastSuccessful = datetime.utcnow()
            self.lastHeartbeat = datetime.utcnow()
            self.missedHeartbeats = 0  # Reset missed count on successful heartbeat

    async def record_missed(self):
        """Record a missed heartbeat"""
        async with self._lock:
            self.missedHeartbeats += 1
            return self.missedHeartbeats

    def get_metrics(self) -> dict:
        """Get current metrics with JSON-serializable values"""
        return {
            "totalHeartbeats": self.totalHeartbeats,
            "missedHeartbeats": self.missedHeartbeats,
            "averageLatency": round(self.averageLatency, 2),
            "lastSuccessful": self.lastSuccessful.isoformat() if self.lastSuccessful else None,
            "lastHeartbeat": self.lastHeartbeat.isoformat() if self.lastHeartbeat else None,
            "reconnectionAttempts": self.reconnectionAttempts,
            "healthScore": self.get_health_score()
        }

    def get_health_score(self) -> float:
        """Calculate health score (0-1)"""
        if self.totalHeartbeats == 0:
            return 0.0
        return max(0.0, min(1.0, 1 - (self.missedHeartbeats / max(self.totalHeartbeats, 1))))

    def reset(self):
        """Reset metrics"""
        self.missedHeartbeats = 0
        self.reconnectionAttempts = 0
        self.lastHeartbeat = datetime.utcnow()
        self.lastSuccessful = datetime.utcnow()