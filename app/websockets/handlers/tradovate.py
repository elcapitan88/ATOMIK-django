import asyncio
import json
import logging
import websockets
import random
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal
from .base import BrokerWebSocketHandler, WSConnectionStatus, WSMessageType
from ...core.config import settings
from ...models.tradovate import TradovateToken
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """Circuit breaker for handling connection failures"""
    def __init__(self):
        self.failure_count = 0
        self.last_failure = None
        self.state = 'closed'  # closed, open, half-open
        self.threshold = 5  # failures before opening
        self.timeout = 60  # seconds to wait before trying again

    def record_failure(self):
        """Record a failure and potentially open the circuit"""
        self.failure_count += 1
        self.last_failure = datetime.utcnow()
        if self.failure_count >= self.threshold:
            self.state = 'open'

    def record_success(self):
        """Record a success and potentially close the circuit"""
        self.failure_count = 0
        self.state = 'closed'

    def can_execute(self) -> bool:
        """Check if operation should be allowed"""
        if self.state == 'closed':
            return True
        
        if self.state == 'open':
            if datetime.utcnow() - self.last_failure > timedelta(seconds=self.timeout):
                self.state = 'half-open'
                return True
            return False
        
        return self.state == 'half-open'

class MessageQueue:
    """Queue for handling message backlog during reconnection"""
    def __init__(self, max_size: int = 1000):
        self.queue = asyncio.Queue(maxsize=max_size)
        self.processing = False

    async def add_message(self, message: Dict[str, Any]):
        """Add message to queue"""
        try:
            await self.queue.put(message)
        except asyncio.QueueFull:
            logger.warning("Message queue full, dropping oldest message")
            self.queue.get_nowait()
            await self.queue.put(message)

    async def get_message(self) -> Optional[Dict[str, Any]]:
        """Get message from queue"""
        try:
            return await self.queue.get()
        except asyncio.QueueEmpty:
            return None

    def clear(self):
        """Clear all messages from queue"""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

