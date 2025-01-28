# app/websockets/metrics.py
import asyncio
from datetime import datetime

class HeartbeatMetrics:
    def __init__(self):
        self.total_heartbeats = 0
        self.missed_heartbeats = 0
        self.last_heartbeat_time = None
        self.last_received_time = None
        self.consecutive_misses = 0
        self.total_latency = 0
        self._lock = asyncio.Lock()

        # Performance metrics
        self.min_latency = float('inf')
        self.max_latency = 0
        self.avg_latency = 0
        self.latency_samples = []

    async def record_heartbeat(self):
        """Record a successful heartbeat"""
        async with self._lock:
            current_time = datetime.utcnow()
            
            # Update basic metrics
            self.total_heartbeats += 1
            self.consecutive_misses = 0
            self.last_heartbeat_time = current_time

            # Calculate and update latency if we have a previous timestamp
            if self.last_received_time:
                latency = (current_time - self.last_received_time).total_seconds() * 1000
                self.update_latency_metrics(latency)

            self.last_received_time = current_time

    async def record_missed(self):
        """Record a missed heartbeat"""
        async with self._lock:
            self.missed_heartbeats += 1
            self.consecutive_misses += 1
            return self.consecutive_misses

    def update_latency_metrics(self, latency: float):
        """Update latency-related metrics"""
        self.latency_samples.append(latency)
        if len(self.latency_samples) > 100:  # Keep last 100 samples
            self.latency_samples.pop(0)

        # Update min/max
        self.min_latency = min(self.min_latency, latency)
        self.max_latency = max(self.max_latency, latency)

        # Update average
        self.total_latency += latency
        self.avg_latency = self.total_latency / self.total_heartbeats

    def get_metrics(self) -> dict:
        """Get current metrics"""
        return {
            "total_heartbeats": self.total_heartbeats,
            "missed_heartbeats": self.missed_heartbeats,
            "consecutive_misses": self.consecutive_misses,
            "last_heartbeat": self.last_heartbeat_time.isoformat() if self.last_heartbeat_time else None,
            "latency": {
                "min": self.min_latency if self.min_latency != float('inf') else None,
                "max": self.max_latency,
                "avg": self.avg_latency,
                "current": self.latency_samples[-1] if self.latency_samples else None
            }
        }

    def get_health_score(self) -> float:
        """Calculate health score (0-1)"""
        if self.total_heartbeats == 0:
            return 0.0
        
        # Weight different factors
        heartbeat_ratio = 1 - (self.missed_heartbeats / max(self.total_heartbeats, 1))
        consecutive_penalty = max(0, 1 - (self.consecutive_misses / 3))  # Penalty increases with consecutive misses
        
        return (heartbeat_ratio * 0.7 + consecutive_penalty * 0.3)

    def reset(self):
        """Reset metrics"""
        self.total_heartbeats = 0
        self.missed_heartbeats = 0
        self.consecutive_misses = 0
        self.last_heartbeat_time = None
        self.last_received_time = None
        self.total_latency = 0
        self.min_latency = float('inf')
        self.max_latency = 0
        self.avg_latency = 0
        self.latency_samples = []