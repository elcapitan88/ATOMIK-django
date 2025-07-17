# app/core/security.py
from datetime import datetime, timedelta
from typing import Any, Optional, Union
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
import logging

from ..db.base import get_db
from ..models.user import User
from .config import settings

# Configure logging
logger = logging.getLogger(__name__)

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 configuration
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

def create_access_token(
    subject: Any,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create JWT access token
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "access",
        "iat": datetime.utcnow()
    }
    
    try:
        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )
        logger.debug(f"Created access token for subject: {subject}")
        return encoded_jwt
    except Exception as e:
        logger.error(f"Error creating access token: {str(e)}")
        raise

def create_refresh_token(
    subject: Any,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create JWT refresh token
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=7)  # 7 days for refresh token
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "refresh",
        "iat": datetime.utcnow()
    }
    
    try:
        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )
        logger.debug(f"Created refresh token for subject: {subject}")
        return encoded_jwt
    except Exception as e:
        logger.error(f"Error creating refresh token: {str(e)}")
        raise

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password against hash
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Error verifying password: {str(e)}")
        return False

def get_password_hash(password: str) -> str:
    """
    Generate password hash
    """
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Error hashing password: {str(e)}")
        raise

async def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    """
    Get current authenticated user from token
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode JWT token
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        
        # Extract and validate claims
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "access":
            # More specific logging for debugging
            if email is None:
                logger.warning("Token validation failed: missing email in sub claim")
            elif token_type != "access":
                logger.warning(f"Token validation failed: invalid token type '{token_type}', expected 'access'")
            raise credentials_exception
            
        # Get user from database
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            logger.warning(f"User not found: {email}")
            raise credentials_exception
            
        # Check if user is active
        if not user.is_active:
            logger.warning(f"Inactive user attempted access: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
            
        return user
        
    except JWTError as e:
        # More specific JWT error logging
        if "Signature has expired" in str(e):
            logger.info("JWT token has expired")
        elif "Invalid token" in str(e):
            logger.warning(f"Invalid JWT token structure: {str(e)}")
        else:
            logger.error(f"JWT validation error: {str(e)}")
        raise credentials_exception
    except Exception as e:
        logger.error(f"Error in get_current_user: {str(e)}")
        raise credentials_exception


async def get_current_user_from_query(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user from query parameter token (for SSE connections)
    
    This function extracts the JWT token from query parameters instead of headers,
    which is useful for Server-Sent Events (SSE) connections where setting custom
    headers is not possible in browsers.
    
    Query parameter: ?token=your_jwt_token_here
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials - token required in query parameter",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Extract token from query parameters
        token = request.query_params.get("token")
        
        if not token:
            logger.warning("No token provided in query parameters")
            raise credentials_exception
        
        # Decode JWT token (same validation logic as get_current_user)
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        
        # Extract and validate claims
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "access":
            # More specific logging for debugging
            if email is None:
                logger.warning("Query token validation failed: missing email in sub claim")
            elif token_type != "access":
                logger.warning(f"Query token validation failed: invalid token type '{token_type}', expected 'access'")
            raise credentials_exception
            
        # Get user from database
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            logger.warning(f"User not found: {email}")
            raise credentials_exception
            
        # Check if user is active
        if not user.is_active:
            logger.warning(f"Inactive user attempted access: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
            
        logger.debug(f"Successfully authenticated user via query token: {email}")
        return user
        
    except JWTError as e:
        # More specific JWT error logging for query parameters
        if "Signature has expired" in str(e):
            logger.info("Query parameter JWT token has expired")
        elif "Invalid token" in str(e):
            logger.warning(f"Invalid query parameter JWT token structure: {str(e)}")
        else:
            logger.error(f"JWT validation error from query parameter: {str(e)}")
        raise credentials_exception
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Error in get_current_user_from_query: {str(e)}")
        raise credentials_exception

async def validate_token(token: str) -> bool:
    """
    Validate token without extracting user
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return bool(payload.get("sub"))
    except JWTError:
        return False

