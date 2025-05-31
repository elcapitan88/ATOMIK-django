# app/models/pending_registration.py
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime, timedelta
from ..db.base_class import Base

class PendingRegistration(Base):
    __tablename__ = "pending_registrations"

    id = Column(Integer, primary_key=True, index=True)
    session_token = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    username = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    plan_tier = Column(String(50), nullable=True)
    plan_interval = Column(String(50), nullable=True)
    stripe_session_id = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))

    def is_expired(self):
        """Check if this pending registration has expired"""
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return f"<PendingRegistration(email={self.email}, status={self.status})>"