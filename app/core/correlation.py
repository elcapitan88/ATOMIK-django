"""
Correlation ID management for request tracking across the trading system.

Provides unique identifiers for tracing requests through webhook processing,
strategy execution, and trade placement for better debugging and monitoring.
"""

import uuid
import threading
from typing import Optional, Dict, Any
from contextvars import ContextVar
import logging

logger = logging.getLogger(__name__)

# Context variable to store correlation ID across async calls
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)

class CorrelationManager:
    """
    Manages correlation IDs for request tracking throughout the application
    """
    
    @staticmethod
    def generate_correlation_id() -> str:
        """Generate a new correlation ID"""
        return str(uuid.uuid4())
    
    @staticmethod
    def set_correlation_id(correlation_id: Optional[str] = None) -> str:
        """
        Set correlation ID in context
        
        Args:
            correlation_id: Optional existing ID, generates new one if None
            
        Returns:
            str: The correlation ID that was set
        """
        if correlation_id is None:
            correlation_id = CorrelationManager.generate_correlation_id()
        
        correlation_id_var.set(correlation_id)
        logger.debug(f"Set correlation ID: {correlation_id}")
        return correlation_id
    
    @staticmethod
    def get_correlation_id() -> Optional[str]:
        """Get current correlation ID from context"""
        return correlation_id_var.get()
    
    @staticmethod
    def get_or_create_correlation_id() -> str:
        """Get existing correlation ID or create new one"""
        correlation_id = correlation_id_var.get()
        if correlation_id is None:
            correlation_id = CorrelationManager.set_correlation_id()
        return correlation_id
    
    @staticmethod
    def clear_correlation_id():
        """Clear correlation ID from context"""
        correlation_id_var.set(None)
        logger.debug("Cleared correlation ID")

class CorrelationLogger:
    """
    Enhanced logger that automatically includes correlation ID in log messages
    """
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
    
    def _log_with_correlation(self, level: int, msg: str, *args, **kwargs):
        """Add correlation ID to log message"""
        correlation_id = CorrelationManager.get_correlation_id()
        if correlation_id:
            if args:
                msg = f"[{correlation_id[:8]}] {msg}"
            else:
                msg = f"[{correlation_id[:8]}] {msg}"
        
        self.logger.log(level, msg, *args, **kwargs)
    
    def debug(self, msg: str, *args, **kwargs):
        self._log_with_correlation(logging.DEBUG, msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        self._log_with_correlation(logging.INFO, msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        self._log_with_correlation(logging.WARNING, msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        self._log_with_correlation(logging.ERROR, msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        self._log_with_correlation(logging.CRITICAL, msg, *args, **kwargs)
    
    def exception(self, msg: str, *args, **kwargs):
        self._log_with_correlation(logging.ERROR, msg, *args, exc_info=True, **kwargs)

def track_operation(operation_name: str, **context_data) -> Dict[str, Any]:
    """
    Create tracking context for an operation
    
    Args:
        operation_name: Name of the operation being tracked
        **context_data: Additional context data to track
        
    Returns:
        dict: Tracking context with correlation ID and metadata
    """
    correlation_id = CorrelationManager.get_or_create_correlation_id()
    
    tracking_context = {
        "correlation_id": correlation_id,
        "operation": operation_name,
        "timestamp": "%(asctime)s",
        **context_data
    }
    
    logger.debug(f"Tracking operation: {operation_name} [{correlation_id[:8]}]")
    return tracking_context

def log_operation_start(operation_name: str, **context_data):
    """Log the start of an operation with tracking context"""
    correlation_id = CorrelationManager.get_or_create_correlation_id()
    corr_logger = CorrelationLogger(__name__)
    
    context_str = ", ".join(f"{k}={v}" for k, v in context_data.items())
    corr_logger.info(f"STARTED {operation_name} - {context_str}")

def log_operation_end(operation_name: str, success: bool = True, **context_data):
    """Log the end of an operation with tracking context"""
    corr_logger = CorrelationLogger(__name__)
    
    status = "SUCCESS" if success else "FAILED"
    context_str = ", ".join(f"{k}={v}" for k, v in context_data.items())
    corr_logger.info(f"COMPLETED {operation_name} [{status}] - {context_str}")

def log_operation_error(operation_name: str, error: Exception, **context_data):
    """Log an operation error with tracking context"""
    corr_logger = CorrelationLogger(__name__)
    
    context_str = ", ".join(f"{k}={v}" for k, v in context_data.items())
    corr_logger.error(f"ERROR in {operation_name}: {str(error)} - {context_str}")