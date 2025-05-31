# app/db/init_chat.py
"""
Script to initialize chat system with default channels and roles
Run this after running the database migrations
"""
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.services.chat_service import initialize_default_channels


def init_chat_system():
    """Initialize the chat system with default data"""
    db: Session = SessionLocal()
    
    try:
        print("Initializing default chat channels...")
        initialize_default_channels(db)
        print("✅ Chat system initialized successfully!")
        
    except Exception as e:
        print(f"❌ Error initializing chat system: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_chat_system()