import redis
import logging
from typing import Optional
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
from contextlib import contextmanager

from .config import settings

logger = logging.getLogger(__name__)

class RedisManager:
    """Centralized Redis connection manager with pooling"""
    
    def __init__(self):
        self._pool: Optional[redis.ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._initialized = False
    
    def initialize(self) -> bool:
        """Initialize Redis connection pool"""
        if self._initialized:
            return True
            
        try:
            if not settings.REDIS_URL:
                logger.warning("Redis URL not configured, Redis features will be disabled")
                return False
                
            # Create connection pool with optimized settings
            self._pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=20,  # Pool size for concurrent connections
                retry_on_timeout=True,
                retry_on_error=[RedisConnectionError],
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30,
                decode_responses=True
            )
            
            # Create client from pool
            self._client = redis.Redis(connection_pool=self._pool)
            
            # Test connection
            self._client.ping()
            
            self._initialized = True
            logger.info("Redis connection pool initialized successfully")
            return True
            
        except RedisError as e:
            logger.error(f"Failed to initialize Redis connection pool: {e}")
            self._pool = None
            self._client = None
            self._initialized = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error initializing Redis: {e}")
            self._pool = None
            self._client = None
            self._initialized = False
            return False
    
    def get_client(self) -> Optional[redis.Redis]:
        """Get Redis client from pool"""
        if not self._initialized:
            if not self.initialize():
                return None
        return self._client
    
    @contextmanager
    def get_connection(self):
        """Context manager for Redis connections with automatic cleanup"""
        client = self.get_client()
        if client is None:
            yield None
            return
            
        try:
            yield client
        except RedisError as e:
            logger.warning(f"Redis operation failed: {e}")
            yield None
        except Exception as e:
            logger.error(f"Unexpected Redis error: {e}")
            yield None
    
    def is_available(self) -> bool:
        """Check if Redis is available"""
        if not self._initialized or not self._client:
            return False
            
        try:
            self._client.ping()
            return True
        except RedisError:
            return False
        except Exception:
            return False
    
    def close(self):
        """Close Redis connection pool"""
        if self._pool:
            try:
                self._pool.disconnect()
                logger.info("Redis connection pool closed")
            except Exception as e:
                logger.error(f"Error closing Redis pool: {e}")
        
        self._pool = None
        self._client = None
        self._initialized = False
    
    def get_stats(self) -> dict:
        """Get connection pool statistics"""
        if not self._pool:
            return {"status": "not_initialized"}
            
        try:
            return {
                "status": "available" if self.is_available() else "unavailable",
                "max_connections": self._pool.max_connections,
                "created_connections": self._pool.created_connections,
                "available_connections": len(self._pool._available_connections),
                "in_use_connections": len(self._pool._in_use_connections)
            }
        except Exception as e:
            logger.error(f"Error getting Redis stats: {e}")
            return {"status": "error", "error": str(e)}

# Global Redis manager instance
redis_manager = RedisManager()

def get_redis_client() -> Optional[redis.Redis]:
    """Global function to get Redis client"""
    return redis_manager.get_client()

def get_redis_connection():
    """Global context manager for Redis connections"""
    return redis_manager.get_connection()

# Initialize on import
redis_manager.initialize()