from sqlalchemy import Boolean, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKey
from datetime import datetime
from ..db.base_class import Base

class MaintenanceSettings(Base):
    __tablename__ = "maintenance_settings"

    id = Column(Integer, primary_key=True, index=True)
    is_enabled = Column(Boolean, default=False, nullable=False)
    message = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship to user who created/updated the maintenance setting
    creator = relationship("User")
    
    def __str__(self):
        status = "enabled" if self.is_enabled else "disabled"
        return f"MaintenanceSettings(status={status}, created_by={self.created_by})"