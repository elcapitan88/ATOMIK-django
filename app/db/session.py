# app/db/session.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import QueuePool
from app.core.config import settings
import logging
import contextlib
import os

logger = logging.getLogger(__name__)

# Configure the logger level based on the environment
if settings.ENVIRONMENT == "production":
    logger.setLevel(logging.WARNING)
else:
    logger.setLevel(logging.DEBUG)

# Get database parameters from settings
db_params = settings.get_db_params()

# Check if we're on Railway for optimal setup
is_on_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None

# Configure ASYNC database engine (for Railway optimization)
try:
    # Check if asyncpg is available
    import asyncpg
    
    # Convert sync URL to async URL if needed
    database_url = settings.active_database_url
    if not database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    
    # Create async engine for Railway optimization
    async_engine = create_async_engine(
        database_url,
        **db_params
    )
    logger.info(f"Async database engine created successfully in {settings.ENVIRONMENT} mode (Railway: {is_on_railway})")
except ImportError:
    logger.warning("asyncpg not installed - async database features disabled. Install with: pip install asyncpg")
    async_engine = None
except Exception as e:
    logger.critical(f"Failed to create async database engine: {str(e)}")
    async_engine = None
    # Don't raise here, let the sync engine handle everything
    logger.warning("Falling back to sync database engine only")

# Configure SYNC database engine (for backward compatibility)
try:
    # Use sync URL for existing code
    sync_database_url = settings.active_database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    engine = create_engine(
        sync_database_url,
        poolclass=QueuePool,
        **db_params
    )
    logger.info(f"Sync database engine created successfully in {settings.ENVIRONMENT} mode")
except Exception as e:
    logger.critical(f"Failed to create sync database engine: {str(e)}")
    engine = None  # Set to None if creation fails
    raise  # Re-raise the exception after logging

# Create ASYNC session factory (for Railway optimization)
if async_engine is not None:
    AsyncSessionLocal = sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False
    )
else:
    logger.critical("AsyncSessionLocal not created due to async engine initialization failure")
    AsyncSessionLocal = None

# Create SYNC session factory (for backward compatibility)
if engine is not None:
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )
else:
    logger.critical("SessionLocal not created due to engine initialization failure")
    SessionLocal = None

# ASYNC dependency for FastAPI endpoints (Railway optimized)
async def get_async_db():
    """
    Get ASYNC database session with Railway optimization
    """
    if AsyncSessionLocal is None:
        logger.critical("Cannot create async database session - AsyncSessionLocal is None")
        raise Exception("Async database session factory not initialized")
        
    async with AsyncSessionLocal() as db:
        try:
            # Log session creation in development mode
            if settings.ENVIRONMENT == "development":
                logger.debug(f"Async database session created (Railway: {is_on_railway})")
            yield db
        except Exception as e:
            await db.rollback()
            logger.error(f"Async database session error: {str(e)}")
            raise

# SYNC dependency for FastAPI endpoints (backward compatibility)
async def get_db():
    """
    Get database session with enhanced error handling and logging
    """
    if SessionLocal is None:
        logger.critical("Cannot create database session - SessionLocal is None")
        raise Exception("Database session factory not initialized")
        
    db = SessionLocal()
    try:
        # Log session creation in development mode
        if settings.ENVIRONMENT == "development":
            logger.debug("Database session created")
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database session error: {str(e)}")
        raise
    finally:
        db.close()
        if settings.ENVIRONMENT == "development":
            logger.debug("Database session closed")

# Context manager for manual session usage
@contextlib.contextmanager
def get_db_context():
    """
    Context manager for database sessions
    """
    if SessionLocal is None:
        logger.critical("Cannot create database session - SessionLocal is None")
        raise Exception("Database session factory not initialized")
        
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database session error in context manager: {str(e)}")
        raise
    finally:
        db.close()

# Function to test database connection with detailed feedback
async def test_db_connection():
    """Test database connection and log the results"""
    try:
        if engine is None:
            logger.critical("Cannot test connection - engine is None")
            return {
                "status": "error",
                "message": "Database engine not initialized",
                "connection": False
            }

        with get_db_context() as db:
            db.execute(text("SELECT 1"))
            logger.info(f"Database connection test successful in {settings.ENVIRONMENT} mode")
            return {
                "status": "success",
                "message": f"Connected to database in {settings.ENVIRONMENT} mode",
                "connection": True
            }
            
    except Exception as e:
        error_message = str(e)
        logger.critical(f"Database connection test failed: {error_message}")
        return {
            "status": "error",
            "message": f"Database connection failed: {error_message}",
            "connection": False
        }

# Export everything needed by other modules
__all__ = [
    "engine",           # Sync engine (existing)
    "async_engine",     # Async engine (new)
    "SessionLocal",     # Sync session factory (existing)
    "AsyncSessionLocal", # Async session factory (new)
    "get_db",           # Sync database dependency (existing)
    "get_async_db",     # Async database dependency (new)
    "get_db_context",   # Sync context manager (existing)
    "test_db_connection" # Connection test (existing)
]