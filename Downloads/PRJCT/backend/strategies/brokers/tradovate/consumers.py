# strategies/brokers/tradovate/consumers.py

import logging
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from decimal import Decimal
from typing import Dict, List, Optional, Any
import asyncio
import requests
from django.utils import timezone
from django.conf import settings
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from ...consumers.base import BaseWebSocketConsumer
from .models import TradovateAccount, TradovateToken, TradovateOrder
from .utils import format_position
from .constants import (
    CONTRACT_SPECS,
    KNOWN_CONTRACTS,
    OrderStatus,
    OrderType,
    TimeInForce
)

logger = logging.getLogger(__name__)

class TradovateConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for Tradovate integration.
    Handles real-time market data and account updates.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.token_manager = TradovateTokenManager()
        self.account: Optional[TradovateAccount] = None
        self.token: Optional[TradovateToken] = None
        self.subscriptions = set()
        self.account_id: Optional[str] = None
        self.is_authenticated = False
        self.heartbeat_task = None
        self.last_heartbeat = None
        self.group_name = None
        self.message_handlers = {
            'subscribe': self.handle_subscription,
            'unsubscribe': self.handle_unsubscribe,
            'order': self.handle_order,
            'market_data': self.handle_market_data,
            'heartbeat': self.handle_heartbeat
        }

    async def connect(self):
        """Handle WebSocket connection setup."""
        logger.info("Establishing Tradovate WebSocket connection")
        
        try:
            # Get account_id from URL route
            self.account_id = self.scope['url_route']['kwargs'].get('account_id')
            if not self.account_id:
                raise WebSocketConnectionError("No account ID provided")

            # Get and validate account access
            self.account = await self.get_account()
            if not self.account:
                raise WebSocketConnectionError("Invalid account access")

            # Get valid token
            self.token = await sync_to_async(self.token_manager.get_valid_token)(
                self.scope["user"].id,
                self.account.environment
            )
            
            if not self.token:
                raise WebSocketAuthenticationError("No valid token available")

            # Accept the connection
            await self.accept()
            logger.info(f"WebSocket connection accepted for account {self.account_id}")

            # Set up group name for broadcasts
            self.group_name = f"tradovate_account_{self.account_id}"
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )

            # Initialize connection
            await self.initialize_connection()

        except Exception as e:
            logger.error(f"Connection error: {str(e)}", exc_info=True)
            await self.close()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        try:
            # Cancel heartbeat task
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
                try:
                    await self.heartbeat_task
                except asyncio.CancelledError:
                    pass

            # Unsubscribe from all data
            await self.unsubscribe_all()

            # Leave group
            if self.group_name:
                await self.channel_layer.group_discard(
                    self.group_name,
                    self.channel_name
                )

            logger.info(f"WebSocket disconnected for account {self.account_id}")

        except Exception as e:
            logger.error(f"Error during disconnect: {str(e)}")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            # Parse message
            try:
                message = json.loads(text_data)
            except json.JSONDecodeError:
                await self.send_error("Invalid JSON format")
                return

            # Update heartbeat
            self.last_heartbeat = timezone.now()

            # Route message to appropriate handler
            message_type = message.get('type')
            handler = self.message_handlers.get(message_type)
            
            if handler:
                await handler(message.get('data', {}))
            else:
                await self.send_error(f"Unknown message type: {message_type}")

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            await self.send_error(f"Message processing failed: {str(e)}")

    @sync_to_async
    def get_account(self) -> Optional[TradovateAccount]:
        """Get and validate account access."""
        try:
            return TradovateAccount.objects.get(
                account_id=self.account_id,
                user=self.scope["user"],
                is_active=True
            )
        except TradovateAccount.DoesNotExist:
            return None

    async def initialize_connection(self):
        """Initialize WebSocket connection and subscriptions."""
        # Start heartbeat
        self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        
        # Subscribe to account updates
        await self.subscribe_account_updates()
        
        # Send initial state
        await self.send_initial_state()

    async def heartbeat_loop(self):
        """Maintain connection heartbeat."""
        while True:
            try:
                await asyncio.sleep(15)  # 15-second interval
                await self.send_json({
                    'type': 'heartbeat',
                    'timestamp': timezone.now().isoformat()
                })
                
                # Check for missed heartbeats
                if self.last_heartbeat:
                    time_since_last = (timezone.now() - self.last_heartbeat).total_seconds()
                    if time_since_last > 30:  # 30-second timeout
                        logger.warning("Heartbeat timeout, closing connection")
                        await self.close()
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {str(e)}")
                await self.close()
                break

    async def handle_subscription(self, data):
        """Handle market data subscription requests."""
        symbols = data.get('symbols', [])
        if not symbols:
            await self.send_error("No symbols specified")
            return

        try:
            # Subscribe to market data
            base_url = (
                settings.TRADOVATE_LIVE_WS_URL 
                if self.account.environment == 'live' 
                else settings.TRADOVATE_DEMO_WS_URL
            )
            
            for symbol in symbols:
                subscription = {
                    "op": "subscribe",
                    "args": ["md/subscribeQuote", {"symbol": symbol}]
                }
                await self.send_json(subscription)
                self.subscriptions.add(symbol)

            await self.send_json({
                'type': 'subscription_success',
                'data': {'symbols': list(self.subscriptions)}
            })

        except Exception as e:
            logger.error(f"Subscription error: {str(e)}")
            await self.send_error(f"Subscription failed: {str(e)}")

    async def handle_unsubscribe(self, data):
        """Handle market data unsubscription requests."""
        symbols = data.get('symbols', [])
        if not symbols:
            await self.send_error("No symbols specified")
            return

        try:
            for symbol in symbols:
                if symbol in self.subscriptions:
                    unsubscription = {
                        "op": "unsubscribe",
                        "args": ["md/unsubscribeQuote", {"symbol": symbol}]
                    }
                    await self.send_json(unsubscription)
                    self.subscriptions.remove(symbol)

            await self.send_json({
                'type': 'unsubscribe_success',
                'data': {'symbols': list(self.subscriptions)}
            })

        except Exception as e:
            logger.error(f"Unsubscription error: {str(e)}")
            await self.send_error(f"Unsubscription failed: {str(e)}")

    async def unsubscribe_all(self):
        """Unsubscribe from all market data."""
        if self.subscriptions:
            await self.handle_unsubscribe({'symbols': list(self.subscriptions)})

    async def handle_order(self, data):
        """Handle order submissions."""
        if not self.account_id:
            await self.send_error("No account ID specified")
            return

        try:
            # Validate order parameters
            # Add order validation logic here
            
            # Submit order
            # Add order submission logic here
            
            await self.send_json({
                'type': 'order_response',
                'data': {'status': 'submitted'}
            })

        except Exception as e:
            logger.error(f"Order error: {str(e)}")
            await self.send_error(f"Order submission failed: {str(e)}")

    async def handle_market_data(self, data):
        """Handle market data updates."""
        try:
            await self.send_json({
                'type': 'market_data',
                'data': data
            })
        except Exception as e:
            logger.error(f"Market data error: {str(e)}")

    async def handle_heartbeat(self, _):
        """Handle heartbeat messages."""
        self.last_heartbeat = timezone.now()
        await self.send_json({
            'type': 'heartbeat_response',
            'timestamp': timezone.now().isoformat()
        })

    async def send_error(self, message: str):
        """Send error message to client."""
        await self.send_json({
            'type': 'error',
            'message': message,
            'timestamp': timezone.now().isoformat()
        })

    async def send_json(self, content: Dict[str, Any]):
        """Send JSON message with error handling."""
        try:
            await self.send(text_data=json.dumps(content))
        except Exception as e:
            logger.error(f"Send error: {str(e)}")
            raise WebSocketError(f"Failed to send message: {str(e)}")

    async def subscribe_account_updates(self):
        """Subscribe to account-specific updates."""
        try:
            subscription = {
                "op": "subscribe",
                "args": [
                    "user/changes",
                    {
                        "users": True,
                        "accounts": True,
                        "positions": True,
                        "orders": True,
                        "fills": True
                    }
                ]
            }
            await self.send_json(subscription)
            logger.info(f"Subscribed to updates for account {self.account_id}")
        except Exception as e:
            logger.error(f"Error subscribing to account updates: {str(e)}")
            raise

    async def send_initial_state(self):
        """Send initial state data after connection."""
        try:
            # Add logic to fetch and send initial account state
            pass
        except Exception as e:
            logger.error(f"Error sending initial state: {str(e)}")