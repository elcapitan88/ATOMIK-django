# app/models/affiliate.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Float, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.base_class import Base

class Affiliate(Base):
    __tablename__ = "affiliates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # Rewardful integration fields  
    rewardful_id = Column(String, unique=True, nullable=True, index=True)
    referral_link = Column(String, nullable=True)
    referral_code = Column(String, unique=True, nullable=True, index=True)
    
    # Status and tracking
    is_active = Column(Boolean, default=True)
    total_referrals = Column(Integer, default=0)
    total_clicks = Column(Integer, default=0)
    total_commissions_earned = Column(Float, default=0.0)
    total_commissions_paid = Column(Float, default=0.0)
    
    # Payout configuration
    payout_method = Column(String, nullable=True)  # 'paypal', 'wise', or None
    payout_details = Column(JSON, nullable=True)  # Store PayPal email, Wise details, etc.
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="affiliate")
    referrals = relationship("AffiliateReferral", back_populates="affiliate", cascade="all, delete-orphan")
    clicks = relationship("AffiliateClick", back_populates="affiliate", cascade="all, delete-orphan")
    
    def __str__(self):
        return f"Affiliate(user_id={self.user_id}, code={self.referral_code})"


class AffiliateReferral(Base):
    __tablename__ = "affiliate_referrals"

    id = Column(Integer, primary_key=True, index=True)
    affiliate_id = Column(Integer, ForeignKey("affiliates.id", ondelete="CASCADE"), nullable=False)
    referred_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    
    # Rewardful integration fields
    rewardful_referral_id = Column(String, unique=True, nullable=True, index=True)
    
    # Customer information
    customer_email = Column(String, nullable=False, index=True)
    customer_name = Column(String, nullable=True)
    
    # Conversion tracking
    conversion_amount = Column(Float, nullable=True)
    commission_amount = Column(Float, nullable=True)
    commission_rate = Column(Float, nullable=True)  # Store the rate used (e.g., 0.20 for 20%)
    
    # Status tracking
    status = Column(String, default="pending")  # pending, confirmed, paid, cancelled
    is_first_conversion = Column(Boolean, default=True)
    
    # Subscription details
    subscription_type = Column(String, nullable=True)  # monthly, yearly, lifetime
    subscription_tier = Column(String, nullable=True)  # pro, elite
    
    # Timestamps
    referral_date = Column(DateTime, default=datetime.utcnow)
    conversion_date = Column(DateTime, nullable=True)
    commission_paid_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    affiliate = relationship("Affiliate", back_populates="referrals")
    referred_user = relationship("User", foreign_keys=[referred_user_id])
    
    def __str__(self):
        return f"AffiliateReferral(email={self.customer_email}, status={self.status})"


class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"

    id = Column(Integer, primary_key=True, index=True)
    affiliate_id = Column(Integer, ForeignKey("affiliates.id", ondelete="CASCADE"), nullable=False)
    
    # Click tracking data
    ip_address = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)
    referrer_url = Column(String, nullable=True)
    landing_page = Column(String, nullable=True)
    
    # Geographic data (optional)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    
    # Conversion tracking
    converted = Column(Boolean, default=False)
    conversion_date = Column(DateTime, nullable=True)
    
    # Timestamps
    click_date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    affiliate = relationship("Affiliate", back_populates="clicks")
    
    def __str__(self):
        return f"AffiliateClick(affiliate_id={self.affiliate_id}, converted={self.converted})"


class AffiliatePayout(Base):
    __tablename__ = "affiliate_payouts"

    id = Column(Integer, primary_key=True, index=True)
    affiliate_id = Column(Integer, ForeignKey("affiliates.id", ondelete="CASCADE"), nullable=False)
    
    # Payout details
    payout_amount = Column(Float, nullable=False)
    payout_method = Column(String, nullable=False)  # 'paypal', 'wise'
    payout_details = Column(JSON, nullable=True)  # Method-specific details
    
    # Period covered by this payout
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    
    # Status tracking
    status = Column(String, default="pending")  # pending, processing, completed, failed
    payout_date = Column(DateTime, nullable=True)
    transaction_id = Column(String, nullable=True)  # PayPal/Wise transaction ID
    
    # Metadata
    currency = Column(String, default="USD")
    commission_count = Column(Integer, default=0)  # Number of commissions included
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    affiliate = relationship("Affiliate", backref="payouts")
    
    def __str__(self):
        return f"AffiliatePayout(affiliate_id={self.affiliate_id}, amount=${self.payout_amount}, status={self.status})"