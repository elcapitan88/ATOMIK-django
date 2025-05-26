# app/models/__init__.py
from .user import User
from .webhook import Webhook, WebhookLog
from .strategy import ActivatedStrategy
from .broker import BrokerAccount, BrokerCredentials
from .subscription import Subscription
from .order import Order

# This ensures all models are registered
__all__ = [
    "User",
    "Webhook",
    "WebhookLog",
    "ActivatedStrategy",
    "BrokerAccount",
    "BrokerCredentials",
    "Subscription",
    "Order"
]