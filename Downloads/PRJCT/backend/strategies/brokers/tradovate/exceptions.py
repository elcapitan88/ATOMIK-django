# strategies/brokers/tradovate/exceptions.py
from ..base.exceptions import BrokerBaseException

class TradovateAPIError(BrokerBaseException):
    """Base exception for Tradovate API errors."""
    pass

class RateLimitExceeded(TradovateAPIError):
    """Raised when API rate limit is exceeded."""
    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after