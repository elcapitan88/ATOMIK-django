# app/webhooks/rewardful.py
import json
import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..services.rewardful_service import rewardful_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/rewardful", tags=["Rewardful Webhooks"])

@router.post("/general")
async def handle_rewardful_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle general Rewardful webhooks.
    
    Rewardful sends webhooks for various events like referral creation,
    conversion, and commission payments. This endpoint processes all events.
    """
    try:
        # Get raw payload
        payload = await request.body()
        
        # Parse JSON payload
        try:
            event_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in Rewardful webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Log the webhook for debugging
        event_type = event_data.get('type', 'unknown')
        logger.info(f"Received Rewardful webhook: {event_type}")
        
        # Define all supported event types
        supported_events = {
            # Affiliate events
            'affiliate.confirmed',
            'affiliate.created', 
            'affiliate.deleted',
            'affiliate.updated',
            
            # Affiliate link events
            'affiliate_link.created',
            'affiliate_link.updated',
            'affiliate_link.deleted',
            
            # Commission events
            'commission.created',
            'commission.deleted',
            'commission.paid',
            'commission.updated',
            'commission.voided',
            
            # Referral events
            'referral.converted',
            'referral.created',
            'referral.deleted',
            'referral.lead',
            
            # Sale events
            'sale.created',
            'sale.deleted',
            'sale.refunded',
            'sale.updated',
            
            # Payout events
            'payout.created',
            'payout.updated',
            'payout.due',
            'payout.paid',
            'payout.deleted',
            'payout.failed',
            
            # Affiliate coupon events
            'affiliate_coupon.created',
            'affiliate_coupon.activated',
            'affiliate_coupon.deactivated',
            'affiliate_coupon.deleted',
            'affiliate_coupon.updated'
        }
        
        # Process all supported event types
        if event_type in supported_events:
            await rewardful_service.process_rewardful_webhook(event_data, db)
            return {"status": "success", "message": f"Processed {event_type} webhook"}
        else:
            logger.warning(f"Unsupported Rewardful webhook type: {event_type}")
            return {"status": "ignored", "message": f"Webhook type {event_type} not supported"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing Rewardful webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook"
        )

@router.post("/referral-created")
async def handle_referral_created(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Rewardful referral.created webhook.
    
    This webhook is triggered when a new referral is created (someone clicks a referral link).
    """
    try:
        # Get raw payload
        payload = await request.body()
        
        # Parse JSON payload
        try:
            event_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in Rewardful webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Process the referral created event
        await rewardful_service.process_rewardful_webhook({
            'type': 'referral.created',
            'data': event_data
        }, db)
        
        logger.info(f"Successfully processed referral.created webhook")
        
        return {"status": "success", "message": "Referral created webhook processed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing referral.created webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook"
        )

@router.post("/referral-converted")
async def handle_referral_converted(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Rewardful referral.converted webhook.
    
    This webhook is triggered when a referral converts (makes a purchase).
    """
    try:
        # Get raw payload
        payload = await request.body()
        
        # Parse JSON payload
        try:
            event_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in Rewardful webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Process the referral converted event
        await rewardful_service.process_rewardful_webhook({
            'type': 'referral.converted',
            'data': event_data
        }, db)
        
        logger.info(f"Successfully processed referral.converted webhook")
        
        return {"status": "success", "message": "Referral converted webhook processed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing referral.converted webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook"
        )

@router.post("/commission-earned")
async def handle_commission_earned(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Rewardful commission.earned webhook.
    
    This webhook is triggered when a commission is earned by an affiliate.
    """
    try:
        # Get raw payload
        payload = await request.body()
        
        # Parse JSON payload
        try:
            event_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in Rewardful webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Process the commission earned event
        await rewardful_service.process_rewardful_webhook({
            'type': 'commission.earned',
            'data': event_data
        }, db)
        
        logger.info(f"Successfully processed commission.earned webhook")
        
        return {"status": "success", "message": "Commission earned webhook processed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing commission.earned webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook"
        )

@router.get("/test")
async def test_webhook_endpoint():
    """
    Test endpoint to verify webhook configuration.
    """
    return {
        "status": "success",
        "message": "Rewardful webhook endpoint is working",
        "endpoints": [
            "/webhooks/rewardful/general",
            "/webhooks/rewardful/referral-created",
            "/webhooks/rewardful/referral-converted", 
            "/webhooks/rewardful/commission-earned"
        ]
    }