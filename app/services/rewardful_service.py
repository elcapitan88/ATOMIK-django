# app/services/rewardful_service.py
import json
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException

from ..models.affiliate import Affiliate, AffiliateReferral, AffiliateClick
from ..models.user import User
from ..core.config import settings

logger = logging.getLogger(__name__)

class RewardfulService:
    """
    Rewardful service for handling affiliate program integration.
    Rewardful automatically handles Stripe integration via webhooks.
    """
    
    def __init__(self):
        self.api_secret = settings.REWARDFUL_API_SECRET
        self.api_key = settings.REWARDFUL_API_KEY
        self.base_url = "https://api.getrewardful.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_secret}",
            "Content-Type": "application/json"
        }
        self.logger = logging.getLogger(__name__)
    
    def generate_referral_link(self, referral_code: str) -> str:
        """
        Generate a referral link for an affiliate.
        
        Args:
            referral_code: Affiliate's referral code
            
        Returns:
            str: Complete referral URL
        """
        return f"https://www.atomiktrading.io?ref={referral_code}"
    
    async def create_affiliate_record(self, user: User, db: Session) -> Affiliate:
        """
        Create a new affiliate record for a user and register with Rewardful.
        
        Args:
            user: User model instance
            db: Database session
            
        Returns:
            Affiliate: Created affiliate record
        """
        try:
            # Check if user already has an affiliate record
            existing_affiliate = db.query(Affiliate).filter(
                Affiliate.user_id == user.id
            ).first()
            
            if existing_affiliate:
                if existing_affiliate.is_active:
                    return existing_affiliate
                else:
                    # Reactivate existing affiliate
                    existing_affiliate.is_active = True
                    existing_affiliate.updated_at = datetime.utcnow()
                    db.commit()
                    return existing_affiliate
            
            # Generate unique referral code
            referral_code = self._generate_unique_referral_code(user, db)
            
            # Create affiliate in Rewardful
            rewardful_affiliate_data = {
                "email": user.email,
                "first_name": user.full_name.split()[0] if user.full_name else user.username,
                "last_name": " ".join(user.full_name.split()[1:]) if user.full_name and len(user.full_name.split()) > 1 else "",
                "referral_code": referral_code
            }
            
            response = requests.post(
                f"{self.base_url}/affiliates",
                headers=self.headers,
                json=rewardful_affiliate_data
            )
            
            if response.status_code != 201:
                self.logger.error(f"Failed to create Rewardful affiliate: {response.text}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to create affiliate in Rewardful"
                )
            
            rewardful_data = response.json()
            
            # Create new affiliate record in our database
            affiliate = Affiliate(
                user_id=user.id,
                rewardful_id=rewardful_data.get("id"),
                referral_code=referral_code,
                referral_link=self.generate_referral_link(referral_code),
                is_active=True,
                total_referrals=0,
                total_clicks=0,
                total_commissions_earned=0.0,
                total_commissions_paid=0.0
            )
            
            db.add(affiliate)
            db.commit()
            db.refresh(affiliate)
            
            self.logger.info(f"Created affiliate record for user {user.id} with code {referral_code}")
            return affiliate
            
        except Exception as e:
            db.rollback()
            self.logger.error(f"Error creating affiliate record: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error creating affiliate record"
            )
    
    def _generate_unique_referral_code(self, user: User, db: Session) -> str:
        """
        Generate a unique referral code for the user.
        
        Args:
            user: User model instance
            db: Database session
            
        Returns:
            str: Unique referral code
        """
        import string
        import random
        
        # Start with username or email prefix
        base_code = ""
        if user.username:
            base_code = user.username.lower()[:8]
        elif user.email:
            base_code = user.email.split('@')[0].lower()[:8]
        else:
            base_code = "user"
        
        # Clean the base code (alphanumeric only)
        base_code = ''.join(c for c in base_code if c.isalnum())
        
        # Try the base code first
        if len(base_code) >= 3:
            existing = db.query(Affiliate).filter(
                Affiliate.referral_code == base_code
            ).first()
            if not existing:
                return base_code
        
        # If base code exists, append random characters
        for i in range(10):  # Try 10 times
            suffix = ''.join(random.choices(string.digits, k=3))
            code = f"{base_code}{suffix}"
            
            existing = db.query(Affiliate).filter(
                Affiliate.referral_code == code
            ).first()
            if not existing:
                return code
        
        # Fallback to completely random code
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    async def process_rewardful_webhook(self, event_data: Dict[str, Any], db: Session) -> None:
        """
        Process a webhook from Rewardful.
        
        Args:
            event_data: Webhook event data
            db: Database session
        """
        try:
            event_type = event_data.get('type')
            data = event_data.get('data', {})
            
            if event_type == 'referral.created':
                await self._handle_referral_created(data, db)
            elif event_type == 'referral.converted':
                await self._handle_referral_converted(data, db)
            elif event_type == 'commission.earned':
                await self._handle_commission_earned(data, db)
            else:
                self.logger.warning(f"Unknown Rewardful event type: {event_type}")
                
        except Exception as e:
            self.logger.error(f"Error processing Rewardful webhook: {str(e)}")
            raise
    
    async def _handle_referral_created(self, data: Dict[str, Any], db: Session) -> None:
        """Handle referral.created webhook event."""
        try:
            # Extract referral data
            referral_id = data.get('id')
            affiliate_id = data.get('affiliate_id')
            customer_email = data.get('customer_email')
            customer_name = data.get('customer_name')
            
            # Find the affiliate
            affiliate = db.query(Affiliate).filter(
                Affiliate.rewardful_id == str(affiliate_id)
            ).first()
            
            if not affiliate:
                self.logger.warning(f"No affiliate found for Rewardful ID: {affiliate_id}")
                return
            
            # Check if referral already exists
            existing_referral = db.query(AffiliateReferral).filter(
                AffiliateReferral.rewardful_referral_id == str(referral_id)
            ).first()
            
            if existing_referral:
                self.logger.info(f"Referral {referral_id} already exists")
                return
            
            # Create new referral record
            referral = AffiliateReferral(
                affiliate_id=affiliate.id,
                rewardful_referral_id=str(referral_id),
                customer_email=customer_email,
                customer_name=customer_name,
                status='pending',
                is_first_conversion=True
            )
            
            db.add(referral)
            
            # Update affiliate stats
            affiliate.total_referrals += 1
            affiliate.updated_at = datetime.utcnow()
            
            db.commit()
            
            self.logger.info(f"Created referral record for affiliate {affiliate.id}")
            
        except Exception as e:
            db.rollback()
            self.logger.error(f"Error handling referral.created: {str(e)}")
            raise
    
    async def _handle_referral_converted(self, data: Dict[str, Any], db: Session) -> None:
        """Handle referral.converted webhook event."""
        try:
            referral_id = data.get('id')
            amount = data.get('sale_amount', 0)
            commission_amount = data.get('commission_amount', 0)
            
            # Find the referral
            referral = db.query(AffiliateReferral).filter(
                AffiliateReferral.rewardful_referral_id == str(referral_id)
            ).first()
            
            if not referral:
                self.logger.warning(f"No referral found for ID: {referral_id}")
                return
            
            # Update referral with conversion data
            referral.conversion_amount = float(amount)
            referral.commission_amount = float(commission_amount)
            referral.commission_rate = (float(commission_amount) / float(amount)) if amount > 0 else 0
            referral.status = 'confirmed'
            referral.conversion_date = datetime.utcnow()
            referral.updated_at = datetime.utcnow()
            
            # Update affiliate stats
            affiliate = referral.affiliate
            affiliate.total_commissions_earned += float(commission_amount)
            affiliate.updated_at = datetime.utcnow()
            
            db.commit()
            
            self.logger.info(f"Updated referral {referral_id} with conversion data")
            
        except Exception as e:
            db.rollback()
            self.logger.error(f"Error handling referral.converted: {str(e)}")
            raise
    
    async def _handle_commission_earned(self, data: Dict[str, Any], db: Session) -> None:
        """Handle commission.earned webhook event."""
        try:
            referral_id = data.get('referral_id')
            amount_earned = data.get('amount', 0)
            
            # Find the referral
            referral = db.query(AffiliateReferral).filter(
                AffiliateReferral.rewardful_referral_id == str(referral_id)
            ).first()
            
            if not referral:
                self.logger.warning(f"No referral found for ID: {referral_id}")
                return
            
            # Update referral with earning data
            referral.status = 'paid'
            referral.commission_paid_date = datetime.utcnow()
            referral.updated_at = datetime.utcnow()
            
            # Update affiliate stats
            affiliate = referral.affiliate
            affiliate.total_commissions_paid += float(amount_earned)
            affiliate.updated_at = datetime.utcnow()
            
            db.commit()
            
            self.logger.info(f"Updated referral {referral_id} as paid")
            
        except Exception as e:
            db.rollback()
            self.logger.error(f"Error handling commission.earned: {str(e)}")
            raise
    
    async def get_affiliate_stats(self, affiliate: Affiliate, db: Session) -> Dict[str, Any]:
        """
        Get comprehensive statistics for an affiliate.
        
        Args:
            affiliate: Affiliate model instance
            db: Database session
            
        Returns:
            Dict: Affiliate statistics
        """
        try:
            # Get referral counts by status
            total_referrals = db.query(AffiliateReferral).filter(
                AffiliateReferral.affiliate_id == affiliate.id
            ).count()
            
            confirmed_referrals = db.query(AffiliateReferral).filter(
                AffiliateReferral.affiliate_id == affiliate.id,
                AffiliateReferral.status.in_(['confirmed', 'paid'])
            ).count()
            
            pending_referrals = db.query(AffiliateReferral).filter(
                AffiliateReferral.affiliate_id == affiliate.id,
                AffiliateReferral.status == 'pending'
            ).count()
            
            # Get commission totals
            total_earned = db.query(
                func.coalesce(func.sum(AffiliateReferral.commission_amount), 0)
            ).filter(
                AffiliateReferral.affiliate_id == affiliate.id,
                AffiliateReferral.commission_amount.isnot(None)
            ).scalar() or 0
            
            total_paid = db.query(
                func.coalesce(func.sum(AffiliateReferral.commission_amount), 0)
            ).filter(
                AffiliateReferral.affiliate_id == affiliate.id,
                AffiliateReferral.status == 'paid'
            ).scalar() or 0
            
            pending_payout = total_earned - total_paid
            
            # Get click stats
            total_clicks = db.query(AffiliateClick).filter(
                AffiliateClick.affiliate_id == affiliate.id
            ).count()
            
            # Calculate conversion rate
            conversion_rate = 0
            if total_clicks > 0:
                conversion_rate = (confirmed_referrals / total_clicks) * 100
            
            return {
                'affiliate_id': affiliate.id,
                'referral_code': affiliate.referral_code,
                'referral_link': affiliate.referral_link,
                'is_active': affiliate.is_active,
                'stats': {
                    'total_referrals': total_referrals,
                    'confirmed_referrals': confirmed_referrals,
                    'pending_referrals': pending_referrals,
                    'total_clicks': total_clicks,
                    'conversion_rate': round(conversion_rate, 2),
                    'total_earned': float(total_earned),
                    'total_paid': float(total_paid),
                    'pending_payout': float(pending_payout)
                },
                'created_at': affiliate.created_at.isoformat(),
                'updated_at': affiliate.updated_at.isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error getting affiliate stats: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error retrieving affiliate statistics"
            )


# Create service instance
rewardful_service = RewardfulService()