# app/models/promo_code.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from ..db.base_class import Base

class PromoCode(Base):
    """Model for storing promotional codes that grant Elite lifetime subscriptions"""
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    max_uses = Column(Integer, nullable=True)
    current_uses = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by], backref="created_promo_codes")
    
    # Commented out to avoid circular dependency
    # users = relationship("User", back_populates="used_promo_code", foreign_keys="[User.promo_code_id]")
    
    def is_valid(self) -> bool:
        """Check if the promo code is valid for use"""
        if not self.is_active:
            return False
            
        # Check expiration if set
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
            
        # Check usage limit if set
        if self.max_uses is not None and self.current_uses >= self.max_uses:
            return False
            
        return True