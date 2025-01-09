from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    name = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    secret_key = Column(String(64), nullable=False)
    source_type = Column(String(50), default='custom')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_triggered = Column(DateTime, nullable=True)
    allowed_ips = Column(Text, nullable=True)
    max_triggers_per_minute = Column(Integer, default=60)
    require_signature = Column(Boolean, default=True)
    max_retries = Column(Integer, default=3)
    retry_interval = Column(Integer, default=60)

    # Relationships
    user = relationship("User", back_populates="webhooks")
    webhook_logs = relationship("WebhookLog", back_populates="webhook", cascade="all, delete-orphan")  # Updated relationship name

class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"))
    triggered_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    payload = Column(Text)
    error_message = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    processing_time = Column(Float, nullable=True)

    # Relationship to webhook
    webhook = relationship("Webhook", back_populates="webhook_logs")