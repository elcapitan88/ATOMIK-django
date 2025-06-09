"""
Alert Manager for Trading System Monitoring

Handles alerts for worker crashes, system failures, and trading anomalies.
Provides logging and Redis storage for monitoring dashboard integration.
"""

import asyncio
import logging
import time
import json
from typing import Dict, Any, List, Optional, Set, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta

from ..core.correlation import CorrelationLogger, CorrelationManager
from ..core.redis_manager import get_redis_connection
from redis.exceptions import RedisError

logger = CorrelationLogger(__name__)

class AlertSeverity(Enum):
    """Alert severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class AlertType(Enum):
    """Types of alerts"""
    WORKER_CRASH = "worker_crash"
    WORKER_MEMORY_HIGH = "worker_memory_high"
    TRADING_FAILURE = "trading_failure"
    STRATEGY_FAILURE = "strategy_failure"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    DATABASE_ERROR = "database_error"
    REDIS_UNAVAILABLE = "redis_unavailable"
    WEBHOOK_FAILURE = "webhook_failure"
    ORDER_EXECUTION_FAILED = "order_execution_failed"
    ROLLBACK_FAILURE = "rollback_failure"
    SYSTEM_OVERLOAD = "system_overload"

@dataclass
class Alert:
    """Represents a system alert"""
    alert_id: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    context_data: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False
    resolved: bool = False
    notification_sent: bool = False
    retry_count: int = 0
    max_retries: int = 3

class AlertManager:
    """
    Manages system alerts with logging and Redis storage
    """
    
    def __init__(self):
        self._active_alerts: Dict[str, Alert] = {}
        self._alert_handlers: Dict[AlertType, List[Callable]] = {}
        self._alert_rate_limits: Dict[str, float] = {}  # Rate limiting for duplicate alerts
        self._lock = asyncio.Lock()
        
        # Default rate limits (seconds between duplicate alerts of same type)
        self._default_rate_limits = {
            AlertType.WORKER_CRASH: 60,  # 1 minute
            AlertType.WORKER_MEMORY_HIGH: 300,  # 5 minutes
            AlertType.TRADING_FAILURE: 30,  # 30 seconds
            AlertType.STRATEGY_FAILURE: 60,  # 1 minute
            AlertType.CIRCUIT_BREAKER_OPEN: 300,  # 5 minutes
            AlertType.DATABASE_ERROR: 60,  # 1 minute
            AlertType.REDIS_UNAVAILABLE: 300,  # 5 minutes
            AlertType.WEBHOOK_FAILURE: 30,  # 30 seconds
            AlertType.ORDER_EXECUTION_FAILED: 30,  # 30 seconds
            AlertType.ROLLBACK_FAILURE: 60,  # 1 minute
            AlertType.SYSTEM_OVERLOAD: 300,  # 5 minutes
        }
    
    async def send_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        context_data: Optional[Dict[str, Any]] = None,
        alert_id: Optional[str] = None
    ) -> Optional[Alert]:
        """
        Send an alert through the alert system
        
        Args:
            alert_type: Type of alert
            severity: Severity level
            title: Short alert title
            message: Detailed alert message
            context_data: Additional context information
            alert_id: Optional custom alert ID
            
        Returns:
            Alert object if sent, None if rate limited
        """
        if context_data is None:
            context_data = {}
        
        # Check rate limiting
        if await self._is_rate_limited(alert_type, alert_id):
            logger.debug(f"Alert rate limited: {alert_type.value}")
            return None
        
        if alert_id is None:
            alert_id = f"{alert_type.value}_{int(time.time() * 1000)}"
        
        correlation_id = CorrelationManager.get_correlation_id()
        
        alert = Alert(
            alert_id=alert_id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            context_data=context_data,
            correlation_id=correlation_id
        )
        
        async with self._lock:
            self._active_alerts[alert_id] = alert
        
        # Execute alert handlers
        await self._execute_alert_handlers(alert)
        
        # Send to logging system
        await self._log_alert(alert)
        
        # Persist alert for monitoring
        await self._persist_alert(alert)
        
        alert.notification_sent = True
        
        return alert
    
    async def _is_rate_limited(self, alert_type: AlertType, alert_id: Optional[str] = None) -> bool:
        """Check if alert type is rate limited"""
        rate_limit_key = f"{alert_type.value}:{alert_id}" if alert_id else alert_type.value
        current_time = time.time()
        
        if rate_limit_key in self._alert_rate_limits:
            last_sent = self._alert_rate_limits[rate_limit_key]
            rate_limit = self._default_rate_limits.get(alert_type, 60)
            
            if current_time - last_sent < rate_limit:
                return True
        
        # Update rate limit timestamp
        self._alert_rate_limits[rate_limit_key] = current_time
        return False
    
    async def _execute_alert_handlers(self, alert: Alert):
        """Execute registered alert handlers"""
        handlers = self._alert_handlers.get(alert.alert_type, [])
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                logger.error(f"Error in alert handler for {alert.alert_type.value}: {e}")
    
    async def _log_alert(self, alert: Alert):
        """Send alert to logging system with appropriate severity"""
        log_level = {
            AlertSeverity.LOW: logging.INFO,
            AlertSeverity.MEDIUM: logging.WARNING,
            AlertSeverity.HIGH: logging.ERROR,
            AlertSeverity.CRITICAL: logging.CRITICAL
        }.get(alert.severity, logging.WARNING)
        
        context_str = ""
        if alert.context_data:
            context_items = [f"{k}={v}" for k, v in alert.context_data.items()]
            context_str = f" | Context: {', '.join(context_items)}"
        
        correlation_str = ""
        if alert.correlation_id:
            correlation_str = f" | Correlation: {alert.correlation_id[:8]}"
        
        log_message = f"ALERT [{alert.severity.value.upper()}] {alert.alert_type.value}: {alert.title} - {alert.message}{context_str}{correlation_str}"
        
        # Use the correlation logger to include correlation ID
        corr_logger = CorrelationLogger(__name__)
        corr_logger.log(log_level, log_message)
    
    async def _persist_alert(self, alert: Alert):
        """Persist alert to Redis for monitoring dashboard"""
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    logger.debug("Redis unavailable, skipping alert persistence")
                    return
                
                alert_key = f"alert:{alert.alert_id}"
                alert_data = {
                    "alert_id": alert.alert_id,
                    "alert_type": alert.alert_type.value,
                    "severity": alert.severity.value,
                    "title": alert.title,
                    "message": alert.message,
                    "context_data": alert.context_data,
                    "correlation_id": alert.correlation_id,
                    "timestamp": alert.timestamp,
                    "acknowledged": alert.acknowledged,
                    "resolved": alert.resolved,
                    "notification_sent": alert.notification_sent
                }
                
                # Store alert with TTL (keep for 7 days)
                redis_client.setex(alert_key, 7 * 24 * 3600, json.dumps(alert_data))
                
                # Add to recent alerts list
                recent_alerts_key = "recent_alerts"
                redis_client.lpush(recent_alerts_key, alert.alert_id)
                redis_client.ltrim(recent_alerts_key, 0, 99)  # Keep last 100 alerts
                
                # Update alert counters by type and severity
                today = datetime.now().strftime("%Y-%m-%d")
                type_counter_key = f"alert_count:type:{alert.alert_type.value}:{today}"
                severity_counter_key = f"alert_count:severity:{alert.severity.value}:{today}"
                
                redis_client.incr(type_counter_key)
                redis_client.expire(type_counter_key, 7 * 24 * 3600)  # 7 days
                redis_client.incr(severity_counter_key)
                redis_client.expire(severity_counter_key, 7 * 24 * 3600)  # 7 days
                
                logger.debug(f"Persisted alert to Redis: {alert.alert_id}")
                
        except RedisError as e:
            logger.warning(f"Failed to persist alert to Redis: {e}")
        except Exception as e:
            logger.error(f"Unexpected error persisting alert: {e}")
    
    def register_alert_handler(self, alert_type: AlertType, handler: Callable[[Alert], Any]):
        """Register a handler for specific alert types"""
        if alert_type not in self._alert_handlers:
            self._alert_handlers[alert_type] = []
        
        self._alert_handlers[alert_type].append(handler)
        logger.info(f"Registered alert handler for {alert_type.value}")
    
    async def acknowledge_alert(self, alert_id: str, acknowledged_by: str = "system") -> bool:
        """Acknowledge an alert"""
        async with self._lock:
            if alert_id in self._active_alerts:
                alert = self._active_alerts[alert_id]
                alert.acknowledged = True
                
                logger.info(f"Alert acknowledged: {alert_id} by {acknowledged_by}")
                
                # Update persisted alert
                await self._persist_alert(alert)
                return True
        
        return False
    
    async def resolve_alert(self, alert_id: str, resolved_by: str = "system") -> bool:
        """Mark an alert as resolved"""
        async with self._lock:
            if alert_id in self._active_alerts:
                alert = self._active_alerts[alert_id]
                alert.resolved = True
                alert.acknowledged = True
                
                logger.info(f"Alert resolved: {alert_id} by {resolved_by}")
                
                # Update persisted alert
                await self._persist_alert(alert)
                
                # Remove from active alerts
                del self._active_alerts[alert_id]
                return True
        
        return False
    
    async def get_active_alerts(self, severity: Optional[AlertSeverity] = None) -> List[Alert]:
        """Get list of active alerts, optionally filtered by severity"""
        async with self._lock:
            alerts = list(self._active_alerts.values())
        
        if severity:
            alerts = [alert for alert in alerts if alert.severity == severity]
        
        # Sort by timestamp (newest first)
        alerts.sort(key=lambda a: a.timestamp, reverse=True)
        return alerts
    
    async def get_alert_stats(self) -> Dict[str, Any]:
        """Get alert system statistics"""
        async with self._lock:
            active_count = len(self._active_alerts)
            severity_counts = {}
            type_counts = {}
            
            for alert in self._active_alerts.values():
                severity_counts[alert.severity.value] = severity_counts.get(alert.severity.value, 0) + 1
                type_counts[alert.alert_type.value] = type_counts.get(alert.alert_type.value, 0) + 1
        
        return {
            "active_alerts": active_count,
            "alert_handlers": sum(len(handlers) for handlers in self._alert_handlers.values()),
            "severity_breakdown": severity_counts,
            "type_breakdown": type_counts,
            "rate_limited_types": len(self._alert_rate_limits)
        }

# Specific alert sending functions for common scenarios
class TradingAlerts:
    """Helper class for sending trading-specific alerts"""
    
    @staticmethod
    async def worker_crash(worker_id: str, pid: int, signal: str, context: Dict[str, Any] = None):
        """Send worker crash alert"""
        if context is None:
            context = {}
        
        await alert_manager.send_alert(
            alert_type=AlertType.WORKER_CRASH,
            severity=AlertSeverity.CRITICAL,
            title=f"Worker Crash Detected",
            message=f"Worker {worker_id} (PID {pid}) crashed with signal {signal}",
            context_data={
                "worker_id": worker_id,
                "pid": pid,
                "signal": signal,
                **context
            }
        )
    
    @staticmethod
    async def trading_failure(strategy_id: str, account_id: str, error: str, context: Dict[str, Any] = None):
        """Send trading failure alert"""
        if context is None:
            context = {}
        
        await alert_manager.send_alert(
            alert_type=AlertType.TRADING_FAILURE,
            severity=AlertSeverity.HIGH,
            title=f"Trading Operation Failed",
            message=f"Strategy {strategy_id} failed on account {account_id}: {error}",
            context_data={
                "strategy_id": strategy_id,
                "account_id": account_id,
                "error": error,
                **context
            }
        )
    
    @staticmethod
    async def circuit_breaker_opened(circuit_name: str, failure_count: int, context: Dict[str, Any] = None):
        """Send circuit breaker opened alert"""
        if context is None:
            context = {}
        
        await alert_manager.send_alert(
            alert_type=AlertType.CIRCUIT_BREAKER_OPEN,
            severity=AlertSeverity.HIGH,
            title=f"Circuit Breaker Opened",
            message=f"Circuit breaker '{circuit_name}' opened after {failure_count} failures",
            context_data={
                "circuit_name": circuit_name,
                "failure_count": failure_count,
                **context
            }
        )
    
    @staticmethod
    async def rollback_failure(transaction_id: str, operation_type: str, error: str, context: Dict[str, Any] = None):
        """Send rollback failure alert"""
        if context is None:
            context = {}
        
        await alert_manager.send_alert(
            alert_type=AlertType.ROLLBACK_FAILURE,
            severity=AlertSeverity.CRITICAL,
            title=f"Transaction Rollback Failed",
            message=f"Failed to rollback {operation_type} transaction {transaction_id}: {error}",
            context_data={
                "transaction_id": transaction_id,
                "operation_type": operation_type,
                "error": error,
                **context
            }
        )
    
    @staticmethod
    async def strategy_failure(strategy_id: str, error: str, context: Dict[str, Any] = None):
        """Send strategy failure alert"""
        if context is None:
            context = {}
        
        await alert_manager.send_alert(
            alert_type=AlertType.STRATEGY_FAILURE,
            severity=AlertSeverity.MEDIUM,
            title=f"Strategy Execution Failed",
            message=f"Strategy {strategy_id} failed: {error}",
            context_data={
                "strategy_id": strategy_id,
                "error": error,
                **context
            }
        )
    
    @staticmethod
    async def webhook_failure(webhook_id: str, error: str, context: Dict[str, Any] = None):
        """Send webhook failure alert"""
        if context is None:
            context = {}
        
        await alert_manager.send_alert(
            alert_type=AlertType.WEBHOOK_FAILURE,
            severity=AlertSeverity.MEDIUM,
            title=f"Webhook Processing Failed",
            message=f"Webhook {webhook_id} failed: {error}",
            context_data={
                "webhook_id": webhook_id,
                "error": error,
                **context
            }
        )

# Global alert manager instance
alert_manager = AlertManager()