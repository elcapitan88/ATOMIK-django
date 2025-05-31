from typing import Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
import logging

# Fix these imports by adding the 'app.' prefix
from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.support import TicketCreate, TicketResponse, IssueType, TicketPriority
from app.services.hubspot_service import hubspot_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/tickets", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_support_ticket(
    *,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    issue_type: IssueType = Form(...),
    subject: str = Form(...),
    description: str = Form(...),
    priority: TicketPriority = Form(TicketPriority.MEDIUM),
    screenshot: UploadFile = File(None)
) -> Any:
    """
    Create a new support ticket that will be sent to HubSpot.
    """
    try:
        # Create Ticket object from form data
        ticket_data = TicketCreate(
            issue_type=issue_type,
            subject=subject,
            description=description,
            priority=priority
        )
        
        # Process screenshot if provided
        screenshot_file = None
        if screenshot and screenshot.filename:
            # Validate file type
            if not screenshot.content_type.startswith("image/"):
                raise HTTPException(
                    status_code=400,
                    detail="File must be an image"
                )
            screenshot_file = screenshot
        
        # Submit ticket to HubSpot
        result = await hubspot_service.create_ticket(
            ticket_data=ticket_data,
            user_id=current_user.id,
            user_email=current_user.email,
            screenshot=screenshot_file,
            db=db
        )
        
        return result
        
    except ValueError as e:
        logger.error(f"Error creating support ticket: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error creating support ticket: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request"
        )


@router.get("/tickets/health", status_code=status.HTTP_200_OK)
async def check_hubspot_health(
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Simple health check endpoint for the HubSpot integration.
    """
    if not hubspot_service.api_key:
        return {"status": "warning", "message": "HubSpot API key not configured"}
    
    return {"status": "ok", "message": "HubSpot integration is configured"}