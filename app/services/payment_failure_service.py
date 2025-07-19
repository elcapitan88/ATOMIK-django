# app/services/payment_failure_service.py
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging

from app.models.subscription import Subscription, DunningStage
from app.models.user import User

logger = logging.getLogger(__name__)

class PaymentFailureService:
    """Service for handling payment failures and dunning management"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def handle_payment_failure(
        self, 
        stripe_customer_id: str, 
        failure_reason: str = None,
        invoice_data: Dict[str, Any] = None,
        test_mode: bool = False
    ) -> bool:
        """
        Handle payment failure for a customer
        
        Args:
            stripe_customer_id: Stripe customer ID
            failure_reason: Reason for payment failure
            invoice_data: Additional invoice data from Stripe
        
        Returns:
            bool: True if handled successfully
        """
        try:
            # Find subscription by customer ID
            subscription = self.db.query(Subscription).filter(
                Subscription.stripe_customer_id == stripe_customer_id
            ).first()
            
            if not subscription:
                logger.warning(f"No subscription found for customer {stripe_customer_id}")
                return False
            
            # Skip processing for lifetime subscriptions (unless in test mode)
            if subscription.is_lifetime and not test_mode:
                logger.info(f"Skipping payment failure for lifetime subscription: {stripe_customer_id}")
                return True
            
            if subscription.is_lifetime and test_mode:
                logger.info(f"Processing payment failure for lifetime subscription in test mode: {stripe_customer_id}")
            
            # Check if this is first payment failure or subsequent
            if subscription.dunning_stage == 'none':
                # First payment failure - start grace period
                self._start_grace_period(subscription, failure_reason)
                logger.info(f"Started grace period for subscription {subscription.id}")
            else:
                # Subsequent failure - advance dunning stage
                self._advance_dunning_stage(subscription, failure_reason)
                logger.info(f"Advanced dunning stage for subscription {subscription.id} to {subscription.dunning_stage}")
            
            # Update failure reason if provided
            if failure_reason:
                subscription.last_payment_failure_reason = failure_reason
            
            subscription.updated_at = datetime.utcnow()
            self.db.commit()
            
            # Trigger appropriate notifications based on dunning stage
            self._trigger_notification(subscription)
            
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error handling payment failure for {stripe_customer_id}: {str(e)}")
            return False
    
    def handle_payment_success(self, stripe_customer_id: str) -> bool:
        """
        Handle successful payment - reset payment failure state
        
        Args:
            stripe_customer_id: Stripe customer ID
        
        Returns:
            bool: True if handled successfully
        """
        try:
            subscription = self.db.query(Subscription).filter(
                Subscription.stripe_customer_id == stripe_customer_id
            ).first()
            
            if not subscription:
                logger.warning(f"No subscription found for customer {stripe_customer_id}")
                return False
            
            # Reset payment failure state if there were issues
            if subscription.has_payment_issues:
                old_stage = subscription.dunning_stage
                subscription.resolve_payment_failure()
                subscription.updated_at = datetime.utcnow()
                self.db.commit()
                
                logger.info(f"Payment resolved for subscription {subscription.id}, was in stage: {old_stage}")
                
                # Send recovery confirmation email
                self._trigger_recovery_notification(subscription)
            
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error handling payment success for {stripe_customer_id}: {str(e)}")
            return False
    
    def process_dunning_advancement(self) -> int:
        """
        Process all subscriptions that need dunning stage advancement
        This should be run daily as a background task
        
        Returns:
            int: Number of subscriptions processed
        """
        processed = 0
        
        try:
            # Find subscriptions in grace period that need stage advancement
            now = datetime.utcnow()
            
            # Get subscriptions that need advancement based on time thresholds
            subscriptions = self.db.query(Subscription).filter(
                Subscription.dunning_stage.in_(['warning', 'urgent', 'final']),
                Subscription.grace_period_ends_at.isnot(None)
            ).all()
            
            for subscription in subscriptions:
                days_in_grace = (now - subscription.payment_failed_at).days
                
                # Advance stages based on days in grace period
                advancement_needed = False
                
                if subscription.dunning_stage == 'warning' and days_in_grace >= 3:
                    advancement_needed = True
                elif subscription.dunning_stage == 'urgent' and days_in_grace >= 6:
                    advancement_needed = True
                elif subscription.dunning_stage == 'final' and days_in_grace >= 7:
                    advancement_needed = True
                
                if advancement_needed:
                    self._advance_dunning_stage(subscription)
                    self._trigger_notification(subscription)
                    processed += 1
            
            if processed > 0:
                self.db.commit()
                logger.info(f"Processed {processed} subscriptions for dunning advancement")
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error processing dunning advancement: {str(e)}")
        
        return processed
    
    def get_payment_status(self, user_id: int) -> Dict[str, Any]:
        """
        Get payment status for a user
        
        Args:
            user_id: User ID
        
        Returns:
            Dict containing payment status information
        """
        subscription = self.db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).first()
        
        if not subscription:
            return {"has_subscription": False}
        
        return {
            "has_subscription": True,
            "status": subscription.status,
            "tier": subscription.tier,
            "is_lifetime": subscription.is_lifetime,
            "has_payment_issues": subscription.has_payment_issues,
            "dunning_stage": subscription.safe_dunning_stage.value,
            "is_in_grace_period": subscription.is_in_grace_period,
            "days_left_in_grace_period": subscription.days_left_in_grace_period,
            "payment_failed_at": subscription.payment_failed_at.isoformat() if subscription.payment_failed_at else None,
            "grace_period_ends_at": subscription.grace_period_ends_at.isoformat() if subscription.grace_period_ends_at else None
        }
    
    def _start_grace_period(self, subscription: Subscription, failure_reason: str = None):
        """Start grace period for subscription"""
        subscription.start_grace_period(grace_days=7)
        if failure_reason:
            subscription.last_payment_failure_reason = failure_reason
    
    def _advance_dunning_stage(self, subscription: Subscription, failure_reason: str = None):
        """Advance dunning stage for subscription"""
        subscription.advance_dunning_stage()
        if failure_reason:
            subscription.last_payment_failure_reason = failure_reason
    
    def _trigger_notification(self, subscription: Subscription):
        """Trigger appropriate notification based on dunning stage"""
        try:
            from app.services.email.email_notification import PaymentEmailService
            import asyncio
            
            user = subscription.user
            if not user or not user.email:
                logger.warning(f"No user email found for subscription {subscription.id}")
                return
            
            # Create billing portal URL for payment update
            billing_portal_url = f"{settings.active_frontend_url}/billing"
            
            # Send appropriate email based on dunning stage
            if subscription.dunning_stage == 'warning':
                # First payment failure - start of grace period
                asyncio.create_task(
                    PaymentEmailService.send_payment_failure_email(
                        user_email=user.email,
                        user_name=getattr(user, 'full_name', None) or user.username,
                        failure_reason=subscription.last_payment_failure_reason,
                        days_in_grace=subscription.days_left_in_grace_period,
                        billing_portal_url=billing_portal_url
                    )
                )
            elif subscription.dunning_stage == 'urgent':
                # Reminder at 3 days
                asyncio.create_task(
                    PaymentEmailService.send_grace_period_reminder(
                        user_email=user.email,
                        user_name=getattr(user, 'full_name', None) or user.username,
                        days_remaining=subscription.days_left_in_grace_period,
                        billing_portal_url=billing_portal_url
                    )
                )
            elif subscription.dunning_stage == 'final':
                # Final notice before suspension
                asyncio.create_task(
                    PaymentEmailService.send_final_notice(
                        user_email=user.email,
                        user_name=getattr(user, 'full_name', None) or user.username,
                        billing_portal_url=billing_portal_url
                    )
                )
        except Exception as e:
            logger.error(f"Error sending payment notification: {str(e)}")
    
    def _trigger_recovery_notification(self, subscription: Subscription):
        """Trigger payment recovery notification"""
        try:
            from app.services.email.email_notification import PaymentEmailService
            import asyncio
            
            user = subscription.user
            if not user or not user.email:
                logger.warning(f"No user email found for subscription {subscription.id}")
                return
            
            # Send payment recovery confirmation
            asyncio.create_task(
                PaymentEmailService.send_payment_recovery_email(
                    user_email=user.email,
                    user_name=getattr(user, 'full_name', None) or user.username
                )
            )
        except Exception as e:
            logger.error(f"Error sending payment recovery notification: {str(e)}")