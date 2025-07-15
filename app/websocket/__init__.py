"""
Application WebSocket Package

⚠️ IMPORTANT: This is for APPLICATION WebSocket (chat, notifications, UI events)
NOT for trading data! Trading WebSocket is in /Websocket-Proxy/

This package contains:
- WebSocket connection management
- Authentication helpers
- Message handlers
- WebSocket utilities

Separated from trading WebSocket for clean architecture.
"""

from .manager import app_websocket_manager
from .auth import get_current_user_websocket, validate_websocket_permissions, get_user_chat_channels

__all__ = [
    "app_websocket_manager",
    "get_current_user_websocket", 
    "validate_websocket_permissions",
    "get_user_chat_channels"
]