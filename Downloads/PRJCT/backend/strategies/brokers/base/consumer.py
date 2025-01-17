import json
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Set
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .interfaces import (
    IConnectionManager,
    IWebSocketClient,
    ITrading,
    IDataProvider,
    BaseBroker
)
from .types import (
    WebSocketConfig,
    WebSocketMessage,
    OrderRequest,
    MarketData,
    OrderStatus
)
from .exceptions import (
    BrokerBaseException,
    BrokerConnectionError,
    WebSocketError
)

logger = logging.getLogger(__name__)

class BaseBrokerConsumer(AsyncWebsocketConsumer, ABC):
    """
    Base WebSocket consumer for broker connections.
    Handles connection lifecycle, message routing, and error handling.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.broker: Optional[BaseBroker] = None
        self.config: Optional[WebSocketConfig] = None
        self.subscriptions: Set[str] = set()
        self.account_id: Optional[str] = None
        self.is_authenticated: bool = False
        self.last_heartbeat: Optional[float] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        self.message_handlers: Dict[str, Any] = {
            'subscribe': self.handle_subscription,
            'unsubscribe': self.handle_unsubscribe,
            'order': self.handle_order,
            'cancel_order': self.handle_cancel_order,
            'market_data': self.handle_market_data,
            'heartbeat': self.handle_heartbeat
        }

    async def connect(self) -> None:
        """Handle WebSocket connection and initialization."""
        logger.info(f"Establishing connection for {self.__class__.__name__}")
        
        try:
            # Initialize broker
            await self.initialize_broker()
            if not self.broker or not self.broker.is_connected:
                raise BrokerConnectionError("Failed to initialize broker connection")

            # Accept the connection
            await self.accept()
            logger.info("WebSocket connection accepted")

            # Start background tasks
            self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
            self.cleanup_task = asyncio.create_task(self.cleanup_loop())

            # Subscribe to default channels
            if self.account_id:
                await self.broker.subscribe_account_updates(self.account_id)
                await self.broker.subscribe_positions(self.account_id)
                await self.broker.subscribe_orders(self.account_id)

        except Exception as e:
            logger.error(f"Connection error: {str(e)}", exc_info=True)
            await self.handle_error("Connection failed", e)
            await self.close()

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection and cleanup."""
        logger.info(f"Disconnecting {self.__class__.__name__}, code: {close_code}")
        
        try:
            # Cancel background tasks
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
            if self.cleanup_task:
                self.cleanup_task.cancel()

            # Cleanup broker resources
            if self.broker:
                await self.broker.cleanup()

            # Clear subscriptions
            self.subscriptions.clear()

        except Exception as e:
            logger.error(f"Disconnection error: {str(e)}", exc_info=True)
        finally:
            self.is_authenticated = False
            self.last_heartbeat = None

    async def receive(self, text_data: str) -> None:
        """Handle incoming WebSocket messages."""
        try:
            # Check authentication
            if not self.is_authenticated and not await self.authenticate():
                await self.handle_error("Authentication required", None)
                await self.close()
                return

            # Parse and validate message
            try:
                message = json.loads(text_data)
            except json.JSONDecodeError:
                await self.handle_error("Invalid JSON format", None)
                return

            # Update heartbeat
            self.last_heartbeat = asyncio.get_event_loop().time()

            # Route message to appropriate handler
            message_type = message.get('type')
            if message_type in self.message_handlers:
                await self.message_handlers[message_type](message)
            else:
                await self.handle_broker_message(message)

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            await self.handle_error("Message processing failed", e)

    @abstractmethod
    async def initialize_broker(self) -> None:
        """Initialize broker instance. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with broker. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def handle_broker_message(self, message: Dict[str, Any]) -> None:
        """Handle broker-specific messages. Must be implemented by subclasses."""
        pass

    async def handle_subscription(self, message: Dict[str, Any]) -> None:
        """Handle subscription requests."""
        try:
            symbols = message.get('symbols', [])
            if not symbols:
                await self.handle_error("No symbols specified", None)
                return

            await self.broker.subscribe_market_data(symbols)
            self.subscriptions.update(symbols)
            
            await self.send_json({
                'type': 'subscription_success',
                'data': {
                    'symbols': list(self.subscriptions)
                }
            })

        except Exception as e:
            logger.error(f"Subscription error: {str(e)}", exc_info=True)
            await self.handle_error("Subscription failed", e)

    async def handle_unsubscribe(self, message: Dict[str, Any]) -> None:
        """Handle unsubscribe requests."""
        try:
            symbols = message.get('symbols', [])
            if not symbols:
                await self.handle_error("No symbols specified", None)
                return

            await self.broker.unsubscribe_market_data(symbols)
            self.subscriptions.difference_update(symbols)
            
            await self.send_json({
                'type': 'unsubscribe_success',
                'data': {
                    'symbols': list(self.subscriptions)
                }
            })

        except Exception as e:
            logger.error(f"Unsubscribe error: {str(e)}", exc_info=True)
            await self.handle_error("Unsubscribe failed", e)

    async def handle_order(self, message: Dict[str, Any]) -> None:
        """Handle order requests."""
        try:
            if not self.account_id:
                raise ValueError("No account ID specified")

            order_request = OrderRequest(**message.get('data', {}))
            response = await self.broker.place_order(self.account_id, order_request)
            
            await self.send_json({
                'type': 'order_response',
                'data': response.dict()
            })

        except Exception as e:
            logger.error(f"Order error: {str(e)}", exc_info=True)
            await self.handle_error("Order placement failed", e)

    async def handle_cancel_order(self, message: Dict[str, Any]) -> None:
        """Handle order cancellation requests."""
        try:
            if not self.account_id:
                raise ValueError("No account ID specified")

            order_id = message.get('order_id')
            if not order_id:
                raise ValueError("No order ID specified")

            success = await self.broker.cancel_order(self.account_id, order_id)
            
            await self.send_json({
                'type': 'cancel_response',
                'data': {'success': success, 'order_id': order_id}
            })

        except Exception as e:
            logger.error(f"Cancel error: {str(e)}", exc_info=True)
            await self.handle_error("Order cancellation failed", e)

    async def handle_market_data(self, data: Dict[str, Any]) -> None:
        """Handle market data updates."""
        try:
            market_data = await self.broker.normalize_market_data(data)
            
            await self.send_json({
                'type': 'market_data',
                'data': market_data.dict()
            })

        except Exception as e:
            logger.error(f"Market data error: {str(e)}", exc_info=True)
            await self.handle_error("Market data processing failed", e)

    async def handle_heartbeat(self, _: Dict[str, Any]) -> None:
        """Handle heartbeat messages."""
        await self.send_json({
            'type': 'heartbeat',
            'timestamp': timezone.now().isoformat()
        })

    async def handle_error(self, message: str, error: Optional[Exception]) -> None:
        """Handle and report errors."""
        error_data = {
            'type': 'error',
            'message': message,
            'timestamp': timezone.now().isoformat()
        }

        if error:
            error_data['error'] = str(error)
            error_data['error_type'] = error.__class__.__name__

        await self.send_json(error_data)

    async def heartbeat_loop(self) -> None:
        """Maintain connection heartbeat."""
        try:
            while True:
                await asyncio.sleep(15)  # 15-second heartbeat interval
                if self.last_heartbeat:
                    time_since_last = asyncio.get_event_loop().time() - self.last_heartbeat
                    if time_since_last > 30:  # 30-second timeout
                        logger.warning("Heartbeat timeout, closing connection")
                        await self.close()
                        break
                await self.send_json({
                    'type': 'heartbeat',
                    'timestamp': timezone.now().isoformat()
                })

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Heartbeat error: {str(e)}", exc_info=True)
            await self.close()

    async def cleanup_loop(self) -> None:
        """Periodically cleanup resources."""
        try:
            while True:
                await asyncio.sleep(300)  # 5-minute cleanup interval
                if not self.is_authenticated:
                    break
                # Perform cleanup tasks here

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Cleanup error: {str(e)}", exc_info=True)

    async def send_json(self, content: Dict[str, Any]) -> None:
        """Send JSON message with error handling."""
        try:
            await super().send(text_data=json.dumps(content))
        except Exception as e:
            logger.error(f"Send error: {str(e)}", exc_info=True)
            raise WebSocketError(f"Failed to send message: {str(e)}")