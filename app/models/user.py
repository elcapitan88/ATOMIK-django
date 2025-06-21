# In app/models/user.py
from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    full_name = Column(String, nullable=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    app_role = Column(String, nullable=True)  # 'admin', 'moderator', 'beta_tester', None
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Profile fields
    profile_picture = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    
    # Add promo_code_id column
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    webhooks = relationship("Webhook", back_populates="user", cascade="all, delete-orphan")
    broker_accounts = relationship("BrokerAccount", back_populates="user", cascade="all, delete-orphan")
    strategies = relationship("ActivatedStrategy", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    support_tickets = relationship("SupportTicketLog", back_populates="user")
    
    # Add relationship to used promo code
    used_promo_code = relationship("PromoCode", foreign_keys=[promo_code_id])
    
    # Affiliate relationship
    affiliate = relationship("Affiliate", back_populates="user", uselist=False)
    
    # Strategy AI relationships - temporarily commented out
    # strategy_interpretations = relationship("StrategyInterpretation", back_populates="user", cascade="all, delete-orphan")
    # strategy_customizations = relationship("StrategyCustomization", back_populates="user", cascade="all, delete-orphan")
    # generated_codes = relationship("GeneratedCode", back_populates="user", cascade="all, delete-orphan")
    # ai_usage_tracking = relationship("AIUsageTracking", back_populates="user", cascade="all, delete-orphan")
    # component_interpretations = relationship("ComponentInterpretation", back_populates="user", cascade="all, delete-orphan")
    
    def __str__(self):
        return f"User(email={self.email})"
    
    # App role helper methods
    def is_admin(self) -> bool:
        """Check if user has admin app role"""
        return self.app_role == 'admin'
    
    def is_moderator(self) -> bool:
        """Check if user has moderator or admin app role"""
        return self.app_role in ['admin', 'moderator']
    
    def is_beta_tester(self) -> bool:
        """Check if user has beta tester, moderator, or admin app role"""
        return self.app_role in ['admin', 'moderator', 'beta_tester']
    
    def has_app_role(self, role: str) -> bool:
        """Check if user has a specific app role"""
        return self.app_role == role