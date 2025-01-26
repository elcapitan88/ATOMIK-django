# app/core/security.py
from datetime import datetime, timedelta
from typing import Any, Optional, Union
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
import bcrypt
import secrets
from ..db.base import get_db
from ..models.user import User
from .config import settings

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)

def create_access_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create JWT access token"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt

def create_password_reset_token(email: str) -> str:
    """Create password reset token"""
    expire = datetime.utcnow() + timedelta(
        minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )
    to_encode = {"exp": expire, "sub": email, "type": "reset"}
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )

def verify_password_reset_token(token: str) -> Optional[str]:
    """Verify password reset token"""
    try:
        decoded_token = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        if decoded_token.get("type") != "reset":
            return None
        return decoded_token.get("sub")
    except JWTError:
        return None

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generate password hash"""
    return pwd_context.hash(password)

def generate_security_token(length: int = 32) -> str:
    """Generate secure random token"""
    return secrets.token_urlsafe(length)

async def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    """Get current authenticated user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user

async def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current superuser"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges"
        )
    return current_user

def validate_password_strength(password: str) -> bool:
    """
    Validate password strength
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character
    """
    if len(password) < 8:
        return False
    if not any(c.isupper() for c in password):
        return False
    if not any(c.islower() for c in password):
        return False
    if not any(c.isdigit() for c in password):
        return False
    if not any(c in "!@#$%^&*(),.?\":{}|<>" for c in password):
        return False
    return True

# Rate limiting decorators
def limit_requests(max_requests: int = 100, period: int = 60):
    """Rate limiting decorator"""
    return limiter.limit(f"{max_requests} per {period}second")

# IP blocking
blocked_ips: set = set()

def check_ip_blocked(request: Request):
    """Check if IP is blocked"""
    client_ip = get_remote_address(request)
    if client_ip in blocked_ips:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IP address blocked"
        )

def block_ip(ip: str):
    """Block an IP address"""
    blocked_ips.add(ip)

def unblock_ip(ip: str):
    """Unblock an IP address"""
    blocked_ips.discard(ip)

# Session management
class SessionManager:
    def __init__(self):
        self.active_sessions: dict = {}

    def create_session(self, user_id: int) -> str:
        """Create new session"""
        session_id = generate_security_token()
        self.active_sessions[session_id] = {
            "user_id": user_id,
            "created_at": datetime.utcnow()
        }
        return session_id

    def validate_session(self, session_id: str) -> bool:
        """Validate session"""
        session = self.active_sessions.get(session_id)
        if not session:
            return False
        # Check session age
        age = datetime.utcnow() - session["created_at"]
        if age > timedelta(hours=24):
            self.end_session(session_id)
            return False
        return True

    def end_session(self, session_id: str):
        """End session"""
        self.active_sessions.pop(session_id, None)

# Global session manager instance
session_manager = SessionManager()