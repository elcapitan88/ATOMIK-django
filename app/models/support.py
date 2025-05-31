from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from app.db.base_class import Base


class IssueType(str, enum.Enum):
    BUG = "bug"
    FEATURE = "feature"
    QUESTION = "question"
    ACCOUNT = "account"


class TicketPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SupportTicketLog(Base):
    """Minimal model to log ticket submissions to HubSpot"""
    __tablename__ = "support_ticket_logs"
    
    user = relationship("User", back_populates="support_tickets")
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    issue_type = Column(Enum(IssueType), nullable=False)
    subject = Column(String(255), nullable=False)
    hubspot_ticket_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)