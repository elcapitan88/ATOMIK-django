# app/db/session.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import QueuePool
from app.core.config import settings
import logging
import contextlib

logger = logging.getLogger(__name__)

# Configure the logger level based on the environment
if settings.ENVIRONMENT == "production":
    logger.setLevel(logging.WARNING)
else:
    logger.setLevel(logging.DEBUG)

# Get database parameters from settings
db_params = settings.get_db_params()

# Configure database engine with proper error handling
try:
    # Use the active_database_url property to get the appropriate URL for the current environment
    engine = create_engine(
        settings.active_database_url,
        poolclass=QueuePool,
        **db_params
    )
    logger.info(f"Database engine created successfully in {settings.ENVIRONMENT} mode")
except Exception as e:
    logger.critical(f"Failed to create database engine: {str(e)}")
    engine = None  # Set to None if creation fails
    raise  # Re-raise the exception after logging

# Create session factory
if engine is not None:
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )
else:
    logger.critical("SessionLocal not created due to engine initialization failure")
    SessionLocal = None

# Enhanced dependency for FastAPI endpoints
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
    "engine",
    "SessionLocal",
    "get_db",
    "get_db_context",
    "test_db_connection"
]