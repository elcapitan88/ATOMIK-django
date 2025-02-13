# app/services/stripe_service.py
import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import logging
from datetime import datetime

from ..models.subscription import Subscription
from ..models.user import User
from ..core.config import settings

logger = logging.getLogger(__name__)

class StripeService:
    def __init__(self):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        self.logger = logging.getLogger(__name__)

    async def verify_subscription_status(self, customer_id: str) -> bool:
        """
        Verify if customer has an active subscription
        
        Args:
            customer_id: Stripe customer ID
            
        Returns:
            bool: True if subscription is active, False otherwise
        """
        try:
            # Get all subscriptions for customer
            subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status='active',
                limit=1
            )

            # Check for active subscription
            if not subscriptions.data:
                logger.warning(f"No active subscriptions found for customer {customer_id}")
                return False

            subscription = subscriptions.data[0]

            # Additional verification checks
            if subscription.status != 'active':
                logger.warning(f"Subscription {subscription.id} is not active for customer {customer_id}")
                return False

            # Check if subscription is past due
            if subscription.latest_invoice:
                invoice = stripe.Invoice.retrieve(subscription.latest_invoice)
                if invoice.status == 'past_due':
                    logger.warning(f"Subscription {subscription.id} is past due for customer {customer_id}")
                    return False

            logger.info(f"Verified active subscription for customer {customer_id}")
            return True

        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error during subscription verification: {str(e)}")
            # In case of Stripe API errors, we should err on the side of caution
            return False
        except Exception as e:
            logger.error(f"Unexpected error during subscription verification: {str(e)}")
            return False

    async def get_or_create_customer(self, user: User, db: Session) -> str:
        """
        Get existing Stripe customer or create new one.
        
        Args:
            user: User model instance
            db: Database session
            
        Returns:
            str: Stripe customer ID
        """
        try:
            # First check if user has a customer_id
            if user.subscription and user.subscription.stripe_customer_id:
                # Verify the customer still exists in Stripe
                try:
                    stripe.Customer.retrieve(user.subscription.stripe_customer_id)
                    return user.subscription.stripe_customer_id
                except stripe.error.InvalidRequestError:
                    # Customer doesn't exist in Stripe, will create new one
                    pass

            # Search for existing customer in Stripe by email
            customers = stripe.Customer.list(email=user.email, limit=1)
            if customers.data:
                customer_id = customers.data[0].id
                # Update our record with found customer_id
                await self._update_customer_record(user, customer_id, db)
                return customer_id

            # Create new customer if none exists
            customer = stripe.Customer.create(
                email=user.email,
                metadata={
                    'user_id': str(user.id),
                    'username': user.username
                }
            )
            await self._update_customer_record(user, customer.id, db)
            return customer.id

        except stripe.error.StripeError as e:
            self.logger.error(f"Stripe API error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Stripe error: {str(e)}"
            )
        except Exception as e:
            self.logger.error(f"Error in customer management: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Internal server error during customer management"
            )

    async def create_portal_session(self, customer_id: str) -> str:
        """
        Create a Stripe Customer Portal session.
        
        Args:
            customer_id: Stripe customer ID
            
        Returns:
            str: Portal session URL
        """
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=f"{settings.FRONTEND_URL}/dashboard"
            )
            return session.url
        except stripe.error.StripeError as e:
            self.logger.error(f"Error creating portal session: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail="Error creating billing portal session"
            )

    async def verify_webhook_signature(self, payload: bytes, sig_header: str) -> dict:
        """
        Verify Stripe webhook signature.
        
        Args:
            payload: Raw webhook payload
            sig_header: Stripe signature header
            
        Returns:
            dict: Verified Stripe event
        """
        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET
            )
            return event
        except stripe.error.SignatureVerificationError as e:
            self.logger.error(f"Invalid webhook signature: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail="Invalid webhook signature"
            )
        except Exception as e:
            self.logger.error(f"Webhook verification error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail="Invalid webhook data"
            )

    async def handle_subscription_webhook(self, event_type: str, data: dict, db: Session) -> None:
        """
        Handle subscription-related webhooks from Stripe.
        We only use webhooks to update customer metadata and handle customer deletion.
        
        Args:
            event_type: Type of Stripe event
            data: Event data
            db: Database session
        """
        try:
            if event_type == "customer.deleted":
                # Remove customer_id from our database if customer is deleted in Stripe
                customer_id = data['id']
                subscription = db.query(Subscription).filter(
                    Subscription.stripe_customer_id == customer_id
                ).first()
                if subscription:
                    db.delete(subscription)
                    db.commit()
                    self.logger.info(f"Removed deleted customer {customer_id} from database")

            elif event_type == "customer.updated":
                # Update customer metadata if needed
                customer_id = data['id']
                subscription = db.query(Subscription).filter(
                    Subscription.stripe_customer_id == customer_id
                ).first()
                if subscription and subscription.user:
                    # Ensure Stripe has current user metadata
                    stripe.Customer.modify(
                        customer_id,
                        metadata={
                            'user_id': str(subscription.user.id),
                            'username': subscription.user.username,
                            'email': subscription.user.email
                        }
                    )

        except Exception as e:
            self.logger.error(f"Error handling webhook {event_type}: {str(e)}")
            db.rollback()
            raise

    async def _update_customer_record(self, user: User, customer_id: str, db: Session) -> None:
        """
        Update or create subscription record with customer ID.
        
        Args:
            user: User model instance
            customer_id: Stripe customer ID
            db: Database session
        """
        try:
            if not user.subscription:
                subscription = Subscription(
                    user_id=user.id,
                    stripe_customer_id=customer_id
                )
                db.add(subscription)
            else:
                user.subscription.stripe_customer_id = customer_id
            db.commit()
        except Exception as e:
            db.rollback()
            self.logger.error(f"Error updating customer record: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error updating customer record"
            )

    async def get_product_prices(self) -> list:
        """
        Get list of available product prices.
        
        Returns:
            list: List of Stripe price objects
        """
        try:
            prices = stripe.Price.list(
                active=True,
                expand=['data.product']
            )
            return prices.data
        except stripe.error.StripeError as e:
            self.logger.error(f"Error fetching prices: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail="Error fetching subscription prices"
            )