# In app/services/trading_service.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from contextlib import contextmanager
from sqlalchemy.orm import Session
from app.db.session import SessionLocal, get_db_context
from app.models.order import Order, OrderStatus, OrderSide, OrderType
from app.models.broker import BrokerAccount
from app.core.brokers.base import BaseBroker
from app.core.subscription_tiers import SubscriptionTier

logger = logging.getLogger(__name__)

class OrderStatusMonitoringService:
    """Service to monitor and update order statuses through polling"""
    
    def __init__(self):
        self._active_monitors = {}  # Track by order ID
        self._is_running = False
        self._monitoring_task = None
    
    async def initialize(self):
        """Initialize the service and start polling"""
        if self._is_running:
            return
            
        self._is_running = True
        self._monitoring_task = asyncio.create_task(self._run_monitoring_loop())
        logger.info("Order status monitoring service started")
    
    async def shutdown(self):
        """Shutdown the service"""
        self._is_running = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("Order status monitoring service stopped")
    
    async def add_order(self, order_id: str, account: BrokerAccount, user_id: int, order_data: Optional[Dict[str, Any]] = None):
        """Add a new order to be monitored"""
        if not order_id or order_id == "None":
            logger.warning(f"Attempted to monitor invalid order ID: {order_id}")
            return

        # Use proper async session context manager
        async with get_db_context() as db:
            try:
                # Check if order exists in database
                order = db.query(Order).filter(
                    Order.broker_order_id == str(order_id)
                ).first()
                
                if not order:
                    if order_data:
                        logger.info(f"Order {order_id} not found in database, creating complete record with order data")
                        # Create a complete order record with provided data
                        order = Order(
                            broker_order_id=str(order_id),
                            broker_account_id=account.id, 
                            user_id=user_id,
                            symbol=order_data.get('symbol'),
                            side=OrderSide(order_data.get('side', '').lower()),
                            order_type=OrderType(order_data.get('type', 'MARKET').lower()),
                            quantity=order_data.get('quantity'),
                            remaining_quantity=order_data.get('quantity'),
                            time_in_force=order_data.get('time_in_force', 'GTC'),
                            status=OrderStatus.PENDING,
                            submitted_at=datetime.utcnow()
                        )
                    else:
                        logger.warning(f"Order {order_id} not found in database, creating minimal placeholder (missing order_data)")
                        # Fallback to minimal placeholder (this shouldn't happen anymore)
                        order = Order(
                            broker_order_id=str(order_id),
                            broker_account_id=account.id, 
                            user_id=user_id,
                            status=OrderStatus.PENDING,
                            submitted_at=datetime.utcnow()
                        )
                    db.add(order)
                    db.commit()
                    db.refresh(order)
                
                # Add to monitoring list
                self._active_monitors[order_id] = {
                    "account": account,
                    "last_check": datetime.utcnow(),
                    "next_check": datetime.utcnow(),  # Start checking right away
                    "check_count": 0,
                    "backoff_factor": 1.0,
                    "user_id": user_id,
                    "order_db_id": order.id
                }
                
                logger.info(f"Added order {order_id} to monitoring queue")
                
            except Exception as e:
                logger.error(f"Error adding order to monitoring: {str(e)}")
                # Session rollback handled by context manager
    
    async def _run_monitoring_loop(self):
        """Main polling loop"""
        try:
            while self._is_running:
                now = datetime.utcnow()
                orders_to_check = []
                
                # Identify orders that need checking
                for order_id, data in list(self._active_monitors.items()):
                    if now >= data["next_check"]:
                        orders_to_check.append(order_id)
                
                # Check orders in batches to avoid overloading
                for order_id in orders_to_check:
                    if order_id not in self._active_monitors:
                        continue  # Order might have been removed
                        
                    await self._check_order_status(order_id)
                
                # Sleep briefly before next cycle
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logger.info("Order monitoring loop cancelled")
        except Exception as e:
            logger.error(f"Error in order monitoring loop: {str(e)}")
            # Auto-restart loop if it crashes
            if self._is_running:
                self._monitoring_task = asyncio.create_task(self._run_monitoring_loop())
    
    async def _check_order_status(self, order_id: str):
        """Check status of a specific order"""
        if order_id not in self._active_monitors:
            return
            
        monitor_data = self._active_monitors[order_id]
        account = monitor_data["account"]
        
        # Use proper session context manager for each check
        async with get_db_context() as db:
            try:
                # Get broker instance
                broker = BaseBroker.get_broker_instance(account.broker_id, db)
                
                # Call get_order_status (need to implement in TradovateBroker)
                status_result = await broker.get_order_status(account, order_id)
                
                # Update the order in database
                order = db.query(Order).get(monitor_data["order_db_id"])
                if order:
                    old_status = order.status
                    
                    # Update order fields
                    order.status = status_result.get("status", order.status)
                    order.filled_quantity = status_result.get("filled_quantity", order.filled_quantity)
                    order.remaining_quantity = status_result.get("remaining_quantity", order.remaining_quantity)
                    order.average_fill_price = status_result.get("average_price", order.average_fill_price)
                    order.updated_at = datetime.utcnow()
                    
                    # Set filled_at timestamp if newly filled
                    if old_status != OrderStatus.FILLED and order.status == OrderStatus.FILLED:
                        order.filled_at = datetime.utcnow()
                        logger.info(f"Order {order_id} filled at price {order.average_fill_price}")
                    
                    # Save changes
                    db.commit()
                    
                    # Log status change
                    if old_status != order.status:
                        logger.info(f"Order {order_id} status changed: {old_status} -> {order.status}")
                    
                    # Stop monitoring if we've reached a terminal state
                    if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED]:
                        logger.info(f"Order {order_id} reached terminal state {order.status}, removing from monitoring")
                        self._remove_from_monitoring(order_id)
                        return
                
                # Update monitoring data
                if order_id in self._active_monitors:
                    monitor_data["last_check"] = datetime.utcnow()
                    monitor_data["check_count"] += 1
                    
                    # Exponential backoff - check more frequently initially, then slow down
                    # Start with 3 second interval, increase exponentially, cap at 30 seconds
                    if monitor_data["check_count"] < 5:
                        next_interval = 3  # First few checks are frequent
                    else:
                        monitor_data["backoff_factor"] = min(
                            monitor_data["backoff_factor"] * 1.5,  # Exponential growth
                            10.0  # Maximum backoff factor
                        )
                        next_interval = min(3 * monitor_data["backoff_factor"], 30)
                    
                    monitor_data["next_check"] = datetime.utcnow() + timedelta(seconds=next_interval)
                    
                    # If we've been checking for too long, give up
                    if monitor_data["check_count"] > 60:  # After ~30 minutes
                        logger.warning(f"Giving up on monitoring order {order_id} after {monitor_data['check_count']} checks")
                        self._remove_from_monitoring(order_id)
                
            except Exception as e:
                logger.error(f"Error checking order {order_id} status: {str(e)}")
                
                # Increase backoff on errors
                if order_id in self._active_monitors:
                    monitor_data = self._active_monitors[order_id]
                    monitor_data["backoff_factor"] = min(monitor_data["backoff_factor"] * 2, 10.0)
                    monitor_data["next_check"] = datetime.utcnow() + timedelta(
                        seconds=min(5 * monitor_data["backoff_factor"], 60)
                    )
                    monitor_data["check_count"] += 1
                    
                    # Give up after too many errors
                    if monitor_data["check_count"] > 20:
                        logger.warning(f"Giving up on monitoring order {order_id} after too many errors")
                        self._remove_from_monitoring(order_id)
                # Session cleanup handled by context manager
    
    def _remove_from_monitoring(self, order_id: str):
        """Remove an order from monitoring"""
        if order_id in self._active_monitors:
            del self._active_monitors[order_id]
    
    def get_stats(self):
        """Get statistics about currently monitored orders"""
        return {
            "active_monitors": len(self._active_monitors),
            "running": self._is_running,
            "orders": [
                {
                    "order_id": order_id,
                    "checks": data["check_count"],
                    "last_check": data["last_check"].isoformat(),
                    "next_check": data["next_check"].isoformat(),
                    "account_id": data["account"].account_id
                }
                for order_id, data in self._active_monitors.items()
            ]
        }

# Create a singleton instance
order_monitoring_service = OrderStatusMonitoringService()

def get_order_monitoring_service():
    """Get the global order monitoring service instance"""
    return order_monitoring_service