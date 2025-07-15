#main.py
from sqlalchemy.orm import Session
from app.core.security import get_user_from_token
from app.models.subscription import Subscription
from app.models.user import User
from fastapi import Request, HTTPException, FastAPI, Depends
from datetime import datetime

# Standard library imports
import logging
import asyncio
from datetime import datetime
from typing import Any, Optional, Callable, Set, Dict
from contextlib import asynccontextmanager

# FastAPI imports
from fastapi.middleware.cors import CORSMiddleware

# SQLAlchemy imports
from sqlalchemy.exc import SQLAlchemyError

# Local imports
from app.api.v1.api import api_router, tradovate_callback_router
from app.webhooks import rewardful
from app.core.config import settings
from app.db.base import init_db, get_db
from app.db.session import engine, get_db, SessionLocal
from app.core.db_health import check_database_health
from app.core.redis_manager import redis_manager
from app.core.memory_monitor import memory_monitor
from app.services.trading_service import order_monitoring_service
from fastapi.responses import RedirectResponse, JSONResponse
from app.core.tasks import cleanup_expired_registrations


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

        # Initialize database
        try:
            logger.info("Initializing database...")
            init_db()
            health_status = await check_database_health(retries=3, retry_delay=2)  # Add retries
            
            # Be more forgiving in production
            if settings.ENVIRONMENT in ["production", "development"]:
                if health_status['status'] in ["critical", "error"]:
                    logger.error(f"Database health check returned {health_status['status']}: {health_status['message']}")
                    logger.warning("Continuing startup despite database health check failure")
                else:
                    logger.info(f"Database health check: {health_status['status']}")
            else:
                # In other environments (like testing), be strict
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

        # Initialize Redis connection manager
        try:
            logger.info("Initializing Redis connection manager...")
            if redis_manager.initialize():
                logger.info("Redis connection manager initialized successfully")
            else:
                logger.warning("Redis connection manager failed to initialize - Redis features will be disabled")
        except Exception as redis_error:
            logger.warning(f"Redis initialization failed: {str(redis_error)} - Redis features will be disabled")

        # Initialize order monitoring service
        try:
            logger.info("Initializing order monitoring service...")
            await order_monitoring_service.initialize()
            logger.info("Order monitoring service initialized successfully")
        except Exception as monitor_error:
            logger.error(f"Order monitoring service initialization failed: {str(monitor_error)}")
            if settings.ENVIRONMENT != "production":
                raise

        # Initialize memory monitoring
        try:
            logger.info("Starting memory monitoring...")
            await memory_monitor.start_monitoring()
            logger.info("Memory monitoring started successfully")
        except Exception as memory_error:
            logger.warning(f"Memory monitoring initialization failed: {str(memory_error)}")


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
            
            # Stop memory monitoring
            try:
                await memory_monitor.stop_monitoring()
                logger.info("Memory monitoring stopped")
            except Exception as e:
                logger.error(f"Error stopping memory monitoring: {e}")
            
            # Stop order monitoring service
            try:
                await order_monitoring_service.shutdown()
                logger.info("Order monitoring service stopped")
            except Exception as e:
                logger.error(f"Error stopping order monitoring service: {e}")
            
            # Close Redis connections
            try:
                redis_manager.close()
                logger.info("Redis connections closed")
            except Exception as e:
                logger.error(f"Error closing Redis connections: {e}")
            
            # Cancel all background tasks
            for task in background_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            
            # Close database connections
            from app.db.session import engine
            if engine is not None:
                engine.dispose()
                logger.info("Database connections closed")
            
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

# Add orjson for faster JSON serialization
try:
    import orjson
    from fastapi.responses import ORJSONResponse
    app_kwargs["default_response_class"] = ORJSONResponse
    logger.info("Using orjson for faster JSON serialization")
except ImportError:
    logger.warning("orjson not available, using standard JSON")

app = FastAPI(**app_kwargs)

# Add CSP middleware first
app.middleware("http")(CSPMiddleware(app))

