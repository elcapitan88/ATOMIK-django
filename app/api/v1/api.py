# app/api/v1/api.py
from fastapi import APIRouter, Depends
from .endpoints import auth, broker, subscriptions, webhooks, strategy, tradovate, support, interactivebrokers, chat, feature_flags
from .endpoints.admin import admin
from .endpoints import chat_sse
from typing import Optional
from sqlalchemy.orm import Session
from app.db.session import get_db

# Create routers
api_router = APIRouter()
tradovate_callback_router = APIRouter()


api_router.include_router(broker.router, prefix="/brokers", tags=["brokers"])
api_router.include_router(tradovate.router, prefix="/brokers/tradovate", tags=["tradovate"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(strategy.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(subscriptions.router, prefix="/subscriptions", tags=["subscriptions"])
api_router.include_router(support.router, prefix="/support", tags=["support"])
api_router.include_router(interactivebrokers.router, prefix="/brokers/interactivebrokers", tags=["interactivebrokers"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(chat_sse.router, prefix="/chat", tags=["chat-sse"])
api_router.include_router(feature_flags.router, prefix="/beta", tags=["feature-flags"])

# Define the callback route - Notice the change in the path
@tradovate_callback_router.get("/tradovate/callback")  # Changed from "/api/tradovate/callback"
async def tradovate_callback_handler(
    code: str,
    state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return await tradovate.tradovate_callback(code=code, state=state, db=db)