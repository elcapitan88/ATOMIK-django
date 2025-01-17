# These imports need to be updated
import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List
from django.utils import timezone
import websockets
from .exceptions import (
    WebSocketError,
    WebSocketConnectionError,
    WebSocketAuthenticationError,
    WebSocketMessageError
)
from strategies.monitoring.logging_config import trade_logger
from strategies.monitoring.performance import PerformanceMonitoringMixin

logger = logging.getLogger(__name__)

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF-OPEN

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_time = datetime.now()
        if self.failures >= self.failure_threshold:
            self.state = 'OPEN'

    def record_success(self) -> None:
        self.failures = 0
        self.state = 'CLOSED'

    def can_execute(self) -> bool:
        if self.state == 'CLOSED':
            return True
        if self.state == 'OPEN':
            if (datetime.now() - self.last_failure_time).seconds >= self.reset_timeout:
                self.state = 'HALF-OPEN'
                return True
            return False
        return True  # HALF-OPEN state allows one try
    
class MessageQueue:
    def __init__(self, max_size: int = 10000):
        self.queue = deque(maxlen=max_size)
        self.high_priority_queue = deque(maxlen=1000)
        
    def add(self, message: Dict[str, Any], high_priority: bool = False) -> None:
        if high_priority:
            self.high_priority_queue.append((timezone.now(), message))
        else:
            self.queue.append((timezone.now(), message))

    def get_next(self) -> Optional[Dict[str, Any]]:
        if len(self.high_priority_queue) > 0:
            return self.high_priority_queue.popleft()[1]
        if len(self.queue) > 0:
            return self.queue.popleft()[1]
        return None

    def clear_old_messages(self, max_age: int = 300) -> None:
        current_time = timezone.now()
        self.queue = deque(
            [(t, m) for t, m in self.queue 
             if (current_time - t).seconds < max_age],
            maxlen=self.queue.maxlen
        )
    

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from collections import deque
from django.utils import timezone
import websockets
from .exceptions import (
    WebSocketError,
    WebSocketConnectionError,
    WebSocketAuthenticationError,
    WebSocketMessageError
)

logger = logging.getLogger(__name__)

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF-OPEN

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_time = datetime.now()
        if self.failures >= self.failure_threshold:
            self.state = 'OPEN'

    def record_success(self) -> None:
        self.failures = 0
        self.state = 'CLOSED'

    def can_execute(self) -> bool:
        if self.state == 'CLOSED':
            return True
        if self.state == 'OPEN':
            if (datetime.now() - self.last_failure_time).seconds >= self.reset_timeout:
                self.state = 'HALF-OPEN'
                return True
            return False
        return True  # HALF-OPEN state allows one try

class MessageQueue:
    def __init__(self, max_size: int = 10000):
        self.queue = deque(maxlen=max_size)
        self.high_priority_queue = deque(maxlen=1000)
        
    def add(self, message: Dict[str, Any], high_priority: bool = False) -> None:
        if high_priority:
            self.high_priority_queue.append((timezone.now(), message))
        else:
            self.queue.append((timezone.now(), message))

    def get_next(self) -> Optional[Dict[str, Any]]:
        if len(self.high_priority_queue) > 0:
            return self.high_priority_queue.popleft()[1]
        if len(self.queue) > 0:
            return self.queue.popleft()[1]
        return None

    def clear_old_messages(self, max_age: int = 300) -> None:
        current_time = timezone.now()
        self.queue = deque(
            [(t, m) for t, m in self.queue 
             if (current_time - t).seconds < max_age],
            maxlen=self.queue.maxlen
        )

