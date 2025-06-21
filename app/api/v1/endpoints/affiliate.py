# app/api/v1/endpoints/affiliate.py
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime

from ....db.session import get_db
from ....models.user import User
from ....models.affiliate import Affiliate, AffiliateReferral
from ....services.firstpromoter_service import firstpromoter_service
from ....api.deps import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

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
            stats = await firstpromoter_service.get_affiliate_stats(existing_affiliate, db)
            return {
                "success": True,
                "message": "You are already an affiliate",
                "affiliate": stats
            }
        
        # Create new affiliate record
        affiliate = await firstpromoter_service.create_affiliate_record(current_user, db)
        
        # Get initial stats (will be mostly zeros)
        stats = await firstpromoter_service.get_affiliate_stats(affiliate, db)
        
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
        stats = await firstpromoter_service.get_affiliate_stats(affiliate, db)
        
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
            "next_payout_date": "1st of next month",  # FirstPromoter pays monthly
            "minimum_payout": 50.0,  # $50 minimum
            "payout_method": "Stripe (connected to your account)",
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
                "tracking_period": "90 days",
                "payment_schedule": "Monthly"
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
        stats = await firstpromoter_service.get_affiliate_stats(affiliate, db)
        
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