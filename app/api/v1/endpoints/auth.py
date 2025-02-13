# app/api/v1/endpoints/auth.py
from ....services.stripe_service import StripeService 
from ....models.subscription import Subscription 
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging
from typing import Optional

from ....core.security import (
    verify_password, 
    get_password_hash, 
    create_access_token,
    get_current_user
)
from ....schemas.user import UserCreate, UserOut, Token
from ....models.user import User
from ....db.base import get_db
from ....core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/register", response_model=UserOut)
async def register(
    user_in: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Register new user
    """
    try:
        # Check for existing user
        existing_user = db.query(User).filter(
            or_(
                User.email == user_in.email,
                User.username == user_in.username
            )
        ).first()
        
        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="Email or username already registered"
            )

        # Create new user
        user = User(
            email=user_in.email,
            username=user_in.username,
            hashed_password=get_password_hash(user_in.password),
            is_active=True
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        logger.info(f"User registered successfully: {user.email}")
        return user

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Registration failed"
        )

# app/api/v1/endpoints/auth.py
from ....services.stripe_service import StripeService  # Add this import
from sqlalchemy import or_
from ....models.subscription import Subscription  # Add this import

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    OAuth2 compatible token login with subscription verification
    """
    try:
        # Find user by email
        user = db.query(User).filter(User.email == form_data.username).first()
        if not user or not verify_password(form_data.password, user.hashed_password):
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=400,
                detail="Inactive user"
            )

        # Skip subscription check if in development mode
        if settings.SKIP_SUBSCRIPTION_CHECK:
            logger.debug(f"Skipping subscription check for {user.email} - Development Mode")
            access_token = create_access_token(subject=user.email)
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username
                }
            }

        # Verify subscription status
        stripe_service = StripeService()
        subscription = db.query(Subscription).filter(
            Subscription.user_id == user.id
        ).first()

        if not subscription:
            logger.warning(f"No subscription found for user {user.email}")
            raise HTTPException(
                status_code=403,
                detail="No active subscription found"
            )

        has_active_subscription = await stripe_service.verify_subscription_status(
            subscription.stripe_customer_id
        )

        if not has_active_subscription:
            logger.warning(f"Inactive subscription for user {user.email}")
            raise HTTPException(
                status_code=403,
                detail="Your subscription is not active"
            )

        # Create access token only after subscription verification
        access_token = create_access_token(subject=user.email)
        
        logger.info(f"User logged in successfully: {user.email}")
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Login failed"
        )

@router.get("/verify", response_model=dict)
async def verify_token(current_user: User = Depends(get_current_user)):
    """
    Verify access token and return user info
    """
    try:
        return {
            "valid": True,
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "username": current_user.username
            }
        }
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )

@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """
    Logout current user
    """
    try:
        # In a more complex implementation, you might want to invalidate the token
        # or add it to a blacklist
        logger.info(f"User logged out: {current_user.email}")
        return {"message": "Successfully logged out"}
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Logout failed"
        )

@router.get("/check-username/{username}")
async def check_username(
    username: str,
    db: Session = Depends(get_db)
):
    """
    Check if username is available
    """
    user = db.query(User).filter(User.username == username).first()
    return {"exists": bool(user)}