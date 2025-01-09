import stripe
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from fastapi import HTTPException
from typing import Optional, Dict, Any
import logging

from ..core.config import settings
from ..models.subscription import Subscription, SubscriptionTier, SubscriptionStatus, BillingInterval
from ..models.user import User

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

# Stripe Product/Price IDs mapping
STRIPE_PRODUCTS = {
    SubscriptionTier.STARTED: {
        BillingInterval.MONTHLY: "price_started_monthly",  # Replace with actual price IDs
        BillingInterval.YEARLY: "price_started_yearly",
    },
    SubscriptionTier.PLUS: {
        BillingInterval.MONTHLY: "price_plus_monthly",
        BillingInterval.YEARLY: "price_plus_yearly",
    },
    SubscriptionTier.PRO: {
        BillingInterval.MONTHLY: "price_pro_monthly",
        BillingInterval.YEARLY: "price_pro_yearly",
    },
    SubscriptionTier.LIFETIME: "price_lifetime",  # One-time payment price ID
}

class StripeService:
    @staticmethod
    async def create_customer(user: User, db: Session) -> str:
        """Create a Stripe customer for a user"""
        try:
            customer = stripe.Customer.create(
                email=user.email,
                metadata={"user_id": user.id}
            )
            return customer.id
        except stripe.error.StripeError as e:
            logger.error(f"Stripe customer creation failed: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to create Stripe customer: {str(e)}"
            )

    @staticmethod
    async def create_subscription(
        user: User,
        tier: SubscriptionTier,
        interval: BillingInterval,
        db: Session
    ) -> Subscription:
        """Create a new subscription for a user"""
        try:
            # Get or create Stripe customer
            if not user.subscription or not user.subscription.stripe_customer_id:
                customer_id = await StripeService.create_customer(user, db)
            else:
                customer_id = user.subscription.stripe_customer_id

            # Get price ID based on tier and interval
            if tier == SubscriptionTier.LIFETIME:
                raise HTTPException(
                    status_code=400,
                    detail="Lifetime subscriptions must be processed separately"
                )

            price_id = STRIPE_PRODUCTS[tier][interval]

            # Calculate trial end if applicable
            trial_end = None
            if tier in [SubscriptionTier.PLUS, SubscriptionTier.PRO]:
                trial_end = int((datetime.utcnow() + timedelta(days=14)).timestamp())

            # Create Stripe subscription
            stripe_subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                trial_end=trial_end,
                expand=["latest_invoice.payment_intent"]
            )

            # Create subscription record
            subscription = Subscription(
                user_id=user.id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=stripe_subscription.id,
                stripe_price_id=price_id,
                tier=tier,
                status=SubscriptionStatus.TRIALING if trial_end else SubscriptionStatus.ACTIVE,
                billing_interval=interval,
                trial_end=datetime.fromtimestamp(trial_end) if trial_end else None,
                current_period_start=datetime.fromtimestamp(stripe_subscription.current_period_start),
                current_period_end=datetime.fromtimestamp(stripe_subscription.current_period_end)
            )

            db.add(subscription)
            db.commit()
            db.refresh(subscription)

            return subscription

        except stripe.error.StripeError as e:
            logger.error(f"Stripe subscription creation failed: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to create subscription: {str(e)}"
            )

    @staticmethod
    async def process_lifetime_purchase(
        user: User,
        db: Session
    ) -> Dict[str, Any]:
        """Process a lifetime subscription purchase"""
        try:
            # Get or create Stripe customer
            if not user.subscription or not user.subscription.stripe_customer_id:
                customer_id = await StripeService.create_customer(user, db)
            else:
                customer_id = user.subscription.stripe_customer_id

            # Create payment intent
            payment_intent = stripe.PaymentIntent.create(
                amount=299000,  # $2,990.00
                currency="usd",
                customer=customer_id,
                metadata={
                    "user_id": user.id,
                    "type": "lifetime_subscription"
                }
            )

            return {
                "client_secret": payment_intent.client_secret,
                "payment_intent_id": payment_intent.id
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe lifetime purchase failed: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to process lifetime purchase: {str(e)}"
            )

    @staticmethod
    async def handle_subscription_updated(
        subscription_id: str,
        db: Session
    ) -> None:
        """Handle Stripe subscription update webhook"""
        try:
            stripe_subscription = stripe.Subscription.retrieve(subscription_id)
            subscription = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == subscription_id
            ).first()

            if not subscription:
                logger.error(f"Subscription not found: {subscription_id}")
                return

            # Update subscription status
            subscription.status = SubscriptionStatus(stripe_subscription.status)
            subscription.current_period_start = datetime.fromtimestamp(
                stripe_subscription.current_period_start
            )
            subscription.current_period_end = datetime.fromtimestamp(
                stripe_subscription.current_period_end
            )
            subscription.cancel_at_period_end = stripe_subscription.cancel_at_period_end

            if stripe_subscription.status == "canceled":
                subscription.canceled_at = datetime.utcnow()

            db.commit()

        except Exception as e:
            logger.error(f"Error handling subscription update: {str(e)}")
            raise

    @staticmethod
    async def handle_payment_success(
        payment_intent_id: str,
        db: Session
    ) -> None:
        """Handle successful payment webhook"""
        try:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            
            # Check if this is a lifetime subscription payment
            if payment_intent.metadata.get("type") == "lifetime_subscription":
                user_id = int(payment_intent.metadata.get("user_id"))
                await StripeService.activate_lifetime_subscription(
                    user_id,
                    payment_intent.customer,
                    db
                )

        except Exception as e:
            logger.error(f"Error handling payment success: {str(e)}")
            raise

    @staticmethod
    async def activate_lifetime_subscription(
        user_id: int,
        customer_id: str,
        db: Session
    ) -> None:
        """Activate a lifetime subscription after successful payment"""
        try:
            subscription = Subscription(
                user_id=user_id,
                stripe_customer_id=customer_id,
                tier=SubscriptionTier.LIFETIME,
                status=SubscriptionStatus.ACTIVE,
                billing_interval=BillingInterval.LIFETIME,
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.max  # Far future date
            )

            db.add(subscription)
            db.commit()

        except Exception as e:
            logger.error(f"Error activating lifetime subscription: {str(e)}")
            raise

    @staticmethod
    def get_subscription_features(tier: SubscriptionTier) -> Dict[str, Any]:
        """Get features for a subscription tier"""
        return {
            SubscriptionTier.STARTED: {
                "webhooks": 1,
                "strategies": 1,
                "broker_connections": 1,
                "multiple_accounts": False,
                "marketplace_access": False,
                "realtime_data": False,
                "trial_days": 0,
                "support_level": "basic",
                "analytics": "basic",
                "api_access": False
            },
            SubscriptionTier.PLUS: {
                "webhooks": 5,
                "strategies": -1,  # Unlimited
                "broker_connections": 5,
                "multiple_accounts": True,
                "marketplace_access": True,
                "realtime_data": True,
                "trial_days": 14,
                "support_level": "priority",
                "analytics": "basic",
                "api_access": False
            },
            SubscriptionTier.PRO: {
                "webhooks": -1,  # Unlimited
                "strategies": -1,
                "broker_connections": -1,
                "multiple_accounts": True,
                "marketplace_access": True,
                "realtime_data": True,
                "trial_days": 14,
                "support_level": "premium",
                "analytics": "advanced",
                "api_access": True
            },
            SubscriptionTier.LIFETIME: {
                "webhooks": -1,
                "strategies": -1,
                "broker_connections": -1,
                "multiple_accounts": True,
                "marketplace_access": True,
                "realtime_data": True,
                "trial_days": 0,
                "support_level": "vip",
                "analytics": "advanced",
                "api_access": True,
                "early_access": True
            }
        }.get(tier, {})