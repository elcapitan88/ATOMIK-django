# app/core/environment.py
import logging
import os
from enum import Enum
from typing import Dict, Any, Optional
from functools import lru_cache
import json

logger = logging.getLogger(__name__)

class Environment(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"

class EnvironmentManager:
    """Manages environment-specific configurations and transitions"""
    
    def __init__(self):
        # Get current environment from settings
        from app.core.config import settings
        self.current_env = settings.ENVIRONMENT
        self.debug_mode = settings.DEBUG
        
        # Configure logging based on environment
        self._configure_logging()
        
        logger.info(f"Environment manager initialized in {self.current_env} mode")
    
    def _configure_logging(self):
        """Configure logging based on current environment"""
        from app.core.config import settings
        
        log_levels = {
            Environment.DEVELOPMENT: logging.DEBUG,
            Environment.TESTING: logging.INFO,
            Environment.PRODUCTION: logging.WARNING
        }
        
        # Override with settings if explicitly set
        if hasattr(settings, 'LOG_LEVEL'):
            log_level_name = settings.LOG_LEVEL.upper()
            if hasattr(logging, log_level_name):
                log_level = getattr(logging, log_level_name)
            else:
                log_level = log_levels.get(self.current_env, logging.INFO)
        else:
            log_level = log_levels.get(self.current_env, logging.INFO)
        
        # Configure root logger
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    def get_environment_config(self) -> Dict[str, Any]:
        """Get current environment configuration details"""
        from app.core.config import settings
        
        # Get the database URL (but mask password)
        db_url = settings.active_database_url
        masked_db_url = self._mask_sensitive_url(db_url)
        
        return {
            "environment": self.current_env,
            "debug_mode": self.debug_mode,
            "database_url": masked_db_url,
            "cors_origins": settings.CORS_ORIGINS,
            "workers": settings.WORKERS,
            "skip_subscription_check": settings.SKIP_SUBSCRIPTION_CHECK
        }
    
    def _mask_sensitive_url(self, url: str) -> str:
        """Mask password in database URL"""
        if not url:
            return ""
        
        # Simple masking that doesn't depend on URL parsing libraries
        if "@" in url and "://" in url:
            prefix = url.split("://")[0] + "://"
            credentials_and_rest = url.split("://")[1]
            
            if "@" in credentials_and_rest:
                credentials = credentials_and_rest.split("@")[0]
                rest = "@" + credentials_and_rest.split("@")[1]
                
                if ":" in credentials:
                    username = credentials.split(":")[0]
                    return f"{prefix}{username}:****{rest}"
        
        # If we can't parse it safely, mask the entire URL except the beginning
        return url[:10] + "****"
    
    def check_database_connection(self) -> Dict[str, Any]:
        """Check database connection in current environment"""
        from app.db.session import test_db_connection
        import asyncio
        
        connection_result = asyncio.run(test_db_connection())
        return connection_result
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance-related stats for the current environment"""
        import psutil
        
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            return {
                "cpu_percent": process.cpu_percent(),
                "memory_usage_mb": memory_info.rss / (1024 * 1024),
                "threads": process.num_threads(),
                "open_files": len(process.open_files()),
                "connections": len(process.connections())
            }
        except Exception as e:
            logger.error(f"Error getting performance stats: {str(e)}")
            return {"error": str(e)}

# Create singleton instance
environment_manager = EnvironmentManager()

def get_environment_manager() -> EnvironmentManager:
    """Get the environment manager instance"""
    return environment_manager