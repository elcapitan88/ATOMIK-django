"""
Enhanced Logging System with Context and Error Details

Provides structured logging with correlation IDs, context data, and detailed
error information for better debugging and monitoring of trading operations.
"""

import logging
import json
import traceback
import sys
import time
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager
from functools import wraps

from ..core.correlation import CorrelationManager, CorrelationLogger

class LogContext:
    """Thread-local context for logging additional information"""
    
    def __init__(self):
        self._context: Dict[str, Any] = {}
    
    def set(self, key: str, value: Any):
        """Set a context value"""
        self._context[key] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a context value"""
        return self._context.get(key, default)
    
    def update(self, context: Dict[str, Any]):
        """Update context with multiple values"""
        self._context.update(context)
    
    def clear(self):
        """Clear all context"""
        self._context.clear()
    
    def copy(self) -> Dict[str, Any]:
        """Get a copy of current context"""
        return self._context.copy()

# Global log context instance
log_context = LogContext()

@dataclass
class ErrorDetails:
    """Structured error information"""
    error_type: str
    error_message: str
    error_code: Optional[str] = None
    stack_trace: Optional[str] = None
    context_data: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    operation: Optional[str] = None
    component: Optional[str] = None

class EnhancedLogger:
    """
    Enhanced logger with structured logging and context management
    """
    
    def __init__(self, name: str):
        self.logger = CorrelationLogger(name)
        self.name = name
    
    def _build_log_data(
        self, 
        message: str, 
        level: str,
        extra_context: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
        operation: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build structured log data"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "logger": self.name,
            "message": message,
            "correlation_id": CorrelationManager.get_correlation_id(),
        }
        
        # Add operation context
        if operation:
            log_data["operation"] = operation
        
        # Add global log context
        context = log_context.copy()
        if context:
            log_data["context"] = context
        
        # Add extra context
        if extra_context:
            log_data["extra_context"] = extra_context
        
        # Add error details if present
        if error:
            error_details = self._extract_error_details(error, operation)
            log_data["error"] = asdict(error_details)
        
        return log_data
    
    def _extract_error_details(self, error: Exception, operation: Optional[str] = None) -> ErrorDetails:
        """Extract detailed error information"""
        return ErrorDetails(
            error_type=type(error).__name__,
            error_message=str(error),
            stack_trace=traceback.format_exc(),
            context_data=log_context.copy(),
            correlation_id=CorrelationManager.get_correlation_id(),
            operation=operation,
            component=self.name
        )
    
    def debug(self, message: str, **kwargs):
        """Log debug message with context"""
        log_data = self._build_log_data(message, "DEBUG", kwargs.get("extra_context"), kwargs.get("error"), kwargs.get("operation"))
        self.logger.debug(f"{message} | {json.dumps(log_data, default=str)}")
    
    def info(self, message: str, **kwargs):
        """Log info message with context"""
        log_data = self._build_log_data(message, "INFO", kwargs.get("extra_context"), kwargs.get("error"), kwargs.get("operation"))
        self.logger.info(f"{message} | {json.dumps(log_data, default=str)}")
    
    def warning(self, message: str, **kwargs):
        """Log warning message with context"""
        log_data = self._build_log_data(message, "WARNING", kwargs.get("extra_context"), kwargs.get("error"), kwargs.get("operation"))
        self.logger.warning(f"{message} | {json.dumps(log_data, default=str)}")
    
    def error(self, message: str, **kwargs):
        """Log error message with context"""
        log_data = self._build_log_data(message, "ERROR", kwargs.get("extra_context"), kwargs.get("error"), kwargs.get("operation"))
        self.logger.error(f"{message} | {json.dumps(log_data, default=str)}")
    
    def critical(self, message: str, **kwargs):
        """Log critical message with context"""
        log_data = self._build_log_data(message, "CRITICAL", kwargs.get("extra_context"), kwargs.get("error"), kwargs.get("operation"))
        self.logger.critical(f"{message} | {json.dumps(log_data, default=str)}")
    
    def exception(self, message: str, **kwargs):
        """Log exception with full context and stack trace"""
        exc_type, exc_value, exc_traceback = sys.exc_info()
        
        if exc_value:
            kwargs["error"] = exc_value
        
        log_data = self._build_log_data(message, "ERROR", kwargs.get("extra_context"), kwargs.get("error"), kwargs.get("operation"))
        self.logger.error(f"{message} | {json.dumps(log_data, default=str)}")
    
    def log_operation_start(self, operation: str, **context_data):
        """Log the start of an operation"""
        self.info(f"OPERATION_START: {operation}", operation=operation, extra_context=context_data)
    
    def log_operation_end(self, operation: str, success: bool = True, duration: Optional[float] = None, **context_data):
        """Log the end of an operation"""
        status = "SUCCESS" if success else "FAILED"
        extra_context = {**context_data}
        if duration is not None:
            extra_context["duration_seconds"] = duration
        
        level_method = self.info if success else self.error
        level_method(f"OPERATION_END: {operation} [{status}]", operation=operation, extra_context=extra_context)
    
    def log_trading_event(self, event_type: str, strategy_id: str, account_id: str, **event_data):
        """Log trading-specific events with structured data"""
        context = {
            "event_type": event_type,
            "strategy_id": strategy_id,
            "account_id": account_id,
            **event_data
        }
        self.info(f"TRADING_EVENT: {event_type}", operation="trading", extra_context=context)
    
    def log_performance_metric(self, metric_name: str, value: Union[int, float], unit: str = "", **metadata):
        """Log performance metrics"""
        context = {
            "metric_name": metric_name,
            "value": value,
            "unit": unit,
            **metadata
        }
        self.info(f"PERFORMANCE_METRIC: {metric_name}={value}{unit}", operation="performance", extra_context=context)

@contextmanager
def logging_context(**context_data):
    """Context manager to set logging context for a block of code"""
    original_context = log_context.copy()
    try:
        log_context.update(context_data)
        yield
    finally:
        log_context.clear()
        log_context.update(original_context)

@contextmanager
def operation_logging(logger: EnhancedLogger, operation_name: str, **context_data):
    """Context manager for logging operation start/end with timing"""
    start_time = time.time()
    
    logger.log_operation_start(operation_name, **context_data)
    
    try:
        yield
        duration = time.time() - start_time
        logger.log_operation_end(operation_name, success=True, duration=duration, **context_data)
    except Exception as e:
        duration = time.time() - start_time
        logger.log_operation_end(operation_name, success=False, duration=duration, error=str(e), **context_data)
        raise

def log_exceptions(operation: str = None):
    """Decorator to automatically log exceptions with context"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger = EnhancedLogger(func.__module__)
            op_name = operation or f"{func.__name__}"
            
            try:
                with logging_context(function=func.__name__, module=func.__module__):
                    return await func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Exception in {op_name}", operation=op_name, error=e)
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger = EnhancedLogger(func.__module__)
            op_name = operation or f"{func.__name__}"
            
            try:
                with logging_context(function=func.__name__, module=func.__module__):
                    return func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Exception in {op_name}", operation=op_name, error=e)
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

