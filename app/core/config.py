# app/core/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional, List, Any
from pathlib import Path
import secrets
from pydantic import validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Base Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Trading API"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    # Server Settings
    SERVER_HOST: str = "http://localhost:8000"
    
    # Database Settings
    DATABASE_URL: str
    SQL_ECHO: bool = False 
    
    # Security and Authentication Settings
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 90
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    
    # WebSocket Settings
    WEBHOOK_SECRET_KEY: str = secrets.token_urlsafe(32)
    WEBSOCKET_MAX_CONNECTIONS: int = 1000
    WEBSOCKET_RATE_LIMIT: int = 100
    WEBSOCKET_PING_INTERVAL: int = 30
    WEBSOCKET_PING_TIMEOUT: int = 10
    WEBSOCKET_HEARTBEAT_INTERVAL: int = 30
    WEBSOCKET_RECONNECT_ATTEMPTS: int = 3
    WEBSOCKET_RECONNECT_DELAY: int = 5

    # CORS Settings
    CORS_ORIGINS: str = "http://localhost:3000"

    # Redis Settings
    REDIS_URL: Optional[str] = "redis://localhost:6379"

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
    TRADOVATE_LIVE_RENEW_TOKEN_URL: Optional[str] = None
    TRADOVATE_DEMO_RENEW_TOKEN_URL: Optional[str] = None

    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str  
    STRIPE_PUBLIC_KEY: str
    STRIPE_SUCCESS_URL: str = "http://localhost:3000/payment/success"
    STRIPE_CANCEL_URL: str = "http://localhost:3000/pricing"
    SKIP_SUBSCRIPTION_CHECK: bool = False

    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    
    FRONTEND_URL: str = "http://localhost:3000"
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

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()

# Create settings instance
settings = get_settings()



# Validate critical settings on import
assert settings.SECRET_KEY, "SECRET_KEY environment variable is required"
assert settings.DATABASE_URL, "DATABASE_URL environment variable is required"
assert settings.SECRET_KEY, "SECRET_KEY environment variable is required"
assert settings.DATABASE_URL, "DATABASE_URL environment variable is required"
assert settings.STRIPE_SECRET_KEY, "STRIPE_SECRET_KEY environment variable is required"
assert settings.STRIPE_WEBHOOK_SECRET, "STRIPE_WEBHOOK_SECRET environment variable is required"
assert settings.STRIPE_PUBLIC_KEY, "STRIPE_PUBLIC_KEY environment variable is required"

# Validate Stripe key formats
assert settings.STRIPE_SECRET_KEY.startswith("sk_"), "Invalid Stripe secret key format"
assert settings.STRIPE_WEBHOOK_SECRET.startswith("whsec_"), "Invalid Stripe webhook secret format"
assert settings.STRIPE_PUBLIC_KEY.startswith("pk_"), "Invalid Stripe public key format"