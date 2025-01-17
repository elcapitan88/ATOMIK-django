from typing import Dict, List, Any, Optional
from datetime import datetime
from decimal import Decimal

from ..base.types import (
    OrderType, OrderSide, OrderStatus, TimeInForce,
    PositionSide, AccountStatus, OrderUpdate, PositionUpdate,
    AccountUpdate, TradeUpdate
)
from .constants import CONTRACT_SPECS

class TradovateSerializer:
    """
    Serializer class for Tradovate data structures.
    Handles conversion between Tradovate API formats and internal application formats.
    """

    @staticmethod
    def serialize_order_request(order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize internal order format to Tradovate API format."""
        serialized = {
            "accountSpec": order_data.get("account_id"),
            "symbol": order_data.get("symbol"),
            "orderQty": abs(order_data.get("quantity", 0)),
            "action": "Buy" if order_data.get("side") == OrderSide.BUY else "Sell",
            "orderType": order_data.get("order_type", "Market"),
            "isAutomated": True
        }

        # Add optional fields if present
        if "price" in order_data:
            serialized["price"] = float(order_data["price"])
        
        if "stop_price" in order_data:
            serialized["stopPrice"] = float(order_data["stop_price"])
        
        if "time_in_force" in order_data:
            serialized["timeInForce"] = order_data["time_in_force"]

        if "client_order_id" in order_data:
            serialized["clientId"] = order_data["client_order_id"]

        return serialized

    @staticmethod
    def deserialize_order(order_data: Dict[str, Any]) -> OrderUpdate:
        """Convert Tradovate order format to internal format."""
        return {
            "order_id": str(order_data.get("orderId")),
            "client_order_id": order_data.get("clientId"),
            "broker_order_id": str(order_data.get("id")),
            "status": TradovateSerializer._map_order_status(order_data.get("status")),
            "filled_quantity": Decimal(str(order_data.get("filledQty", 0))),
            "remaining_quantity": Decimal(str(order_data.get("remainingQty", 0))),
            "average_price": Decimal(str(order_data.get("avgPrice", 0))),
            "last_filled_price": Decimal(str(order_data.get("lastFillPrice", 0))),
            "last_filled_quantity": Decimal(str(order_data.get("lastFillQty", 0))),
            "timestamp": datetime.fromtimestamp(order_data.get("timestamp") / 1000.0)
        }

    @staticmethod
    def deserialize_position(position_data: Dict[str, Any]) -> PositionUpdate:
        """Convert Tradovate position format to internal format."""
        quantity = Decimal(str(position_data.get("netPos", 0)))
        side = PositionSide.LONG if quantity > 0 else PositionSide.SHORT
        
        return {
            "symbol": position_data.get("symbol"),
            "quantity": abs(quantity),
            "entry_price": Decimal(str(position_data.get("avgPrice", 0))),
            "current_price": Decimal(str(position_data.get("lastPrice", 0))),
            "unrealized_pnl": Decimal(str(position_data.get("unrealizedPnL", 0))),
            "realized_pnl": Decimal(str(position_data.get("realizedPnL", 0))),
            "side": side,
            "timestamp": datetime.fromtimestamp(position_data.get("timestamp") / 1000.0)
        }

    @staticmethod
    def deserialize_account(account_data: Dict[str, Any]) -> AccountUpdate:
        """Convert Tradovate account format to internal format."""
        return {
            "account_id": str(account_data.get("id")),
            "status": TradovateSerializer._map_account_status(account_data.get("status")),
            "balance": Decimal(str(account_data.get("cashBalance", 0))),
            "equity": Decimal(str(account_data.get("netLiq", 0))),
            "margin_used": Decimal(str(account_data.get("marginUsed", 0))),
            "margin_available": Decimal(str(account_data.get("marginAvailable", 0))),
            "timestamp": datetime.fromtimestamp(account_data.get("timestamp") / 1000.0)
        }

    @staticmethod
    def deserialize_trade(trade_data: Dict[str, Any]) -> TradeUpdate:
        """Convert Tradovate trade format to internal format."""
        return {
            "trade_id": str(trade_data.get("id")),
            "order_id": str(trade_data.get("orderId")),
            "symbol": trade_data.get("symbol"),
            "side": OrderSide.BUY if trade_data.get("action") == "Buy" else OrderSide.SELL,
            "quantity": Decimal(str(trade_data.get("qty", 0))),
            "price": Decimal(str(trade_data.get("price", 0))),
            "timestamp": datetime.fromtimestamp(trade_data.get("timestamp") / 1000.0)
        }

    @staticmethod
    def serialize_ws_auth(access_token: str) -> Dict[str, Any]:
        """Serialize WebSocket authentication message."""
        return {
            "op": "authorize",
            "args": [access_token]
        }

    @staticmethod
    def serialize_ws_subscription(
        subscription_type: str,
        symbols: Optional[List[str]] = None,
        account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Serialize WebSocket subscription message."""
        payload = {
            "op": "subscribe",
            "args": [subscription_type]
        }

        if symbols:
            payload["symbols"] = symbols
        if account_id:
            payload["account_id"] = account_id

        return payload

    @staticmethod
    def _map_order_status(status: str) -> OrderStatus:
        """Map Tradovate order status to internal status."""
        status_map = {
            "Accepted": OrderStatus.PENDING,
            "Working": OrderStatus.WORKING,
            "Completed": OrderStatus.FILLED,
            "Cancelled": OrderStatus.CANCELLED,
            "Rejected": OrderStatus.REJECTED,
            "Expired": OrderStatus.EXPIRED
        }
        return status_map.get(status, OrderStatus.PENDING)

    @staticmethod
    def _map_account_status(status: str) -> AccountStatus:
        """Map Tradovate account status to internal status."""
        status_map = {
            "Active": AccountStatus.ACTIVE,
            "Inactive": AccountStatus.INACTIVE,
            "Suspended": AccountStatus.SUSPENDED,
            "Closed": AccountStatus.INACTIVE
        }
        return status_map.get(status, AccountStatus.ERROR)

    @staticmethod
    def calculate_margin_requirement(
        symbol: str,
        quantity: int,
        is_day_trade: bool = True
    ) -> Decimal:
        """Calculate margin requirement for a position."""
        if symbol not in CONTRACT_SPECS:
            raise ValueError(f"Unknown symbol: {symbol}")

        contract = CONTRACT_SPECS[symbol]
        margin = (
            Decimal(str(contract["margin_day"])) if is_day_trade 
            else Decimal(str(contract["margin_overnight"]))
        )
        
        return margin * Decimal(str(quantity))

    @staticmethod
    def calculate_position_value(
        symbol: str,
        quantity: int,
        price: Decimal
    ) -> Decimal:
        """Calculate total position value."""
        if symbol not in CONTRACT_SPECS:
            raise ValueError(f"Unknown symbol: {symbol}")

        contract = CONTRACT_SPECS[symbol]
        tick_value = Decimal(str(contract["value_per_tick"]))
        ticks_per_point = Decimal('4')  # Standard for most futures
        
        return quantity * price * tick_value * ticks_per_point

    @staticmethod
    def format_price(symbol: str, price: Decimal) -> Decimal:
        """Format price according to contract specifications."""
        if symbol not in CONTRACT_SPECS:
            raise ValueError(f"Unknown symbol: {symbol}")

        contract = CONTRACT_SPECS[symbol]
        tick_size = Decimal(str(contract["tick_size"]))
        return Decimal(str(round(price / tick_size) * tick_size))