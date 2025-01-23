from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class WebSocketErrorType(Enum):
    # Connection Errors
    CONNECTION_FAILED = "CONNECTION_FAILED"
    CONNECTION_LOST = "CONNECTION_LOST"
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    
    # Authentication Errors
    AUTH_FAILED = "AUTH_FAILED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    
    # Message Errors
    INVALID_MESSAGE = "INVALID_MESSAGE"
    MESSAGE_PARSE_ERROR = "MESSAGE_PARSE_ERROR"
    MESSAGE_TOO_LARGE = "MESSAGE_TOO_LARGE"
    
    # State Errors
    INVALID_STATE = "INVALID_STATE"
    STATE_SYNC_ERROR = "STATE_SYNC_ERROR"
    
    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    
    # Broker-Specific Errors
    BROKER_ERROR = "BROKER_ERROR"
    BROKER_TIMEOUT = "BROKER_TIMEOUT"
    BROKER_REJECTED = "BROKER_REJECTED"
    
    # System Errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RESOURCE_ERROR = "RESOURCE_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"

class ErrorSeverity(Enum):
    LOW = "LOW"           # Non-critical errors, can continue operation
    MEDIUM = "MEDIUM"     # Affects functionality but not critical
    HIGH = "HIGH"        # Serious issues requiring immediate attention
    CRITICAL = "CRITICAL" # System-wide failures

class WebSocketError(Exception):
    """Base exception class for WebSocket-related errors."""
    
    def __init__(
        self,
        error_type: WebSocketErrorType,
        message: str,
        severity: ErrorSeverity,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(message)
        self.error_type = error_type
        self.severity = severity
        self.details = details or {}
        self.timestamp = datetime.utcnow()
        self.original_error = original_error

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary format for logging and transmission."""
        return {
            "error_type": self.error_type.value,
            "message": str(self),
            "severity": self.severity.value,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "original_error": str(self.original_error) if self.original_error else None
        }

    def log_error(self):
        """Log the error with appropriate severity level."""
        error_dict = self.to_dict()
        if self.severity == ErrorSeverity.CRITICAL:
            logger.critical(f"Critical WebSocket Error: {error_dict}")
        elif self.severity == ErrorSeverity.HIGH:
            logger.error(f"WebSocket Error: {error_dict}")
        elif self.severity == ErrorSeverity.MEDIUM:
            logger.warning(f"WebSocket Warning: {error_dict}")
        else:
            logger.info(f"WebSocket Info: {error_dict}")

class ConnectionError(WebSocketError):
    """Errors related to WebSocket connections."""
    def __init__(
        self,
        error_type: WebSocketErrorType,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(
            error_type=error_type,
            message=message,
            severity=ErrorSeverity.HIGH,
            details=details,
            original_error=original_error
        )

class AuthenticationError(WebSocketError):
    """Authentication-related errors."""
    def __init__(
        self,
        error_type: WebSocketErrorType,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(
            error_type=error_type,
            message=message,
            severity=ErrorSeverity.HIGH,
            details=details,
            original_error=original_error
        )

class MessageError(WebSocketError):
    """Message processing and validation errors."""
    def __init__(
        self,
        error_type: WebSocketErrorType,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(
            error_type=error_type,
            message=message,
            severity=ErrorSeverity.MEDIUM,
            details=details,
            original_error=original_error
        )

class StateError(WebSocketError):
    """State management and synchronization errors."""
    def __init__(
        self,
        error_type: WebSocketErrorType,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(
            error_type=error_type,
            message=message,
            severity=ErrorSeverity.HIGH,
            details=details,
            original_error=original_error
        )

class RateLimitError(WebSocketError):
    """Rate limiting errors."""
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(
            error_type=WebSocketErrorType.RATE_LIMIT_EXCEEDED,
            message=message,
            severity=ErrorSeverity.MEDIUM,
            details=details,
            original_error=original_error
        )

class BrokerError(WebSocketError):
    """Broker-specific errors."""
    def __init__(
        self,
        error_type: WebSocketErrorType,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(
            error_type=error_type,
            message=message,
            severity=ErrorSeverity.HIGH,
            details=details,
            original_error=original_error
        )

class SystemError(WebSocketError):
    """System-level errors."""
    def __init__(
        self,
        error_type: WebSocketErrorType,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(
            error_type=error_type,
            message=message,
            severity=ErrorSeverity.CRITICAL,
            details=details,
            original_error=original_error
        )

def handle_websocket_error(error: WebSocketError) -> Dict[str, Any]:
    """
    Central error handler for WebSocket errors.
    Returns a standardized error response format.
    """
    error.log_error()
    
    response = {
        "success": False,
        "error": error.to_dict(),
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Add additional context based on error type
    if isinstance(error, ConnectionError):
        response["recommendation"] = "Please check your connection and try again."
    elif isinstance(error, AuthenticationError):
        response["recommendation"] = "Please reauthenticate and try again."
    elif isinstance(error, RateLimitError):
        response["recommendation"] = "Please reduce request frequency."
    
    return response

# Example usage:
def example_error_handling():
    try:
        # Simulate a connection error
        raise ConnectionError(
            error_type=WebSocketErrorType.CONNECTION_FAILED,
            message="Failed to establish WebSocket connection",
            details={"host": "example.com", "port": 8080}
        )
    except WebSocketError as e:
        error_response = handle_websocket_error(e)
        # Handle the error response (e.g., send to client, log, etc.)
        return error_response