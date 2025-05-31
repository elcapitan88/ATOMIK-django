# app/services/promo_code_service.py
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import string
import secrets
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.models.promo_code import PromoCode
from app.models.user import User
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)

class PromoCodeService:
    """Service for managing promotional codes"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def generate_code(self, length: int = 8, prefix: str = "") -> str:
        """Generate a random, secure promo code"""
        # Use uppercase letters and digits for better readability
        chars = string.ascii_uppercase + string.digits
        # Remove easily confused characters
        chars = chars.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
        
        # Generate random string
        random_part = ''.join(secrets.choice(chars) for _ in range(length))
        
        # Add prefix if provided
        if prefix:
            return f"{prefix}-{random_part}"
        
        return random_part
    
    def create_promo_code(
        self, 
        admin_id: int,
        description: str = None,
        max_uses: int = None,
        expiry_days: int = None,
        prefix: str = "",
        code_length: int = 8
    ) -> PromoCode:
        """Create a new promotional code"""
        try:
            # Generate a unique code
            code = self.generate_code(length=code_length, prefix=prefix)
            # Check if code already exists
            while self.db.query(PromoCode).filter(PromoCode.code == code).first():
                code = self.generate_code(length=code_length, prefix=prefix)
            
            # Calculate expiry date if provided
            expires_at = None
            if expiry_days:
                expires_at = datetime.utcnow() + timedelta(days=expiry_days)
            
            # Create new promo code
            promo_code = PromoCode(
                code=code,
                description=description,
                max_uses=max_uses,
                expires_at=expires_at,
                created_by=admin_id,
                is_active=True
            )
            
            self.db.add(promo_code)
            self.db.commit()
            self.db.refresh(promo_code)
            
            logger.info(f"Created new promo code: {code}")
            return promo_code
            
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"Database error creating promo code: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error creating promo code: {str(e)}")
            raise
    
    def validate_code(self, code: str) -> Dict[str, Any]:
        """
        Validate a promo code
        
        Returns:
            Dict with validation result:
            {
                "valid": bool,
                "promo_code": PromoCode or None,
                "message": Optional error message
            }
        """
        try:
            # Find code
            promo_code = self.db.query(PromoCode).filter(PromoCode.code == code).first()
            
            if not promo_code:
                return {
                    "valid": False,
                    "promo_code": None,
                    "message": "Invalid promo code"
                }
            
            # Check if code is active
            if not promo_code.is_active:
                return {
                    "valid": False, 
                    "promo_code": promo_code,
                    "message": "This promo code is no longer active"
                }
            
            # Check expiration
            if promo_code.expires_at and datetime.utcnow() > promo_code.expires_at:
                return {
                    "valid": False, 
                    "promo_code": promo_code,
                    "message": "This promo code has expired"
                }
            
            # Check usage limit
            if promo_code.max_uses is not None and promo_code.current_uses >= promo_code.max_uses:
                return {
                    "valid": False, 
                    "promo_code": promo_code,
                    "message": "This promo code has reached its usage limit"
                }
            
            # All checks passed
            return {
                "valid": True,
                "promo_code": promo_code,
                "message": "Valid promo code"
            }
            
        except Exception as e:
            logger.error(f"Error validating promo code: {str(e)}")
            return {
                "valid": False,
                "promo_code": None,
                "message": f"Error validating code: {str(e)}"
            }
    
    def apply_code_to_user(self, user_id: int, code: str) -> Dict[str, Any]:
        """
        Apply a promo code to a user
        
        Returns:
            Dict with result:
            {
                "success": bool,
                "message": str,
                "subscription": Subscription or None
            }
        """
        try:
            # Validate the code first
            validation = self.validate_code(code)
            if not validation["valid"]:
                return {
                    "success": False,
                    "message": validation["message"],
                    "subscription": None
                }
            
            promo_code = validation["promo_code"]
            
            # Check if user exists
            user = self.db.query(User).filter(User.id == user_id).first()
            if not user:
                return {
                    "success": False,
                    "message": "User not found",
                    "subscription": None
                }
            
            # Check if user already has a promo code applied
            if user.promo_code_id:
                return {
                    "success": False,
                    "message": "User already has a promo code applied",
                    "subscription": None
                }
            
            # Start a transaction
            try:
                # Apply the promo code to the user
                user.promo_code_id = promo_code.id
                
                # Increment usage counter
                promo_code.current_uses += 1
                
                # Create or update user's subscription to Elite lifetime
                subscription = self.db.query(Subscription).filter(
                    Subscription.user_id == user_id
                ).first()
                
                if subscription:
                    # Update existing subscription
                    subscription.tier = "elite"
                    subscription.is_lifetime = True
                    subscription.status = "active"
                    subscription.updated_at = datetime.utcnow()
                else:
                    # Create new elite subscription
                    subscription = Subscription(
                        user_id=user_id,
                        tier="elite",
                        status="active",
                        is_lifetime=True,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    self.db.add(subscription)
                
                # Commit changes
                self.db.commit()
                self.db.refresh(subscription)
                
                logger.info(f"Applied promo code {code} to user {user_id}")
                
                return {
                    "success": True,
                    "message": "Promo code applied successfully. Elite lifetime subscription activated.",
                    "subscription": subscription
                }
                
            except SQLAlchemyError as e:
                self.db.rollback()
                logger.error(f"Database error applying promo code: {str(e)}")
                return {
                    "success": False,
                    "message": "Database error occurred",
                    "subscription": None
                }
                
        except Exception as e:
            logger.error(f"Error applying promo code: {str(e)}")
            return {
                "success": False,
                "message": f"Error applying promo code: {str(e)}",
                "subscription": None
            }
    
    def get_promo_codes(
        self, 
        active_only: bool = False, 
        limit: int = 100, 
        offset: int = 0
    ) -> List[PromoCode]:
        """Get list of promo codes with pagination"""
        query = self.db.query(PromoCode)
        
        if active_only:
            query = query.filter(PromoCode.is_active == True)
        
        return query.order_by(PromoCode.created_at.desc()).offset(offset).limit(limit).all()
    
    def get_promo_code_by_id(self, code_id: int) -> Optional[PromoCode]:
        """Get a promo code by ID"""
        return self.db.query(PromoCode).filter(PromoCode.id == code_id).first()
    
    def get_promo_code_by_code(self, code: str) -> Optional[PromoCode]:
        """Get a promo code by code string"""
        return self.db.query(PromoCode).filter(PromoCode.code == code).first()
    
    def update_promo_code(
        self, 
        code: str, 
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update a promo code
        
        Args:
            code: The promo code string
            updates: Dict with fields to update
            
        Returns:
            Dict with result
        """
        try:
            promo_code = self.db.query(PromoCode).filter(PromoCode.code == code).first()
            
            if not promo_code:
                return {
                    "success": False,
                    "message": "Promo code not found"
                }
            
            # Apply updates
            allowed_fields = [
                "description", "is_active", "max_uses", "expires_at"
            ]
            
            for field in allowed_fields:
                if field in updates:
                    setattr(promo_code, field, updates[field])
            
            promo_code.updated_at = datetime.utcnow()
            
            self.db.commit()
            self.db.refresh(promo_code)
            
            logger.info(f"Updated promo code: {code}")
            
            return {
                "success": True,
                "message": "Promo code updated successfully",
                "promo_code": promo_code
            }
            
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(f"Database error updating promo code: {str(e)}")
            return {
                "success": False,
                "message": f"Database error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error updating promo code: {str(e)}")
            return {
                "success": False,
                "message": f"Error: {str(e)}"
            }
    
    def deactivate_promo_code(self, code: str) -> Dict[str, Any]:
        """Deactivate a promo code"""
        return self.update_promo_code(code, {"is_active": False})
    
    def get_promo_code_stats(self, code: str) -> Dict[str, Any]:
        """Get usage statistics for a promo code"""
        try:
            promo_code = self.db.query(PromoCode).filter(PromoCode.code == code).first()
            
            if not promo_code:
                return {
                    "success": False,
                    "message": "Promo code not found"
                }
            
            # Get users who used this code
            users = self.db.query(User).filter(User.promo_code_id == promo_code.id).all()
            
            # Calculate stats
            stats = {
                "code": promo_code.code,
                "total_uses": promo_code.current_uses,
                "max_uses": promo_code.max_uses,
                "is_active": promo_code.is_active,
                "expires_at": promo_code.expires_at.isoformat() if promo_code.expires_at else None,
                "created_at": promo_code.created_at.isoformat(),
                "user_count": len(users),
                "remaining_uses": (promo_code.max_uses - promo_code.current_uses) if promo_code.max_uses else "unlimited"
            }
            
            return {
                "success": True,
                "stats": stats
            }
            
        except Exception as e:
            logger.error(f"Error getting promo code stats: {str(e)}")
            return {
                "success": False,
                "message": f"Error: {str(e)}"
            }