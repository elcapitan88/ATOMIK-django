# main.py
from fastapi import FastAPI, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, Callable, Set, Dict, Any
from contextlib import asynccontextmanager

# Standard library imports
import logging
import asyncio
from datetime import datetime

# FastAPI imports
from fastapi.middleware.cors import CORSMiddleware

# SQLAlchemy imports
from sqlalchemy.exc import SQLAlchemyError

# Local imports
from app.api.v1.api import api_router, tradovate_callback_router
from app.core.config import settings
from app.websockets.manager import websocket_manager
from app.db.base import init_db, get_db
from app.db.session import engine, get_db
from app.core.db_health import check_database_health
from app.core.tasks.token_refresh import start_token_refresh_task, stop_token_refresh_task
from app.api.v1.endpoints import websocket

# Import new WebSocket components
from app.websockets.handlers.endpoint_handlers import TradovateEndpointHandler
from app.websockets.handlers.event_handlers import TradovateEventHandler
from app.websockets.handlers.webhook_handlers import TradovateWebhookHandler
from app.websockets.handlers.order_executor import TradovateOrderExecutor
from app.websockets.monitoring.monitor import MonitoringService
from app.websockets.scaling.resource_manager import ResourceManager
from app.websockets.errors import WebSocketError, handle_websocket_error
from app.websockets.websocket_config import WebSocketConfig

# Configure logging
log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(process)d - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Railway captures stdout/stderr
    ]
)
logger = logging.getLogger(__name__)

# Add environment info to logs
logger.info(f"Starting application in {settings.ENVIRONMENT} environment")

# Define CSP Middleware
class CSPMiddleware:
    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, request: Request, call_next: Callable):
        response = await call_next(request)
        
        # Make CSP more permissive
        csp_directives = [
            # Allow everything during development
            "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:",
            "connect-src * ws: wss:",
            "script-src * 'unsafe-inline' 'unsafe-eval'",
            "style-src * 'unsafe-inline'",
            "img-src * data: blob:",
            "frame-src *",
            "font-src * data:",
            "worker-src * blob:"
        ]
        
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)
        return response

# Track background tasks
background_tasks: Set[asyncio.Task] = set()

# Consolidated cleanup function that works for both lifespan and startup
async def cleanup_on_failed_startup():
    """Cleanup resources if startup fails"""
    try:
        logger.info("Performing cleanup after failed startup...")
        
        # Cancel any running background tasks
        for task in background_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Cleanup WebSocket manager if initialized
        global websocket_manager
        await websocket_manager.cleanup()
            
        # Close database connections
        if engine is not None:
            engine.dispose()
        
        logger.info("Cleanup after failed startup completed")
    except Exception as e:
        logger.error(f"Error during failed startup cleanup: {str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for handling startup and shutdown events"""
    try:
        # Initialize WebSocket manager
        app.state.websocket_manager = websocket_manager
        await websocket_manager.initialize()
        logger.info("WebSocket manager initialized successfully")

        # Initialize database
        try:
            logger.info("Initializing database...")
            init_db()
            health_status = await check_database_health(retries=3, retry_delay=2)  # Add retries
            
            # Be more forgiving in production
            if settings.ENVIRONMENT == "production":
                if health_status['status'] in ["critical", "error"]:
                    logger.error(f"Database health check returned {health_status['status']}: {health_status['message']}")
                    logger.warning("Continuing startup despite database health check failure in production")
                else:
                    logger.info(f"Database health check: {health_status['status']}")
            else:
                # In development, be more strict
                if health_status['status'] not in ["healthy", "degraded"]:
                    raise Exception(f"Database health check failed: {health_status['message']}")
                
            logger.info("Database initialization completed")
        except Exception as db_error:
            if settings.ENVIRONMENT == "production":
                # Log error but continue in production
                logger.error(f"Database initialization issue in production: {str(db_error)}")
                logger.warning("Continuing startup despite database initialization issue")
            else:
                # In development, fail fast
                logger.error(f"Database initialization failed: {str(db_error)}")
                raise

        # Start token refresh task
        try:
            logger.info("Starting token refresh task...")
            token_refresh_task = asyncio.create_task(start_token_refresh_task())
            background_tasks.add(token_refresh_task)
            logger.info("Token refresh task started successfully")
        except Exception as task_error:
            logger.error(f"Token refresh task initialization failed: {str(task_error)}")
            if settings.ENVIRONMENT != "production":
                raise

        logger.info("Application startup completed successfully")
        yield

    except Exception as e:
        logger.critical(f"Application startup failed: {str(e)}")
        await cleanup_on_failed_startup()
        raise

    finally:
        # Cleanup on shutdown
        try:
            logger.info("Initiating application shutdown...")
            
            # Stop token refresh task
            await stop_token_refresh_task()
            
            # Cancel all background tasks
            for task in background_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            
            # Cleanup WebSocket manager
            if hasattr(app.state, 'websocket_manager'):
                await websocket_manager.cleanup()
            
            # Close database connections - synchronous version
            from app.db.session import engine
            if engine is not None:
                engine.dispose()  # Removed await since engine is synchronous
            
            logger.info("Application shutdown completed successfully")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")
    
# Create FastAPI app instance
app_kwargs = {
    "title": "Trading API",
    "description": "API for trading strategy automation and signal processing",
    "version": "1.0.0",
    "contact": {
        "name": "API Support",
        "email": "support@example.com",
    },
    "lifespan": lifespan
}

# Only show docs in development and testing environments
if settings.ENVIRONMENT == "production":
    app_kwargs.update({
        "docs_url": None,  # Disable /docs in production
        "redoc_url": None,  # Disable /redoc in production
        "openapi_url": None  # Disable OpenAPI schema in production
    })

app = FastAPI(**app_kwargs)

# Add CSP middleware first
app.middleware("http")(CSPMiddleware(app))

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

class Config:
        env_file = ".env"
        case_sensitive = True
        env_file_encoding = 'utf-8'

        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str) -> Any:
            if field_name == "CORS_ORIGINS":
                if isinstance(raw_val, str):
                    # Remove quotes if present
                    cleaned_val = raw_val.strip('"').strip("'")
                    # Split by comma and clean each value
                    return [origin.strip() for origin in cleaned_val.split(",") if origin.strip()]
                return raw_val
            return raw_val

