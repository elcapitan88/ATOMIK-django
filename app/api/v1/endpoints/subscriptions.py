from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
import logging
from typing import Optional
import stripe
from sqlalchemy.exc import IntegrityError

from app.models.subscription import Subscription
from app.models.user import User
from app.core.config import settings
from app.db.session import get_db
from app.core.security import get_current_user
from app.services.stripe_service import StripeService
from app.schemas.subscription import SubscriptionVerification, PortalSession, SubscriptionConfig

router = APIRouter()
logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY
stripe_service = StripeService()

@router.get("/verify", response_model=SubscriptionVerification)
async def verify_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Verify user's subscription status"""
    try:
        # Development mode check
        if settings.SKIP_SUBSCRIPTION_CHECK:
            logger.debug(f"Subscription check skipped for user {current_user.email} (dev mode)")
            return {
                "has_access": True,
                "dev_mode": True
            }

        # Get user's subscription
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()

        if not subscription or not subscription.stripe_customer_id:
            logger.warning(f"No subscription found for user {current_user.email}")
            return {
                "has_access": False,
                "reason": "no_subscription"
            }

        # Verify with Stripe
        has_active_subscription = await stripe_service.verify_subscription_status(
            subscription.stripe_customer_id
        )

        return {
            "has_access": has_active_subscription,
            "customer_id": subscription.stripe_customer_id
        }

    except Exception as e:
        logger.error(f"Subscription verification error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Error verifying subscription status"
        )

@router.post("/create-portal-session", response_model=PortalSession)
async def create_portal_session(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create Stripe Customer Portal session"""
    try:
        # Get or create customer
        customer_id = await stripe_service.get_or_create_customer(current_user, db)
        
        # Create portal session
        portal_url = await stripe_service.create_portal_session(customer_id)
        
        return {"url": portal_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Portal session creation error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create portal session"
        )

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Handle Stripe webhooks"""
    try:
        # Get the webhook signature from headers
        sig_header = request.headers.get('stripe-signature')
        if not sig_header:
            logger.error("No Stripe signature found in webhook request")
            return {"status": "error", "message": "No signature header"}

        # Get the raw request body
        payload = await request.body()
        
        # Verify webhook signature
        try:
            event = await stripe_service.verify_webhook_signature(
                payload=payload,
                sig_header=sig_header
            )
        except Exception as e:
            logger.error(f"Webhook signature verification failed: {str(e)}")
            return {"status": "error", "message": "Invalid signature"}

        # Process different event types
        if event.type == "checkout.session.completed":
            background_tasks.add_task(
                handle_successful_checkout,
                db=db,
                session=event.data.object
            )
        elif event.type == "customer.subscription.updated":
            background_tasks.add_task(
                handle_subscription_update,
                db=db,
                subscription=event.data.object
            )
        elif event.type == "customer.subscription.deleted":
            background_tasks.add_task(
                handle_subscription_deletion,
                db=db,
                subscription=event.data.object
            )

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return {"status": "error", "message": str(e)}

@router.get("/config", response_model=SubscriptionConfig)
async def get_subscription_config():
    """Get subscription configuration"""
    return {
        "publishable_key": settings.STRIPE_PUBLIC_KEY,
        "checks_disabled": settings.SKIP_SUBSCRIPTION_CHECK,
        "environment": settings.ENVIRONMENT
    }

# Background task handlers
async def handle_successful_checkout(db: Session, session: dict):
    """Process successful checkout session"""
    try:
        customer_email = session.get('customer_email')
        logger.info(f"Processing successful checkout for email: {customer_email}")

        if not customer_email:
            logger.error("No customer email in checkout session")
            return

        # Find user
        user = db.query(User).filter(User.email == customer_email).first()
        if not user:
            logger.error(f"No user found for email: {customer_email}")
            return

        # Create or update subscription
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user.id
        ).first()

        if not subscription:
            subscription = Subscription(
                user_id=user.id,
                stripe_customer_id=session.get('customer')
            )
            db.add(subscription)
            logger.info(f"Created new subscription for user {user.email}")
        else:
            subscription.stripe_customer_id = session.get('customer')
            logger.info(f"Updated subscription for user {user.email}")

        db.commit()
        logger.info(f"Subscription successfully processed for user {user.email}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error processing checkout: {str(e)}")

async def handle_subscription_update(db: Session, subscription: dict):
    """Handle subscription update event"""
    try:
        customer_id = subscription.get('customer')
        if not customer_id:
            return

        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_customer_id == customer_id
        ).first()

        if db_subscription:
            # Update subscription status if needed
            db.commit()
            logger.info(f"Subscription updated for customer {customer_id}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating subscription: {str(e)}")

async def handle_subscription_deletion(db: Session, subscription: dict):
    """Handle subscription deletion event"""
    try:
        customer_id = subscription.get('customer')
        if not customer_id:
            return

        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_customer_id == customer_id
        ).first()

        if db_subscription:
            db.delete(db_subscription)
            db.commit()
            logger.info(f"Subscription deleted for customer {customer_id}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting subscription: {str(e)}")

@router.get("/verify-session/{session_id}")
async def verify_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Verify Stripe session status"""
    try:
        # Retrieve session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)
        
        if session.payment_status != 'paid':
            return {"valid": False, "reason": "payment_incomplete"}

        # Verify subscription was created
        subscription = db.query(Subscription).filter(
            Subscription.stripe_customer_id == session.customer
        ).first()

        if not subscription:
            return {"valid": False, "reason": "subscription_not_found"}

        return {
            "valid": True,
            "customer_id": session.customer
        }

    except Exception as e:
        logger.error(f"Session verification error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Error verifying session"
        )
    

@router.get("/debug-session/{session_id}")
async def debug_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Debug endpoint for session verification"""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        return {
            "session_status": session.status,
            "payment_status": session.payment_status,
            "customer_email": session.customer_email,
            "customer_id": session.customer
        }
    except Exception as e:
        logger.error(f"Debug session error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    
@router.get("/debug-environment")
async def debug_environment():
    """Debug endpoint for checking environment settings"""
    from app.core.config import settings
    
    return {
        "environment": settings.ENVIRONMENT,
        "stripe_success_url": settings.STRIPE_SUCCESS_URL,
        "active_stripe_success_url": getattr(settings, 'active_stripe_success_url', None) or settings.STRIPE_SUCCESS_URL,
        "stripe_cancel_url": settings.STRIPE_CANCEL_URL,
        "frontend_url": settings.FRONTEND_URL,
        "active_server_host": getattr(settings, 'active_server_host', None) or settings.SERVER_HOST,
        "api_base_url": settings.API_V1_STR,
        "is_production": settings.ENVIRONMENT == "production",
    }