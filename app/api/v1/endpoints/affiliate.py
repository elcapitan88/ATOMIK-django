# app/api/v1/endpoints/affiliate.py
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel

from ....db.session import get_db
from ....models.user import User
from ....models.affiliate import Affiliate, AffiliateReferral, AffiliateClick, AffiliatePayout
from ....services.rewardful_service import rewardful_service
from ....api.deps import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic models for request validation
class ClickTrackingRequest(BaseModel):
    referral_code: str
    page_url: Optional[str] = None
    referrer: Optional[str] = None
    user_agent: Optional[str] = None

class PayoutMethodRequest(BaseModel):
    payout_method: str  # 'paypal' or 'wise'
    payout_details: Dict[str, Any]  # PayPal email, Wise details, etc.

@router.post("/track-click", response_model=Dict[str, Any])
async def track_referral_click(
    click_data: ClickTrackingRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Track a referral link click (public endpoint - no auth required).
    
    Args:
        click_data: Click tracking data including referral code
        request: FastAPI request object for IP address
        db: Database session
    
    Returns:
        Dict containing success status
    """
    try:
        # Find the affiliate by referral code
        affiliate = db.query(Affiliate).filter(
            Affiliate.referral_code == click_data.referral_code,
            Affiliate.is_active == True
        ).first()
        
        if not affiliate:
            # Log the actual issue for debugging
            logger.error(f"AFFILIATE NOT FOUND for referral code: {click_data.referral_code}")
            # Check if affiliate exists but is inactive
            inactive_affiliate = db.query(Affiliate).filter(
                Affiliate.referral_code == click_data.referral_code
            ).first()
            if inactive_affiliate:
                logger.error(f"Affiliate exists but is inactive: {inactive_affiliate.id}, active: {inactive_affiliate.is_active}")
            else:
                logger.error("No affiliate found with this referral code at all")
            # Still return success to avoid revealing valid codes
            return {
                "success": True,
                "message": "Click tracked"
            }
        
        # Get client IP address
        client_ip = request.client.host
        if hasattr(request, 'headers'):
            # Check for forwarded IP in case of proxy/load balancer
            forwarded_for = request.headers.get('X-Forwarded-For')
            if forwarded_for:
                client_ip = forwarded_for.split(',')[0].strip()
        
        # Create click record
        click_record = AffiliateClick(
            affiliate_id=affiliate.id,
            ip_address=client_ip,
            user_agent=click_data.user_agent or request.headers.get('User-Agent'),
            landing_page=click_data.page_url,
            referrer_url=click_data.referrer or request.headers.get('Referer'),
            click_date=datetime.utcnow()
        )
        
        db.add(click_record)
        db.commit()
        
        logger.info(f"CLICK RECORDED SUCCESSFULLY for affiliate {affiliate.id} with code {click_data.referral_code}")
        logger.info(f"Click record ID: {click_record.id if hasattr(click_record, 'id') else 'pending'}")
        
        return {
            "success": True,
            "message": "Click tracked successfully"
        }
        
    except Exception as e:
        logger.error(f"Error tracking referral click: {str(e)}")
        db.rollback()
        # Return success to avoid revealing system errors to potential attackers
        return {
            "success": True,
            "message": "Click tracked"
        }

@router.post("/become-affiliate", response_model=Dict[str, Any])
async def become_affiliate(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Allow a user to become an affiliate.
    
    Returns:
        Dict containing affiliate information including referral link
    """
    try:
        # Check if user already has an active affiliate account
        existing_affiliate = db.query(Affiliate).filter(
            Affiliate.user_id == current_user.id
        ).first()
        
        if existing_affiliate and existing_affiliate.is_active:
            # Return existing affiliate data
            stats = await rewardful_service.get_affiliate_stats(existing_affiliate, db)
            return {
                "success": True,
                "message": "You are already an affiliate",
                "affiliate": stats
            }
        
        # Create new affiliate record
        affiliate = await rewardful_service.create_affiliate_record(current_user, db)
        
        # Get initial stats (will be mostly zeros)
        stats = await rewardful_service.get_affiliate_stats(affiliate, db)
        
        logger.info(f"User {current_user.id} became an affiliate with code {affiliate.referral_code}")
        
        return {
            "success": True,
            "message": "Welcome to our affiliate program!",
            "affiliate": stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in become_affiliate: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while setting up your affiliate account"
        )

@router.get("/dashboard", response_model=Dict[str, Any])
async def get_affiliate_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get affiliate dashboard data including stats and referral information.
    
    Returns:
        Dict containing comprehensive affiliate dashboard data
    """
    try:
        # Check if user is an affiliate
        affiliate = db.query(Affiliate).filter(
            Affiliate.user_id == current_user.id,
            Affiliate.is_active == True
        ).first()
        
        if not affiliate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You are not an active affiliate. Please join our affiliate program first."
            )
        
        # Get comprehensive stats
        stats = await rewardful_service.get_affiliate_stats(affiliate, db)
        
        # Get recent referrals (last 10)
        recent_referrals = db.query(AffiliateReferral).filter(
            AffiliateReferral.affiliate_id == affiliate.id
        ).order_by(AffiliateReferral.created_at.desc()).limit(10).all()
        
        # Format recent referrals
        referrals_data = []
        for referral in recent_referrals:
            referrals_data.append({
                "id": referral.id,
                "customer_email": referral.customer_email,
                "customer_name": referral.customer_name,
                "status": referral.status,
                "conversion_amount": referral.conversion_amount,
                "commission_amount": referral.commission_amount,
                "referral_date": referral.referral_date.isoformat() if referral.referral_date else None,
                "conversion_date": referral.conversion_date.isoformat() if referral.conversion_date else None,
                "subscription_type": referral.subscription_type,
                "subscription_tier": referral.subscription_tier
            })
        
        # Add payout information
        payout_info = {
            "next_payout_date": "By the 7th of next month",
            "minimum_payout": 50.0,  # $50 minimum
            "payout_method": affiliate.payout_method or "Not configured",
            "payout_details": affiliate.payout_details or {},
            "currency": "USD"
        }
        
        return {
            "success": True,
            "affiliate": stats,
            "recent_referrals": referrals_data,
            "payout_info": payout_info,
            "program_info": {
                "commission_rate": "20%",
                "commission_type": "Lifetime recurring",
                "tracking_period": "15 days",
                "payment_schedule": "Monthly (by 7th)",
                "terms_url": "/affiliate-terms"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_affiliate_dashboard: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while loading your affiliate dashboard"
        )

@router.get("/referrals", response_model=Dict[str, Any])
async def get_referrals(
    page: int = 1,
    limit: int = 20,
    status_filter: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get paginated list of referrals for the current affiliate.
    
    Args:
        page: Page number (1-indexed)
        limit: Number of referrals per page
        status_filter: Filter by referral status (pending, confirmed, paid)
    
    Returns:
        Dict containing paginated referrals and metadata
    """
    try:
        # Check if user is an affiliate
        affiliate = db.query(Affiliate).filter(
            Affiliate.user_id == current_user.id,
            Affiliate.is_active == True
        ).first()
        
        if not affiliate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You are not an active affiliate"
            )
        
        # Build query
        query = db.query(AffiliateReferral).filter(
            AffiliateReferral.affiliate_id == affiliate.id
        )
        
        # Apply status filter if provided
        if status_filter and status_filter in ['pending', 'confirmed', 'paid', 'cancelled']:
            query = query.filter(AffiliateReferral.status == status_filter)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        offset = (page - 1) * limit
        referrals = query.order_by(
            AffiliateReferral.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        # Format referrals
        referrals_data = []
        for referral in referrals:
            referrals_data.append({
                "id": referral.id,
                "customer_email": referral.customer_email,
                "customer_name": referral.customer_name,
                "status": referral.status,
                "conversion_amount": referral.conversion_amount,
                "commission_amount": referral.commission_amount,
                "commission_rate": referral.commission_rate,
                "subscription_type": referral.subscription_type,
                "subscription_tier": referral.subscription_tier,
                "is_first_conversion": referral.is_first_conversion,
                "referral_date": referral.referral_date.isoformat() if referral.referral_date else None,
                "conversion_date": referral.conversion_date.isoformat() if referral.conversion_date else None,
                "commission_paid_date": referral.commission_paid_date.isoformat() if referral.commission_paid_date else None
            })
        
        # Calculate pagination metadata
        total_pages = (total_count + limit - 1) // limit
        has_next = page < total_pages
        has_prev = page > 1
        
        return {
            "success": True,
            "referrals": referrals_data,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "has_next": has_next,
                "has_prev": has_prev
            },
            "filters": {
                "status": status_filter,
                "available_statuses": ["pending", "confirmed", "paid", "cancelled"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_referrals: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while loading your referrals"
        )

@router.get("/stats", response_model=Dict[str, Any])
async def get_affiliate_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed affiliate statistics.
    
    Returns:
        Dict containing detailed affiliate statistics
    """
    try:
        # Check if user is an affiliate
        affiliate = db.query(Affiliate).filter(
            Affiliate.user_id == current_user.id,
            Affiliate.is_active == True
        ).first()
        
        if not affiliate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You are not an active affiliate"
            )
        
        # Get comprehensive stats
        stats = await rewardful_service.get_affiliate_stats(affiliate, db)
        
        return {
            "success": True,
            "stats": stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_affiliate_stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while loading your statistics"
        )

@router.delete("/deactivate", response_model=Dict[str, Any])
async def deactivate_affiliate(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Deactivate affiliate account (soft delete).
    
    Returns:
        Dict containing success message
    """
    try:
        # Check if user is an affiliate
        affiliate = db.query(Affiliate).filter(
            Affiliate.user_id == current_user.id,
            Affiliate.is_active == True
        ).first()
        
        if not affiliate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You are not an active affiliate"
            )
        
        # Deactivate (soft delete)
        affiliate.is_active = False
        affiliate.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(f"Deactivated affiliate account for user {current_user.id}")
        
        return {
            "success": True,
            "message": "Your affiliate account has been deactivated"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in deactivate_affiliate: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deactivating your affiliate account"
        )

@router.put("/payout-method", response_model=Dict[str, Any])
async def update_payout_method(
    payout_data: PayoutMethodRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update affiliate payout method (PayPal or Wise).
    
    Args:
        payout_data: Payout method and details
    
    Returns:
        Dict containing success message
    """
    try:
        # Check if user is an affiliate
        affiliate = db.query(Affiliate).filter(
            Affiliate.user_id == current_user.id,
            Affiliate.is_active == True
        ).first()
        
        if not affiliate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You are not an active affiliate"
            )
        
        # Validate payout method
        if payout_data.payout_method not in ['paypal', 'wise']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payout method. Must be 'paypal' or 'wise'"
            )
        
        # Validate required fields based on method
        if payout_data.payout_method == 'paypal':
            if not payout_data.payout_details.get('email'):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="PayPal email is required"
                )
        elif payout_data.payout_method == 'wise':
            required_fields = ['email', 'recipient_type']
            for field in required_fields:
                if not payout_data.payout_details.get(field):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Wise {field} is required"
                    )
        
        # Update payout method
        affiliate.payout_method = payout_data.payout_method
        affiliate.payout_details = payout_data.payout_details
        affiliate.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(f"Updated payout method for affiliate {affiliate.id} to {payout_data.payout_method}")
        
        return {
            "success": True,
            "message": f"Payout method updated to {payout_data.payout_method.title()}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating payout method: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating your payout method"
        )

@router.get("/payout-history", response_model=Dict[str, Any])
async def get_payout_history(
    page: int = 1,
    limit: int = 12,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get paginated payout history for the current affiliate.
    
    Args:
        page: Page number (1-indexed)
        limit: Number of payouts per page (default 12 for monthly view)
    
    Returns:
        Dict containing paginated payout history
    """
    try:
        # Check if user is an affiliate
        affiliate = db.query(Affiliate).filter(
            Affiliate.user_id == current_user.id,
            Affiliate.is_active == True
        ).first()
        
        if not affiliate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You are not an active affiliate"
            )
        
        # Get total count
        total_count = db.query(AffiliatePayout).filter(
            AffiliatePayout.affiliate_id == affiliate.id
        ).count()
        
        # Apply pagination
        offset = (page - 1) * limit
        payouts = db.query(AffiliatePayout).filter(
            AffiliatePayout.affiliate_id == affiliate.id
        ).order_by(
            AffiliatePayout.period_end.desc()
        ).offset(offset).limit(limit).all()
        
        # Format payouts
        payouts_data = []
        for payout in payouts:
            payouts_data.append({
                "id": payout.id,
                "payout_amount": payout.payout_amount,
                "payout_method": payout.payout_method,
                "status": payout.status,
                "period_start": payout.period_start.isoformat(),
                "period_end": payout.period_end.isoformat(),
                "payout_date": payout.payout_date.isoformat() if payout.payout_date else None,
                "transaction_id": payout.transaction_id,
                "currency": payout.currency,
                "commission_count": payout.commission_count,
                "created_at": payout.created_at.isoformat()
            })
        
        # Calculate pagination metadata
        total_pages = (total_count + limit - 1) // limit
        has_next = page < total_pages
        has_prev = page > 1
        
        # Calculate summary stats
        from sqlalchemy import func
        
        total_paid = db.query(func.sum(AffiliatePayout.payout_amount)).filter(
            AffiliatePayout.affiliate_id == affiliate.id,
            AffiliatePayout.status == "completed"
        ).scalar() or 0
        
        pending_amount = db.query(func.sum(AffiliatePayout.payout_amount)).filter(
            AffiliatePayout.affiliate_id == affiliate.id,
            AffiliatePayout.status.in_(["pending", "processing"])
        ).scalar() or 0
        
        return {
            "success": True,
            "payouts": payouts_data,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "has_next": has_next,
                "has_prev": has_prev
            },
            "summary": {
                "total_paid": total_paid,
                "pending_amount": pending_amount,
                "payout_method": affiliate.payout_method or "Not configured"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting payout history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while loading your payout history"
        )