# app/api/v1/endpoints/auth.py
from ....services.stripe_service import StripeService 
from ....models.subscription import Subscription 
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from ....models.password_reset import PasswordReset
from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
from datetime import datetime
import jinja2
import secrets
import uuid
from ....models.pending_registration import PendingRegistration

from ....core.security import (
    verify_password, 
    get_password_hash, 
    create_access_token,
    get_current_user
)
from sqlalchemy.exc import SQLAlchemyError
from ....schemas.user import UserCreate, UserOut, Token
from ....models.user import User
from ....db.base import get_db
from ....core.config import settings
from ....services.email.email_password_reset import send_email
from app.services.promo_code_service import PromoCodeService
from ....services.email.email_notification import send_welcome_email, send_admin_signup_notification

logger = logging.getLogger(__name__)
router = APIRouter()

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.post("/register", response_model=Token)
async def register_user(
    user_data: dict,
    background_tasks: BackgroundTasks,  # Add BackgroundTasks parameter
    db: Session = Depends(get_db)
):
    """Register a new user with any subscription tier"""
    try:
        # Extract basic user data
        email = user_data.get("email")
        username = user_data.get("username")
        password = user_data.get("password")
        
        # Extract plan data
        plan_data = user_data.get("plan")
        
        # Validate required fields
        if not email or not password:
            raise HTTPException(status_code=400, detail="Email and password are required")
        
        # Check if user exists
        existing_user = db.query(User).filter(
            or_(
                User.email == email,
                User.username == username
            )
        ).first()
        
        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists")
        
        # Create new user
        hashed_password = get_password_hash(password)
        user = User(
            email=email,
            username=username,
            hashed_password=hashed_password,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(user)
        db.flush()  # Get ID without committing yet
        
        # Default to starter tier
        tier = "starter"
        
        # If plan data is provided, use it for subscription
        if plan_data:
            tier = plan_data.get("tier", "starter")
            if not tier:
                logger.error(f"Registration attempt missing plan tier: {email}")
                raise HTTPException(status_code=400, detail="Plan tier is required")
                
            # Get stripe details
            stripe_customer_id = plan_data.get("stripe_customer_id")
            stripe_subscription_id = plan_data.get("stripe_subscription_id")
            is_lifetime = plan_data.get("is_lifetime", False)
            
            # Additional logging for debugging
            logger.info(f"Creating paid subscription with: tier={tier}, " +
                       f"customer_id={stripe_customer_id}, " +
                       f"subscription_id={stripe_subscription_id}, " +
                       f"is_lifetime={is_lifetime}")
            
            # Create subscription with paid tier details
            subscription = Subscription(
                user_id=user.id,
                tier=tier,
                status="active",
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
                is_lifetime=is_lifetime,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
        else:
            # No plan data, create default starter subscription
            subscription = Subscription(
                user_id=user.id,
                tier="starter",
                status="active",
                is_lifetime=False,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
        
        db.add(subscription)
        db.commit()
        
        # Create and return token
        access_token = create_access_token(subject=user.email)
        
        logger.info(f"User registered successfully: {email}")
        
        # Send welcome email to user
        await send_welcome_email(
            background_tasks=background_tasks,
            username=username or email.split('@')[0],
            email=email
        )
        
        # Send notification to admin
        await send_admin_signup_notification(
            background_tasks=background_tasks,
            username=username or email.split('@')[0],
            email=email,
            tier=tier
        )
        
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
        db.rollback()
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

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
    
@router.patch("/profile", response_model=Dict[str, Any])
async def update_profile(
    profile_data: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user profile information"""
    try:
        # Update allowed fields only
        allowed_fields = ["full_name", "phone", "username", "email"]
        update_data = {}
        
        for field in allowed_fields:
            if field in profile_data and profile_data[field] is not None:
                update_data[field] = profile_data[field]
        
        # Handle nested fields like socialMedia
        if "socialMedia" in profile_data and isinstance(profile_data["socialMedia"], dict):
            # Serialize social media as JSON or create separate columns as needed
            # For simplicity in this example, we're not handling nested fields yet
            pass
            
        # Handle preferences
        if "preferences" in profile_data and isinstance(profile_data["preferences"], dict):
            # Serialize preferences as JSON or create separate columns as needed
            pass
            
        if update_data:
            # Update user record
            for key, value in update_data.items():
                setattr(current_user, key, value)
                
            # Update modified timestamp
            current_user.updated_at = datetime.utcnow()
            
            db.commit()
            db.refresh(current_user)
            
            logger.info(f"Profile updated for user ID {current_user.id}")
            
            # Return updated user data (excluding sensitive fields)
            return {
                "id": current_user.id,
                "username": current_user.username, 
                "email": current_user.email,
                "full_name": current_user.full_name,
                "is_active": current_user.is_active,
                "message": "Profile updated successfully"
            }
        else:
            return {"message": "No valid fields to update"}
            
    except Exception as e:
        logger.error(f"Profile update error: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update profile: {str(e)}"
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
                "username": current_user.username,
                "full_name": current_user.full_name
            }
        }
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )
    
@router.post("/register-starter", response_model=Token)
async def register_with_starter_plan(
    registration_data: dict,
    background_tasks: BackgroundTasks,  # Add BackgroundTasks parameter
    db: Session = Depends(get_db)
):
    """
    Register new user and create a starter subscription in one step
    """
    try:
        # Extract required fields
        email = registration_data.get("email")
        password = registration_data.get("password")
        username = registration_data.get("username")
        
        # Validate required fields
        if not email or not password:
            raise HTTPException(
                status_code=400,
                detail="Email and password are required"
            )
            
        # If username isn't provided, generate one from email
        if not username:
            username = email.split('@')[0]  # Use part before @ as username
        
        # Begin transaction to ensure atomicity
        try:
            # Check for existing user
            existing_user = db.query(User).filter(
                or_(
                    User.email == email,
                    User.username == username
                )
            ).first()
            
            if existing_user:
                # Check if user already has a subscription
                subscription = db.query(Subscription).filter(
                    Subscription.user_id == existing_user.id
                ).first()
                
                if not subscription:
                    # Create starter subscription for existing user
                    subscription = Subscription(
                        user_id=existing_user.id,
                        tier="starter",
                        status="active",
                        is_lifetime=False,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(subscription)
                    db.flush()
                    logger.info(f"Created starter subscription for existing user {existing_user.email}")
                
                # Create access token for existing user
                access_token = create_access_token(subject=existing_user.email)
                
                # Commit transaction
                db.commit()
                
                return {
                    "access_token": access_token,
                    "token_type": "bearer",
                    "user": {
                        "id": existing_user.id,
                        "email": existing_user.email,
                        "username": existing_user.username
                    }
                }

            # Create new user
            user = User(
                email=email,
                username=username,
                hashed_password=get_password_hash(password),
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(user)
            db.flush()  # Flush to get user.id without committing
            
            # Create starter subscription for new user
            subscription = Subscription(
                user_id=user.id,
                tier="starter",
                status="active",
                is_lifetime=False,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(subscription)
            db.flush()
            
            # Create access token
            access_token = create_access_token(subject=user.email)
            
            # Commit transaction
            db.commit()
            
            logger.info(f"User registered with starter plan: {user.email}")
            
            # Send welcome email to user
            await send_welcome_email(
                background_tasks=background_tasks,
                username=username,
                email=email
            )
            
            # Send notification to admin
            await send_admin_signup_notification(
                background_tasks=background_tasks,
                username=username,
                email=email,
                tier="starter"
            )
            
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": username
                }
            }
        except SQLAlchemyError as e:
            # Rollback on any database error
            db.rollback()
            logger.error(f"Database error during registration: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail="Registration failed due to database error"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration with starter plan error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Registration failed"
        )
    
@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Initiate password reset flow by generating token and sending email
    """
    user = db.query(User).filter(User.email == request.email).first()
    
    # Always return success even if user doesn't exist (security best practice)
    if not user:
        logger.info(f"Password reset requested for non-existent email: {request.email}")
        return {"message": "If your email is registered, you will receive a password reset link"}
    
    # Generate a secure random token
    reset_token = secrets.token_urlsafe(32)
    
    # Calculate expiration time (e.g., 1 hour from now)
    from datetime import datetime, timedelta
    expiration = datetime.utcnow() + timedelta(hours=1)
    
    # Store token in database
    # First, delete any existing tokens for this user
    db.query(PasswordReset).filter(PasswordReset.user_id == user.id).delete()
    
    # Create new reset record
    password_reset = PasswordReset(
        user_id=user.id,
        token=reset_token,
        expires_at=expiration
    )
    db.add(password_reset)
    
    try:
        db.commit()
        
        # Generate reset URL
        reset_url = f"{settings.active_frontend_url}/auth/reset-password?token={reset_token}"
        
        # Send email in background task
        background_tasks.add_task(
            send_password_reset_email,
            email=user.email,
            username=user.username,
            reset_url=reset_url
        )
        
        logger.info(f"Password reset token generated for user: {user.email}")
        return {"message": "If your email is registered, you will receive a password reset link"}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error during password reset: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process password reset")

@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Complete password reset using token
    """
    # Find the token in the database
    reset_record = db.query(PasswordReset).filter(
        PasswordReset.token == request.token
    ).first()
    
    if not reset_record:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    
    # Check if token is expired
    from datetime import datetime
    if reset_record.expires_at < datetime.utcnow():
        # Clean up expired token
        db.delete(reset_record)
        db.commit()
        raise HTTPException(status_code=400, detail="Token has expired")
    
    # Get the user
    user = db.query(User).filter(User.id == reset_record.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update password
    user.hashed_password = get_password_hash(request.new_password)
    user.updated_at = datetime.utcnow()
    
    # Delete the used token
    db.delete(reset_record)
    
    try:
        db.commit()
        logger.info(f"Password reset successful for user: {user.email}")
        return {"message": "Password has been reset successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error during password reset confirmation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to reset password")
    
@router.post("/register-with-code", response_model=Token)
async def register_with_promo_code(
    user_data: dict,
    db: Session = Depends(get_db)
):
    """Register a new user with a promo code"""
    try:
        # Extract basic user data
        email = user_data.get("email")
        username = user_data.get("username")
        password = user_data.get("password")
        promo_code = user_data.get("promoCode")  # Get promo code from request
        
        # Validate required fields
        if not email or not password:
            raise HTTPException(status_code=400, detail="Email and password are required")
        
        # Check if user exists
        existing_user = db.query(User).filter(
            or_(
                User.email == email,
                User.username == username
            )
        ).first()
        
        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists")
        
        # Create new user
        hashed_password = get_password_hash(password)
        user = User(
            email=email,
            username=username,
            hashed_password=hashed_password,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(user)
        db.flush()  # Get ID without committing yet
        
        # Default subscription tier
        tier = "starter"
        is_lifetime = False
        
        # If promo code provided, validate and apply it
        promo_code_applied = False
        if promo_code:
            promo_service = PromoCodeService(db)
            validation = promo_service.validate_code(promo_code)
            
            if validation["valid"]:
                # Apply promo code
                user.promo_code_id = validation["promo_code"].id
                
                # Increment usage counter
                validation["promo_code"].current_uses += 1
                
                # Set subscription to Elite lifetime
                tier = "elite"
                is_lifetime = True
                promo_code_applied = True
                
                logger.info(f"Applied promo code {promo_code} during registration for {email}")
            else:
                # Log invalid code attempt but continue with registration
                logger.warning(f"Invalid promo code {promo_code} during registration for {email}: {validation['message']}")
        
        # Create subscription with appropriate tier
        subscription = Subscription(
            user_id=user.id,
            tier=tier,
            status="active",
            is_lifetime=is_lifetime,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(subscription)
        
        # Commit everything
        db.commit()
        
        # Create and return token
        access_token = create_access_token(subject=user.email)
        
        logger.info(f"User registered successfully: {email}")
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username
            },
            "promo_code_applied": promo_code_applied
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
    
@router.post("/prepare-registration", response_model=Dict[str, str])
async def prepare_registration(
    registration_data: dict,
    db: Session = Depends(get_db)
):
    """
    Prepare registration by storing data server-side before Stripe redirect
    """
    try:
        # Extract registration data
        email = registration_data.get("email")
        username = registration_data.get("username")
        password = registration_data.get("password")
        plan_tier = registration_data.get("plan")
        plan_interval = registration_data.get("interval")
        
        # Validate required fields
        if not all([email, username, password, plan_tier, plan_interval]):
            raise HTTPException(
                status_code=400,
                detail="Missing required registration fields"
            )
        
        # Check if user already exists
        existing_user = db.query(User).filter(
            or_(User.email == email, User.username == username)
        ).first()
        
        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="User with this email or username already exists"
            )
        
        # Generate unique session token
        session_token = str(uuid.uuid4())
        
        # Hash the password
        password_hash = get_password_hash(password)
        
        # Store in pending registrations
        pending_reg = PendingRegistration(
            session_token=session_token,
            email=email,
            username=username,
            password_hash=password_hash,
            plan_tier=plan_tier,
            plan_interval=plan_interval
        )
        
        db.add(pending_reg)
        db.commit()
        
        logger.info(f"Created pending registration for {email} with session token {session_token}")
        
        # Create Stripe checkout session with session token in metadata
        stripe_service = StripeService()
        checkout_url = await stripe_service.create_checkout_session_with_trial(
            customer_email=email,
            tier=plan_tier,
            interval=plan_interval,
            success_url=f"{settings.active_stripe_success_url}?session_id={{CHECKOUT_SESSION_ID}}&session_token={session_token}",
            cancel_url=settings.active_stripe_cancel_url,
            metadata={
                'session_token': session_token,
                'tier': plan_tier,
                'interval': plan_interval,
                'username': username,
                'email': email,
                'has_trial': 'True'
            }
        )
        
        # Update pending registration with Stripe session ID if available
        # (Note: We might need to extract this from the checkout URL or response)
        
        return {
            "session_token": session_token,
            "checkout_url": checkout_url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error preparing registration: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to prepare registration: {str(e)}"
        )
    

@router.post("/apply-promo-code", response_model=Dict[str, Any])
async def apply_promo_code(
    promo_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Apply a promo code to an existing user"""
    transaction_created = False
    
    try:
        # Validate input
        promo_code = promo_data.get("promoCode")
        
        if not promo_code:
            raise HTTPException(status_code=400, detail="Promo code is required")
            
        # Normalize promo code (strip whitespace, uppercase)
        promo_code = promo_code.strip().upper()
        
        # Check if user already has a promo code
        if current_user.promo_code_id:
            raise HTTPException(status_code=400, detail="You have already used a promotional code")
        
        # Start transaction explicitly to ensure atomicity
        db.begin_nested()
        transaction_created = True
        
        # Apply the promo code
        promo_service = PromoCodeService(db)
        result = promo_service.apply_code_to_user(current_user.id, promo_code)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        
        # Verify result contains subscription
        if not result.get("subscription"):
            raise HTTPException(status_code=500, detail="Subscription update failed")
            
        # Commit transaction
        db.commit()
        transaction_created = False
        
        logger.info(f"Applied promo code {promo_code} to user {current_user.email}")
        
        # Format subscription data for response
        subscription_data = {
            "tier": result["subscription"].tier,
            "is_lifetime": result["subscription"].is_lifetime,
            "status": result["subscription"].status
        }
        
        # Return success response with subscription details
        return {
            "success": True,
            "message": result["message"],
            "subscription": subscription_data,
            "applied_at": datetime.utcnow().isoformat(),
            "promo_code": promo_code
        }
        
    except HTTPException as e:
        # Roll back transaction if created
        if transaction_created:
            db.rollback()
        # Re-raise HTTP exceptions
        raise
        
    except Exception as e:
        # Roll back transaction if created
        if transaction_created:
            db.rollback()
            
        logger.error(f"Error applying promo code: {str(e)}")
        
        # Return a generic error for security
        raise HTTPException(
            status_code=500,
            detail="An error occurred while applying the promo code. Please try again later."
        )

# Helper function to send email
async def send_password_reset_email(email: str, username: str, reset_url: str):
    """
    Send password reset email using the email service
    """
    try:
        # Use the configured email service
        result = await send_email(
            to=email,
            subject="Reset Your Atomik Trading Password",
            template="password_reset",
            context={
                "username": username,
                "reset_url": reset_url,
                "expiry_hours": 1
            }
        )
        
        if result:
            logger.info(f"Password reset email sent to {email}")
        else:
            logger.warning(f"Failed to send password reset email to {email}")
        
        # For development, also log the URL
        if settings.ENVIRONMENT == "development":
            logger.info(f"Password reset URL for {email}: {reset_url}")
        
    except Exception as e:
        logger.error(f"Failed to send password reset email: {str(e)}")

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