from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    stripe_customer_id = Column(String, unique=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    status = Column(String, default="inactive")
    tier = Column(String, default="starter")
    is_lifetime = Column(Boolean, default=False)
    connected_accounts_count = Column(Integer, default=0)
    active_webhooks_count = Column(Integer, default=0) 
    active_strategies_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="subscription")