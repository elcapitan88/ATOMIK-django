import json
import logging
import asyncio
from typing import Dict, Any, Optional, Set, List, Union
from decimal import Decimal
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from django.conf import settings
from asgiref.sync import sync_to_async

from .exceptions import (
    WebSocketError,
    WebSocketValidationError,
    WebSocketAuthenticationError,
    WebSocketMessageError
)
from .utils import (
    get_client_ip,
    validate_tradingview_payload,
    validate_trendspider_payload,
    normalize_payload,
    format_message,
    parse_websocket_message
)

logger = logging.getLogger(__name__)

class BaseWebSocketConsumer(AsyncWebsocketConsumer):
    """
    Base WebSocket consumer for handling trading connections.
    Implements core WebSocket functionality with error handling and message processing.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.account_id: Optional[str] = None
        self.subscriptions: Set[str] = set()
        self.is_authenticated: bool = False
        self.last_heartbeat: Optional[datetime] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        self.message_buffer: List[Dict] = []
        self.buffer_limit = 1000
        self.message_handlers: Dict[str, Any] = {
            'subscribe': self.handle_subscription,
            'unsubscribe': self.handle_unsubscribe,
            'order': self.handle_order,
            'market_data': self.handle_market_data,
            'heartbeat': self.handle_heartbeat
        }

    async def connect(self) -> None:
        """Handle WebSocket connection with initialization."""
        logger.info(f"Establishing connection for {self.__class__.__name__}")
        
        try:
            # Get account_id from URL route
            self.account_id = self.scope['url_route']['kwargs'].get('account_id')
            if not self.account_id:
                raise WebSocketValidationError("No account ID provided")

            # Get user from scope
            self.user = self.scope["user"]
            if not self.user or not self.user.is_authenticated:
                raise WebSocketAuthenticationError("User not authenticated")

            # Verify account access
            if not await self.verify_account_access():
                raise WebSocketAuthenticationError("Invalid account access")

            # Accept the connection
            await self.accept()
            logger.info(f"WebSocket connection accepted for account {self.account_id}")

            # Initialize and start background tasks
            await self.start_background_tasks()

            # Join user-specific group for broadcasts
            self.user_group = f"user_{self.user.id}"
            await self.channel_layer.group_add(
                self.user_group,
                self.channel_name
            )

            # Send initial state if needed
            await self.send_initial_state()

        except WebSocketError as e:
            logger.error(f"Connection error: {str(e)}")
            await self.close()
        except Exception as e:
            logger.error(f"Unexpected error in connect: {str(e)}", exc_info=True)
            await self.close()

    async def disconnect(self, close_code: int) -> None:
        """Handle WebSocket disconnection and cleanup."""
        try:
            logger.info(f"Disconnecting {self.__class__.__name__}, code: {close_code}")
            
            # Cancel background tasks
            await self.stop_background_tasks()

            # Leave user group
            if hasattr(self, 'user_group'):
                await self.channel_layer.group_discard(
                    self.user_group,
                    self.channel_name
                )

            # Clear subscriptions
            self.subscriptions.clear()

            # Cleanup any remaining resources
            await self.cleanup()

        except Exception as e:
            logger.error(f"Error in disconnect: {str(e)}", exc_info=True)
        finally:
            self.is_authenticated = False
            self.last_heartbeat = None

    async def receive(self, text_data: str) -> None:
        """Handle incoming WebSocket messages."""
        try:
            if not self.is_authenticated and not await self.authenticate():
                await self.send_error("Authentication required")
                await self.close()
                return

            # Parse and validate message
            message = parse_websocket_message(text_data)
            
            # Update heartbeat
            self.last_heartbeat = timezone.now()

            # Add to message buffer if needed
            if len(self.message_buffer) < self.buffer_limit:
                self.message_buffer.append(message)

            # Route message to appropriate handler
            message_type = message.get('type')
            handler = self.message_handlers.get(message_type)
            
            if handler:
                await handler(message.get('data', {}))
            else:
                await self.handle_broker_message(message)

        except json.JSONDecodeError:
            await self.send_error("Invalid JSON format")
        except WebSocketError as e:
            await self.send_error(str(e))
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            await self.send_error("Internal server error")

    async def send_json(self, content: Dict[str, Any]) -> None:
        """Send JSON message with error handling."""
        try:
            await super().send(text_data=json.dumps(content))
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            raise WebSocketError(f"Failed to send message: {str(e)}")

    async def send_error(self, message: str, code: Optional[str] = None) -> None:
        """Send error message to client."""
        await self.send_json({
            'type': 'error',
            'message': message,
            'code': code,
            'timestamp': timezone.now().isoformat()
        })

    async def handle_subscription(self, data: Dict[str, Any]) -> None:
        """Handle subscription requests."""
        try:
            symbols = data.get('symbols', [])
            if not symbols:
                raise WebSocketValidationError("No symbols specified")

            for symbol in symbols:
                self.subscriptions.add(symbol)

            await self.send_json({
                'type': 'subscription_success',
                'data': {'symbols': list(self.subscriptions)}
            })

        except Exception as e:
            logger.error(f"Subscription error: {str(e)}")
            await self.send_error(str(e))

    async def handle_unsubscribe(self, data: Dict[str, Any]) -> None:
        """Handle unsubscribe requests."""
        try:
            symbols = data.get('symbols', [])
            if not symbols:
                raise WebSocketValidationError("No symbols specified")

            for symbol in symbols:
                self.subscriptions.discard(symbol)

            await self.send_json({
                'type': 'unsubscribe_success',
                'data': {'symbols': list(self.subscriptions)}
            })

        except Exception as e:
            logger.error(f"Unsubscribe error: {str(e)}")
            await self.send_error(str(e))

    async def handle_market_data(self, data: Dict[str, Any]) -> None:
        """Handle market data updates."""
        raise NotImplementedError("Subclasses must implement handle_market_data")

    async def handle_order(self, data: Dict[str, Any]) -> None:
        """Handle order requests."""
        raise NotImplementedError("Subclasses must implement handle_order")

    async def handle_broker_message(self, message: Dict[str, Any]) -> None:
        """Handle broker-specific messages."""
        raise NotImplementedError("Subclasses must implement handle_broker_message")

    async def verify_account_access(self) -> bool:
        """Verify user has access to the account."""
        raise NotImplementedError("Subclasses must implement verify_account_access")

    async def authenticate(self) -> bool:
        """Authenticate the WebSocket connection."""
        raise NotImplementedError("Subclasses must implement authenticate")

    async def send_initial_state(self) -> None:
        """Send initial state data after connection."""
        raise NotImplementedError("Subclasses must implement send_initial_state")

    async def start_background_tasks(self) -> None:
        """Start background tasks like heartbeat and cleanup."""
        self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        self.cleanup_task = asyncio.create_task(self.cleanup_loop())

    async def stop_background_tasks(self) -> None:
        """Stop background tasks."""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.cleanup_task:
            self.cleanup_task.cancel()
        try:
            await asyncio.gather(self.heartbeat_task, self.cleanup_task)
        except asyncio.CancelledError:
            pass

    async def heartbeat_loop(self) -> None:
        """Maintain connection heartbeat."""
        try:
            while True:
                await asyncio.sleep(settings.WEBSOCKET_HEARTBEAT_INTERVAL)
                if self.last_heartbeat:
                    time_since_last = (timezone.now() - self.last_heartbeat).total_seconds()
                    if time_since_last > settings.WEBSOCKET_HEARTBEAT_INTERVAL * 2:
                        logger.warning("Heartbeat timeout")
                        await self.close()
                        break
                await self.send_json({
                    'type': 'heartbeat',
                    'timestamp': timezone.now().isoformat()
                })

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in heartbeat loop: {str(e)}")
            await self.close()

    async def cleanup_loop(self) -> None:
        """Periodically cleanup resources."""
        try:
            while True:
                await asyncio.sleep(300)  # 5-minute cleanup interval
                if len(self.message_buffer) > self.buffer_limit:
                    self.message_buffer = self.message_buffer[-self.buffer_limit:]

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in cleanup loop: {str(e)}")

    async def cleanup(self) -> None:
        """Cleanup resources before disconnection."""
        self.message_buffer.clear()
        self.subscriptions.clear()

    async def handle_heartbeat(self, _: Dict[str, Any]) -> None:
        """Handle heartbeat messages."""
        self.last_heartbeat = timezone.now()
        await self.send_json({
            'type': 'heartbeat_response',
            'timestamp': timezone.now().isoformat()
        })