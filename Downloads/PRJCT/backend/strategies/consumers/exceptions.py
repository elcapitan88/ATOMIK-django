# strategies/consumers/exceptions.py

class WebSocketError(Exception):
    """Base exception for WebSocket errors."""
    pass

class WebSocketValidationError(WebSocketError):
    """Raised when WebSocket message validation fails."""
    pass

class WebSocketAuthenticationError(WebSocketError):
    """Raised when WebSocket authentication fails."""
    pass

class WebSocketConnectionError(WebSocketError):
    """Raised when WebSocket connection fails."""
    pass

class WebSocketMessageError(WebSocketError):
    """Raised when processing WebSocket message fails."""
    pass