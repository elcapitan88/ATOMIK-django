import psutil
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass

from .redis_manager import redis_manager

logger = logging.getLogger(__name__)

@dataclass
class MemoryMetrics:
    """Memory usage metrics"""
    rss_mb: float  # Resident Set Size in MB
    vms_mb: float  # Virtual Memory Size in MB
    percent: float  # Memory percentage
    available_mb: float  # Available system memory in MB
    timestamp: datetime

class MemoryMonitor:
    """Monitor application memory usage and resource health"""
    
    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._metrics_history = []
        self._max_history = 100  # Keep last 100 measurements
        
        # Memory thresholds
        self.warning_threshold_mb = 512  # 512MB warning
        self.critical_threshold_mb = 1024  # 1GB critical
        self.memory_percent_warning = 75  # 75% system memory warning
        
    async def start_monitoring(self):
        """Start memory monitoring"""
        if self._monitoring:
            return
            
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Memory monitoring started")
        
    async def stop_monitoring(self):
        """Stop memory monitoring"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Memory monitoring stopped")
        
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        try:
            while self._monitoring:
                try:
                    # Collect metrics
                    metrics = self._collect_metrics()
                    
                    # Store in history
                    self._metrics_history.append(metrics)
                    if len(self._metrics_history) > self._max_history:
                        self._metrics_history.pop(0)
                    
                    # Check for warnings
                    await self._check_thresholds(metrics)
                    
                    # Store in Redis if available
                    await self._store_metrics_redis(metrics)
                    
                except Exception as e:
                    logger.error(f"Error in memory monitoring loop: {e}")
                
                await asyncio.sleep(self.check_interval)
                
        except asyncio.CancelledError:
            logger.info("Memory monitoring cancelled")
        except Exception as e:
            logger.error(f"Memory monitoring loop failed: {e}")
            
    def _collect_metrics(self) -> MemoryMetrics:
        """Collect current memory metrics"""
        try:
            # Get current process
            process = psutil.Process()
            memory_info = process.memory_info()
            
            # Get system memory
            system_memory = psutil.virtual_memory()
            
            return MemoryMetrics(
                rss_mb=memory_info.rss / 1024 / 1024,  # Convert to MB
                vms_mb=memory_info.vms / 1024 / 1024,  # Convert to MB
                percent=process.memory_percent(),
                available_mb=system_memory.available / 1024 / 1024,  # Convert to MB
                timestamp=datetime.utcnow()
            )
            
        except Exception as e:
            logger.error(f"Error collecting memory metrics: {e}")
            return MemoryMetrics(0, 0, 0, 0, datetime.utcnow())
            
    async def _check_thresholds(self, metrics: MemoryMetrics):
        """Check if memory usage exceeds thresholds"""
        try:
            # Check RSS memory usage
            if metrics.rss_mb > self.critical_threshold_mb:
                logger.critical(
                    f"CRITICAL: Memory usage {metrics.rss_mb:.1f}MB exceeds critical threshold "
                    f"{self.critical_threshold_mb}MB"
                )
                # Force garbage collection
                import gc
                gc.collect()
                
            elif metrics.rss_mb > self.warning_threshold_mb:
                logger.warning(
                    f"WARNING: Memory usage {metrics.rss_mb:.1f}MB exceeds warning threshold "
                    f"{self.warning_threshold_mb}MB"
                )
                
            # Check system memory percentage
            if metrics.percent > self.memory_percent_warning:
                logger.warning(
                    f"WARNING: Process using {metrics.percent:.1f}% of system memory"
                )
                
        except Exception as e:
            logger.error(f"Error checking memory thresholds: {e}")
            
    async def _store_metrics_redis(self, metrics: MemoryMetrics):
        """Store metrics in Redis for monitoring"""
        try:
            with redis_manager.get_connection() as redis_client:
                if redis_client:
                    # Store current metrics
                    metrics_data = {
                        "rss_mb": metrics.rss_mb,
                        "vms_mb": metrics.vms_mb,
                        "percent": metrics.percent,
                        "available_mb": metrics.available_mb,
                        "timestamp": metrics.timestamp.isoformat()
                    }
                    
                    # Store with TTL
                    redis_client.setex(
                        "memory_metrics:current",
                        300,  # 5 minute TTL
                        str(metrics_data)
                    )
                    
                    # Add to time series (keep last 24 hours)
                    timestamp = metrics.timestamp.timestamp()
                    redis_client.zadd(
                        "memory_metrics:timeseries",
                        {str(metrics_data): timestamp}
                    )
                    
                    # Remove old entries (older than 24 hours)
                    cutoff = (datetime.utcnow() - timedelta(hours=24)).timestamp()
                    redis_client.zremrangebyscore(
                        "memory_metrics:timeseries", 0, cutoff
                    )
                    
        except Exception as e:
            logger.debug(f"Could not store metrics in Redis: {e}")
            
    def get_current_metrics(self) -> Optional[MemoryMetrics]:
        """Get current memory metrics"""
        return self._collect_metrics()
        
    def get_metrics_history(self, limit: int = 50) -> list:
        """Get recent metrics history"""
        return self._metrics_history[-limit:]
        
    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics"""
        current = self.get_current_metrics()
        
        if not current:
            return {"status": "error", "message": "Could not collect metrics"}
            
        history = self.get_metrics_history(10)
        
        return {
            "status": "running" if self._monitoring else "stopped",
            "current": {
                "rss_mb": round(current.rss_mb, 2),
                "vms_mb": round(current.vms_mb, 2),
                "percent": round(current.percent, 2),
                "available_mb": round(current.available_mb, 2),
                "timestamp": current.timestamp.isoformat()
            },
            "thresholds": {
                "warning_mb": self.warning_threshold_mb,
                "critical_mb": self.critical_threshold_mb,
                "warning_percent": self.memory_percent_warning
            },
            "alerts": {
                "rss_warning": current.rss_mb > self.warning_threshold_mb,
                "rss_critical": current.rss_mb > self.critical_threshold_mb,
                "percent_warning": current.percent > self.memory_percent_warning
            },
            "history_count": len(history),
            "check_interval": self.check_interval
        }

# Global memory monitor instance
memory_monitor = MemoryMonitor()

def get_memory_monitor() -> MemoryMonitor:
    """Get the global memory monitor instance"""
    return memory_monitor