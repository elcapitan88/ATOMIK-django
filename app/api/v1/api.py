from fastapi import APIRouter
from .endpoints import auth, broker, webhooks, strategy, websocket, subscription, tradovate

api_router = APIRouter()

# Standard API routes
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(broker.router, prefix="/brokers", tags=["brokers"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(strategy.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(websocket.router, prefix="/ws", tags=["websocket"])
api_router.include_router(subscription.router, prefix="/subscriptions", tags=["subscriptions"])

# Special route for Tradovate callback - this needs to be at root level
tradovate_callback_router = APIRouter()
tradovate_callback_router.include_router(tradovate.router, prefix="/tradovate", tags=["tradovate"])

# Export both routers
__all__ = ['api_router', 'tradovate_callback_router']