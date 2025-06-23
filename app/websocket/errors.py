"""
WebSocket Error Handling for Application Chat/UI Events

Provides comprehensive error handling for the application WebSocket system.
Adapted from the original trading WebSocket but focused on chat/UI errors.
"""

from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
import logging
from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """Error codes for Application WebSocket errors"""
    # Connection Errors (4000-4099)
    CONNECTION_FAILED = 4000
    CONNECTION_TIMEOUT = 4001
    CONNECTION_LIMIT_EXCEEDED = 4002
    CONNECTION_REJECTED = 4003
    
    # Authentication Errors (4100-4199)
    AUTH_FAILED = 4100
    AUTH_EXPIRED = 4101
    AUTH_INVALID = 4102
    AUTH_REQUIRED = 4103
    
    # Chat-specific Errors (4200-4299)
    CHANNEL_NOT_FOUND = 4200
    CHANNEL_ACCESS_DENIED = 4201
    MESSAGE_TOO_LONG = 4202
    RATE_LIMIT_EXCEEDED = 4203
    
    # Message Errors (4300-4399)
    MESSAGE_INVALID = 4300
    MESSAGE_TOO_LARGE = 4301
    MESSAGE_RATE_LIMITED = 4302
    MESSAGE_TYPE_INVALID = 4303
    
    # State Errors (4400-4499)
    STATE_INVALID = 4400
    STATE_TRANSITION_INVALID = 4401
    
    # Server Errors (4900-4999)
    SERVER_ERROR = 4900
    MAINTENANCE = 4901
    OVERLOADED = 4902


class ErrorSeverity(Enum):
    """Error severity levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class WebSocketError(Exception):
    """Base class for all Application WebSocket errors"""
    def __init__(
        self,
        message: str,
        code: ErrorCode,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.code = code
        self.severity = severity
        self.details = details or {}
        self.timestamp = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary format for sending to client"""
        return {
            "type": "error",
            "code": self.code.value,
            "message": str(self),
            "severity": self.severity.value,
            "details": self.details,
            "timestamp": self.timestamp.isoformat()
        }

    def log(self):
        """Log the error with appropriate severity"""
        log_message = f"[App WebSocket] {self.code.name}: {str(self)}"
        if self.details:
            log_message += f" - Details: {self.details}"

        if self.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message)
        elif self.severity == ErrorSeverity.ERROR:
            logger.error(log_message)
        elif self.severity == ErrorSeverity.WARNING:
            logger.warning(log_message)
        elif self.severity == ErrorSeverity.INFO:
            logger.info(log_message)
        else:
            logger.debug(log_message)


class ConnectionError(WebSocketError):
    """Connection-related errors"""
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.CONNECTION_FAILED,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, code, severity, details)


class AuthenticationError(WebSocketError):
    """Authentication-related errors"""
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.AUTH_FAILED,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, code, severity, details)


class ChatError(WebSocketError):
    """Chat-specific errors"""
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.CHANNEL_NOT_FOUND,
        severity: ErrorSeverity = ErrorSeverity.WARNING,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, code, severity, details)


class MessageError(WebSocketError):
    """Message processing errors"""
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.MESSAGE_INVALID,
        severity: ErrorSeverity = ErrorSeverity.WARNING,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, code, severity, details)


class RateLimitError(WebSocketError):
    """Rate limiting errors"""
    def __init__(
        self,
        message: str,
        retry_after: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(
            message,
            ErrorCode.RATE_LIMIT_EXCEEDED,
            ErrorSeverity.WARNING,
            details
        )


async def handle_websocket_error(
    error: Exception,
    websocket: Optional[WebSocket] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Handle WebSocket errors and perform appropriate cleanup
    
    Args:
        error: The exception to handle
        websocket: Optional WebSocket connection
        user_id: Optional user identifier
    
    Returns:
        Dict containing error details
    """
    try:
        # Convert to WebSocket error if needed
        if not isinstance(error, WebSocketError):
            if "auth" in str(error).lower():
                ws_error = AuthenticationError(str(error))
            elif "channel" in str(error).lower():
                ws_error = ChatError(str(error))
            elif "rate" in str(error).lower():
                ws_error = RateLimitError(str(error))
            elif "message" in str(error).lower():
                ws_error = MessageError(str(error))
            else:
                ws_error = WebSocketError(
                    str(error),
                    ErrorCode.SERVER_ERROR,
                    ErrorSeverity.ERROR
                )
        else:
            ws_error = error

        # Log the error
        ws_error.log()

        # Close WebSocket if provided and still connected
        if websocket and websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=ws_error.code.value, reason=str(ws_error))
            except Exception as close_error:
                logger.error(f"Error closing WebSocket: {str(close_error)}")

        # Create error response
        error_response = ws_error.to_dict()
        if user_id:
            error_response["user_id"] = user_id

        return error_response

    except Exception as handling_error:
        logger.error(f"Error in error handler: {str(handling_error)}")
        return {
            "type": "error",
            "code": ErrorCode.SERVER_ERROR.value,
            "message": "Error handling failed",
            "severity": ErrorSeverity.CRITICAL.value,
            "timestamp": datetime.utcnow().isoformat()
        }


# Export everything needed by other modules
__all__ = [
    'ErrorCode',
    'ErrorSeverity',  
    'WebSocketError',
    'ConnectionError',
    'AuthenticationError',
    'ChatError',
    'MessageError',
    'RateLimitError',
    'handle_websocket_error'
]