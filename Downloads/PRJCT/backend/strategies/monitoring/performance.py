from typing import Dict, Any, Optional
import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

class PerformanceMonitoringMixin:
    """Mixin for monitoring performance metrics"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = {
            'message_latency': deque(maxlen=1000),
            'processing_times': deque(maxlen=1000),
            'error_counts': {},
            'message_counts': {},
            'memory_usage': deque(maxlen=100),
            'cpu_usage': deque(maxlen=100)
        }
        self.start_time = timezone.now()
        self._monitoring_task = None

    async def start_performance_monitoring(self):
        """Start the performance monitoring background task"""
        self._monitoring_task = asyncio.create_task(self._monitor_performance())

    async def stop_performance_monitoring(self):
        """Stop the performance monitoring background task"""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

    async def _monitor_performance(self):
        """Background task to monitor system performance"""
        while True:
            try:
                # Monitor message processing
                self.metrics['cpu_usage'].append({
                    'timestamp': timezone.now().isoformat(),
                    'value': len(self.metrics['message_latency'])  # Messages processed
                })

                # Calculate metrics
                self._calculate_metrics()

                # Log metrics if they exceed thresholds
                self._check_thresholds()

                await asyncio.sleep(60)  # Monitor every minute
            except Exception as e:
                logger.error(f"Error in performance monitoring: {str(e)}")
                await asyncio.sleep(5)

    def _calculate_metrics(self):
        """Calculate current performance metrics"""
        now = timezone.now()
        
        # Calculate message rates
        one_minute_ago = now - timedelta(minutes=1)
        recent_messages = [
            t for t in self.metrics['message_latency']
            if t['timestamp'] > one_minute_ago
        ]
        
        self.current_metrics = {
            'messages_per_minute': len(recent_messages),
            'average_latency': sum(m['latency'] for m in recent_messages) / len(recent_messages) if recent_messages else 0,
            'error_rate': sum(self.metrics['error_counts'].values()) / len(recent_messages) if recent_messages else 0,
            'uptime_hours': (now - self.start_time).total_seconds() / 3600,
            'total_messages': sum(self.metrics['message_counts'].values()),
            'total_errors': sum(self.metrics['error_counts'].values())
        }

    def _check_thresholds(self):
        """Check if any metrics exceed warning thresholds"""
        thresholds = {
            'messages_per_minute': getattr(settings, 'MAX_MESSAGES_PER_MINUTE', 1000),
            'error_rate': 0.1,  # 10% error rate
            'average_latency': 1.0  # 1 second
        }

        for metric, value in self.current_metrics.items():
            if metric in thresholds and value > thresholds[metric]:
                logger.warning(
                    f"Performance threshold exceeded for {metric}: {value}",
                    extra={'extra_fields': {
                        'metric': metric,
                        'value': value,
                        'threshold': thresholds[metric]
                    }}
                )

    def record_message_latency(self, message_type: str, latency: float):
        """Record message processing latency"""
        self.metrics['message_latency'].append({
            'timestamp': timezone.now(),
            'type': message_type,
            'latency': latency
        })
        
        # Update message counts
        self.metrics['message_counts'][message_type] = \
            self.metrics['message_counts'].get(message_type, 0) + 1

    def record_error(self, error_type: str):
        """Record error occurrence"""
        self.metrics['error_counts'][error_type] = \
            self.metrics['error_counts'].get(error_type, 0) + 1

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics"""
        self._calculate_metrics()
        return {
            'current_metrics': self.current_metrics,
            'error_counts': dict(self.metrics['error_counts']),
            'message_counts': dict(self.metrics['message_counts']),
            'recent_latencies': list(self.metrics['message_latency'])[-10:],
            'message_rate_trend': list(self.metrics['cpu_usage'])[-10:],
        }

    def get_health_check(self) -> Dict[str, Any]:
        """Get basic health check information"""
        return {
            'status': 'healthy' if self.current_metrics['error_rate'] < 0.1 else 'degraded',
            'uptime_hours': self.current_metrics['uptime_hours'],
            'total_messages': self.current_metrics['total_messages'],
            'error_rate': self.current_metrics['error_rate']
        }