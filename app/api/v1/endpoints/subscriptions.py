from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Body
from sqlalchemy.orm import Session
import logging
from typing import Dict, Optional, Any, List
import stripe
from datetime import datetime
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

        # For lifetime subscriptions, bypass Stripe verification
        if subscription.is_lifetime and subscription.status == "active":
            logger.info(f"Verified active lifetime subscription for user {current_user.email}")
            return {
                "has_access": True,
                "customer_id": subscription.stripe_customer_id,
                "tier": subscription.tier,
                "is_lifetime": True
            }

        # Verify with Stripe for regular subscriptions
        has_active_subscription = await stripe_service.verify_subscription_status(
            subscription.stripe_customer_id
        )

        return {
            "has_access": has_active_subscription,
            "customer_id": subscription.stripe_customer_id,
            "tier": subscription.tier,
            "is_lifetime": False
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

@router.post("/create-checkout", response_model=Dict[str, str])
async def create_checkout_session(
    request: Request,
    checkout_data: Dict[str, str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a Stripe checkout session for a specific subscription tier and interval"""
    try:
        # Extract tier and interval from request
        tier = checkout_data.get('plan', '').lower()
        interval = checkout_data.get('interval', '').lower()
        
        logger.info(f"Creating checkout for tier: {tier}, interval: {interval}, user: {current_user.email}")
        
        # Validate tier and interval
        if tier not in ['starter', 'pro', 'elite']:
            raise HTTPException(
                status_code=400,
                detail="Invalid subscription tier"
            )
            
        if interval not in ['monthly', 'yearly', 'lifetime']:
            raise HTTPException(
                status_code=400,
                detail="Invalid billing interval"
            )
            
        # Starter plan is free, redirect to dashboard (user is already registered)
        if tier == 'starter':
            return {
                "url": f"{settings.active_frontend_url}/dashboard"
            }
        
        # Get or create Stripe customer
        customer_id = await stripe_service.get_or_create_customer(current_user, db)
        
        # Get price ID for the selected tier and interval
        price_id = get_price_id(tier, interval)
        
        if not price_id:
            logger.error(f"No price ID found for {tier} plan with {interval} billing")
            raise HTTPException(
                status_code=400,
                detail=f"No price found for {tier} plan with {interval} billing"
            )
        
        # Determine checkout mode based on interval
        mode = 'subscription' if interval != 'lifetime' else 'payment'
        
        # Define the success and cancel URLs based on environment
        if settings.ENVIRONMENT == 'development':
            success_url = f"http://localhost:3000/payment/success?session_id={{CHECKOUT_SESSION_ID}}&email={current_user.email}"
            cancel_url = "http://localhost:3000/pricing"
        else:
            success_url = f"{settings.PROD_FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}&email={current_user.email}"
            cancel_url = f"{settings.PROD_FRONTEND_URL}/pricing"
        
        # Log URL for debugging
        logger.info(f"Using success URL: {success_url}")
        
        # Create checkout session with the correct price
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[
                {
                    'price': price_id,
                    'quantity': 1,
                },
            ],
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                'tier': tier,
                'interval': interval,
                'user_id': str(current_user.id),
                'username': current_user.username,
                'email': current_user.email,
                'is_lifetime': str(interval == 'lifetime')
            }
        )
        
        logger.info(f"Created checkout session: {session.id} for {tier}/{interval}")
        return {"url": session.url}
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error during checkout creation: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Stripe error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create checkout session"
        )
    
@router.post("/create-guest-checkout", response_model=Dict[str, str])
async def create_guest_checkout_session(
    request: Request,
    checkout_data: Dict[str, str],
    db: Session = Depends(get_db)
):
    """Create a Stripe checkout session for a guest user"""
    try:
        # Extract tier and interval
        tier = checkout_data.get('plan', '').lower()
        interval = checkout_data.get('interval', '').lower()
        email = checkout_data.get('email')
        username = checkout_data.get('username')
        
        logger.info(f"Creating guest checkout for tier: {tier}, interval: {interval}, email: {email}")
        
        if not email or tier not in ['pro', 'elite'] or interval not in ['monthly', 'yearly', 'lifetime']:
            raise HTTPException(
                status_code=400,
                detail="Invalid checkout parameters"
            )
            
        # Get price ID for the selected tier and interval
        price_id = get_price_id(tier, interval)
        
        if not price_id:
            logger.error(f"No price ID found for {tier} plan with {interval} billing")
            raise HTTPException(
                status_code=400,
                detail=f"No price found for {tier} plan with {interval} billing"
            )
        
        # Determine checkout mode based on interval
        mode = 'subscription' if interval != 'lifetime' else 'payment'
        
        # Define the success_url and cancel_url here before using them
        success_url = f"http://localhost:3000/payment/success?session_id={{CHECKOUT_SESSION_ID}}&email={email}"
        cancel_url = "http://localhost:3000/pricing"
        
        # Log the success URL for debugging
        logger.info(f"Using success URL: {success_url}")
        
        # Create checkout session without requiring customer ID
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=email,  # Pre-fill customer email
            line_items=[
                {
                    'price': price_id,
                    'quantity': 1,
                },
            ],
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                'tier': tier,
                'interval': interval,
                'username': username,
                'email': email,
                'is_guest_checkout': 'true',
                'is_lifetime': str(interval == 'lifetime')
            }
        )
        
        logger.info(f"Created guest checkout session: {session.id} for {email}")
        return {"url": session.url}
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error during checkout creation: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Stripe error: {str(e)}"
        )
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create checkout session"
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

        # Log event for debugging
        logger.info(f"Processing webhook event: {event.type}")
        
        # Process different event types
        event_type = event.type
        event_data = event.data.object

        # Handle checkout session completion
        if event_type == "checkout.session.completed":
            session = event_data
            
            # Extract metadata - do not use defaults
            metadata = session.get('metadata', {}) or {}
            
            # Get email from session
            email = metadata.get('email') or session.get('customer_email')
            
            # Extract tier from metadata - no defaults
            tier = metadata.get('tier')
            
            # If no tier is specified in metadata, log an error
            if not tier:
                logger.error(f"No plan tier specified in checkout session metadata. Session ID: {session.id}")
                return {"status": "error", "message": "No plan tier specified in checkout session metadata"}
            
            # Extract other metadata fields
            interval = metadata.get('interval')
            is_lifetime = metadata.get('is_lifetime') == 'True'
            
            # Get Stripe IDs
            customer_id = session.get('customer')
            subscription_id = session.get('subscription')
            
            logger.info(f"Checkout completed for {tier} plan (interval: {interval}). Email: {email}, Customer ID: {customer_id}, Sub ID: {subscription_id}")
            
            # If no customer ID, log an error
            if not customer_id:
                logger.error(f"No customer ID in checkout session. Session ID: {session.id}")
            
            # Find user by email
            if email:
                # Try to find the user by email
                user = db.query(User).filter(User.email == email).first()
                
                if user:
                    # Update or create subscription
                    subscription = db.query(Subscription).filter(
                        Subscription.user_id == user.id
                    ).first()
                    
                    if not subscription:
                        # Create new subscription with exact tier from payment
                        subscription = Subscription(
                            user_id=user.id,
                            tier=tier,  # Use exact tier from metadata
                            status="active",
                            stripe_customer_id=customer_id,
                            stripe_subscription_id=subscription_id,
                            is_lifetime=is_lifetime,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        db.add(subscription)
                        logger.info(f"Created new subscription for user {email} with tier {tier}")
                    else:
                        # Update existing subscription with exact tier from payment
                        subscription.tier = tier  # Use exact tier from metadata
                        subscription.status = "active"
                        subscription.is_lifetime = is_lifetime
                        
                        # Set Stripe IDs if available
                        if customer_id:
                            subscription.stripe_customer_id = customer_id
                        
                        if subscription_id:
                            subscription.stripe_subscription_id = subscription_id
                        
                        subscription.updated_at = datetime.utcnow()
                        logger.info(f"Updated subscription for user {email} to tier {tier}")
                    
                    try:
                        db.commit()
                        logger.info(f"Successfully committed subscription update for {email} with tier {tier}")
                    except Exception as commit_error:
                        db.rollback()
                        logger.error(f"Error committing subscription update: {str(commit_error)}")
                else:
                    logger.warning(f"No user found for email {email} - Will rely on frontend registration")
            else:
                logger.error("No email found in checkout session - Cannot update user subscription")
        
        # NEW: Handle subscription created event
        elif event_type == "customer.subscription.created":
            subscription = event_data
            customer_id = subscription.get('customer')
            subscription_id = subscription.get('id')
            
            if not customer_id or not subscription_id:
                logger.error(f"Missing customer_id or subscription_id in subscription created event")
                return {"status": "error", "message": "Invalid subscription data"}
                
            logger.info(f"New subscription created: {subscription_id} for customer {customer_id}")
            
            # Find subscription by customer ID and update subscription ID
            db_subscription = db.query(Subscription).filter(
                Subscription.stripe_customer_id == customer_id
            ).first()
            
            if db_subscription:
                # Update subscription ID
                db_subscription.stripe_subscription_id = subscription_id
                db_subscription.updated_at = datetime.utcnow()
                
                try:
                    db.commit()
                    logger.info(f"Updated subscription {db_subscription.id} with subscription ID {subscription_id}")
                except Exception as commit_error:
                    db.rollback()
                    logger.error(f"Error updating subscription with new ID: {str(commit_error)}")
            else:
                logger.warning(f"No subscription found for customer {customer_id}")
        
        # Handle subscription updates
        elif event_type == "customer.subscription.updated":
            background_tasks.add_task(
                handle_subscription_update,
                db=db,
                subscription=event_data
            )
        
        # Handle subscription cancellations
        elif event_type == "customer.subscription.deleted":
            background_tasks.add_task(
                handle_subscription_deletion,
                db=db,
                subscription=event_data
            )

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return {"status": "error", "message": str(e)}

# Update subscription handler for better handling of subscription IDs
async def handle_subscription_update(db: Session, subscription: dict):
    """Handle subscription update event"""
    try:
        customer_id = subscription.get('customer')
        subscription_id = subscription.get('id')
        status = subscription.get('status')
        
        if not customer_id:
            return

        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_customer_id == customer_id
        ).first()

        if db_subscription:
            # Always update subscription_id if available
            if subscription_id and not db_subscription.stripe_subscription_id:
                logger.info(f"Adding missing subscription ID {subscription_id} to customer {customer_id}")
                db_subscription.stripe_subscription_id = subscription_id
            
            # Update subscription status
            db_subscription.status = status
            db_subscription.updated_at = datetime.utcnow()
            
            # If canceled, mark accordingly but don't delete
            if status == 'canceled':
                logger.info(f"Subscription {subscription_id} canceled for customer {customer_id}")
            
            db.commit()
            logger.info(f"Subscription updated for customer {customer_id}: status={status}")
        else:
            logger.warning(f"No subscription record found for customer {customer_id}")

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

        if db_subscription and not db_subscription.is_lifetime:
            # For regular subscriptions, update status to canceled
            db_subscription.status = "canceled"
            db.commit()
            logger.info(f"Subscription status updated to canceled for customer {customer_id}")
        elif db_subscription and db_subscription.is_lifetime:
            # For lifetime subscriptions, don't change status on deletion events
            logger.info(f"Ignoring deletion event for lifetime subscription of customer {customer_id}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error handling subscription deletion: {str(e)}")

@router.get("/config", response_model=SubscriptionConfig)
async def get_subscription_config():
    """Get subscription configuration"""
    return {
        "publishable_key": settings.STRIPE_PUBLIC_KEY,
        "checks_disabled": settings.SKIP_SUBSCRIPTION_CHECK,
        "environment": settings.ENVIRONMENT
    }

@router.get("/verify-session/{session_id}")
async def verify_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Verify Stripe session status with improved subscription ID handling"""
    try:
        # Retrieve session from Stripe
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=['subscription']  # IMPORTANT: Expand the subscription object
        )
        
        # Get customer email from session
        customer_email = session.customer_email
        customer_id = session.customer
        
        # Check for completed payment
        if session.mode == 'payment':
            if session.payment_status != 'paid':
                return {"valid": False, "reason": "payment_incomplete"}
        elif session.mode == 'subscription':
            if not session.subscription:
                return {"valid": False, "reason": "subscription_not_created"}
        
        # Check for customer
        if not customer_id and not customer_email:
            return {"valid": False, "reason": "customer_not_found"}

        # Look for user account
        user = None
        if customer_email:
            user = db.query(User).filter(User.email == customer_email).first()
        
        # Look for subscription
        subscription = None
        if customer_id:
            subscription = db.query(Subscription).filter(
                Subscription.stripe_customer_id == customer_id
            ).first()
            if subscription and subscription.user_id:
                user = db.query(User).filter(User.id == subscription.user_id).first()
        
        # Get subscription ID if available
        subscription_id = None
        if session.subscription:
            # Try to get from expanded subscription object
            subscription_id = session.subscription.id if hasattr(session.subscription, 'id') else session.subscription
            
            # Log the subscription ID for debugging
            logger.info(f"Found subscription ID in session: {subscription_id}")
        
        # Return all relevant information
        return {
            "valid": True,
            "user_exists": user is not None,
            "subscription_exists": subscription is not None,
            "customer_id": customer_id,
            "customer_email": customer_email,
            "subscription_id": subscription_id,
            "mode": session.mode,
            "metadata": session.metadata  # Include metadata for account creation
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
            "customer_id": session.customer,
            "mode": session.mode,
            "metadata": session.metadata
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

@router.get("/price-tiers")
async def get_price_tiers():
    """Get information about available subscription tiers"""
    return {
        "tiers": [
            {
                "id": "starter",
                "name": "Starter",
                "description": "Perfect for beginners exploring algorithmic trading",
                "prices": {"monthly": 0, "yearly": 0, "lifetime": 0},
                "features": [
                    "1 connected trading account",
                    "Up to 3 active webhooks",
                    "Basic webhook integrations",
                    "Manual trade execution",
                    "Community support"
                ]
            },
            {
                "id": "pro",
                "name": "Pro",
                "description": "For serious traders seeking automation and reliability",
                "prices": {"monthly": 49, "yearly": 468, "lifetime": 990},
                "features": [
                    "Up to 5 connected trading accounts",
                    "Unlimited active webhooks",
                    "Advanced webhook configurations",
                    "Automated trade execution",
                    "Email & chat support",
                    "Advanced position management"
                ]
            },
            {
                "id": "elite",
                "name": "Elite",
                "description": "For professional traders and institutions",
                "prices": {"monthly": 89, "yearly": 828, "lifetime": 1990},
                "features": [
                    "Unlimited connected accounts",
                    "Enterprise-grade webhooks",
                    "Advanced trade execution rules",
                    "Priority email & chat support",
                    "Early access to new features",
                    "Custom strategy development"
                ]
            }
        ]
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

@router.post("/create-starter", response_model=Dict[str, Any])
async def create_starter_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a free Starter subscription for an authenticated user"""
    try:
        logger.info(f"Creating starter subscription for user {current_user.email}")
        
        # Check if user already has a subscription
        subscription = db.query(Subscription).filter(
            Subscription.user_id == current_user.id
        ).first()
        
        if subscription:
            # Update existing subscription to starter tier
            subscription.tier = "starter"
            subscription.status = "active"
            db.commit()
            logger.info(f"Updated existing subscription to starter tier for {current_user.email}")
        else:
            # Create new starter subscription
            subscription = Subscription(
                user_id=current_user.id,
                tier="starter",
                status="active",
                is_lifetime=False
            )
            db.add(subscription)
            db.commit()
            logger.info(f"Created new starter subscription for {current_user.email}")
        
        return {
            "success": True,
            "message": "Starter subscription created successfully",
            "tier": "starter"
        }
        
    except Exception as e:
        logger.error(f"Error creating starter subscription: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create starter subscription: {str(e)}"
        )

async def handle_successful_subscription(db: Session, session: dict):
    """Process successful subscription payment"""
    try:
        # Extract metadata
        metadata = session.get('metadata', {})
        user_id = metadata.get('user_id')
        
        if not user_id:
            logger.error("No user ID in session metadata")
            return
            
        # Find user by ID
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"No user found for ID: {user_id}")
            return
            
        # Update user's subscription
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user.id
        ).first()
        
        # Update or create subscription
        if subscription:
            subscription.tier = metadata.get('tier', 'pro')
            subscription.status = "active"
            subscription.stripe_customer_id = session.get('customer')
            subscription.stripe_subscription_id = session.get('subscription')
            subscription.is_lifetime = metadata.get('is_lifetime') == 'True'
        else:
            subscription = Subscription(
                user_id=user.id,
                tier=metadata.get('tier', 'pro'),
                status="active",
                stripe_customer_id=session.get('customer'),
                stripe_subscription_id=session.get('subscription'),
                is_lifetime=metadata.get('is_lifetime') == 'True'
            )
            db.add(subscription)
            
        db.commit()
        logger.info(f"Subscription updated for user {user.email}")
            
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing subscription: {str(e)}")

async def handle_successful_lifetime_purchase(db: Session, session: dict):
    """Process successful one-time payment for lifetime subscription"""
    try:
        # Extract customer information
        customer_id = session.get('customer')
        customer_email = session.get('customer_email')
        metadata = session.get('metadata', {})
        
        tier = metadata.get('tier', 'elite')  # Default to elite if not specified
        
        logger.info(f"Processing lifetime purchase for customer: {customer_id}, tier: {tier}")

        if not customer_id:
            logger.error("No customer ID in checkout session")
            return

        # Find user by customer ID in subscription records
        subscription = db.query(Subscription).filter(
            Subscription.stripe_customer_id == customer_id
        ).first()
        
        user = None
        if subscription:
            user = subscription.user
        
        # If no existing subscription, try to find user by email
        if not user and customer_email:
            user = db.query(User).filter(User.email == customer_email).first()
            
        if not user:
            logger.error(f"No user found for customer: {customer_id} or email: {customer_email}")
            return

        # Create or update subscription record with lifetime flag
        if not subscription:
            subscription = Subscription(
                user_id=user.id,
                stripe_customer_id=customer_id,
                tier=tier,
                is_lifetime=True,
                status="active"
            )
            db.add(subscription)
            logger.info(f"Created new lifetime subscription for user {user.email}")
        else:
            subscription.tier = tier
            subscription.is_lifetime = True
            subscription.status = "active"
            logger.info(f"Updated to lifetime subscription for user {user.email}")

        db.commit()
        logger.info(f"Lifetime subscription successfully processed for user {user.email}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error processing lifetime purchase: {str(e)}")

async def handle_subscription_update(db: Session, subscription: dict):
    """Handle subscription update event"""
    try:
        customer_id = subscription.get('customer')
        subscription_id = subscription.get('id')
        status = subscription.get('status')
        
        if not customer_id:
            return

        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_customer_id == customer_id
        ).first()

        if db_subscription:
            # Update subscription status
            db_subscription.status = status
            db_subscription.stripe_subscription_id = subscription_id
            
            # If canceled, mark accordingly but don't delete
            if status == 'canceled':
                logger.info(f"Subscription {subscription_id} canceled for customer {customer_id}")
            
            db.commit()
            logger.info(f"Subscription updated for customer {customer_id}: status={status}")

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

        if db_subscription and not db_subscription.is_lifetime:
            # For regular subscriptions, update status to canceled
            db_subscription.status = "canceled"
            db.commit()
            logger.info(f"Subscription status updated to canceled for customer {customer_id}")
        elif db_subscription and db_subscription.is_lifetime:
            # For lifetime subscriptions, don't change status on deletion events
            logger.info(f"Ignoring deletion event for lifetime subscription of customer {customer_id}")

    except Exception as e:
        db.rollback()
        logger.error(f"Error handling subscription deletion: {str(e)}")

def get_price_id(tier: str, interval: str) -> str:
    """Get the Stripe Price ID for a specific tier and interval"""
    price_mapping = {
        # Pro tier
        ('pro', 'monthly'): settings.STRIPE_PRICE_PRO_MONTHLY,
        ('pro', 'yearly'): settings.STRIPE_PRICE_PRO_YEARLY,
        ('pro', 'lifetime'): settings.STRIPE_PRICE_PRO_LIFETIME,
        
        # Elite tier
        ('elite', 'monthly'): settings.STRIPE_PRICE_ELITE_MONTHLY,
        ('elite', 'yearly'): settings.STRIPE_PRICE_ELITE_YEARLY,
        ('elite', 'lifetime'): settings.STRIPE_PRICE_ELITE_LIFETIME,
    }
    
    return price_mapping.get((tier, interval))

@router.post("/admin/sync-resource-counts")
async def sync_resource_counts(
    admin_key: str = Body(...),
    db: Session = Depends(get_db)
):
    """
    Admin endpoint to synchronize resource counts with actual data
    Requires an admin key for authentication
    """
    # Simple admin key check - in production, use proper admin auth
    if admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    try:
        # Get all subscriptions
        subscriptions = db.query(Subscription).all()
        updated_count = 0
        
        for subscription in subscriptions:
            # Skip if no user associated
            if not subscription.user_id:
                continue
                
            # Count connected accounts
            connected_accounts = db.query(BrokerAccount).filter(
                BrokerAccount.user_id == subscription.user_id,
                BrokerAccount.is_active == True,
                BrokerAccount.is_deleted == False
            ).count()
            
            # Count active webhooks
            active_webhooks = db.query(Webhook).filter(
                Webhook.user_id == subscription.user_id,
                Webhook.is_active == True
            ).count()
            
            # Count active strategies
            active_strategies = db.query(ActivatedStrategy).filter(
                ActivatedStrategy.user_id == subscription.user_id,
                ActivatedStrategy.is_active == True
            ).count()
            
            # Update subscription with actual counts
            subscription.connected_accounts_count = connected_accounts
            subscription.active_webhooks_count = active_webhooks
            subscription.active_strategies_count = active_strategies
            
            updated_count += 1
        
        # Commit all changes
        db.commit()
        
        return {
            "status": "success",
            "message": f"Synchronized resource counts for {updated_count} subscriptions"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error synchronizing resource counts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to synchronize resource counts: {str(e)}"
        )