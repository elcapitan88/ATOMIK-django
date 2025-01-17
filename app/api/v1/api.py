# app/api/v1/api.py
from fastapi import APIRouter, Depends
from .endpoints import auth, broker, webhooks, strategy, websocket, subscription, tradovate
from typing import Optional
from sqlalchemy.orm import Session
from app.db.session import get_db

# Create routers
api_router = APIRouter()
tradovate_callback_router = APIRouter()

# Include all standard routes under /api/v1
api_router.include_router(tradovate.router, prefix="/brokers/tradovate", tags=["tradovate"])
api_router.include_router(broker.router, prefix="/brokers", tags=["brokers"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(strategy.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(websocket.router, prefix="/ws", tags=["websocket"])
api_router.include_router(subscription.router, prefix="/subscriptions", tags=["subscriptions"])

# Define the callback route - Notice the change in the path
@tradovate_callback_router.get("/tradovate/callback")  # Changed from "/api/tradovate/callback"
async def tradovate_callback_handler(
    code: str,
    state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return await tradovate.tradovate_callback(code=code, state=state, db=db)