def log_performance(metric_name: str, logger_name: str = __name__):
    """Decorator to log performance metrics for functions"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger = EnhancedLogger(logger_name)
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                logger.log_performance_metric(metric_name, duration, "seconds", function=func.__name__, status="success")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.log_performance_metric(metric_name, duration, "seconds", function=func.__name__, status="failed", error=str(e))
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger = EnhancedLogger(logger_name)
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                logger.log_performance_metric(metric_name, duration, "seconds", function=func.__name__, status="success")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.log_performance_metric(metric_name, duration, "seconds", function=func.__name__, status="failed", error=str(e))
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

# Convenience functions for common logging patterns
def get_enhanced_logger(name: str) -> EnhancedLogger:
    """Get an enhanced logger instance"""
    return EnhancedLogger(name)

def log_trading_operation(logger: EnhancedLogger, operation: str, strategy_id: str, account_id: str, **context):
    """Log a trading operation with standard context"""
    with logging_context(strategy_id=strategy_id, account_id=account_id, **context):
        logger.info(f"Trading operation: {operation}", operation="trading_operation")

def log_webhook_processing(logger: EnhancedLogger, webhook_id: str, payload: Dict[str, Any], **context):
    """Log webhook processing with standard context"""
    with logging_context(webhook_id=webhook_id, payload_hash=hash(str(payload)), **context):
        logger.info(f"Processing webhook: {webhook_id}", operation="webhook_processing")

def log_order_execution(logger: EnhancedLogger, order_data: Dict[str, Any], **context):
    """Log order execution with standard context"""
    with logging_context(
        symbol=order_data.get("symbol"),
        side=order_data.get("side"),
        quantity=order_data.get("quantity"),
        account_id=order_data.get("account_id"),
        **context
    ):
        logger.info(f"Executing order: {order_data.get('side')} {order_data.get('quantity')} {order_data.get('symbol')}", operation="order_execution")

# Import asyncio at the end to avoid circular imports
import asyncio