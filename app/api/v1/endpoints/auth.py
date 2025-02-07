# app/api/v1/endpoints/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
import logging

from ....core.security import (
    verify_password, 
    get_password_hash, 
    create_access_token,
    get_current_user
)
from ....core.config import settings
from ....schemas.user import UserCreate, UserOut, Token
from ....models.user import User
from ....db.base import get_db

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

@router.post("/register", response_model=UserOut)
def register(*, db: Session = Depends(get_db), user_in: UserCreate):
    """
    Register a new user.
    """
    try:
        # Check for existing email
        if db.query(User).filter(User.email == user_in.email).first():
            raise HTTPException(
                status_code=400,
                detail="A user with this email already exists"
            )
            
        # Check for existing username
        if db.query(User).filter(User.username == user_in.username).first():
            raise HTTPException(
                status_code=400,
                detail="This username is already taken"
            )
        
        # Create new user
        user = User(
            email=user_in.email,
            username=user_in.username,
            hashed_password=get_password_hash(user_in.password),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        logger.info(f"New user registered: {user.email}")
        return user
        
    except IntegrityError as e:
        db.rollback()
        logger.error(f"Registration failed due to integrity error: {str(e)}")
        if "users.username" in str(e):
            raise HTTPException(
                status_code=400,
                detail="This username is already taken"
            )
        elif "users.email" in str(e):
            raise HTTPException(
                status_code=400,
                detail="A user with this email already exists"
            )
        raise HTTPException(
            status_code=400,
            detail="Registration failed. Please try again."
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error during registration: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later."
        )

@router.post("/login", response_model=Token)
def login(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    try:
        # Authenticate user
        user = db.query(User).filter(User.email == form_data.username).first()
        if not user or not verify_password(form_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=400,
                detail="Inactive user"
            )
        
        # Generate access token
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            subject=user.email, expires_delta=access_token_expires
        )
        
        logger.info(f"User logged in: {user.email}")
        return {
            "access_token": access_token, 
            "token_type": "bearer"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during login"
        )

@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Logout the current user.
    """
    try:
        # You could add token to a blacklist here if implementing token invalidation
        
        logger.info(f"User {current_user.email} logged out successfully")
        return {
            "status": "success",
            "message": "Successfully logged out"
        }
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Error during logout"
        )

@router.get("/verify/")  # Add support for both GET and POST
@router.post("/verify/")
async def verify_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Verify the current access token"""
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
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )

@router.post("/refresh-token", response_model=Token)
async def refresh_token(
    current_user: User = Depends(get_current_user)
):
    """
    Refresh access token.
    """
    try:
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            subject=current_user.email,
            expires_delta=access_token_expires
        )
        
        logger.info(f"Token refreshed for user: {current_user.email}")
        return {
            "access_token": access_token,
            "token_type": "bearer"
        }
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Error refreshing token"
        )
    
# app/api/v1/endpoints/auth.py

@router.get("/check-username/{username}")
async def check_username(
    username: str,
    db: Session = Depends(get_db)
):
    """Check if a username is already taken"""
    user = db.query(User).filter(User.username == username).first()
    return {"exists": bool(user)}