class TradovateWebSocketHandler(BrokerWebSocketHandler):
    def __init__(self, db: Session, user_id: int, environment: str = 'demo'):
        """Initialize Tradovate WebSocket handler"""
        super().__init__()
        self.db = db
        self.user_id = user_id
        self.environment = environment
        self.ws_url = (
            settings.TRADOVATE_LIVE_WS_URL 
            if environment == 'live' 
            else settings.TRADOVATE_DEMO_WS_URL
        )
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.circuit_breaker = CircuitBreaker()
        self.message_queue = MessageQueue()
        self.connection_lock = asyncio.Lock()
        self.message_handlers = {
            'md': self._handle_market_data,
            'order': self._handle_order_update,
            'account': self._handle_account_update,
            'error': self._handle_error_message
        }
        self.last_reconnect_time = None
        self.subscription_state = set()

    async def execute_with_circuit_breaker(self, operation):
        """Execute an operation with circuit breaker protection"""
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker is open")
        
        try:
            result = await operation()
            self.circuit_breaker.record_success()
            return result
        except Exception as e:
            self.circuit_breaker.record_failure()
            raise

    async def connect(self) -> bool:
        """Establish connection to Tradovate WebSocket"""
        async with self.connection_lock:
            if self.status in [WSConnectionStatus.CONNECTED, WSConnectionStatus.CONNECTING]:
                return True

            try:
                self.status = WSConnectionStatus.CONNECTING
                
                # Connect with circuit breaker
                async def connect_operation():
                    self.websocket = await websockets.connect(
                        self.ws_url,
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=10
                    )
                    return True

                connected = await self.execute_with_circuit_breaker(connect_operation)
                if not connected:
                    return False

                # Authenticate immediately after connection
                auth_success = await self.authenticate({})
                if not auth_success:
                    await self.disconnect()
                    return False

                self.status = WSConnectionStatus.CONNECTED
                self.reset_error_count()
                self.reconnect_attempts = 0
                self.update_heartbeat()

                # Start message processor
                asyncio.create_task(self._process_messages())
                
                # Resubscribe to previous subscriptions
                if self.subscription_state:
                    await self.subscribe(list(self.subscription_state))

                logger.info(f"Connected to Tradovate WebSocket ({self.environment})")
                return True

            except Exception as e:
                self.status = WSConnectionStatus.ERROR
                logger.error(f"Failed to connect to Tradovate: {str(e)}")
                return False

    async def disconnect(self) -> bool:
        """Disconnect from Tradovate WebSocket"""
        try:
            if self.websocket:
                await self.websocket.close()
                self.websocket = None
            self.status = WSConnectionStatus.DISCONNECTED
            await self.cleanup()
            logger.info("Disconnected from Tradovate WebSocket")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting from Tradovate: {str(e)}")
            return False

    async def reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Max reconnection attempts reached")
            return False

        try:
            self.status = WSConnectionStatus.RECONNECTING
            self.reconnect_attempts += 1
            
            # Calculate backoff time
            backoff = min(300, (2 ** self.reconnect_attempts) + random.uniform(0, 1))
            logger.info(f"Waiting {backoff:.2f}s before reconnection attempt {self.reconnect_attempts}")
            await asyncio.sleep(backoff)
            
            self.last_reconnect_time = datetime.utcnow()
            
            # Attempt reconnection with circuit breaker
            connected = await self.execute_with_circuit_breaker(self.connect)
            
            if connected:
                # Process any queued messages
                await self._process_message_queue()
                
            return connected

        except Exception as e:
            logger.error(f"Reconnection failed: {str(e)}")
            return False

    async def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """Authenticate with Tradovate WebSocket"""
        try:
            # Get valid token from database
            token = (
                self.db.query(TradovateToken)
                .filter(
                    TradovateToken.user_id == self.user_id,
                    TradovateToken.environment == self.environment,
                    TradovateToken.is_valid == True
                )
                .first()
            )

            if not token:
                logger.error("No valid Tradovate token found")
                return False

            auth_message = {
                "type": "auth",
                "token": token.access_token
            }

            await self.send_message(auth_message)
            
            # Wait for auth response
            response = await self._wait_for_message("auth")
            if response and response.get("success"):
                logger.info("Successfully authenticated with Tradovate")
                return True
            else:
                logger.error("Tradovate authentication failed")
                return False

        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return False

    async def subscribe(self, symbols: List[str]) -> bool:
        """Subscribe to market data for specified symbols"""
        try:
            subscription_message = {
                "type": "subscribe",
                "symbols": symbols
            }

            success = await self.send_message(subscription_message)
            if success:
                self.subscription_state.update(symbols)
                logger.info(f"Subscribed to symbols: {symbols}")
                return True
            return False

        except Exception as e:
            logger.error(f"Subscription error: {str(e)}")
            return False

    async def send_message(self, message: Dict[str, Any]) -> bool:
        """Send a message to Tradovate WebSocket"""
        if not self.is_connected() or not self.websocket:
            # Queue message for later if not connected
            await self.message_queue.add_message(message)
            return False

        try:
            await self.websocket.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            await self.handle_error(e)
            return False

    async def handle_message(self, message: Dict[str, Any]) -> None:
        """Handle incoming messages from Tradovate"""
        try:
            message_type = message.get('type')
            handler = self.message_handlers.get(message_type)
            
            if handler:
                await handler(message)
            else:
                logger.warning(f"Unknown message type: {message_type}")

        except Exception as e:
            logger.error(f"Error handling message: {str(e)}")
            await self.handle_error(e)

    async def handle_error(self, error: Exception) -> None:
        """Enhanced error handling with metrics"""
        self.increment_error_count()
        logger.error(f"WebSocket error: {str(error)}")
        
        # Update error metrics
        error_type = type(error).__name__
        await self._update_error_metrics(error_type)
        
        if self.error_count >= self.max_errors:
            logger.error("Max error count reached, initiating reconnect")
            if self.should_reconnect():
                await self.reconnect()

    async def _update_error_metrics(self, error_type: str):
        """Update error metrics for monitoring"""
        try:
            # Update Redis metrics if available
            if hasattr(self, 'websocket_manager') and self.websocket_manager.redis:
                key = f"ws:errors:{self.user_id}:{error_type}"
                await self.websocket_manager.redis.incr(key)
                await self.websocket_manager.redis.expire(key, 86400)  # 24 hours
        except Exception as e:
            logger.error(f"Failed to update error metrics: {str(e)}")

    async def _process_messages(self) -> None:
        """Background task to process incoming messages"""
        while True:
            try:
                if not self.websocket:
                    await asyncio.sleep(1)
                    continue

                message = await self.websocket.recv()
                if not message:
                    continue

                data = json.loads(message)
                await self.handle_message(data)
                self.update_heartbeat()

            except websockets.exceptions.ConnectionClosed:
                logger.error("WebSocket connection closed")
                if self.should_reconnect():
                    await self.reconnect()
                break
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                await self.handle_error(e)

    async def _process_message_queue(self):
        """Process queued messages after reconnection"""
        while True:
            message = await self.message_queue.get_message()
            if not message:
                break
                
            await self.send_message(message)
            await asyncio.sleep(0.1)  # Prevent flooding

    async def _wait_for_message(self, expected_type: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Wait for a specific type of message response"""
        try:
            if not self.websocket:
                raise Exception("Not connected")

            async with asyncio.timeout(timeout):
                while True:
                    message = await self.websocket.recv()
                    data = json.loads(message)
                    if data.get("type") == expected_type:
                        return data

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for {expected_type} message")
            return None
        except Exception as e:
            logger.error(f"Error waiting for message: {str(e)}")
            return None

    # Message handlers
    async def _handle_market_data(self, message: Dict[str, Any]) -> None:
        """Handle market data messages"""
        try:
            processed_data = await self.process_market_data(message)
            if processed_data:
                await self.websocket_manager.broadcast_market_data(
                    processed_data["symbol"],
                    processed_data
                )
        except Exception as e:
            logger.error(f"Error handling market data: {str(e)}")

    async def _handle_order_update(self, message: Dict[str, Any]) -> None:
        """Handle order update messages"""
        try:
            processed_data = await self.process_order_update(message)
            if processed_data:
                await self.websocket_manager.broadcast_to_user(
                    self.user_id,
                    {
                        "type": WSMessageType.ORDER_UPDATE,
                        "data": processed_data
                    }
                )
        except Exception as e:
            logger.error(f"Error handling order update: {str(e)}")

    async def _handle_account_update(self, message: Dict[str, Any]) -> None:
        """Handle account update messages"""
        try:
            processed_data = await self.process_account_update(message)
            if processed_data:
                await self.websocket_manager.broadcast_to_user(
                    self.user_id,
                    {
                        "type": WSMessageType.ACCOUNT_UPDATE,
                        "data": processed_data
                    }
                )
        except Exception as e:
            logger.error(f"Error handling account update: {str(e)}")

    async def _handle_error_message(self, message: Dict[str, Any]) -> None:
        """Handle error messages from Tradovate"""
        error_message = message.get('message', 'Unknown Tradovate error')
        logger.error(f"Tradovate error: {error_message}")
        await self.handle_error(Exception(error_message))
    
    async def process_market_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process and normalize market data messages"""
        try:
            return {
                "type": WSMessageType.MARKET_DATA,
                "symbol": data.get("symbol"),
                "price": Decimal(str(data.get("price", 0))),
                "volume": data.get("size"),
                "timestamp": datetime.utcnow().timestamp(),
                "bid": Decimal(str(data.get("bid", 0))),
                "ask": Decimal(str(data.get("ask", 0))),
                "broker": "tradovate",
                "raw_data": data  # Store original data for reference
            }
        except Exception as e:
            logger.error(f"Error processing market data: {str(e)}")
            return None

    async def process_order_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process and normalize order update messages"""
        try:
            return {
                "type": WSMessageType.ORDER_UPDATE,
                "order_id": data.get("orderId"),
                "symbol": data.get("symbol"),
                "status": data.get("status"),
                "filled_quantity": data.get("filledQty", 0),
                "remaining_quantity": data.get("remainingQty", 0),
                "price": Decimal(str(data.get("price", 0))),
                "timestamp": datetime.utcnow().timestamp(),
                "broker": "tradovate",
                "raw_data": data
            }
        except Exception as e:
            logger.error(f"Error processing order update: {str(e)}")
            return None

    async def process_account_update(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process and normalize account update messages"""
        try:
            return {
                "type": WSMessageType.ACCOUNT_UPDATE,
                "account_id": data.get("accountId"),
                "balance": Decimal(str(data.get("balance", 0))),
                "margin_used": Decimal(str(data.get("marginUsed", 0))),
                "available_margin": Decimal(str(data.get("availableMargin", 0))),
                "positions": data.get("positions", []),
                "timestamp": datetime.utcnow().timestamp(),
                "broker": "tradovate",
                "raw_data": data
            }
        except Exception as e:
            logger.error(f"Error processing account update: {str(e)}")
            return None

    async def send_heartbeat(self) -> bool:
        """Send heartbeat message to maintain connection"""
        heartbeat_message = {
            "type": WSMessageType.HEARTBEAT,
            "timestamp": datetime.utcnow().timestamp()
        }
        return await self.send_message(heartbeat_message)

    async def start_heartbeat_loop(self):
        """Start background heartbeat task"""
        while True:
            try:
                if self.is_connected():
                    await self.send_heartbeat()
                await asyncio.sleep(20)  # Send heartbeat every 20 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {str(e)}")

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get current connection statistics"""
        return {
            "status": self.status,
            "connection_id": self.connection_id,
            "error_count": self.error_count,
            "reconnect_attempts": self.reconnect_attempts,
            "last_heartbeat": self.last_heartbeat,
            "subscribed_symbols": list(self.subscription_state),
            "circuit_breaker_state": self.circuit_breaker.state,
            "message_queue_size": self.message_queue.queue.qsize()
        }

    async def validate_subscription(self, symbols: List[str]) -> List[str]:
        """Validate symbols before subscription"""
        valid_symbols = []
        for symbol in symbols:
            # Add your symbol validation logic here
            if self._is_valid_symbol(symbol):
                valid_symbols.append(symbol)
            else:
                logger.warning(f"Invalid symbol: {symbol}")
        return valid_symbols

    def _is_valid_symbol(self, symbol: str) -> bool:
        """Validate individual symbol"""
        # Add your symbol validation logic here
        # This is a placeholder implementation
        return bool(symbol and isinstance(symbol, str) and len(symbol) <= 10)

    async def _handle_subscription_response(self, response: Dict[str, Any]):
        """Handle subscription response from broker"""
        success = response.get("success", False)
        symbols = response.get("symbols", [])
        
        if success:
            self.subscription_state.update(symbols)
            logger.info(f"Successfully subscribed to: {symbols}")
        else:
            error = response.get("error", "Unknown subscription error")
            logger.error(f"Subscription failed: {error}")
            
            # Remove failed symbols from subscription state
            for symbol in symbols:
                self.subscription_state.discard(symbol)

    async def _validate_message(self, message: Dict[str, Any]) -> bool:
        """Validate incoming message structure"""
        required_fields = {
            "md": ["symbol", "price"],
            "order": ["orderId", "status"],
            "account": ["accountId"],
            "error": ["message"]
        }
        
        message_type = message.get("type")
        if not message_type:
            return False
            
        fields = required_fields.get(message_type, [])
        return all(field in message for field in fields)

    async def _process_batch_messages(self, messages: List[Dict[str, Any]]):
        """Process multiple messages in batch"""
        for message in messages:
            try:
                if await self._validate_message(message):
                    await self.handle_message(message)
                else:
                    logger.warning(f"Invalid message format: {message}")
            except Exception as e:
                logger.error(f"Error processing batch message: {str(e)}")

    async def cleanup(self) -> None:
        """Cleanup resources and reset state"""
        try:
            # Clear message queue
            self.message_queue.clear()
            
            # Reset circuit breaker
            self.circuit_breaker = CircuitBreaker()
            
            # Clear subscription state
            self.subscription_state.clear()
            
            # Reset connection state
            self.status = WSConnectionStatus.DISCONNECTED
            self.last_heartbeat = None
            self.error_count = 0
            self.reconnect_attempts = 0
            
            # Close websocket if still open
            if self.websocket:
                await self.websocket.close()
                self.websocket = None
                
            logger.info(f"Cleaned up WebSocket handler state for user {self.user_id}")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    async def unsubscribe_all(self) -> bool:
        """Unsubscribe from all current subscriptions"""
        try:
            if self.subscription_state:
                success = await self.unsubscribe(list(self.subscription_state))
                if success:
                    self.subscription_state.clear()
                return success
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from all symbols: {str(e)}")
            return False