class BaseWebSocketClient:
    def __init__(self, url: str, options: Dict[str, Any] = None):
        # Connection settings
        self.url = url
        self.options = {
            'reconnect_attempts': 5,
            'reconnect_interval': 1,
            'heartbeat_interval': 15,
            'connection_timeout': 10,
            'circuit_breaker_threshold': 5,
            'circuit_breaker_reset': 60,
            'message_batch_size': 100,
            'message_batch_timeout': 1.0,
            **(options or {})
        }

        # Connection state
        self.ws = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.should_reconnect = True
        self.connection_state = 'DISCONNECTED'  # DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING
        self.last_heartbeat = None

        # Callback handlers
        self.onMessage: Optional[Callable] = None
        self.onConnect: Optional[Callable] = None
        self.onDisconnect: Optional[Callable] = None
        self.onError: Optional[Callable] = None
        self.onReconnect: Optional[Callable] = None

        # Circuit breaker for connection management
        self.circuit_breaker = CircuitBreaker(
            self.options['circuit_breaker_threshold'],
            self.options['circuit_breaker_reset']
        )

        # Message handling
        self.message_queue = MessageQueue()
        self.message_batches: Dict[str, List[Dict]] = {}
        self.batch_timers: Dict[str, asyncio.Task] = {}
        self.processing_tasks = set()

        # Locks for thread safety
        self._connection_lock = asyncio.Lock()
        self._message_lock = asyncio.Lock()

        # Performance monitoring
        self.metrics = {
            'connection_attempts': 0,
            'successful_connections': 0,
            'total_messages_sent': 0,
            'total_messages_received': 0,
            'failed_messages': 0,
            'last_error': None
        }

    async def connect(self) -> None:
        """Establish WebSocket connection with retry logic."""
        if not self.circuit_breaker.can_execute():
            raise WebSocketConnectionError("Circuit breaker is open")

        async with self._connection_lock:
            if self.is_connected:
                return

            self.connection_state = 'CONNECTING'
            self.metrics['connection_attempts'] += 1

            try:
                logger.info(f"Connecting to {self.url}")
                self.ws = await websockets.connect(
                    self.url,
                    ping_interval=self.options['heartbeat_interval'],
                    ping_timeout=self.options['connection_timeout']
                )
                
                # Initialize connection
                self.is_connected = True
                self.connection_state = 'CONNECTED'
                self.metrics['successful_connections'] += 1
                self.circuit_breaker.record_success()
                
                # Start background tasks
                await self.setup_handlers()
                await self.authenticate()
                await self.start_heartbeat()
                
                if self.onConnect:
                    await self.onConnect()
                
                logger.info("WebSocket connection established successfully")

            except Exception as e:
                self.connection_state = 'DISCONNECTED'
                self.metrics['last_error'] = str(e)
                self.circuit_breaker.record_failure()
                logger.error(f"Connection error: {str(e)}")
                raise WebSocketConnectionError(f"Failed to connect: {str(e)}")

    async def authenticate(self) -> None:
        """To be implemented by broker-specific classes."""
        raise NotImplementedError("Authentication must be implemented by broker-specific class")

    async def setup_handlers(self) -> None:
        """Setup WebSocket event handlers."""
        if not self.ws:
            return

        self.ws.on_message = self.handle_message
        self.ws.on_close = self.handle_close
        self.ws.on_error = self.handle_error

    async def send_message(self, message: Dict[str, Any], high_priority: bool = False) -> None:
        """Send a message through the WebSocket connection."""
        if not self.is_connected:
            self.message_queue.add(message, high_priority)
            return

        try:
            message_str = json.dumps(message)
            await self.ws.send(message_str)
            self.metrics['total_messages_sent'] += 1
            logger.debug(f"Message sent: {message_str[:100]}...")
        except Exception as e:
            self.metrics['failed_messages'] += 1
            self.message_queue.add(message, high_priority)
            logger.error(f"Error sending message: {str(e)}")
            raise WebSocketMessageError(f"Failed to send message: {str(e)}")

    async def handle_message(self, message: str) -> None:
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)
            self.metrics['total_messages_received'] += 1
            
            # Handle heartbeat messages
            if data.get('type') == 'heartbeat':
                self.last_heartbeat = timezone.now()
                await self.send_message({'type': 'heartbeat_response'})
                return

            # Process message based on type
            message_type = self.get_message_type(data)
            normalized_message = await self.normalize_message(message_type, data)
            
            if self.onMessage:
                await self.onMessage(normalized_message)

        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except Exception as e:
            logger.error(f"Error handling message: {str(e)}")
            if self.onError:
                await self.onError(str(e))

    async def handle_close(self) -> None:
        """Handle WebSocket connection close."""
        self.is_connected = False
        self.connection_state = 'DISCONNECTED'
        logger.warning("WebSocket connection closed")
        
        if self.onDisconnect:
            await self.onDisconnect()
        
        if self.should_reconnect:
            await self.reconnect()

    async def handle_error(self, error: Exception) -> None:
        """Handle WebSocket errors."""
        logger.error(f"WebSocket error: {str(error)}")
        self.metrics['last_error'] = str(error)
        
        if self.onError:
            await self.onError(str(error))

    async def reconnect(self) -> None:
        """Reconnect to the WebSocket server."""
        self.connection_state = 'RECONNECTING'
        await self.disconnect()
        
        try:
            await self.connect()
            if self.onReconnect:
                await self.onReconnect()
        except Exception as e:
            logger.error(f"Reconnection failed: {str(e)}")

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self.is_connected = False
        self.connection_state = 'DISCONNECTED'
        
        # Cancel all background tasks
        for task in self.processing_tasks:
            task.cancel()
        
        if self.ws:
            await self.ws.close()
            self.ws = None
        
        if self.onDisconnect:
            await self.onDisconnect()

    async def start_heartbeat(self) -> None:
        """Maintain connection heartbeat."""
        while self.is_connected:
            try:
                await self.send_message({'type': 'heartbeat'})
                await asyncio.sleep(self.options['heartbeat_interval'])
                
                # Check for missed heartbeats
                if self.last_heartbeat:
                    time_since_last = (timezone.now() - self.last_heartbeat).seconds
                    if time_since_last > self.options['heartbeat_interval'] * 2:
                        logger.warning("Missed heartbeats, initiating reconnection")
                        await self.reconnect()
                        
            except Exception as e:
                logger.error(f"Heartbeat error: {str(e)}")
                await self.reconnect()

    def get_message_type(self, message: Dict) -> str:
        """Extract message type from message. To be implemented by broker-specific classes."""
        raise NotImplementedError

    async def normalize_message(self, message_type: str, message: Dict) -> Dict:
        """Normalize message based on type. To be implemented by broker-specific classes."""
        raise NotImplementedError

    def get_status(self) -> Dict[str, Any]:
        """Get current connection status and metrics."""
        return {
            'connection_state': self.connection_state,
            'circuit_breaker_state': self.circuit_breaker.state,
            'metrics': self.metrics,
            'queued_messages': len(self.message_queue.queue) + len(self.message_queue.high_priority_queue),
            'last_heartbeat': self.last_heartbeat,
        }


