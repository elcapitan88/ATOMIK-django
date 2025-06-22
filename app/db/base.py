from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from ..core.config import settings
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Force refresh of affiliate models - timestamp: 2025-06-22T04:30:00Z

# Create SQLAlchemy engine
active_db_url = settings.active_database_url
logger.info(f"🔍 CONNECTING TO DATABASE: {active_db_url[:50]}...")
engine = create_engine(
    active_db_url,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,  # Recycle connections every 30 minutes
    echo=settings.SQL_ECHO,  # Log SQL queries
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Import all models here so SQLAlchemy knows about them
from app.db.base_class import Base  # noqa
from app.models.user import User  # noqa
from app.models.webhook import Webhook, WebhookLog  # noqa
from app.models.strategy import ActivatedStrategy  # noqa
from app.models.broker import BrokerAccount, BrokerCredentials  # noqa
from app.models.subscription import Subscription
from app.models.order import Order
from app.models.promo_code import PromoCode
from app.models.affiliate import Affiliate, AffiliateReferral, AffiliateClick, AffiliatePayout  # noqa

# Create a dependency for FastAPI endpoints
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
        db.execute(text("SELECT 1"))
        db.close()
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {str(e)}")
        return False

# Database initialization function
def init_db():
    """Initialize the database"""
    try:
        # Import all models to ensure they're registered
        import app.models.user
        import app.models.webhook
        import app.models.strategy
        import app.models.broker
        import app.models.subscription
        import app.models.order
        import app.models.affiliate
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
        
        # Test the connection
        test_db_connection()
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise

# Export everything needed by other modules
__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
    "test_db_connection",
    "User",
    "Webhook",
    "WebhookLog",
    "ActivatedStrategy",
    "BrokerAccount",
    "BrokerCredentials",
    "Subscription",
    "Order",
    "Affiliate",
    "AffiliateReferral",
    "AffiliateClick",
    "AffiliatePayout"
]