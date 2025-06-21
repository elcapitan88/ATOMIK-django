# app/core/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional, List, Any, Dict
from pathlib import Path
import secrets
from pydantic import validator
from pydantic_settings import BaseSettings
import os
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # Base Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Trading API"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    # Server Settings
    SERVER_HOST: str = ""
    FRONTEND_URL: str = ""

    DEV_SERVER_HOST: str = "http://localhost:8000"
    DEV_FRONTEND_URL: str = "http://localhost:3000"
    DEV_TRADOVATE_REDIRECT_URI: str = "http://localhost:8000/api/tradovate/callback"

    PROD_SERVER_HOST: str = "https://api.atomiktrading.io"
    PROD_FRONTEND_URL: str = "https://www.atomiktrading.io"
    PROD_TRADOVATE_REDIRECT_URI: str = "https://api.atomiktrading.io/api/tradovate/callback"

        
    # Database Settings
    DATABASE_URL: str
    DEV_DATABASE_URL: str = ""  
    PROD_DATABASE_URL: str = ""
    SQL_ECHO: bool = False 
    
    # Database pool settings (optimized for memory efficiency)
    DB_POOL_SIZE: int = 8
    DB_MAX_OVERFLOW: int = 15
    DB_POOL_TIMEOUT: int = 20
    DB_POOL_RECYCLE: int = 3600  # 1 hour
    DB_POOL_PRE_PING: bool = True
    

    #Email Settings
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_SERVER: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    SMTP_USE_TLS: bool = True


    
    # Worker settings
    WORKERS: int = 4

    HUBSPOT_API_KEY: Optional[str] = None

    @property
    def active_database_url(self) -> str:
        """Get the optimal database URL based on where we're running"""
        
        # Check if we're running ON Railway
        is_on_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None
        
        if is_on_railway:
            # Check for Railway's template variable (internal connection)
            railway_private_url = os.getenv("DATABASE_PRIVATE_URL")
            if railway_private_url:
                logger.info(f"Using Railway private network database URL")
                return railway_private_url
        
        # Fallback to standard URL logic (works for both local and Railway)
        if self.ENVIRONMENT == "production" and self.PROD_DATABASE_URL:
            return self.PROD_DATABASE_URL
        elif self.ENVIRONMENT == "development" and self.DEV_DATABASE_URL:
            return self.DEV_DATABASE_URL
        return self.DATABASE_URL
    
    def _get_railway_internal_url(self) -> Optional[str]:
        """Build Railway internal database URL if environment variables are available"""
        try:
            # Railway provides these environment variables automatically
            db_host = os.getenv("PGHOST")
            db_port = os.getenv("PGPORT", "5432")
            db_user = os.getenv("PGUSER")
            db_password = os.getenv("PGPASSWORD") 
            db_name = os.getenv("PGDATABASE")
            
            if all([db_host, db_user, db_password, db_name]):
                # Build Railway internal connection URL
                return f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            else:
                return None
        except Exception:
            return None
    
    def get_db_params(self) -> Dict[str, Any]:
        """Return database connection parameters based on environment"""
        
        # Check if we're running ON Railway (production environment)
        is_on_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None
        
        if is_on_railway:
            # Running ON Railway - use Railway-optimized settings
            return {
                "pool_size": 30,           # Higher pool for Railway's low latency
                "max_overflow": 50,        # More overflow connections
                "pool_timeout": self.DB_POOL_TIMEOUT,
                "pool_recycle": 7200,      # Longer recycle (2 hours) - Railway is stable
                "pool_pre_ping": self.DB_POOL_PRE_PING,
                "echo": self.SQL_ECHO
                # Removed connect_args to avoid compatibility issues
            }
        else:
            # Local development connecting to Railway database
            return {
                "pool_size": 8,            # Moderate pool for external connection
                "max_overflow": 15,        # Standard overflow
                "pool_timeout": 20,
                "pool_recycle": 1800,      # 30 minutes (shorter for external)
                "pool_pre_ping": self.DB_POOL_PRE_PING,
                "echo": self.SQL_ECHO
                # Removed connect_args to avoid compatibility issues
            }
    
    # Security and Authentication Settings
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 90
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Webhook Settings
    WEBHOOK_SECRET_KEY: str = secrets.token_urlsafe(32)

    # CORS Settings
    CORS_ORIGINS: str = "http://localhost:3000"

    # Redis Settings
    REDIS_URL: Optional[str] = "redis://localhost:6379"
    
    @property
    def active_redis_url(self) -> str:
        """Get the optimal Redis URL based on where we're running"""
        
        # Check if we're running ON Railway
        is_on_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None
        
        if is_on_railway:
            # Try to use Railway's Redis URL
            railway_redis_url = os.getenv("REDIS_URL")
            if railway_redis_url:
                return railway_redis_url
        
        # Fallback to configured Redis URL (for local development)
        return self.REDIS_URL or "redis://localhost:6379"

    DIGITAL_OCEAN_API_KEY: Optional[str] = None
    DIGITAL_OCEAN_REGION: str = "nyc1"
    DIGITAL_OCEAN_SIZE: str = "s-1vcpu-1gb" 
    DIGITAL_OCEAN_IMAGE_ID: str = "182556282" 

    #Railway
    RAILWAY_API_KEY: Optional[str] = None
    RAILWAY_PROJECT_ID: Optional[str] = None
    RAILWAY_IB_BASE_SERVICE_ID: Optional[str] = None

    # Tradovate Settings
    TRADOVATE_CLIENT_ID: Optional[str] = None
    TRADOVATE_CLIENT_SECRET: Optional[str] = None
    TRADOVATE_REDIRECT_URI: Optional[str] = None
    TRADOVATE_AUTH_URL: Optional[str] = None
    TRADOVATE_LIVE_EXCHANGE_URL: Optional[str] = None
    TRADOVATE_LIVE_API_URL: Optional[str] = None
    TRADOVATE_LIVE_WS_URL: Optional[str] = None
    TRADOVATE_DEMO_EXCHANGE_URL: Optional[str] = None
    TRADOVATE_DEMO_API_URL: Optional[str] = None
    TRADOVATE_DEMO_WS_URL: Optional[str] = None
    
    # Note: The following URLs are now only used by the token-refresh-service,
    # but we keep them here for reference and development compatibility
    TRADOVATE_LIVE_RENEW_TOKEN_URL: Optional[str] = None
    TRADOVATE_DEMO_RENEW_TOKEN_URL: Optional[str] = None

    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str  
    STRIPE_PUBLIC_KEY: str

    DEV_STRIPE_SUCCESS_URL: str = "http://localhost:3000/payment/success"
    DEV_STRIPE_CANCEL_URL: str = "http://localhost:3000/pricing"

    PROD_STRIPE_SUCCESS_URL: str = "https://atomiktrading.io/payment/success"
    PROD_STRIPE_CANCEL_URL: str = "https://atomiktrading.io/pricing"

    STRIPE_SUCCESS_URL: str = "https://atomiktrading.io/payment/success"
    STRIPE_CANCEL_URL: str = "https://atomiktrading.io/pricing"

    STRIPE_PRICE_PRO_MONTHLY: str = ""
    STRIPE_PRICE_PRO_YEARLY: str = ""
    STRIPE_PRICE_PRO_LIFETIME: str = ""
    STRIPE_PRICE_ELITE_MONTHLY: str = ""
    STRIPE_PRICE_ELITE_YEARLY: str = ""
    STRIPE_PRICE_ELITE_LIFETIME: str = ""

    # FirstPromoter Configuration (v2)
    FIRSTPROMOTER_WEBHOOK_SECRET: str = ""
    FIRSTPROMOTER_TRACKING_DOMAIN: str = ""

    def get_stripe_price_id(self, tier: str, interval: str) -> str:
        """Get the Stripe Price ID for a specific tier and interval with validation"""
        if tier not in ['pro', 'elite']:
            return None
        if interval not in ['monthly', 'yearly', 'lifetime']:
            return None
            
        var_name = f"STRIPE_PRICE_{tier.upper()}_{interval.upper()}"
        return getattr(self, var_name, "")

    @property
    def active_stripe_success_url(self) -> str:
        if self.ENVIRONMENT == "production" and self.PROD_STRIPE_SUCCESS_URL:
            return self.PROD_STRIPE_SUCCESS_URL
        elif self.ENVIRONMENT == "development" and self.DEV_STRIPE_SUCCESS_URL:
            return self.DEV_STRIPE_SUCCESS_URL
        return self.STRIPE_SUCCESS_URL

    @property
    def active_stripe_cancel_url(self) -> str:
        if self.ENVIRONMENT == "production" and self.PROD_STRIPE_CANCEL_URL:
            return self.PROD_STRIPE_CANCEL_URL
        elif self.ENVIRONMENT == "development" and self.DEV_STRIPE_CANCEL_URL:
            return self.DEV_STRIPE_CANCEL_URL
        return self.STRIPE_CANCEL_URL

    SKIP_SUBSCRIPTION_CHECK: bool = False

    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    
    LOG_LEVEL: str = "DEBUG"

    @validator("STRIPE_SECRET_KEY")
    def validate_stripe_secret_key(cls, v):
        if not v or not v.startswith("sk_"):
            raise ValueError("Invalid Stripe secret key format")
        return v

    @validator("STRIPE_WEBHOOK_SECRET")
    def validate_stripe_webhook_secret(cls, v):
        if not v or not v.startswith("whsec_"):
            raise ValueError("Invalid Stripe webhook secret format")
        return v

    @validator("STRIPE_PUBLIC_KEY")
    def validate_stripe_public_key(cls, v):
        if not v or not v.startswith("pk_"):
            raise ValueError("Invalid Stripe public key format")
        return v

    # Add assertions for critical Stripe settings
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.ENVIRONMENT != "test":  # Skip validation in test environment
            assert self.STRIPE_SECRET_KEY, "STRIPE_SECRET_KEY is required"
            assert self.STRIPE_WEBHOOK_SECRET, "STRIPE_WEBHOOK_SECRET is required"
            assert self.STRIPE_PUBLIC_KEY, "STRIPE_PUBLIC_KEY is required"

    @property
    def cors_origins_list(self) -> List[str]:
        """Convert CORS_ORIGINS string to list"""
        if not self.CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = True
        env_file_encoding = 'utf-8'

    @property
    def active_server_host(self) -> str:
        if self.ENVIRONMENT == "production" and self.PROD_SERVER_HOST:
            return self.PROD_SERVER_HOST
        elif self.ENVIRONMENT == "development" and self.DEV_SERVER_HOST:
            return self.DEV_SERVER_HOST
        return self.SERVER_HOST

    @property
    def active_frontend_url(self) -> str:
        if self.ENVIRONMENT == "production" and self.PROD_FRONTEND_URL:
            return self.PROD_FRONTEND_URL
        elif self.ENVIRONMENT == "development" and self.DEV_FRONTEND_URL:
            return self.DEV_FRONTEND_URL
        return self.FRONTEND_URL

    @property
    def active_tradovate_redirect_uri(self) -> str:
        if self.ENVIRONMENT == "production" and self.PROD_TRADOVATE_REDIRECT_URI:
            return self.PROD_TRADOVATE_REDIRECT_URI
        elif self.ENVIRONMENT == "development" and self.DEV_TRADOVATE_REDIRECT_URI:
            return self.DEV_TRADOVATE_REDIRECT_URI
        return self.TRADOVATE_REDIRECT_URI

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()

# Create settings instance
settings = get_settings()

# Validate critical settings on import
assert settings.SECRET_KEY, "SECRET_KEY environment variable is required"
assert settings.DATABASE_URL, "DATABASE_URL environment variable is required"
assert settings.STRIPE_SECRET_KEY, "STRIPE_SECRET_KEY environment variable is required"
assert settings.STRIPE_WEBHOOK_SECRET, "STRIPE_WEBHOOK_SECRET environment variable is required"
assert settings.STRIPE_PUBLIC_KEY, "STRIPE_PUBLIC_KEY environment variable is required"

# Validate Stripe key formats
assert settings.STRIPE_SECRET_KEY.startswith("sk_"), "Invalid Stripe secret key format"
assert settings.STRIPE_WEBHOOK_SECRET.startswith("whsec_"), "Invalid Stripe webhook secret format"
assert settings.STRIPE_PUBLIC_KEY.startswith("pk_"), "Invalid Stripe public key format"