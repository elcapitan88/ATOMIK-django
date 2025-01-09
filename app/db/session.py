from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Configure database engine
try:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        echo=settings.SQL_ECHO,
    )
    logger.info("Database engine created successfully")
except Exception as e:
    logger.error(f"Failed to create database engine: {str(e)}")
    raise

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Dependency for FastAPI endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Function to test database connection
def test_db_connection():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))  # Modified this line
        db.close()
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {str(e)}")
        return False