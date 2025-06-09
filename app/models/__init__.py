# app/models/__init__.py
from .user import User
from .webhook import Webhook, WebhookLog
from .strategy import ActivatedStrategy
from .broker import BrokerAccount, BrokerCredentials
from .subscription import Subscription
from .order import Order
from .support import SupportTicketLog
from .promo_code import PromoCode
from .password_reset import PasswordReset
from .chat import (
    ChatChannel,
    ChatMessage,
    ChatReaction,
    UserChatRole,
    UserChatSettings,
    ChatChannelMember
)
# Temporarily commented out to fix database schema issues
# from .strategy_ai import (
#     StrategyTemplate,
#     StrategyInterpretation,
#     StrategyCustomization,
#     GeneratedCode,
#     AIUsageTracking,
#     ComponentInterpretation
# )

# This ensures all models are registered
__all__ = [
    "User",
    "Webhook",
    "WebhookLog",
    "ActivatedStrategy",
    "BrokerAccount",
    "BrokerCredentials",
    "Subscription",
    "Order",
    "SupportTicketLog",
    "PromoCode",
    "PasswordReset",
    "ChatChannel",
    "ChatMessage",
    "ChatReaction",
    "UserChatRole",
    "UserChatSettings",
    "ChatChannelMember",
    # "StrategyTemplate",
    # "StrategyInterpretation", 
    # "StrategyCustomization",
    # "GeneratedCode",
    # "AIUsageTracking",
    # "ComponentInterpretation"
]