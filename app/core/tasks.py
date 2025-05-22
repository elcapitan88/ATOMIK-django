# app/core/tasks.py
import asyncio
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.pending_registration import PendingRegistration

logger = logging.getLogger(__name__)

async def cleanup_expired_registrations():
    """
    Background task to clean up expired pending registrations
    Runs every hour
    """
    while True:
        try:
            logger.info("Running cleanup for expired pending registrations")
            
            # Create a new database session
            db: Session = SessionLocal()
            
            try:
                # Find and delete expired registrations
                expired_count = db.query(PendingRegistration).filter(
                    PendingRegistration.expires_at < datetime.utcnow()
                ).delete(synchronize_session=False)
                
                db.commit()
                
                if expired_count > 0:
                    logger.info(f"Cleaned up {expired_count} expired pending registrations")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in cleanup task: {str(e)}")
        
        # Wait 1 hour before next cleanup
        await asyncio.sleep(3600)

# You can also add this function for manual cleanup if needed
def manual_cleanup_expired_registrations(db: Session) -> int:
    """
    Manually trigger cleanup of expired registrations
    Returns number of deleted records
    """
    try:
        expired_count = db.query(PendingRegistration).filter(
            PendingRegistration.expires_at < datetime.utcnow()
        ).delete(synchronize_session=False)
        
        db.commit()
        logger.info(f"Manual cleanup: removed {expired_count} expired registrations")
        return expired_count
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error in manual cleanup: {str(e)}")
        raise