from sqlalchemy.orm import Session
import logging
from app.db.base_class import Base
from app.db.session import engine
from app.core.config import settings
from app.models import User, Webhook, WebhookLog, TradovateToken

logger = logging.getLogger(__name__)

def init_db() -> None:
    try:
        # Drop all tables
        Base.metadata.drop_all(bind=engine)
        logger.info("Dropped all existing tables")
        
        # Create tables
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")

    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise

def create_first_superuser(db: Session) -> None:
    """Create a superuser if configured in settings and none exists."""
    try:
        if settings.FIRST_SUPERUSER_EMAIL and settings.FIRST_SUPERUSER_PASSWORD:
            user = db.query(User).filter(
                User.email == settings.FIRST_SUPERUSER_EMAIL
            ).first()
            
            if not user:
                logger.info("Creating first superuser...")
                user_in = {
                    "email": settings.FIRST_SUPERUSER_EMAIL,
                    "username": "admin",
                    "password": settings.FIRST_SUPERUSER_PASSWORD,
                    "is_superuser": True,
                }
                user = User(**user_in)
                db.add(user)
                db.commit()
                logger.info("First superuser created successfully")
            else:
                logger.info("Superuser already exists")

    except Exception as e:
        logger.error(f"Error creating superuser: {str(e)}")
        db.rollback()
        raise

def init() -> None:
    """Initialize database with required initial data."""
    try:
        # Create tables
        init_db()

        # Create first superuser if needed
        # Uncomment this if you want to automatically create a superuser
        # from app.db.session import SessionLocal
        # db = SessionLocal()
        # create_first_superuser(db)
        # db.close()

    except Exception as e:
        logger.error(f"Error in database initialization: {str(e)}")
        raise