def is_token_expired(token: str) -> bool:
    """
    Check if token is expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return datetime.fromtimestamp(payload.get("exp")) < datetime.utcnow()
    except JWTError:
        return True

class SecurityService:
    """
    Service class for security operations
    """
    @staticmethod
    async def refresh_token(refresh_token: str, db: Session) -> dict:
        """
        Refresh access token using refresh token
        """
        try:
            # Validate refresh token
            payload = jwt.decode(
                refresh_token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM]
            )
            
            if payload.get("type") != "refresh":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid refresh token"
                )
                
            # Get user
            email = payload.get("sub")
            user = db.query(User).filter(User.email == email).first()
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
                
            # Create new access token
            access_token = create_access_token(subject=email)
            
            return {
                "access_token": access_token,
                "token_type": "bearer"
            }
            
        except JWTError as e:
            logger.error(f"Error refreshing token: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
def get_user_from_token(token: str) -> Optional[str]:
    """
    Extract user email from token without raising exceptions
    Returns None if token is invalid
    """
    try:
        # Decode JWT token
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        
        # Extract and validate claims
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "access":
            # More specific logging for debugging
            if email is None:
                logger.warning("Token extraction failed: missing email in sub claim")
            elif token_type != "access":
                logger.warning(f"Token extraction failed: invalid token type '{token_type}', expected 'access'")
            return None
            
        return email
        
    except JWTError as e:
        # More specific JWT error logging for token extraction
        if "Signature has expired" in str(e):
            logger.debug("JWT token has expired during extraction")
        elif "Invalid token" in str(e):
            logger.warning(f"Invalid JWT token structure during extraction: {str(e)}")
        else:
            logger.error(f"JWT validation error during extraction: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error in get_user_from_token: {str(e)}")
        return None


def extract_token_from_request(request: Request) -> Optional[str]:
    """
    Extract JWT token from either Authorization header or query parameter
    
    This utility function provides flexible token extraction for different types
    of requests (standard API calls vs SSE connections).
    
    Returns:
        str: The token if found, None otherwise
    """
    try:
        # First try to get token from Authorization header
        authorization = request.headers.get("Authorization")
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:]  # Remove "Bearer " prefix
            if token:
                logger.debug("Token extracted from Authorization header")
                return token
        
        # Fallback to query parameter
        token = request.query_params.get("token")
        if token:
            logger.debug("Token extracted from query parameter")
            return token
        
        logger.warning("No token found in header or query parameter")
        return None
        
    except Exception as e:
        logger.error(f"Error extracting token from request: {str(e)}")
        return None


async def get_current_user_flexible(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user with flexible token extraction
    
    This function can handle tokens from both Authorization headers and query parameters,
    making it suitable for both regular API endpoints and SSE connections.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials - token required in header or query parameter",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Extract token using flexible method
        token = extract_token_from_request(request)
        
        if not token:
            logger.warning("No token provided in header or query parameters")
            raise credentials_exception
        
        # Decode JWT token (same validation logic as other auth functions)
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        
        # Extract and validate claims
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "access":
            # More specific logging for debugging
            if email is None:
                logger.warning("Flexible auth validation failed: missing email in sub claim")
            elif token_type != "access":
                logger.warning(f"Flexible auth validation failed: invalid token type '{token_type}', expected 'access'")
            raise credentials_exception
            
        # Get user from database
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            logger.warning(f"User not found: {email}")
            raise credentials_exception
            
        # Check if user is active
        if not user.is_active:
            logger.warning(f"Inactive user attempted access: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
            
        logger.debug(f"Successfully authenticated user via flexible auth: {email}")
        return user
        
    except JWTError as e:
        # More specific JWT error logging for flexible auth
        if "Signature has expired" in str(e):
            logger.info("JWT token has expired in flexible auth")
        elif "Invalid token" in str(e):
            logger.warning(f"Invalid JWT token structure in flexible auth: {str(e)}")
        else:
            logger.error(f"JWT validation error in flexible auth: {str(e)}")
        raise credentials_exception
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Error in get_current_user_flexible: {str(e)}")
        raise credentials_exception

# Create singleton instance
security_service = SecurityService()

# Rate limiting
limiter = Limiter(key_func=get_remote_address)

# Duplicate function removed - using the standardized version above

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

async def get_current_user_optional(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme)
) -> Optional[User]:
    """Get current user if token is valid, otherwise return None"""
    if not token:
        return None
    
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        email: str = payload.get("sub")
        if email is None:
            return None
        
        user = db.query(User).filter(User.email == email).first()
        return user
    except JWTError:
        return None


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
