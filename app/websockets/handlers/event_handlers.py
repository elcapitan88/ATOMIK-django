from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable, Union
from datetime import datetime
import logging
import asyncio
from enum import Enum
import json

logger = logging.getLogger(__name__)

class EventType(Enum):
    """Enumeration of possible event types."""
    MARKET_DATA = "market_data"
    ORDER_UPDATE = "order_update"
    POSITION_UPDATE = "position_update"
    ACCOUNT_UPDATE = "account_update"
    TRADE_UPDATE = "trade_update"
    CONNECTION_STATUS = "connection_status"
    ERROR = "error"

class EventPriority(Enum):
    """Priority levels for event processing."""
    HIGH = 1
    MEDIUM = 2
    LOW = 3

class Event:
    """Base event class containing common event attributes."""
    def __init__(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        timestamp: Optional[datetime] = None,
        priority: EventPriority = EventPriority.MEDIUM,
        source: str = ""
    ):
        self.event_type = event_type
        self.data = data
        self.timestamp = timestamp or datetime.utcnow()
        self.priority = priority
        self.source = source
        self.processed = False
        self.processing_attempts = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary format."""
        return {
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority.value,
            "source": self.source,
            "processed": self.processed,
            "processing_attempts": self.processing_attempts
        }

class BaseEventHandler(ABC):
    """Abstract base class for event handlers."""
    
    def __init__(self):
        self.handlers: Dict[EventType, List[Callable]] = {
            event_type: [] for event_type in EventType
        }
        self._event_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._processing = False
        self._retry_delays = [1, 5, 15, 30, 60]  # Seconds between retry attempts
        self._lock = asyncio.Lock()

    def register_handler(self, event_type: Union[EventType, str], handler: Callable) -> None:
        """Register a handler function for a specific event type."""
        if isinstance(event_type, str):
            try:
                event_type = EventType(event_type)
            except ValueError:
                logger.error(f"Invalid event type: {event_type}")
                return

        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)
        logger.info(f"Registered new handler for event type: {event_type.value}")

    async def push_event(self, event: Event) -> None:
        """Push an event to the processing queue."""
        await self._event_queue.put((event.priority.value, event))
        logger.debug(f"Pushed event to queue: {event.event_type.value}")

    async def start_processing(self) -> None:
        """Start processing events from the queue."""
        async with self._lock:
            if self._processing:
                return
            self._processing = True
        
        while self._processing:
            try:
                _, event = await self._event_queue.get()
                await self._process_event(event)
                self._event_queue.task_done()
            except Exception as e:
                logger.error(f"Error processing event: {str(e)}")

    async def stop_processing(self) -> None:
        """Stop processing events."""
        async with self._lock:
            self._processing = False
        logger.info("Event processing stopped")

    async def _process_event(self, event: Event) -> None:
        """Process a single event."""
        if event.event_type not in self.handlers:
            logger.warning(f"No handlers registered for event type: {event.event_type.value}")
            return

        event.processing_attempts += 1
        
        try:
            for handler in self.handlers[event.event_type]:
                await handler(event)
            event.processed = True
            logger.debug(f"Successfully processed event: {event.event_type.value}")
        except Exception as e:
            logger.error(f"Error processing event {event.event_type.value}: {str(e)}")
            if event.processing_attempts <= len(self._retry_delays):
                delay = self._retry_delays[event.processing_attempts - 1]
                await asyncio.sleep(delay)
                await self.push_event(event)
            else:
                logger.error(f"Max retries exceeded for event: {event.event_type.value}")

    @abstractmethod
    async def handle_market_data(self, event: Event) -> None:
        """Handle market data events."""
        pass

    @abstractmethod
    async def handle_order_update(self, event: Event) -> None:
        """Handle order update events."""
        pass

    @abstractmethod
    async def handle_position_update(self, event: Event) -> None:
        """Handle position update events."""
        pass

    @abstractmethod
    async def handle_account_update(self, event: Event) -> None:
        """Handle account update events."""
        pass

class TradovateEventHandler(BaseEventHandler):
    """Tradovate-specific implementation of event handler."""

    def __init__(self):
        super().__init__()
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Set up default handlers for Tradovate events."""
        self.register_handler(EventType.MARKET_DATA, self.handle_market_data)
        self.register_handler(EventType.ORDER_UPDATE, self.handle_order_update)
        self.register_handler(EventType.POSITION_UPDATE, self.handle_position_update)
        self.register_handler(EventType.ACCOUNT_UPDATE, self.handle_account_update)

    async def handle_market_data(self, event: Event) -> None:
        """Handle Tradovate market data events."""
        try:
            data = event.data
            # Transform Tradovate-specific market data format
            transformed_data = {
                "symbol": data.get("contractId"),
                "price": data.get("lastPrice"),
                "volume": data.get("volume"),
                "timestamp": data.get("timestamp"),
                "bid": data.get("bidPrice"),
                "ask": data.get("askPrice")
            }
            
            logger.info(f"Processed market data for {transformed_data['symbol']}")
            
            # Here you would typically:
            # 1. Update local market data cache
            # 2. Notify any registered market data listeners
            # 3. Trigger any relevant market data based calculations
            
            return transformed_data
            
        except Exception as e:
            logger.error(f"Error handling market data: {str(e)}")
            raise

    async def handle_order_update(self, event: Event) -> None:
        """Handle Tradovate order update events."""
        try:
            data = event.data
            transformed_data = {
                "order_id": data.get("orderId"),
                "status": data.get("orderStatus"),
                "filled_quantity": data.get("filledQty"),
                "remaining_quantity": data.get("remainingQty"),
                "timestamp": data.get("timestamp"),
                "price": data.get("price"),
                "symbol": data.get("contractId")
            }
            
            logger.info(f"Processed order update for order {transformed_data['order_id']}")
            
            # Here you would typically:
            # 1. Update order status in local cache
            # 2. Notify any order status listeners
            # 3. Update related position calculations
            
            return transformed_data
            
        except Exception as e:
            logger.error(f"Error handling order update: {str(e)}")
            raise

    async def handle_position_update(self, event: Event) -> None:
        """Handle Tradovate position update events."""
        try:
            data = event.data
            transformed_data = {
                "symbol": data.get("contractId"),
                "position": data.get("netPos"),
                "avg_price": data.get("avgPrice"),
                "unrealized_pl": data.get("unrealizedPL"),
                "realized_pl": data.get("realizedPL"),
                "timestamp": data.get("timestamp")
            }
            
            logger.info(f"Processed position update for {transformed_data['symbol']}")
            
            # Here you would typically:
            # 1. Update position cache
            # 2. Update risk calculations
            # 3. Notify position listeners
            
            return transformed_data
            
        except Exception as e:
            logger.error(f"Error handling position update: {str(e)}")
            raise

    async def handle_account_update(self, event: Event) -> None:
        """Handle Tradovate account update events."""
        try:
            data = event.data
            transformed_data = {
                "account_id": data.get("accountId"),
                "balance": data.get("balance"),
                "margin_used": data.get("marginUsed"),
                "margin_available": data.get("marginAvailable"),
                "timestamp": data.get("timestamp")
            }
            
            logger.info(f"Processed account update for account {transformed_data['account_id']}")
            
            # Here you would typically:
            # 1. Update account status cache
            # 2. Check for margin warnings
            # 3. Update trading limits
            
            return transformed_data
            
        except Exception as e:
            logger.error(f"Error handling account update: {str(e)}")
            raise

    async def process_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Process any type of event with appropriate handler."""
        try:
            event = Event(
                event_type=EventType(event_type),
                data=data,
                timestamp=datetime.utcnow()
            )
            await self.push_event(event)
        except Exception as e:
            logger.error(f"Error processing event: {str(e)}")
            raise