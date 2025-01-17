import logging
from typing import Dict, Any
from django.http import HttpRequest

logger = logging.getLogger(__name__)

class WebhookValidationError(Exception):
    pass

def get_client_ip(request: HttpRequest) -> str:
    """Extract the client IP address from the request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

def validate_tradingview_payload(payload: Dict[str, Any]) -> bool:
    """Validate TradingView webhook payload structure."""
    required_fields = ['strategy', 'action']
    return all(field in payload for field in required_fields)

def validate_trendspider_payload(payload: Dict[str, Any]) -> bool:
    """Validate TrendSpider webhook payload structure."""
    required_fields = ['alert', 'action']
    return all(field in payload for field in required_fields)

def normalize_payload(source_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize different webhook payloads into a standard format."""
    if source_type == 'tradingview':
        return {
            'action': payload['action'],
            'strategy': payload['strategy'],
            'source': 'tradingview'
        }
    elif source_type == 'trendspider':
        return {
            'action': payload['action'],
            'strategy': payload['alert'],
            'source': 'trendspider'
        }
    return payload

def get_sample_payload(source_type: str) -> Dict[str, Any]:
    """Get sample payload for testing based on source type."""
    if source_type == 'tradingview':
        return {
            'strategy': 'Test Strategy',
            'action': 'BUY'
        }
    elif source_type == 'trendspider':
        return {
            'alert': 'Test Alert',
            'action': 'BUY'
        }
    return {
        'strategy': 'Custom Strategy',
        'action': 'BUY'
    }