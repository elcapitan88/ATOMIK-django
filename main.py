# main.py
from fastapi import FastAPI, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional
from app.db.base import get_db 

# Standard library imports
import logging
import asyncio
from datetime import datetime
from typing import Optional, Callable, Set

# FastAPI imports
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# SQLAlchemy imports
from sqlalchemy.exc import SQLAlchemyError

# Local imports
from app.api.v1.api import api_router, tradovate_callback_router
from app.core.config import settings
from app.db.base import init_db
from app.core.db_health import check_database_health
from app.core.tasks.token_refresh import start_token_refresh_task, stop_token_refresh_task
from app.websockets.manager import websocket_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
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

# Create FastAPI app instance
app = FastAPI(
    title="Trading API",
    description="API for trading strategy automation and signal processing",
    version="1.0.0",
    contact={
        "name": "API Support",
        "email": "support@example.com",
    },
)

# Track background tasks
background_tasks: Set[asyncio.Task] = set()

# Add CSP middleware first
app.middleware("http")(CSPMiddleware(app))

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://trader.tradovate.com",
        "https://demo.tradovateapi.com",
        "https://live.tradovateapi.com",
        "https://*.google.com",
        "https://*.doubleclick.net"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(tradovate_callback_router, prefix="/api")  # This will handle /api/tradovate/callback
app.include_router(api_router, prefix="/api/v1") 


async def initialize_database() -> bool:
    """Initialize database and run migrations"""
    try:
        logger.info("Initializing database...")
        init_db()
        
        # Check database health
        health_status = check_database_health()
        if health_status['status'] != 'healthy':
            logger.error(f"Database health check failed: {health_status}")
            return False
            
        logger.info("Database initialization successful")
        return True
        
    except SQLAlchemyError as e:
        logger.error(f"Database initialization failed: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during database initialization: {str(e)}")
        return False

async def initialize_websocket_manager() -> bool:
    """Initialize WebSocket manager"""
    try:
        logger.info("Initializing WebSocket manager...")
        await websocket_manager.initialize()
        logger.info("WebSocket manager initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"WebSocket manager initialization failed: {str(e)}")
        return False

async def start_background_task(task_func, task_name: str) -> Optional[asyncio.Task]:
    """Start a background task with error handling"""
    try:
        task = asyncio.create_task(task_func())
        task.set_name(task_name)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        logger.info(f"Started background task: {task_name}")
        return task
        
    except Exception as e:
        logger.error(f"Failed to start background task {task_name}: {str(e)}")
        return None

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
    """
    Startup event handler that:
    1. Initializes database and creates tables
    2. Starts WebSocket manager
    3. Starts background tasks (token refresh, etc.)
    4. Performs health checks
    """
    logger.info("Starting Trading API Service")
    startup_status = {
        "database": False,
        "websocket": False,
        "background_tasks": False
    }

    try:
        # Step 1: Initialize database
        try:
            logger.info("Initializing database...")
            init_db()
            
            # Check database health
            health_status = check_database_health()
            if health_status['status'] != 'healthy':
                logger.error(f"Database health check failed: {health_status}")
                raise Exception("Database health check failed")
                
            startup_status["database"] = True
            logger.info("Database initialization successful")
            
        except Exception as db_error:
            logger.error(f"Database initialization failed: {str(db_error)}")
            raise

        # Step 2: Initialize WebSocket manager
        try:
            logger.info("Initializing WebSocket manager...")
            success = await websocket_manager.initialize()
            
            if not success:
                raise Exception("WebSocket manager initialization failed")
                
            startup_status["websocket"] = True
            logger.info("WebSocket manager initialized successfully")
            
        except Exception as ws_error:
            logger.error(f"WebSocket manager initialization failed: {str(ws_error)}")
            raise

        # Step 3: Start background tasks
        try:
            logger.info("Starting background tasks...")
            background_tasks_status = []
            
            # Start token refresh task
            token_refresh_task = asyncio.create_task(start_token_refresh_task())
            background_tasks.add(token_refresh_task)
            background_tasks_status.append(("token_refresh", True))
            
            # Add additional background tasks here
            
            startup_status["background_tasks"] = all(status for _, status in background_tasks_status)
            
            if not startup_status["background_tasks"]:
                failed_tasks = [task for task, status in background_tasks_status if not status]
                raise Exception(f"Failed to start background tasks: {failed_tasks}")
                
            logger.info("Background tasks started successfully")
            
        except Exception as task_error:
            logger.error(f"Background task initialization failed: {str(task_error)}")
            raise

        # Step 4: Final health check
        if all(startup_status.values()):
            logger.info("Trading API Service started successfully")
            logger.info("Startup Status: %s", startup_status)
        else:
            failed_components = [k for k, v in startup_status.items() if not v]
            raise Exception(f"Startup failed for components: {failed_components}")

    except Exception as e:
        logger.critical(f"Startup failed: {str(e)}")
        logger.critical("Service cannot start properly - shutting down")
        
        # Attempt cleanup of any initialized components
        await cleanup_on_failed_startup(startup_status)
        
        raise

async def cleanup_on_failed_startup(startup_status: dict):
    """Cleanup any initialized components after failed startup"""
    try:
        logger.info("Performing cleanup after failed startup...")
        
        # Cleanup WebSocket manager if it was initialized
        if startup_status["websocket"]:
            try:
                await websocket_manager.cleanup()
            except Exception as ws_error:
                logger.error(f"WebSocket manager cleanup failed: {str(ws_error)}")

        # Cancel any started background tasks
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

# Initialize set to track background tasks
background_tasks: Set[asyncio.Task] = set()

@app.on_event("shutdown")
async def shutdown_event():
    """
    Shutdown event handler that:
    1. Stops background tasks
    2. Closes WebSocket connections
    3. Closes database connections
    """
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

        # Step 3: Close WebSocket connections
        logger.info("Closing WebSocket connections...")
        await websocket_manager.shutdown()

        # Step 4: Close database connections
        logger.info("Closing database connections...")
        from app.db.session import engine
        await engine.dispose()

        logger.info("Trading API Service shutdown completed successfully")

    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")
        raise
    finally:
        logger.info("Shutdown process completed")

@app.on_event("shutdown")
async def shutdown_event():
    """
    Shutdown event handler that:
    1. Stops background tasks
    2. Closes WebSocket connections
    3. Closes database connections
    """
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

        # Step 3: Close WebSocket connections
        logger.info("Closing WebSocket connections...")
        await websocket_manager.shutdown()

        # Step 4: Close database connections
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
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "components": {
            "database": check_database_health(),
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