from typing import Optional
from pydantic import BaseModel
from enum import Enum


class IssueType(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    QUESTION = "question"
    ACCOUNT = "account"


class TicketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketCreate(BaseModel):
    issue_type: IssueType
    subject: str
    description: str
    priority: TicketPriority = TicketPriority.MEDIUM


class TicketResponse(BaseModel):
    id: int
    hubspot_ticket_id: Optional[str] = None
    message: str = "Ticket submitted successfully"