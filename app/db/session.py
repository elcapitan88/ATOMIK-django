from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Configure database engine with proper error handling
try:
    # Debug: Log the actual database URL being used
    logger.info(f"Connecting to database: {settings.DATABASE_URL[:50]}...")
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,  # Recycle connections every 30 minutes
        pool_pre_ping=True,  # Enable connection health checks
        echo=settings.SQL_ECHO,
    )
    logger.info("Database engine created successfully")
except Exception as e:
    logger.error(f"Failed to create database engine: {str(e)}")
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
    logger.error("SessionLocal not created due to engine initialization failure")
    SessionLocal = None

# Dependency for FastAPI endpoints
async def get_db():
    if SessionLocal is None:
        logger.error("Cannot create database session - SessionLocal is None")
        raise Exception("Database session factory not initialized")
        
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Function to test database connection
async def test_db_connection():
    """Test database connection and log the results"""
    try:
        if engine is None:
            logger.error("Cannot test connection - engine is None")
            return False

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            logger.info("Database connection test successful")
            return True
        except Exception as e:
            logger.error(f"Database connection test failed: {str(e)}")
            return False
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error during connection test: {str(e)}")
        return False

# Export everything needed by other modules
__all__ = [
    "engine",
    "SessionLocal",
    "get_db",
    "test_db_connection"
]