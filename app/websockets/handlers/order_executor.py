from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime
import logging
import asyncio
from decimal import Decimal
import uuid

logger = logging.getLogger(__name__)

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"

class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"

class TimeInForce(Enum):
    DAY = "DAY"
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill

class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

class OrderValidationError(Exception):
    """Exception raised for order validation errors."""
    pass

class Order:
    """Represents a trading order."""
    
    def __init__(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
        client_order_id: Optional[str] = None
    ):
        self.order_id = str(uuid.uuid4())
        self.client_order_id = client_order_id or str(uuid.uuid4())
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.quantity = quantity
        self.price = price
        self.stop_price = stop_price
        self.time_in_force = time_in_force
        self.status = OrderStatus.PENDING
        self.filled_quantity = Decimal('0')
        self.average_fill_price = Decimal('0')
        self.created_at = datetime.utcnow()
        self.last_updated = datetime.utcnow()
        self.broker_order_id: Optional[str] = None
        self.error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert order to dictionary format."""
        return {
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": str(self.quantity),
            "price": str(self.price) if self.price else None,
            "stop_price": str(self.stop_price) if self.stop_price else None,
            "time_in_force": self.time_in_force.value,
            "status": self.status.value,
            "filled_quantity": str(self.filled_quantity),
            "average_fill_price": str(self.average_fill_price),
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "error_message": self.error_message
        }

class BaseOrderExecutor(ABC):
    """Abstract base class for order execution."""
    
    def __init__(self):
        self._order_callbacks: List[callable] = []
        self._active_orders: Dict[str, Order] = {}
        self._lock = asyncio.Lock()

    def register_order_callback(self, callback: callable):
        """Register callback for order updates."""
        self._order_callbacks.append(callback)

    async def _notify_order_callbacks(self, order: Order):
        """Notify all registered callbacks of order updates."""
        for callback in self._order_callbacks:
            try:
                await callback(order)
            except Exception as e:
                logger.error(f"Error in order callback: {str(e)}")

    @abstractmethod
    async def validate_order(self, order: Order) -> bool:
        """Validate order parameters."""
        pass

    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """Submit order to broker."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        pass

    async def execute_order(self, order: Order) -> Order:
        """Execute an order with validation and error handling."""
        try:
            # Validate order
            if not await self.validate_order(order):
                raise OrderValidationError("Order validation failed")

            # Submit order with lock to prevent race conditions
            async with self._lock:
                order = await self.submit_order(order)
                self._active_orders[order.order_id] = order

            # Notify callbacks
            await self._notify_order_callbacks(order)
            return order

        except Exception as e:
            logger.error(f"Error executing order: {str(e)}")
            order.status = OrderStatus.REJECTED
            order.error_message = str(e)
            await self._notify_order_callbacks(order)
            raise

    async def update_order_status(self, order_id: str, status_update: Dict[str, Any]):
        """Update order status and notify callbacks."""
        try:
            async with self._lock:
                if order_id not in self._active_orders:
                    logger.warning(f"Order not found: {order_id}")
                    return

                order = self._active_orders[order_id]
                order.status = OrderStatus[status_update.get('status', order.status.value)]
                order.filled_quantity = Decimal(str(status_update.get('filled_quantity', order.filled_quantity)))
                if 'average_fill_price' in status_update:
                    order.average_fill_price = Decimal(str(status_update['average_fill_price']))
                order.last_updated = datetime.utcnow()

                if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED]:
                    del self._active_orders[order_id]

            await self._notify_order_callbacks(order)

        except Exception as e:
            logger.error(f"Error updating order status: {str(e)}")
            raise

class TradovateOrderExecutor(BaseOrderExecutor):
    """Tradovate-specific order executor implementation."""

    async def validate_order(self, order: Order) -> bool:
        """Validate order parameters for Tradovate."""
        try:
            # Basic validation
            if not order.symbol or not order.quantity or order.quantity <= 0:
                raise OrderValidationError("Invalid symbol or quantity")

            # Order type specific validation
            if order.order_type in [OrderType.LIMIT, OrderType.STOP_LIMIT] and not order.price:
                raise OrderValidationError("Limit orders require a price")

            if order.order_type in [OrderType.STOP, OrderType.STOP_LIMIT] and not order.stop_price:
                raise OrderValidationError("Stop orders require a stop price")

            # Tradovate-specific validation
            # Add any broker-specific validation rules here

            return True

        except Exception as e:
            logger.error(f"Order validation error: {str(e)}")
            return False

    async def submit_order(self, order: Order) -> Order:
        """Submit order to Tradovate."""
        try:
            # Transform order to Tradovate format
            tradovate_order = self._transform_to_tradovate_format(order)
            
            # Submit to Tradovate (placeholder for actual API call)
            # response = await self._tradovate_api.submit_order(tradovate_order)
            
            # Update order with broker response
            order.status = OrderStatus.SUBMITTED
            # order.broker_order_id = response.get('orderId')
            order.last_updated = datetime.utcnow()
            
            logger.info(f"Order submitted successfully: {order.order_id}")
            return order

        except Exception as e:
            logger.error(f"Error submitting order: {str(e)}")
            order.status = OrderStatus.REJECTED
            order.error_message = str(e)
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order with Tradovate."""
        try:
            async with self._lock:
                if order_id not in self._active_orders:
                    raise ValueError(f"Order not found: {order_id}")

                order = self._active_orders[order_id]
                
                # Cancel with Tradovate (placeholder for actual API call)
                # response = await self._tradovate_api.cancel_order(order.broker_order_id)
                
                order.status = OrderStatus.CANCELLED
                order.last_updated = datetime.utcnow()
                del self._active_orders[order_id]
                
                await self._notify_order_callbacks(order)
                return True

        except Exception as e:
            logger.error(f"Error cancelling order: {str(e)}")
            raise

    def _transform_to_tradovate_format(self, order: Order) -> Dict[str, Any]:
        """Transform internal order format to Tradovate format."""
        return {
            "orderId": order.client_order_id,
            "symbol": order.symbol,
            "orderType": order.order_type.value,
            "side": order.side.value,
            "quantity": str(order.quantity),
            "price": str(order.price) if order.price else None,
            "stopPrice": str(order.stop_price) if order.stop_price else None,
            "timeInForce": order.time_in_force.value
        }