# strategies/brokers/base/exceptions.py

class BrokerBaseException(Exception):
    """Base exception class for all broker-related errors."""
    
    def __init__(self, message: str, code: str = None, details: dict = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

class WebSocketError(BrokerBaseException):
    """Base class for WebSocket-related errors."""
    pass

class WebSocketConnectionError(WebSocketError):
    """Raised when there's an error establishing or maintaining a WebSocket connection."""
    pass

class WebSocketAuthenticationError(WebSocketError):
    """Raised when WebSocket authentication fails."""
    pass

class WebSocketMessageError(WebSocketError):
    """Raised when there's an error sending or receiving WebSocket messages."""
    pass

class BrokerConnectionError(BrokerBaseException):
    """Raised when there's an error connecting to a broker's API."""
    pass

class BrokerAuthenticationError(BrokerBaseException):
    """Raised when broker authentication fails."""
    pass

class BrokerResponseError(BrokerBaseException):
    """Raised when receiving an invalid or error response from a broker."""
    pass

class BrokerValidationError(BrokerBaseException):
    """Raised when broker-related data validation fails."""
    pass

class OrderError(BrokerBaseException):
    """Base class for order-related errors."""
    pass

class OrderValidationError(OrderError):
    """Raised when order validation fails."""
    pass

class OrderExecutionError(OrderError):
    """Raised when order execution fails."""
    pass

class OrderCancellationError(OrderError):
    """Raised when order cancellation fails."""
    pass

class PositionError(BrokerBaseException):
    """Base class for position-related errors."""
    pass

class AccountError(BrokerBaseException):
    """Base class for account-related errors."""
    pass

class TokenError(BrokerBaseException):
    """Base class for token-related errors."""
    pass

class RateLimitError(BrokerBaseException):
    """Raised when rate limits are exceeded."""
    def __init__(self, message: str, retry_after: int = None, limit: int = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        self.limit = limit