# Maintenance Mode Middleware
class MaintenanceModeMiddleware:
    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, request: Request, call_next: Callable):
        # Skip maintenance check for static files and admin paths
        if (request.url.path.startswith("/static/") or 
            request.url.path.startswith("/docs") or 
            request.url.path.startswith("/redoc") or
            request.url.path.startswith("/openapi.json") or
            request.url.path == "/"):
            return await call_next(request)

        # Check maintenance status
        from app.models.maintenance import MaintenanceSettings
        from app.db.session import SessionLocal
        
        db = SessionLocal()
        try:
            maintenance = db.query(MaintenanceSettings).first()
            
            if maintenance and maintenance.is_enabled:
                # Check if user is admin
                auth_header = request.headers.get("Authorization")
                is_admin = False
                
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header.replace("Bearer ", "")
                    try:
                        user_email = get_user_from_token(token)
                        if user_email:
                            user = db.query(User).filter(User.email == user_email).first()
                            if user and user.is_admin():
                                is_admin = True
                    except Exception:
                        pass
                
                # Block non-admin users during maintenance
                if not is_admin:
                    message = maintenance.message or settings.MAINTENANCE_MODE_MESSAGE
                    return JSONResponse(
                        status_code=503,
                        content={
                            "detail": "Service temporarily unavailable due to maintenance",
                            "message": message,
                            "maintenance": True
                        }
                    )
        finally:
            db.close()

        return await call_next(request)

# Add maintenance middleware
app.middleware("http")(MaintenanceModeMiddleware(app))

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
app.include_router(rewardful.router)



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
    }

    try:

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

        try:
            from app.core.tasks import cleanup_expired_registrations
            cleanup_task = asyncio.create_task(cleanup_expired_registrations())
            background_tasks.add(cleanup_task)
            logger.info("Started background task for cleaning expired registrations")
        except Exception as e:
            logger.error(f"Failed to start cleanup task: {str(e)}")

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

@app.middleware("http")
async def ensure_subscription_middleware(request: Request, call_next):
    """Middleware to ensure all authenticated users have a subscription record"""
    # Only process if this is an API route (not for static files, etc.)
    if request.url.path.startswith("/api/"):
        # Check for authenticated request
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            
            # Get user from token without throwing error (returns None if invalid)
            try:
                # Use an independent database session for the middleware
                from app.db.session import SessionLocal
                db = SessionLocal()
                
                try:
                    # Extract user from token
                    user_email = get_user_from_token(token)
                    if user_email:
                        # Find user
                        user = db.query(User).filter(User.email == user_email).first()
                        
                        if user:
                            # Check if user has a subscription
                            subscription = db.query(Subscription).filter(
                                Subscription.user_id == user.id
                            ).first()
                            
                            if not subscription:
                                # Create a starter subscription
                                logger.warning(f"User {user.email} had no subscription. Creating starter subscription.")
                                subscription = Subscription(
                                    user_id=user.id,
                                    tier="starter",
                                    status="active",
                                    is_lifetime=False,
                                    created_at=datetime.utcnow(),
                                    updated_at=datetime.utcnow()
                                )
                                db.add(subscription)
                                db.commit()
                                logger.info(f"Created starter subscription for user {user.email}")
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error in subscription middleware: {str(e)}")
                # Continue with the request even if middleware fails
                pass
    
    # Continue processing the request
    response = await call_next(request)
    return response

@app.on_event("startup")
async def start_server_monitor():
    """Start background task to monitor IBEam servers"""
    asyncio.create_task(monitor_ibearmy_servers())

async def monitor_ibearmy_servers():
    """Background task to monitor IBEam servers and auto-shutdown inactive ones"""
    while True:
        try:
            # Sleep first to ensure app is fully started
            await asyncio.sleep(300)  # 5 minutes
            
            # Get a database session
            async with get_db_context() as db:
                # Get all active IB accounts
                accounts = db.query(BrokerAccount).filter(
                    BrokerAccount.broker_id == "interactivebrokers",
                    BrokerAccount.is_active == True
                ).all()
                
                now = datetime.utcnow()
                
                for account in accounts:
                    if not account.credentials or not account.credentials.custom_data:
                        continue
                        
                    try:
                        service_data = json.loads(account.credentials.custom_data)
                        service_id = service_data.get("railway_service_id")
                        
                        if not service_id:
                            continue
                            
                        # Get last activity time - first from account itself
                        last_activity = account.last_connected
                        
                        # Calculate inactivity period in hours
                        hours_inactive = 0
                        if last_activity:
                            hours_inactive = (now - last_activity).total_seconds() / 3600
                            
                        # If inactive for more than 12 hours, stop the server
                        if hours_inactive > 12:
                            logger.info(f"Auto-stopping inactive IBEam server for account {account.account_id}")
                            await railway_server_manager.stop_server(service_id)
                            
                            # Update service status in custom_data
                            service_data["status"] = "stopped"
                            account.credentials.custom_data = json.dumps(service_data)
                            db.commit()
                    except Exception as e:
                        logger.error(f"Error checking server {account.account_id}: {str(e)}")
                        
        except Exception as e:
            logger.error(f"Error in server monitor: {str(e)}")
            
