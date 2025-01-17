# strategies/consumers/utils.py
import json
import logging
from typing import Dict, Any, Optional, Union
from decimal import Decimal
from datetime import datetime
from django.http import HttpRequest
from django.utils import timezone
from .exceptions import WebSocketValidationError

logger = logging.getLogger(__name__)

def get_client_ip(request: HttpRequest) -> str:
    """
    Extract the client IP address from the request.
    Handles both direct client IPs and those behind a proxy.
    
    Args:
        request: The Django request object
        
    Returns:
        str: The client's IP address
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

def validate_tradingview_payload(payload: Dict[str, Any]) -> bool:
    """
    Validate TradingView webhook payload structure.
    
    Args:
        payload: The webhook payload to validate
        
    Returns:
        bool: True if payload is valid
        
    Raises:
        WebSocketValidationError: If payload is invalid
    """
    required_fields = ['strategy', 'action']
    try:
        if not all(field in payload for field in required_fields):
            missing = [field for field in required_fields if field not in payload]
            raise WebSocketValidationError(f"Missing required fields: {missing}")
            
        if not isinstance(payload['action'], str):
            raise WebSocketValidationError("Action must be a string")
            
        if payload['action'].upper() not in ['BUY', 'SELL']:
            raise WebSocketValidationError("Action must be either 'BUY' or 'SELL'")
            
        return True
        
    except Exception as e:
        logger.error(f"TradingView payload validation error: {str(e)}")
        raise WebSocketValidationError(str(e))

def validate_trendspider_payload(payload: Dict[str, Any]) -> bool:
    """
    Validate TrendSpider webhook payload structure.
    
    Args:
        payload: The webhook payload to validate
        
    Returns:
        bool: True if payload is valid
        
    Raises:
        WebSocketValidationError: If payload is invalid
    """
    required_fields = ['alert', 'action']
    try:
        if not all(field in payload for field in required_fields):
            missing = [field for field in required_fields if field not in payload]
            raise WebSocketValidationError(f"Missing required fields: {missing}")
            
        if not isinstance(payload['action'], str):
            raise WebSocketValidationError("Action must be a string")
            
        if payload['action'].upper() not in ['BUY', 'SELL']:
            raise WebSocketValidationError("Action must be either 'BUY' or 'SELL'")
            
        return True
        
    except Exception as e:
        logger.error(f"TrendSpider payload validation error: {str(e)}")
        raise WebSocketValidationError(str(e))

def normalize_payload(source_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize different webhook payloads into a standard format.
    
    Args:
        source_type: The type of webhook source ('tradingview', 'trendspider', etc.)
        payload: The raw webhook payload
        
    Returns:
        Dict: Normalized payload data
        
    Raises:
        WebSocketValidationError: If normalization fails
    """
    try:
        normalized = {
            'timestamp': timezone.now().isoformat(),
            'source': source_type
        }

        if source_type == 'tradingview':
            normalized.update({
                'action': payload['action'].upper(),
                'strategy': payload['strategy'],
                'symbol': payload.get('symbol'),
                'price': float(payload['price']) if 'price' in payload else None,
                'quantity': float(payload['quantity']) if 'quantity' in payload else None,
                'metadata': payload.get('metadata', {})
            })
            
        elif source_type == 'trendspider':
            normalized.update({
                'action': payload['action'].upper(),
                'strategy': payload['alert'],
                'symbol': payload.get('symbol'),
                'price': float(payload['price']) if 'price' in payload else None,
                'quantity': float(payload['size']) if 'size' in payload else None,
                'metadata': payload.get('metadata', {})
            })
            
        else:
            # For custom implementations, preserve original data with minimal normalization
            normalized.update({
                'action': payload.get('action', '').upper(),
                'strategy': payload.get('strategy') or payload.get('alert'),
                'symbol': payload.get('symbol'),
                'price': float(payload['price']) if 'price' in payload else None,
                'quantity': float(payload.get('quantity') or payload.get('size', 0)),
                'metadata': payload.get('metadata', {})
            })

        # Validate normalized payload
        if not normalized['action']:
            raise WebSocketValidationError("Missing or invalid action")
            
        if normalized['action'] not in ['BUY', 'SELL']:
            raise WebSocketValidationError(f"Invalid action: {normalized['action']}")
            
        if not normalized['strategy']:
            raise WebSocketValidationError("Missing strategy name")

        return normalized
        
    except (TypeError, ValueError) as e:
        logger.error(f"Error normalizing payload: {str(e)}")
        raise WebSocketValidationError(f"Error normalizing payload: {str(e)}")
        
    except Exception as e:
        logger.error(f"Unexpected error normalizing payload: {str(e)}")
        raise WebSocketValidationError(f"Unexpected error: {str(e)}")

def format_message(message_type: str, data: Any) -> Dict[str, Any]:
    """
    Format a WebSocket message for transmission.
    
    Args:
        message_type: Type of message
        data: Message data
        
    Returns:
        Dict: Formatted message
    """
    return {
        'type': message_type,
        'data': data,
        'timestamp': timezone.now().isoformat()
    }

def validate_websocket_message(message: Dict[str, Any]) -> bool:
    """
    Validate incoming WebSocket message format.
    
    Args:
        message: The WebSocket message to validate
        
    Returns:
        bool: True if message is valid
        
    Raises:
        WebSocketValidationError: If message is invalid
    """
    try:
        if not isinstance(message, dict):
            raise WebSocketValidationError("Message must be a dictionary")
            
        if 'type' not in message:
            raise WebSocketValidationError("Message must have a 'type' field")
            
        if 'data' not in message:
            raise WebSocketValidationError("Message must have a 'data' field")
            
        return True
        
    except Exception as e:
        logger.error(f"WebSocket message validation error: {str(e)}")
        raise WebSocketValidationError(str(e))

def parse_websocket_message(message: str) -> Dict[str, Any]:
    """
    Parse a raw WebSocket message string.
    
    Args:
        message: Raw message string
        
    Returns:
        Dict: Parsed message data
        
    Raises:
        WebSocketValidationError: If parsing fails
    """
    try:
        parsed = json.loads(message)
        validate_websocket_message(parsed)
        return parsed
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in WebSocket message: {str(e)}")
        raise WebSocketValidationError("Invalid JSON format")
        
    except Exception as e:
        logger.error(f"Error parsing WebSocket message: {str(e)}")
        raise WebSocketValidationError(f"Message parsing failed: {str(e)}")