# Include routers
app.include_router(tradovate_callback_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")
app.include_router(websocket.router, prefix="/ws", tags=["websocket"])


app.state.websocket_manager = websocket_manager

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Request path: {request.url.path}")
    try:
        response = await call_next(request)
        if response.status_code == 404:
            logger.warning(f"404 Not Found: {request.url.path}")
        return response
    except Exception as e:
        logger.error(f"Request error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )

@app.on_event("startup")
async def startup_event():
    """Startup event handler"""
    logger.info("Starting Trading API Service")
    startup_status = {
        "database": False,
        "background_tasks": False,
        "websocket_manager": False  # Add WebSocket manager status
    }

    try:
        # Step 1: Initialize WebSocket manager
        try:
            logger.info("Initializing WebSocket manager...")
            app.state.websocket_manager = websocket_manager
            initialized = await websocket_manager.initialize()
            if not initialized:
                raise Exception("WebSocket manager initialization failed")
            startup_status["websocket_manager"] = True
            logger.info("WebSocket manager initialized successfully")
        except Exception as ws_error:
            logger.error(f"WebSocket manager initialization failed: {str(ws_error)}")
            raise

        # Step 2: Initialize database (existing functionality)
        try:
            logger.info("Initializing database...")
            init_db()
            health_status = await check_database_health()  # Make sure to await this
            if health_status['status'] != 'healthy':
                raise Exception("Database health check failed")
            startup_status["database"] = True
            logger.info("Database initialization successful")
        except Exception as db_error:
            logger.error(f"Database initialization failed: {str(db_error)}")
            raise

        # Step 3: Start background tasks (existing functionality)
        try:
            logger.info("Starting background tasks...")
            token_refresh_task = asyncio.create_task(start_token_refresh_task())
            background_tasks.add(token_refresh_task)
            startup_status["background_tasks"] = True
            logger.info("Background tasks started successfully")
        except Exception as task_error:
            logger.error(f"Background task initialization failed: {str(task_error)}")
            raise

        if all(startup_status.values()):
            logger.info("Trading API Service started successfully")
            logger.info("Startup Status: %s", startup_status)
        else:
            failed_components = [k for k, v in startup_status.items() if not v]
            raise Exception(f"Startup failed for components: {failed_components}")

    except Exception as e:
        logger.critical(f"Startup failed: {str(e)}")
        logger.critical("Service cannot start properly - shutting down")
        await cleanup_on_failed_startup()  # Simplified call with no arguments
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Initiating Trading API Service shutdown")
    
    try:
        # Step 1: Stop token refresh task
        logger.info("Stopping token refresh task...")
        await stop_token_refresh_task()

        # Step 2: Stop all background tasks
        logger.info(f"Stopping {len(background_tasks)} background tasks...")
        for task in background_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Step 3: Close database connections
        logger.info("Closing database connections...")
        from app.db.session import engine
        if engine is not None:
            engine.dispose()  # Engine should be synchronous

        logger.info("Trading API Service shutdown completed successfully")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")
        raise
    finally:
        logger.info("Shutdown process completed")

@app.get("/api/routes-check")
async def check_routes():
    """Health check endpoint for routes"""
    return {
        "status": "ok",
        "callback_route": "/api/tradovate/callback",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Trading API Service",
        "version": "1.0.0",
        "documentation": "/docs",
        "environment": settings.ENVIRONMENT,
        "server_time": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """Check API and database health"""
    websocket_manager = app.state.websocket_manager
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "components": {
            "database": await check_database_health(),  # Make sure to await this
            "websocket": websocket_manager.get_status(),
            "background_tasks": {
                "total": len(background_tasks),
                "active": len([t for t in background_tasks if not t.done()]),
            }
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True if settings.ENVIRONMENT == "development" else False,
        workers=1
    )