class MessageStats:
    """Track message processing statistics"""
    def __init__(self):
        self.processed_count = 0
        self.batch_count = 0
        self.processing_times = []
        self.batch_sizes = []
        self.errors = 0
        self.last_error_time = None
        self.last_error_message = None

async def _process_messages(self, message_type: str, messages: List[Dict]) -> None:
    """Enhanced message processing with performance tracking."""
    start_time = time.time()
    
    try:
        # Existing processing logic
        normalized_messages = [
            await self.normalize_message(message_type, msg)
            for msg in messages
        ]

        if self.onMessage:
            await self.onMessage({
                'type': message_type,
                'data': normalized_messages,
                'timestamp': timezone.now().isoformat()
            })

        # Update statistics
        processing_time = time.time() - start_time
        async with self._lock:
            self.stats.processed_count += len(messages)
            self.stats.batch_count += 1
            self.stats.processing_times.append(processing_time)
            self.stats.batch_sizes.append(len(messages))
            
            # Keep only last 1000 measurements
            if len(self.stats.processing_times) > 1000:
                self.stats.processing_times.pop(0)
                self.stats.batch_sizes.pop(0)

    except Exception as e:
        self.stats.errors += 1
        self.stats.last_error_time = timezone.now()
        self.stats.last_error_message = str(e)
        logger.error(f"Error processing {message_type} messages: {str(e)}")
        if self.onError:
            await self.onError(str(e))

    # Log performance metrics if processing time is high
    if processing_time > 1.0:  # Log if processing takes more than 1 second
        logger.warning(
            f"Slow message processing detected: {processing_time:.2f}s for "
            f"{len(messages)} {message_type} messages"
        )

async def get_performance_metrics(self) -> Dict:
    """Get current performance metrics."""
    async with self._lock:
        processing_times = self.stats.processing_times[-100:]  # Last 100 measurements
        batch_sizes = self.stats.batch_sizes[-100:]
        
        if not processing_times:
            return {
                'status': 'No data available'
            }

        return {
            'processed_messages': self.stats.processed_count,
            'total_batches': self.stats.batch_count,
            'error_count': self.stats.errors,
            'avg_processing_time': sum(processing_times) / len(processing_times),
            'max_processing_time': max(processing_times),
            'avg_batch_size': sum(batch_sizes) / len(batch_sizes),
            'last_error': {
                'time': self.stats.last_error_time.isoformat() if self.stats.last_error_time else None,
                'message': self.stats.last_error_message
            },
            'message_rate': len(processing_times) / sum(processing_times) if sum(processing_times) > 0 else 0,
            'current_queue_sizes': {
                msg_type: len(batch) 
                for msg_type, batch in self.message_batches.items()
            }
        }

async def _should_adjust_batch_size(self, message_type: str) -> bool:
    """Determine if batch size should be adjusted based on performance."""
    metrics = await self.get_performance_metrics()
    
    # If average processing time is too high, reduce batch size
    if metrics['avg_processing_time'] > 0.5:  # More than 500ms
        current_size = self.batch_configs[message_type]['max_size']
        new_size = max(1, current_size // 2)
        self.batch_configs[message_type]['max_size'] = new_size
        logger.info(f"Reducing batch size for {message_type} to {new_size}")
        return True
        
    # If processing is fast and queue is building up, increase batch size
    elif (metrics['avg_processing_time'] < 0.1 and  # Less than 100ms
          message_type in metrics['current_queue_sizes'] and
          metrics['current_queue_sizes'][message_type] > 
          self.batch_configs[message_type]['max_size']):
        current_size = self.batch_configs[message_type]['max_size']
        new_size = min(1000, current_size * 2)  # Cap at 1000
        self.batch_configs[message_type]['max_size'] = new_size
        logger.info(f"Increasing batch size for {message_type} to {new_size}")
        return True
        
    return False