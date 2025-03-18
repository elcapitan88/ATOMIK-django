# app/api/v1/endpoints/admin.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import logging
from datetime import datetime, timedelta

from app.core.security import get_current_user
from app.models.user import User
from app.db.session import get_db
from app.models.promo_code import PromoCode
from app.services.promo_code_service import PromoCodeService

router = APIRouter()
logger = logging.getLogger(__name__)

# Check if user is admin
async def get_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_superuser:
        logger.warning(f"Non-admin user {current_user.id} attempted admin action")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user

# Pydantic models for request/response validation
class PromoCodeCreate(BaseModel):
    description: Optional[str] = Field(None, description="Description of the promo code")
    max_uses: Optional[int] = Field(None, description="Maximum number of times this code can be used")
    expiry_days: Optional[int] = Field(None, description="Number of days until the code expires")
    prefix: Optional[str] = Field("", description="Optional prefix for the code")
    code_length: Optional[int] = Field(8, description="Length of the generated code")

class PromoCodeUpdate(BaseModel):
    description: Optional[str] = None
    is_active: Optional[bool] = None
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None

class PromoCodeResponse(BaseModel):
    id: int
    code: str
    description: Optional[str]
    is_active: bool
    max_uses: Optional[int]
    current_uses: int
    expires_at: Optional[datetime]
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PromoCodeStatsResponse(BaseModel):
    code: str
    total_uses: int
    max_uses: Optional[int]
    is_active: bool
    expires_at: Optional[str]
    created_at: str
    user_count: int
    remaining_uses: Any

class PromoCodeListResponse(BaseModel):
    total: int
    promo_codes: List[PromoCodeResponse]

class ResponseMessage(BaseModel):
    success: bool
    message: str

@router.post("/promo-codes", response_model=PromoCodeResponse)
async def create_promo_code(
    data: PromoCodeCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Create a new promotional code (admin only)"""
    try:
        service = PromoCodeService(db)
        
        promo_code = service.create_promo_code(
            admin_id=admin_user.id,
            description=data.description,
            max_uses=data.max_uses,
            expiry_days=data.expiry_days,
            prefix=data.prefix,
            code_length=data.code_length
        )
        
        logger.info(f"Admin {admin_user.email} created promo code: {promo_code.code}")
        return promo_code
    
    except Exception as e:
        logger.error(f"Error creating promo code: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create promo code: {str(e)}"
        )

@router.get("/promo-codes", response_model=PromoCodeListResponse)
async def list_promo_codes(
    active_only: bool = False,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """List promotional codes (admin only)"""
    try:
        service = PromoCodeService(db)
        promo_codes = service.get_promo_codes(active_only=active_only, limit=limit, offset=offset)
        
        # Get total count
        total_query = db.query(PromoCode)
        if active_only:
            total_query = total_query.filter(PromoCode.is_active == True)
        total = total_query.count()
        
        return {
            "total": total,
            "promo_codes": promo_codes
        }
    
    except Exception as e:
        logger.error(f"Error listing promo codes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list promo codes: {str(e)}"
        )

@router.get("/promo-codes/{code}", response_model=PromoCodeResponse)
async def get_promo_code(
    code: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get a specific promo code by code (admin only)"""
    try:
        service = PromoCodeService(db)
        promo_code = service.get_promo_code_by_code(code)
        
        if not promo_code:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Promo code not found"
            )
        
        return promo_code
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting promo code: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get promo code: {str(e)}"
        )

@router.get("/promo-codes/{code}/stats", response_model=Dict[str, Any])
async def get_promo_code_stats(
    code: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Get usage statistics for a promo code (admin only)"""
    try:
        service = PromoCodeService(db)
        stats = service.get_promo_code_stats(code)
        
        if not stats["success"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=stats["message"]
            )
        
        return stats
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting promo code stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get promo code stats: {str(e)}"
        )

@router.put("/promo-codes/{code}", response_model=ResponseMessage)
async def update_promo_code(
    code: str,
    data: PromoCodeUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Update a promo code (admin only)"""
    try:
        service = PromoCodeService(db)
        result = service.update_promo_code(code, data.model_dump(exclude_unset=True))
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result["message"]
            )
        
        logger.info(f"Admin {admin_user.email} updated promo code: {code}")
        return {
            "success": True,
            "message": "Promo code updated successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating promo code: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update promo code: {str(e)}"
        )

@router.delete("/promo-codes/{code}", response_model=ResponseMessage)
async def deactivate_promo_code(
    code: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Deactivate a promo code (admin only)"""
    try:
        service = PromoCodeService(db)
        result = service.deactivate_promo_code(code)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result["message"]
            )
        
        logger.info(f"Admin {admin_user.email} deactivated promo code: {code}")
        return {
            "success": True,
            "message": "Promo code deactivated successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating promo code: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate promo code: {str(e)}"
        )

@router.post("/promo-codes/{code}/bulk-generate", response_model=Dict[str, Any])
async def bulk_generate_promo_codes(
    code: str,
    count: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """Bulk generate promo codes based on an existing template (admin only)"""
    try:
        # First get the template code
        service = PromoCodeService(db)
        template = service.get_promo_code_by_code(code)
        
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template promo code not found"
            )
        
        # Generate new codes with same settings
        generated_codes = []
        for _ in range(count):
            promo_code = service.create_promo_code(
                admin_id=admin_user.id,
                description=template.description,
                max_uses=template.max_uses,
                # If expires_at exists, calculate days remaining
                expiry_days=(template.expires_at - datetime.utcnow()).days if template.expires_at else None,
                prefix=code.split('-')[0] if '-' in code else "",
                code_length=len(code.split('-')[1]) if '-' in code else len(code)
            )
            generated_codes.append(promo_code.code)
        
        logger.info(f"Admin {admin_user.email} bulk generated {count} promo codes")
        return {
            "success": True,
            "count": len(generated_codes),
            "codes": generated_codes
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk generating promo codes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate promo codes: {str(e)}"
        )