async def start_background_tasks():
    """Start background tasks"""
    from app.core.tasks import sync_resource_counts_task
    
    # Schedule resource count sync to run every hour
    async def run_periodic_sync():
        while True:
            try:
                await sync_resource_counts_task()
            except Exception as e:
                logger.error(f"Error in periodic sync task: {str(e)}")
            await asyncio.sleep(3600)  # 1 hour
    
    # Add task to the set of background tasks
    task = asyncio.create_task(run_periodic_sync())
    background_tasks.add(task)

@app.on_event("startup")
async def refresh_db_metadata():
    import logging
    from sqlalchemy import inspect, MetaData
    from app.db.session import engine
    
    logger = logging.getLogger(__name__)
    logger.info("Explicitly refreshing SQLAlchemy metadata...")
    
    try:
        # Create a fresh metadata object and reflect the database
        metadata = MetaData()
        metadata.reflect(bind=engine)
        
        # Log some info to confirm it worked
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.info(f"Metadata refreshed successfully. Found {len(tables)} tables.")
        
        # Specifically check broker_accounts and subscriptions tables
        broker_cols = [col['name'] for col in inspector.get_columns('broker_credentials')]
        logger.info(f"broker_credentials columns: {', '.join(broker_cols)}")
        
        # Check affiliates table for payout columns
        if 'affiliates' in tables:
            affiliate_cols = [col['name'] for col in inspector.get_columns('affiliates')]
            logger.info(f"🔍 AFFILIATES COLUMNS: {', '.join(affiliate_cols)}")
            
            has_payout_method = 'payout_method' in affiliate_cols
            has_payout_details = 'payout_details' in affiliate_cols
            logger.info(f"🎯 PAYOUT COLUMNS PRESENT - payout_method: {has_payout_method}, payout_details: {has_payout_details}")
        else:
            logger.error("🚨 AFFILIATES TABLE NOT FOUND!")
        
        # Additional debug info
        has_custom_data = 'custom_data' in broker_cols
        logger.info(f"custom_data column present in broker_credentials: {has_custom_data}")
        
    except Exception as e:
        logger.error(f"Error refreshing metadata: {str(e)}")

def mark_legacy_free_users():
    db = SessionLocal()
    try:
        # Get all subscriptions with tier "starter" and mark as legacy free
        legacy_free_users = db.query(Subscription).filter(
            Subscription.tier == "starter",
            Subscription.status == "active"
        ).all()
        
        count = 0
        for subscription in legacy_free_users:
            subscription.is_legacy_free = True
            count += 1
        
        db.commit()
        print(f"Marked {count} users as legacy free")
    except Exception as e:
        db.rollback()
        print(f"Error marking legacy free users: {str(e)}")
    finally:
        db.close()

# Execute the function
#mark_legacy_free_users()

def migrate_starter_to_elite():
    """
    Migrate users from the starter legacy plan to the Elite plan.
    This function finds all active subscriptions with tier "starter"
    and upgrades them to "elite" tier.
    """
    db = SessionLocal()
    try:
        # Get all subscriptions with tier "starter" that are active
        starter_users = db.query(Subscription).filter(
            Subscription.tier == "starter",
            Subscription.status == "active"
        ).all()
        
        count = 0
        for subscription in starter_users:
            # Upgrade tier to elite
            subscription.tier = "elite"
            subscription.updated_at = datetime.utcnow()
            count += 1
        
        db.commit()
        print(f"Migration complete: {count} users upgraded from starter to elite")
    except Exception as e:
        db.rollback()
        print(f"Error migrating users to elite: {str(e)}")
    finally:
        db.close()

