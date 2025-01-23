from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import logging
import json
import asyncio
from enum import Enum
from collections import deque
import statistics
import threading
from dataclasses import dataclass, asdict
import time

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class MetricType(Enum):
    COUNTER = "COUNTER"
    GAUGE = "GAUGE"
    HISTOGRAM = "HISTOGRAM"
    RATE = "RATE"

@dataclass
class MetricValue:
    value: float
    timestamp: datetime
    labels: Dict[str, str]

class Metric:
    """Base class for metrics."""
    
    def __init__(self, name: str, metric_type: MetricType, description: str):
        self.name = name
        self.type = metric_type
        self.description = description
        self.values: deque = deque(maxlen=1000)  # Store last 1000 values
        self._lock = threading.Lock()

    def add_value(self, value: float, labels: Dict[str, str] = None):
        """Add a new value to the metric."""
        with self._lock:
            self.values.append(MetricValue(
                value=value,
                timestamp=datetime.utcnow(),
                labels=labels or {}
            ))

    def get_values(self, time_window: timedelta = None) -> List[MetricValue]:
        """Get metric values, optionally within a time window."""
        with self._lock:
            if not time_window:
                return list(self.values)
            
            cutoff = datetime.utcnow() - time_window
            return [v for v in self.values if v.timestamp >= cutoff]

class MetricsRegistry:
    """Registry for managing metrics."""
    
    def __init__(self):
        self.metrics: Dict[str, Metric] = {}
        self._lock = threading.Lock()

    def register_metric(self, metric: Metric):
        """Register a new metric."""
        with self._lock:
            if metric.name in self.metrics:
                raise ValueError(f"Metric {metric.name} already registered")
            self.metrics[metric.name] = metric

    def get_metric(self, name: str) -> Optional[Metric]:
        """Get a metric by name."""
        return self.metrics.get(name)

    def get_all_metrics(self) -> Dict[str, Metric]:
        """Get all registered metrics."""
        return self.metrics.copy()

class WebSocketMonitor:
    """Monitor for WebSocket connections and operations."""
    
    def __init__(self):
        self.metrics_registry = MetricsRegistry()
        self._setup_metrics()
        self._running = False
        self._monitor_task = None

    def _setup_metrics(self):
        """Set up default metrics."""
        # Connection metrics
        self.metrics_registry.register_metric(Metric(
            "ws_active_connections",
            MetricType.GAUGE,
            "Number of active WebSocket connections"
        ))
        
        self.metrics_registry.register_metric(Metric(
            "ws_connection_attempts",
            MetricType.COUNTER,
            "Number of connection attempts"
        ))
        
        self.metrics_registry.register_metric(Metric(
            "ws_message_rate",
            MetricType.RATE,
            "Rate of WebSocket messages per second"
        ))
        
        # Latency metrics
        self.metrics_registry.register_metric(Metric(
            "ws_message_latency",
            MetricType.HISTOGRAM,
            "Message processing latency in milliseconds"
        ))
        
        # Error metrics
        self.metrics_registry.register_metric(Metric(
            "ws_errors",
            MetricType.COUNTER,
            "Number of WebSocket errors"
        ))

    async def start_monitoring(self):
        """Start the monitoring process."""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_monitoring(self):
        """Stop the monitoring process."""
        self._running = False
        if self._monitor_task:
            await self._monitor_task

    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._collect_metrics()
                await asyncio.sleep(1)  # Collect metrics every second
            except Exception as e:
                logging.error(f"Error in monitor loop: {str(e)}")

    async def _collect_metrics(self):
        """Collect current metrics."""
        # Implement metric collection logic here
        pass

class WSLogger:
    """Custom logger for WebSocket operations."""
    
    def __init__(self, name: str, log_level: LogLevel = LogLevel.INFO):
        self.logger = logging.getLogger(name)
        self.log_level = log_level
        self._setup_logger()

    def _setup_logger(self):
        """Set up logger configuration."""
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Set log level
        self.logger.setLevel(self.log_level.value)

    def log(self, level: LogLevel, message: str, **kwargs):
        """Log a message with additional context."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "message": message,
            **kwargs
        }
        
        if level == LogLevel.DEBUG:
            self.logger.debug(json.dumps(log_data))
        elif level == LogLevel.INFO:
            self.logger.info(json.dumps(log_data))
        elif level == LogLevel.WARNING:
            self.logger.warning(json.dumps(log_data))
        elif level == LogLevel.ERROR:
            self.logger.error(json.dumps(log_data))
        elif level == LogLevel.CRITICAL:
            self.logger.critical(json.dumps(log_data))

class MonitoringService:
    """Service for managing WebSocket monitoring and logging."""
    
    def __init__(self):
        self.monitor = WebSocketMonitor()
        self.logger = WSLogger("websocket_monitor")
        self._performance_metrics: Dict[str, deque] = {
            "message_latency": deque(maxlen=1000),
            "connection_latency": deque(maxlen=1000)
        }

    async def start(self):
        """Start the monitoring service."""
        await self.monitor.start_monitoring()
        self.logger.log(LogLevel.INFO, "Monitoring service started")

    async def stop(self):
        """Stop the monitoring service."""
        await self.monitor.stop_monitoring()
        self.logger.log(LogLevel.INFO, "Monitoring service stopped")

    def record_message_latency(self, latency_ms: float):
        """Record message processing latency."""
        self._performance_metrics["message_latency"].append(latency_ms)

    def record_connection_latency(self, latency_ms: float):
        """Record connection establishment latency."""
        self._performance_metrics["connection_latency"].append(latency_ms)

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get current performance statistics."""
        stats = {}
        
        for metric_name, values in self._performance_metrics.items():
            if values:
                stats[metric_name] = {
                    "mean": statistics.mean(values),
                    "median": statistics.median(values),
                    "p95": statistics.quantiles(values, n=20)[18],  # 95th percentile
                    "min": min(values),
                    "max": max(values)
                }
            else:
                stats[metric_name] = None
        
        return stats

    async def generate_monitoring_report(self) -> Dict[str, Any]:
        """Generate a comprehensive monitoring report."""
        performance_stats = self.get_performance_stats()
        metrics = {
            name: [asdict(v) for v in metric.get_values()]
            for name, metric in self.monitor.metrics_registry.get_all_metrics().items()
        }
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "performance_stats": performance_stats,
            "metrics": metrics
        }

# Example usage
async def example_usage():
    # Initialize monitoring service
    service = MonitoringService()
    
    # Start monitoring
    await service.start()
    
    try:
        # Record some metrics
        service.record_message_latency(15.5)  # 15.5ms latency
        service.record_connection_latency(100.2)  # 100.2ms connection time
        
        # Log some events
        service.logger.log(
            LogLevel.INFO,
            "WebSocket connection established",
            connection_id="conn_123",
            client_ip="192.168.1.1"
        )
        
        # Generate report
        report = await service.generate_monitoring_report()
        print(json.dumps(report, indent=2))
        
    finally:
        # Stop monitoring
        await service.stop()

if __name__ == "__main__":
    asyncio.run(example_usage())