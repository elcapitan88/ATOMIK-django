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
from app.websocket.manager import app_websocket_manager
from app.db.base import init_db, get_db
from app.db.session import engine, get_db
from app.core.db_health import check_database_health
# Token refresh now handled by separate token-refresh-service
# Old trading websocket import removed

# Trading WebSocket functionality moved to separate Websocket-Proxy service

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for handling startup and shutdown events"""
    try:
        # Initialize Application WebSocket manager (chat/UI events)  
        app.state.app_websocket_manager = app_websocket_manager
        await app_websocket_manager.initialize()
        logger.info("Application WebSocket manager initialized successfully")

        # Initialize database
        try:
            logger.info("Initializing database...")
            init_db()
            health_status = check_database_health()
            if health_status['status'] != 'healthy':
                raise Exception("Database health check failed")
            logger.info("Database initialization successful")
        except Exception as db_error:
            logger.error(f"Database initialization failed: {str(db_error)}")
            raise

        # Token refresh now handled by separate token-refresh-service

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
            
            # Token refresh stopped by separate token-refresh-service
            
            # Cancel all background tasks
            for task in background_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            
            # Cleanup Application WebSocket manager
            if hasattr(app.state, 'app_websocket_manager'):
                await app_websocket_manager.cleanup()
            
            # Close database connections - synchronous version
            from app.db.session import engine
            if engine is not None:
                engine.dispose()  # Removed await since engine is synchronous
            
            logger.info("Application shutdown completed successfully")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")

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
        
        # Cleanup Application WebSocket manager
        if hasattr(app.state, 'app_websocket_manager'):
            await app_websocket_manager.cleanup()
            
        # Close database connections
        await engine.dispose()
        
        logger.info("Cleanup after failed startup completed")
    except Exception as e:
        logger.error(f"Error during failed startup cleanup: {str(e)}")
    
# Create FastAPI app instance
app = FastAPI(
    title="Trading API",
    description="API for trading strategy automation and signal processing",
    version="1.0.0",
    contact={
        "name": "API Support",
        "email": "support@example.com",
    },
    lifespan=lifespan
)

# Track background tasks
background_tasks: Set[asyncio.Task] = set()

# Add CSP middleware first
app.middleware("http")(CSPMiddleware(app))

# Configure CORS - Debug: Allow all origins temporarily
cors_origins = ["*"] if settings.ENVIRONMENT == "development" else settings.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
# Old trading websocket router removed - now handled by separate Websocket-Proxy service


# Application WebSocket manager assigned in lifespan



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
            logger.info("Initializing Application WebSocket manager...")
            app.state.app_websocket_manager = app_websocket_manager
            initialized = await app_websocket_manager.initialize()
            if not initialized:
                raise Exception("Application WebSocket manager initialization failed")
            startup_status["websocket_manager"] = True
            logger.info("Application WebSocket manager initialized successfully")
        except Exception as ws_error:
            logger.error(f"WebSocket manager initialization failed: {str(ws_error)}")
            raise

        # Step 2: Initialize database (existing functionality)
        try:
            logger.info("Initializing database...")
            init_db()
            health_status = check_database_health()
            if health_status['status'] != 'healthy':
                raise Exception("Database health check failed")
            startup_status["database"] = True
            logger.info("Database initialization successful")
        except Exception as db_error:
            logger.error(f"Database initialization failed: {str(db_error)}")
            raise

        # Step 3: Background tasks now handled by separate services
        startup_status["background_tasks"] = True
        logger.info("Background tasks handled by separate services")

        if all(startup_status.values()):
            logger.info("Trading API Service started successfully")
            logger.info("Startup Status: %s", startup_status)
        else:
            failed_components = [k for k, v in startup_status.items() if not v]
            raise Exception(f"Startup failed for components: {failed_components}")

    except Exception as e:
        logger.critical(f"Startup failed: {str(e)}")
        logger.critical("Service cannot start properly - shutting down")
        await cleanup_on_failed_startup(startup_status)
        raise

async def cleanup_on_failed_startup(startup_status: dict):
    """Cleanup any initialized components after failed startup"""
    try:
        logger.info("Performing cleanup after failed startup...")
        
        if startup_status["websocket_manager"]:
            await app_websocket_manager.cleanup()
            
        if startup_status["background_tasks"]:
            for task in background_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                        
        logger.info("Cleanup completed")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Initiating Trading API Service shutdown")
    
    try:
        # Step 1: Token refresh handled by separate service

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
        await engine.dispose()

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
    app_websocket_manager = getattr(app.state, 'app_websocket_manager', None)
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "components": {
            "database": check_database_health(),
            "app_websocket": app_websocket_manager.get_status() if app_websocket_manager else {"status": "not_initialized"},
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