# Execute the migration function
# Uncomment the line below to run the migration
# migrate_starter_to_elite()


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler"""
    logger.info("Initiating Trading API Service shutdown")
    
    try:
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

@app.on_event("startup")
async def start_order_monitoring():
    """Start the order status monitoring service"""
    from app.services.trading_service import order_monitoring_service
    await order_monitoring_service.initialize()
    logger.info("Order status monitoring service initialized")

@app.on_event("shutdown")
async def stop_order_monitoring():
    """Stop the order status monitoring service"""
    from app.services.trading_service import order_monitoring_service
    await order_monitoring_service.shutdown()
    logger.info("Order status monitoring service stopped")

@app.on_event("startup")
async def refresh_db_metadata():
    import logging
    from sqlalchemy import inspect, MetaData
    from app.db.session import engine
    
    logger = logging.getLogger(__name__)
    logger.info("Explicitly refreshing SQLAlchemy metadata...")
    
    try:
        # Create a fresh metadata object and reflect the database
        metadata = MetaData()
        metadata.reflect(bind=engine)
        
        # Log some info to confirm it worked
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.info(f"Metadata refreshed successfully. Found {len(tables)} tables.")
        
        # Specifically check broker_accounts and subscriptions tables
        broker_cols = [col['name'] for col in inspector.get_columns('broker_accounts')]
        sub_cols = [col['name'] for col in inspector.get_columns('subscriptions')]
        
        logger.info(f"broker_accounts columns: {', '.join(broker_cols)}")
        logger.info(f"subscriptions columns: {', '.join(sub_cols)}")
        
        # Additional debug info
        has_nickname = 'nickname' in broker_cols
        logger.info(f"nickname column present in broker_accounts: {has_nickname}")
        
    except Exception as e:
        logger.error(f"Error refreshing metadata: {str(e)}")

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
            "database": await check_database_health(),  # Make sure to await this
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
=======
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
from app.models.maintenance import MaintenanceSettings
from app.core.security import get_current_user_optional
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

# Define Maintenance Mode Middleware
class MaintenanceModeMiddleware:
    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, request: Request, call_next: Callable):
        # Skip maintenance check for certain paths
        excluded_paths = [
            "/api/v1/admin/maintenance",         # Allow admin to toggle maintenance
            "/api/v1/admin/maintenance/status",  # Allow public maintenance status check
            "/api/v1/auth/login",                # Allow login
            "/health",                           # Health checks
            "/docs",                             # API docs
            "/openapi.json"                      # OpenAPI spec
        ]
        
        # Skip maintenance check for excluded paths
        if request.url.path in excluded_paths or request.url.path.startswith("/docs"):
            return await call_next(request)
        
        try:
            # Get database session
            db_gen = get_db()
            db = next(db_gen)
            
            try:
                # Check maintenance status
                maintenance = db.query(MaintenanceSettings).order_by(MaintenanceSettings.updated_at.desc()).first()
                
                if maintenance and maintenance.is_enabled:
                    # Try to get current user from Authorization header
                    auth_header = request.headers.get("Authorization")
                    user = None
                    
                    if auth_header and auth_header.startswith("Bearer "):
                        token = auth_header.split(" ")[1]
                        try:
                            from jose import jwt
                            payload = jwt.decode(
                                token,
                                settings.SECRET_KEY,
                                algorithms=[settings.ALGORITHM]
                            )
                            email = payload.get("sub")
                            if email:
                                from app.models.user import User
                                user = db.query(User).filter(User.email == email).first()
                        except Exception:
                            pass
                    
                    # Check if user is admin
                    is_admin = user and (
                        user.username == 'admin' or 
                        (hasattr(user, 'app_role') and user.app_role in ['admin', 'superadmin']) or
                        (hasattr(user, 'role') and user.role in ['admin', 'superadmin'])
                    )
                    
                    if not is_admin:
                        # Return maintenance mode response
                        message = maintenance.message or settings.MAINTENANCE_MODE_MESSAGE
                        return JSONResponse(
                            status_code=503,
                            content={
                                "detail": "Service temporarily unavailable",
                                "message": message,
                                "maintenance_mode": True
                            }
                        )
                
            finally:
                db.close()
                
        except Exception as e:
            # If there's an error checking maintenance status, continue normally
            logger.warning(f"Error checking maintenance status: {e}")
        
        return await call_next(request)


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

# Add Maintenance Mode middleware
app.middleware("http")(MaintenanceModeMiddleware(app))

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
>>>>>>> Development
    )