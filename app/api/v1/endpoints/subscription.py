from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
import stripe
import logging
from datetime import datetime

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.subscription import (
    Subscription,
    SubscriptionTier,
    SubscriptionStatus,
    BillingInterval
)
from app.services.stripe_service import StripeService
from app.core.config import settings
from app.schemas.subscription import (
    SubscriptionCreate,
    SubscriptionOut,
    LifetimePurchaseResponse,
    PlanFeatures
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

@router.get("/plans")
async def get_subscription_plans():
    """Get available subscription plans and their features"""
    plans = {
        "started": {
            "name": "Get Started",
            "description": "Perfect for getting started with automated trading",
            "prices": {
                "monthly": {
                    "amount": 29,
                    "interval": "month",
                    "id": settings.STRIPE_PRICE_STARTED_MONTHLY
                },
                "yearly": {
                    "amount": 290,
                    "interval": "year",
                    "id": settings.STRIPE_PRICE_STARTED_YEARLY
                }
            },
            "features": StripeService.get_subscription_features(SubscriptionTier.STARTED)
        },
        "plus": {
            "name": "Atomik+",
            "description": "Advanced features for serious traders",
            "prices": {
                "monthly": {
                    "amount": 79,
                    "interval": "month",
                    "id": settings.STRIPE_PRICE_PLUS_MONTHLY
                },
                "yearly": {
                    "amount": 790,
                    "interval": "year",
                    "id": settings.STRIPE_PRICE_PLUS_YEARLY
                }
            },
            "features": StripeService.get_subscription_features(SubscriptionTier.PLUS),
            "trial_days": 14
        },
        "pro": {
            "name": "Atomik Pro",
            "description": "Ultimate trading automation platform",
            "prices": {
                "monthly": {
                    "amount": 199,
                    "interval": "month",
                    "id": settings.STRIPE_PRICE_PRO_MONTHLY
                },
                "yearly": {
                    "amount": 1990,
                    "interval": "year",
                    "id": settings.STRIPE_PRICE_PRO_YEARLY
                }
            },
            "features": StripeService.get_subscription_features(SubscriptionTier.PRO),
            "trial_days": 14
        },
        "lifetime": {
            "name": "Lifetime Access",
            "description": "One-time payment for lifetime access",
            "price": {
                "amount": 2990,
                "id": settings.STRIPE_PRICE_LIFETIME
            },
            "features": StripeService.get_subscription_features(SubscriptionTier.LIFETIME)
        }
    }
    
    return {"plans": plans}

@router.get("/current", response_model=SubscriptionOut)
async def get_current_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's subscription details"""
    subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id
    ).first()
    
    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="No active subscription found"
        )
    
    return subscription

@router.post("/create", response_model=SubscriptionOut)
async def create_subscription(
    data: SubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new subscription"""
    try:
        # Check if user already has a subscription
        existing_sub = db.query(Subscription).filter(
            Subscription.user_id == current_user.id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIALING
            ])
        ).first()
        
        if existing_sub:
            raise HTTPException(
                status_code=400,
                detail="User already has an active subscription"
            )

        subscription = await StripeService.create_subscription(
            user=current_user,
            tier=data.tier,
            interval=data.billing_interval,
            db=db
        )
        
        return subscription

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

@router.post("/lifetime/purchase", response_model=LifetimePurchaseResponse)
async def purchase_lifetime(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Initiate lifetime subscription purchase"""
    try:
        # Check if user already has lifetime subscription
        existing_sub = db.query(Subscription).filter(
            Subscription.user_id == current_user.id,
            Subscription.tier == SubscriptionTier.LIFETIME
        ).first()
        
        if existing_sub:
            raise HTTPException(
                status_code=400,
                detail="User already has lifetime access"
            )

        payment_info = await StripeService.process_lifetime_purchase(
            user=current_user,
            db=db
        )
        
        return payment_info

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Handle Stripe webhooks"""
    try:
        # Get webhook payload
        payload = await request.body()
        sig_header = request.headers.get("Stripe-Signature")
        
        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")

        # Handle different event types
        if event.type == "customer.subscription.updated":
            background_tasks.add_task(
                StripeService.handle_subscription_updated,
                event.data.object.id,
                db
            )
        
        elif event.type == "payment_intent.succeeded":
            background_tasks.add_task(
                StripeService.handle_payment_success,
                event.data.object.id,
                db
            )

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@router.post("/cancel")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel current subscription"""
    try:
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIALING
            ])
        ).first()

        if not subscription:
            raise HTTPException(
                status_code=404,
                detail="No active subscription found"
            )

        if subscription.tier == SubscriptionTier.LIFETIME:
            raise HTTPException(
                status_code=400,
                detail="Cannot cancel lifetime subscription"
            )

        # Cancel at period end
        stripe.Subscription.modify(
            subscription.stripe_subscription_id,
            cancel_at_period_end=True
        )

        subscription.cancel_at_period_end = True
        db.commit()

        return {
            "status": "success",
            "message": "Subscription will be canceled at the end of the billing period",
            "end_date": subscription.current_period_end
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

@router.post("/update/{tier}")
async def update_subscription(
    tier: SubscriptionTier,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update subscription tier"""
    try:
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIALING
            ])
        ).first()

        if not subscription:
            raise HTTPException(
                status_code=404,
                detail="No active subscription found"
            )

        if subscription.tier == SubscriptionTier.LIFETIME:
            raise HTTPException(
                status_code=400,
                detail="Cannot update lifetime subscription"
            )

        # Get new price ID
        new_price_id = StripeService.STRIPE_PRODUCTS[tier][subscription.billing_interval]

        # Update subscription
        stripe_subscription = stripe.Subscription.modify(
            subscription.stripe_subscription_id,
            items=[{
                'id': stripe.Subscription.retrieve(subscription.stripe_subscription_id).items.data[0].id,
                'price': new_price_id,
            }],
            proration_behavior='always_invoice'
        )

        # Update database
        subscription.tier = tier
        subscription.stripe_price_id = new_price_id
        db.commit()

        return {
            "status": "success",
            "message": f"Subscription updated to {tier}",
            "effective_date": datetime.fromtimestamp(stripe_subscription.current_period_start)
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

@router.get("/invoices")
async def get_invoices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 10
):
    """Get user's invoice history"""
    try:
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()

        if not subscription:
            return {"invoices": []}

        invoices = stripe.Invoice.list(
            customer=subscription.stripe_customer_id,
            limit=limit
        )

        return {
            "invoices": [{
                "id": invoice.id,
                "amount_due": invoice.amount_due / 100,  # Convert to dollars
                "currency": invoice.currency,
                "status": invoice.status,
                "created": datetime.fromtimestamp(invoice.created),
                "invoice_pdf": invoice.invoice_pdf,
                "hosted_invoice_url": invoice.hosted_invoice_url
            } for invoice in invoices.data]
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )