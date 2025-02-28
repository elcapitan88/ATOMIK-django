import httpx
import logging
import os
from typing import Optional
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.support import SupportTicketLog
from app.schemas.support import TicketCreate

logger = logging.getLogger(__name__)


class HubspotService:
    """Service to interact with HubSpot API for support tickets"""
    
    def __init__(self):
        self.api_key = os.getenv("HUBSPOT_API_KEY")
        self.base_url = "https://api.hubapi.com"
        self.tickets_endpoint = "/crm/v3/objects/tickets"
        self.files_endpoint = "/files/v3/files"
        
        if not self.api_key:
            logger.warning("HUBSPOT_API_KEY environment variable not set")
    
    async def create_ticket(
        self, 
        ticket_data: TicketCreate, 
        user_id: int, 
        user_email: str, 
        screenshot: Optional[UploadFile] = None,
        db: Optional[Session] = None
    ) -> dict:
        """
        Creates a support ticket in HubSpot and logs it in our database
        
        Args:
            ticket_data: The ticket data from the client
            user_id: The ID of the user submitting the ticket
            user_email: The email of the user submitting the ticket
            screenshot: Optional screenshot file
            db: Database session
            
        Returns:
            dict: Response with ticket ID and status
        """
        screenshot_url = None
        
        # Upload screenshot if provided
        if screenshot:
            screenshot_url = await self._upload_file(screenshot)
        
        # Prepare payload for HubSpot
        hubspot_payload = {
            "properties": {
                "subject": ticket_data.subject,
                "content": ticket_data.description,
                "hs_pipeline": "support",
                "hs_pipeline_stage": "1",  # New/Open stage
                "hs_ticket_priority": ticket_data.priority.upper(),  # Convert to uppercase
                # Add a note about user info instead of using custom properties
                "hs_ticket_note": f"User ID: {user_id}\nEmail: {user_email}\nIssue Type: {ticket_data.issue_type}"
            }
        }
        
        # Add screenshot URL if available
        if screenshot_url:
            hubspot_payload["properties"]["screenshot_url"] = screenshot_url
        
        # Create ticket in HubSpot
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}{self.tickets_endpoint}",
                    json=hubspot_payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                
                response.raise_for_status()
                hubspot_data = response.json()
                hubspot_ticket_id = hubspot_data.get("id")
                
                # Log ticket in database if session provided
                if db:
                    ticket_log = SupportTicketLog(
                        user_id=user_id,
                        issue_type=ticket_data.issue_type,
                        subject=ticket_data.subject,
                        hubspot_ticket_id=hubspot_ticket_id
                    )
                    db.add(ticket_log)
                    db.commit()
                    db.refresh(ticket_log)
                
                return {
                    "id": ticket_log.id if db else None,
                    "hubspot_ticket_id": hubspot_ticket_id,
                    "message": "Ticket submitted successfully"
                }
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HubSpot API error: {e.response.text}")
                # Add to database anyway to track failed submissions
                if db:
                    ticket_log = SupportTicketLog(
                        user_id=user_id,
                        issue_type=ticket_data.issue_type,
                        subject=ticket_data.subject,
                        hubspot_ticket_id=None
                    )
                    db.add(ticket_log)
                    db.commit()
                    
                raise ValueError(f"Failed to create ticket in HubSpot: {e.response.text}")
            
            except Exception as e:
                logger.error(f"Error creating HubSpot ticket: {str(e)}")
                raise ValueError(f"Error creating ticket: {str(e)}")
    
    async def _upload_file(self, file: UploadFile) -> str:
        """
        Uploads a file to HubSpot and returns the file URL
        
        Args:
            file: The file to upload
            
        Returns:
            str: The URL of the uploaded file
        """
        try:
            file_content = await file.read()
            file_name = file.filename
            
            # Reset file pointer for potential future reads
            await file.seek(0)
            
            # Create form data with file
            form_data = {
                "file": (file_name, file_content, file.content_type),
                "folderPath": "/support-tickets",
                "options": '{"access": "PUBLIC_INDEXABLE", "overwrite": false}'
            }
            
            # Upload to HubSpot
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}{self.files_endpoint}",
                    files=form_data,
                    headers={
                        "Authorization": f"Bearer {self.api_key}"
                    }
                )
                
                response.raise_for_status()
                file_data = response.json()
                
                # Return the file URL
                return file_data.get("url", "")
                
        except Exception as e:
            logger.error(f"Error uploading file to HubSpot: {str(e)}")
            return ""


# Singleton instance
hubspot_service = HubspotService()