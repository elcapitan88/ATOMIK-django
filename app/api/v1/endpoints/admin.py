# app/api/v1/endpoints/admin.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
import logging

from ....core.security import get_current_user
from ....models.user import User
from ....models.maintenance import MaintenanceSettings
from ....db.base import get_db
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic schemas for maintenance endpoints
class MaintenanceSettingsResponse(BaseModel):
    is_enabled: bool
    message: Optional[str] = None
    created_by: int
    created_at: str
    updated_at: str

class MaintenanceSettingsUpdate(BaseModel):
    is_enabled: bool
    message: Optional[str] = None

def require_admin(current_user: User = Depends(get_current_user)):
    """Require admin privileges"""
    if not (current_user.username == 'admin' or 
            hasattr(current_user, 'app_role') and current_user.app_role in ['admin', 'superadmin'] or
            hasattr(current_user, 'role') and current_user.role in ['admin', 'superadmin']):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user

@router.get("/maintenance", response_model=MaintenanceSettingsResponse)
def get_maintenance_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get current maintenance settings"""
    try:
        maintenance = db.query(MaintenanceSettings).order_by(MaintenanceSettings.updated_at.desc()).first()
        
        if not maintenance:
            # Return default settings if none exist
            return MaintenanceSettingsResponse(
                is_enabled=False,
                message=None,
                created_by=current_user.id,
                created_at="",
                updated_at=""
            )
        
        return MaintenanceSettingsResponse(
            is_enabled=maintenance.is_enabled,
            message=maintenance.message,
            created_by=maintenance.created_by,
            created_at=maintenance.created_at.isoformat(),
            updated_at=maintenance.updated_at.isoformat()
        )
        
    except Exception as e:
        logger.error(f"Error getting maintenance settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving maintenance settings"
        )

@router.put("/maintenance", response_model=MaintenanceSettingsResponse)
def update_maintenance_settings(
    settings: MaintenanceSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update maintenance settings"""
    try:
        # Get the latest maintenance settings or create new one
        maintenance = db.query(MaintenanceSettings).order_by(MaintenanceSettings.updated_at.desc()).first()
        
        if maintenance:
            # Update existing settings
            maintenance.is_enabled = settings.is_enabled
            maintenance.message = settings.message
            maintenance.created_by = current_user.id
        else:
            # Create new settings
            maintenance = MaintenanceSettings(
                is_enabled=settings.is_enabled,
                message=settings.message,
                created_by=current_user.id
            )
            db.add(maintenance)
        
        db.commit()
        db.refresh(maintenance)
        
        logger.info(f"Maintenance mode {'enabled' if settings.is_enabled else 'disabled'} by user {current_user.username}")
        
        return MaintenanceSettingsResponse(
            is_enabled=maintenance.is_enabled,
            message=maintenance.message,
            created_by=maintenance.created_by,
            created_at=maintenance.created_at.isoformat(),
            updated_at=maintenance.updated_at.isoformat()
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating maintenance settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error updating maintenance settings"
        )

@router.get("/maintenance/status")
def get_maintenance_status(db: Session = Depends(get_db)):
    """Public endpoint to check if maintenance mode is enabled (no auth required)"""
    try:
        maintenance = db.query(MaintenanceSettings).order_by(MaintenanceSettings.updated_at.desc()).first()
        
        if not maintenance:
            return {"is_enabled": False, "message": None}
        
        return {
            "is_enabled": maintenance.is_enabled,
            "message": maintenance.message
        }
        
    except Exception as e:
        logger.error(f"Error getting maintenance status: {e}")
        return {"is_enabled": False, "message": None}