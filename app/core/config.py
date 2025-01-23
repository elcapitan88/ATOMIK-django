# app/core/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional, List, Any
from pathlib import Path
import secrets

class Settings(BaseSettings):
    # Base Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Trading API"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # Changed to match your .env

    # Server Settings
    SERVER_HOST: str = "http://localhost:8000"
    
    # Database Settings
    DATABASE_URL: str = "sqlite:///./sql_app.db"
    SQL_ECHO: bool = False 
    
    # Security and Authentication Settings
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    MAX_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15
    SESSION_LIFETIME_HOURS: int = 24
    RATE_LIMIT_PER_MINUTE: int = 60
    
    # WebSocket Settings
    WEBHOOK_SECRET_KEY: str = secrets.token_urlsafe(32)
    WEBSOCKET_MAX_CONNECTIONS: int = 1000
    WEBSOCKET_RATE_LIMIT: int = 100
    WEBSOCKET_PING_INTERVAL: int = 30
    WEBSOCKET_PING_TIMEOUT: int = 10
    WEBSOCKET_HEARTBEAT_INTERVAL: int = 30
    WEBSOCKET_RECONNECT_ATTEMPTS: int = 3
    WEBSOCKET_RECONNECT_DELAY: int = 5
    
    # Tradovate Settings
    TRADOVATE_CLIENT_ID: str
    TRADOVATE_CLIENT_SECRET: str
    TRADOVATE_REDIRECT_URI: str
    TRADOVATE_AUTH_URL: str
    
    # Tradovate Environment URLs
    TRADOVATE_LIVE_EXCHANGE_URL: str
    TRADOVATE_LIVE_API_URL: str
    TRADOVATE_LIVE_WS_URL: str
    TRADOVATE_DEMO_EXCHANGE_URL: str
    TRADOVATE_DEMO_API_URL: str
    TRADOVATE_DEMO_WS_URL: str
    TRADOVATE_LIVE_RENEW_TOKEN_URL: str
    TRADOVATE_DEMO_RENEW_TOKEN_URL: str

    # Subscription Settings
    SKIP_SUBSCRIPTION_CHECK: bool = True
    TRIAL_PERIOD_DAYS: int = 14
    DEFAULT_CURRENCY: str = "USD"

    # Stripe Integration
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    STRIPE_PUBLIC_KEY: str
    
    # Email Settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str
    
    # Frontend Settings
    FRONTEND_URL: str = "http://localhost:3000"
    
    # CORS Settings
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",  # React app
        "http://localhost:8000",  # FastAPI docs
    ]

    # Cache Settings
    REDIS_URL: str = "redis://localhost:6379"
    
    # Logging Settings
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        env_file_encoding = 'utf-8'

        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str) -> Any:
            if field_name == "CORS_ORIGINS" and isinstance(raw_val, str):
                return [origin.strip() for origin in raw_val.split(",")]
            return raw_val

    def get_database_url(self) -> str:
        """Get database URL with proper path resolution"""
        if self.DATABASE_URL.startswith("sqlite"):
            return self.DATABASE_URL.replace(
                "./", str(Path(__file__).parent.parent.parent / "")
            )
        return self.DATABASE_URL

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()

# Create settings instance
settings = get_settings()

# Validate critical settings on import
assert settings.SECRET_KEY, "SECRET_KEY environment variable is required"
assert settings.DATABASE_URL, "DATABASE_URL environment variable is required"