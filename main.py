# main.py
from fastapi import FastAPI, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, Callable, Set, Dict
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
from app.db.base import init_db, get_db
from app.core.db_health import check_database_health
from app.core.tasks.token_refresh import start_token_refresh_task, stop_token_refresh_task

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

# New WebSocket Manager Class
class WebSocketManager:
    """Manager class to coordinate all WebSocket components."""
    
    def __init__(self):
        self.resource_manager = ResourceManager()
        self.monitoring_service = MonitoringService()
        self.order_executor = TradovateOrderExecutor()
        self.event_handler = TradovateEventHandler()
        self.endpoint_handler = TradovateEndpointHandler(
            config={
                "path": "/ws/tradovate",
                "auth_required": True
            }
        )
        self.webhook_handler = TradovateWebhookHandler(
            secret_key=settings.WEBHOOK_SECRET_KEY
        )
        self.active_connections: Dict[str, WebSocket] = {}

    async def initialize(self) -> bool:
        """Initialize the WebSocket manager."""
        try:
            await self.monitoring_service.start()
            await self.resource_manager.load_balancer.register_node(
                "default_node",
                capacity=1000,
                metadata={"type": "default"}
            )
            self.event_handler.register_handler(
                "market_data",
                self.endpoint_handler.handle_market_data
            )
            logger.info("WebSocket manager initialized successfully")
            return True
        except Exception as e:
            logger.error(f"WebSocket manager initialization failed: {str(e)}")
            return False

    def get_status(self):
        """Get current status of WebSocket connections."""
        return {
            "active_connections": len(self.active_connections),
            "monitoring_active": self.monitoring_service.is_running(),
        }

    async def connect(self, websocket: WebSocket, client_id: str):
        """Handle new WebSocket connection."""
        try:
            node_id = await self.resource_manager.register_connection(
                websocket.client.host,
                client_id
            )
            
            if not node_id:
                await websocket.close(code=1008)
                return
                
            await websocket.accept()
            connection_id = f"{client_id}_{websocket.client.host}"
            self.active_connections[connection_id] = websocket
            logger.info(f"New WebSocket connection: {connection_id}")
            return connection_id
            
        except Exception as e:
            logger.error(f"Error handling connection: {str(e)}")
            if websocket.client.state.connected:
                await websocket.close(code=1011)
            raise

    async def disconnect(self, connection_id: str):
        """Handle WebSocket disconnection."""
        try:
            if connection_id in self.active_connections:
                del self.active_connections[connection_id]
            await self.resource_manager.load_balancer.release_connection(connection_id)
            logger.info(f"WebSocket disconnected: {connection_id}")
        except Exception as e:
            logger.error(f"Error handling disconnection: {str(e)}")
            raise

    async def shutdown(self):
        """Shutdown the WebSocket manager."""
        try:
            await self.monitoring_service.stop()
            for connection_id, websocket in self.active_connections.items():
                await websocket.close()
            self.active_connections.clear()
            logger.info("WebSocket manager shut down successfully")
        except Exception as e:
            logger.error(f"Error during WebSocket manager shutdown: {str(e)}")
            raise

# FastAPI lifespan event
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize WebSocket manager
    websocket_manager = WebSocketManager()
    app.state.websocket_manager = websocket_manager
    
    # Initialize the default node
    await websocket_manager.resource_manager.load_balancer.register_node(
        "default_node",
        capacity=1000,
        metadata={"type": "default"}
    )
    
    await websocket_manager.initialize()
    yield
    await websocket_manager.cleanup()
    
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
app.include_router(tradovate_callback_router, prefix="/api")
app.include_router(api_router, prefix="/api/v1")

# Dependency to get WebSocket manager
async def get_websocket_manager():
    return app.state.websocket_manager

@app.websocket("/ws/tradovate/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
    manager: WebSocketManager = Depends(get_websocket_manager)
):
    connection_id = None
    try:
        connection_id = await manager.connect(websocket, client_id)
        while True:
            message = await websocket.receive_json()
            try:
                response = await manager.endpoint_handler.handle_message(
                    message,
                    connection_id
                )
                await websocket.send_json(response)
            except WebSocketError as e:
                error_response = handle_websocket_error(e)
                await websocket.send_json(error_response)
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                await websocket.send_json({
                    "error": "Internal server error",
                    "code": 500
                })
    except WebSocketDisconnect:
        if connection_id:
            await manager.disconnect(connection_id)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        if connection_id:
            await manager.disconnect(connection_id)
        if websocket.client.state.connected:
            await websocket.close(code=1011)

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
        "background_tasks": False
    }

    try:
        # Step 1: Initialize database
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

        # Step 2: Start background tasks
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
        await cleanup_on_failed_startup(startup_status)
        raise

async def cleanup_on_failed_startup(startup_status: dict):
    """Cleanup any initialized components after failed startup"""
    try:
        logger.info("Performing cleanup after failed startup...")
        
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
    websocket_manager = app.state.websocket_manager
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