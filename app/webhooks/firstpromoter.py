# app/webhooks/firstpromoter.py
import json
import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..services.firstpromoter_service import firstpromoter_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/firstpromoter", tags=["FirstPromoter Webhooks"])

@router.post("/referral-created")
async def handle_referral_created(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle FirstPromoter referral.created webhook.
    
    This webhook is triggered when a new referral is created (someone clicks a referral link).
    """
    try:
        # Get raw payload and signature
        payload = await request.body()
        signature = request.headers.get('X-FirstPromoter-Signature', '')
        
        # Verify webhook signature
        if not firstpromoter_service.verify_webhook_signature(payload, signature):
            logger.warning("Invalid FirstPromoter webhook signature for referral.created")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
        
        # Parse JSON payload
        try:
            event_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in FirstPromoter webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Process the referral created event
        await firstpromoter_service.process_referral_webhook({
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
    Handle FirstPromoter referral.converted webhook.
    
    This webhook is triggered when a referral converts (makes a purchase).
    """
    try:
        # Get raw payload and signature
        payload = await request.body()
        signature = request.headers.get('X-FirstPromoter-Signature', '')
        
        # Verify webhook signature
        if not firstpromoter_service.verify_webhook_signature(payload, signature):
            logger.warning("Invalid FirstPromoter webhook signature for referral.converted")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
        
        # Parse JSON payload
        try:
            event_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in FirstPromoter webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Process the referral converted event
        await firstpromoter_service.process_referral_webhook({
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

@router.post("/commission-paid")
async def handle_commission_paid(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle FirstPromoter commission.paid webhook.
    
    This webhook is triggered when a commission is paid to an affiliate.
    """
    try:
        # Get raw payload and signature
        payload = await request.body()
        signature = request.headers.get('X-FirstPromoter-Signature', '')
        
        # Verify webhook signature
        if not firstpromoter_service.verify_webhook_signature(payload, signature):
            logger.warning("Invalid FirstPromoter webhook signature for commission.paid")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
        
        # Parse JSON payload
        try:
            event_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in FirstPromoter webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Process the commission paid event
        await firstpromoter_service.process_referral_webhook({
            'type': 'commission.paid',
            'data': event_data
        }, db)
        
        logger.info(f"Successfully processed commission.paid webhook")
        
        return {"status": "success", "message": "Commission paid webhook processed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing commission.paid webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook"
        )

@router.post("/general")
async def handle_general_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle general FirstPromoter webhooks.
    
    This is a catch-all endpoint for any FirstPromoter webhooks.
    """
    try:
        # Get raw payload and signature
        payload = await request.body()
        signature = request.headers.get('X-FirstPromoter-Signature', '')
        
        # Verify webhook signature
        if not firstpromoter_service.verify_webhook_signature(payload, signature):
            logger.warning("Invalid FirstPromoter webhook signature for general webhook")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
        
        # Parse JSON payload
        try:
            event_data = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in FirstPromoter webhook: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Log the webhook for debugging
        event_type = event_data.get('type', 'unknown')
        logger.info(f"Received FirstPromoter webhook: {event_type}")
        
        # Process known event types
        if event_type in ['referral.created', 'referral.converted', 'commission.paid']:
            await firstpromoter_service.process_referral_webhook(event_data, db)
            return {"status": "success", "message": f"Processed {event_type} webhook"}
        else:
            logger.info(f"Unhandled FirstPromoter webhook type: {event_type}")
            return {"status": "ignored", "message": f"Webhook type {event_type} not handled"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing general FirstPromoter webhook: {str(e)}")
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
        "message": "FirstPromoter webhook endpoint is working",
        "endpoints": [
            "/webhooks/firstpromoter/referral-created",
            "/webhooks/firstpromoter/referral-converted", 
            "/webhooks/firstpromoter/commission-paid",
            "/webhooks/firstpromoter/general"
        ]
    }