# app/api/v1/api.py
from fastapi import APIRouter, Depends
import logging

# Setup logging for import debugging
logger = logging.getLogger(__name__)
logger.info("Starting API router imports...")

try:
    from .endpoints import auth, broker, subscription, webhooks, strategy, tradovate, binance, futures_contracts
    logger.info("Basic endpoints imported successfully")
    
    from .endpoints import admin
    logger.info("Admin endpoint imported successfully")
    
    # Import missing endpoints that are expected by frontend
    from .endpoints import chat, feature_flags, interactivebrokers
    logger.info("Chat, feature flags, and Interactive Brokers endpoints imported successfully")
except Exception as e:
    logger.error(f"Error importing endpoints: {e}")
    import traceback
    logger.error(traceback.format_exc())

# Temporarily disabled strategy_ai endpoints to fix startup issues
# from .endpoints.strategy_ai import interpret_router, generate_router, templates_router, context_router
from typing import Optional
from sqlalchemy.orm import Session
from app.db.session import get_db

# Create routers
api_router = APIRouter()
tradovate_callback_router = APIRouter()

# Include all standard routes under /api/v1
api_router.include_router(tradovate.router, prefix="/brokers/tradovate", tags=["tradovate"])
api_router.include_router(binance.router, prefix="/brokers/binance", tags=["binance"])
api_router.include_router(broker.router, prefix="/brokers", tags=["brokers"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(strategy.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(subscription.router, prefix="/subscriptions", tags=["subscriptions"])

# Register admin router with logging
try:
    logger.info("Registering admin router...")
    api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
    logger.info(f"Admin router registered successfully with {len(admin.router.routes)} routes")
    for route in admin.router.routes:
        logger.info(f"Admin route: {route.methods} {route.path}")
except Exception as e:
    logger.error(f"Error registering admin router: {e}")

# Register missing routers that are expected by frontend
try:
    logger.info("Registering missing routers...")
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
    logger.info("Chat router registered")
    
    
    api_router.include_router(feature_flags.router, prefix="/beta", tags=["features"])
    logger.info("Feature flags router registered")
    
    api_router.include_router(interactivebrokers.router, prefix="/brokers/interactivebrokers", tags=["interactive-brokers"])
    logger.info("Interactive Brokers router registered")
    
    api_router.include_router(futures_contracts.router, prefix="/futures-contracts", tags=["futures-contracts"])
    logger.info("All missing routers registered successfully")
except Exception as e:
    logger.error(f"Error registering missing routers: {e}")
    import traceback
    logger.error(traceback.format_exc())

# Define the callback route - Notice the change in the path
@tradovate_callback_router.get("/tradovate/callback")  # Changed from "/api/tradovate/callback"
async def tradovate_callback_handler(
    code: str,
    state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return await tradovate.tradovate_callback(code=code, state=state, db=db)