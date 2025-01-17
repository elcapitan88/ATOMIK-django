import os
import logging.config
import json
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict
from django.conf import settings

# Custom logging formatter with additional fields
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_record['exception'] = self.formatException(record.exc_info)
            
        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_record.update(record.extra_fields)
            
        return json.dumps(log_record)

class TradeLogger:
    """Centralized logging for trading operations"""
    
    def __init__(self):
        self.logger = logging.getLogger('trading')
        
    def setup_logging(self):
        """Configure logging settings"""
        logging_config = {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'json': {
                    '()': JSONFormatter
                },
                'standard': {
                    'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
                }
            },
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'standard',
                    'level': 'INFO'
                },
                'file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': os.path.join(settings.BASE_DIR, 'logs', 'trading.log'),
                    'maxBytes': 10485760,  # 10MB
                    'backupCount': 5,
                    'formatter': 'json',
                    'level': 'DEBUG'
                },
                'error_file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': os.path.join(settings.BASE_DIR, 'logs', 'error.log'),
                    'maxBytes': 10485760,
                    'backupCount': 5,
                    'formatter': 'json',
                    'level': 'ERROR'
                },
                'webhook_file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': os.path.join(settings.BASE_DIR, 'logs', 'webhooks.log'),
                    'maxBytes': 10485760,
                    'backupCount': 5,
                    'formatter': 'json',
                    'level': 'INFO'
                }
            },
            'loggers': {
                'trading': {
                    'handlers': ['console', 'file', 'error_file'],
                    'level': 'DEBUG',
                    'propagate': False
                },
                'webhooks': {
                    'handlers': ['console', 'webhook_file', 'error_file'],
                    'level': 'INFO',
                    'propagate': False
                },
                'websockets': {
                    'handlers': ['console', 'file', 'error_file'],
                    'level': 'DEBUG',
                    'propagate': False
                }
            }
        }
        
        # Create logs directory if it doesn't exist
        os.makedirs(os.path.join(settings.BASE_DIR, 'logs'), exist_ok=True)
        
        # Apply configuration
        logging.config.dictConfig(logging_config)

    def log_trade(self, trade_data: Dict[str, Any], status: str = 'info'):
        """Log trade-related information"""
        extra = {
            'extra_fields': {
                'trade_id': trade_data.get('trade_id'),
                'account_id': trade_data.get('account_id'),
                'symbol': trade_data.get('symbol'),
                'action': trade_data.get('action'),
                'quantity': trade_data.get('quantity'),
                'price': trade_data.get('price'),
                'status': status
            }
        }
        
        self.logger.info(f"Trade executed: {trade_data}", extra=extra)
        
    def log_webhook(self, webhook_data: Dict[str, Any], status: str = 'info'):
        """Log webhook-related information"""
        webhook_logger = logging.getLogger('webhooks')
        extra = {
            'extra_fields': {
                'webhook_id': webhook_data.get('webhook_id'),
                'source': webhook_data.get('source'),
                'status': status,
                'processing_time': webhook_data.get('processing_time')
            }
        }
        
        webhook_logger.info(f"Webhook received: {webhook_data}", extra=extra)

    def log_websocket(self, ws_data: Dict[str, Any], status: str = 'info'):
        """Log WebSocket-related information"""
        ws_logger = logging.getLogger('websockets')
        extra = {
            'extra_fields': {
                'connection_id': ws_data.get('connection_id'),
                'user_id': ws_data.get('user_id'),
                'status': status,
                'message_type': ws_data.get('message_type')
            }
        }
        
        ws_logger.info(f"WebSocket event: {ws_data}", extra=extra)

def log_execution_time(logger: logging.Logger):
    """Decorator to log function execution time"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = datetime.utcnow()
            try:
                result = await func(*args, **kwargs)
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                logger.info(
                    f"Function {func.__name__} executed in {execution_time:.3f} seconds",
                    extra={'extra_fields': {
                        'execution_time': execution_time,
                        'function': func.__name__
                    }}
                )
                return result
            except Exception as e:
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                logger.error(
                    f"Error in {func.__name__}: {str(e)}",
                    extra={'extra_fields': {
                        'execution_time': execution_time,
                        'function': func.__name__,
                        'error': str(e)
                    }},
                    exc_info=True
                )
                raise
        return wrapper
    return decorator

# Initialize global logger instance
trade_logger = TradeLogger()