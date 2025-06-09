"""
Distributed Locking Service for Trading Operations

Implements Redis-based distributed locking to prevent concurrent trading operations
on the same broker account, ensuring data consistency and preventing race conditions.
"""

import time
import asyncio
import logging
import uuid
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from redis.exceptions import RedisError
from ..core.redis_manager import get_redis_connection

logger = logging.getLogger(__name__)

class DistributedLock:
    """
    Redis-based distributed lock implementation for account-level locking
    
    Prevents multiple strategies from executing trades on the same broker account
    simultaneously, which is critical in multi-strategy webhook scenarios.
    """
    
    def __init__(
        self, 
        lock_key: str, 
        timeout: float = 30.0, 
        retry_delay: float = 0.1,
        max_retries: int = 3
    ):
        """
        Initialize distributed lock
        
        Args:
            lock_key: Unique identifier for the lock (e.g., account_lock:12345)
            timeout: Lock timeout in seconds (default 30s)
            retry_delay: Initial delay between retry attempts
            max_retries: Maximum number of lock acquisition attempts
        """
        self.lock_key = lock_key
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.lock_value = str(uuid.uuid4())  # Unique value to identify lock owner
        self.acquired = False
        
    async def acquire(self) -> bool:
        """
        Attempt to acquire the distributed lock with exponential backoff retry
        
        Returns:
            bool: True if lock was acquired, False otherwise
        """
        attempt = 0
        
        while attempt < self.max_retries:
            try:
                with get_redis_connection() as redis_client:
                    if not redis_client:
                        logger.warning(f"Redis unavailable for lock {self.lock_key}, falling back to no locking")
                        return True  # Fail open for availability
                    
                    # Try to acquire lock with SET NX EX (atomic operation)
                    acquired = redis_client.set(
                        self.lock_key,
                        self.lock_value,
                        nx=True,  # Only set if key doesn't exist
                        ex=int(self.timeout)  # Expire after timeout seconds
                    )
                    
                    if acquired:
                        self.acquired = True
                        logger.debug(f"Lock acquired: {self.lock_key}")
                        return True
                    
                    # Check if the lock is held by us (in case of retry)
                    current_value = redis_client.get(self.lock_key)
                    if current_value and current_value.decode() == self.lock_value:
                        self.acquired = True
                        logger.debug(f"Lock already held by us: {self.lock_key}")
                        return True
                        
            except RedisError as e:
                logger.warning(f"Redis error during lock acquisition for {self.lock_key}: {e}")
                # Fall back to no locking for availability
                return True
            except Exception as e:
                logger.error(f"Unexpected error during lock acquisition for {self.lock_key}: {e}")
                
            # Exponential backoff with jitter
            attempt += 1
            if attempt < self.max_retries:
                delay = self.retry_delay * (2 ** attempt) + (time.time() % 0.1)  # Add jitter
                logger.debug(f"Lock acquisition attempt {attempt} failed for {self.lock_key}, retrying in {delay:.2f}s")
                await asyncio.sleep(delay)
        
        logger.warning(f"Failed to acquire lock after {self.max_retries} attempts: {self.lock_key}")
        return False
    
    async def release(self) -> bool:
        """
        Release the distributed lock safely
        
        Uses Lua script to ensure atomic check-and-release operation
        
        Returns:
            bool: True if lock was released, False otherwise
        """
        if not self.acquired:
            return True
            
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    logger.debug(f"Redis unavailable for lock release: {self.lock_key}")
                    return True
                
                # Lua script for atomic check and release
                lua_script = """
                if redis.call("GET", KEYS[1]) == ARGV[1] then
                    return redis.call("DEL", KEYS[1])
                else
                    return 0
                end
                """
                
                result = redis_client.eval(lua_script, 1, self.lock_key, self.lock_value)
                
                if result == 1:
                    self.acquired = False
                    logger.debug(f"Lock released: {self.lock_key}")
                    return True
                else:
                    logger.warning(f"Lock release failed - not owned by us: {self.lock_key}")
                    return False
                    
        except RedisError as e:
            logger.warning(f"Redis error during lock release for {self.lock_key}: {e}")
            return True  # Assume released for graceful degradation
        except Exception as e:
            logger.error(f"Unexpected error during lock release for {self.lock_key}: {e}")
            return False
    
    async def extend(self, additional_time: float = 30.0) -> bool:
        """
        Extend the lock timeout (useful for long-running operations)
        
        Args:
            additional_time: Additional time in seconds to extend the lock
            
        Returns:
            bool: True if lock was extended, False otherwise
        """
        if not self.acquired:
            return False
            
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    return True  # Assume extended for graceful degradation
                
                # Lua script for atomic check and extend
                lua_script = """
                if redis.call("GET", KEYS[1]) == ARGV[1] then
                    return redis.call("EXPIRE", KEYS[1], ARGV[2])
                else
                    return 0
                end
                """
                
                result = redis_client.eval(
                    lua_script, 
                    1, 
                    self.lock_key, 
                    self.lock_value, 
                    int(additional_time)
                )
                
                return result == 1
                
        except RedisError as e:
            logger.warning(f"Redis error during lock extension for {self.lock_key}: {e}")
            return True  # Assume extended for graceful degradation
        except Exception as e:
            logger.error(f"Unexpected error during lock extension for {self.lock_key}: {e}")
            return False


class AccountLockManager:
    """
    High-level manager for account-specific distributed locks
    
    Provides convenient methods for locking broker accounts during trading operations
    """
    
    @staticmethod
    def generate_account_lock_key(account_id: str) -> str:
        """
        Generate standardized lock key for account
        
        Args:
            account_id: Broker account identifier
            
        Returns:
            str: Standardized lock key format
        """
        return f"account_lock:{account_id}"
    
    @staticmethod
    @asynccontextmanager
    async def lock_account(
        account_id: str, 
        timeout: float = 30.0,
        max_retries: int = 3,
        operation_name: str = "trading_operation"
    ):
        """
        Context manager for account locking
        
        Args:
            account_id: Broker account identifier to lock
            timeout: Lock timeout in seconds
            max_retries: Maximum lock acquisition attempts
            operation_name: Description of operation for logging
            
        Usage:
            async with AccountLockManager.lock_account("12345") as acquired:
                if acquired:
                    # Perform trading operations
                    pass
                else:
                    # Handle lock acquisition failure
                    pass
        """
        lock_key = AccountLockManager.generate_account_lock_key(account_id)
        lock = DistributedLock(lock_key, timeout, max_retries=max_retries)
        
        start_time = time.time()
        acquired = False
        
        try:
            logger.info(f"Attempting to acquire lock for account {account_id} ({operation_name})")
            acquired = await lock.acquire()
            
            if acquired:
                acquisition_time = time.time() - start_time
                logger.info(f"Lock acquired for account {account_id} in {acquisition_time:.3f}s ({operation_name})")
            else:
                logger.warning(f"Failed to acquire lock for account {account_id} ({operation_name})")
            
            yield acquired
            
        except Exception as e:
            logger.error(f"Error during locked operation for account {account_id}: {e}")
            raise
        finally:
            if acquired:
                release_result = await lock.release()
                total_time = time.time() - start_time
                
                if release_result:
                    logger.info(f"Lock released for account {account_id} after {total_time:.3f}s ({operation_name})")
                else:
                    logger.warning(f"Failed to release lock for account {account_id} ({operation_name})")

    @staticmethod
    async def get_lock_info(account_id: str) -> Dict[str, Any]:
        """
        Get information about an account lock
        
        Args:
            account_id: Broker account identifier
            
        Returns:
            dict: Lock information including status and TTL
        """
        lock_key = AccountLockManager.generate_account_lock_key(account_id)
        
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    return {"status": "redis_unavailable"}
                
                # Check if lock exists and get TTL
                lock_value = redis_client.get(lock_key)
                ttl = redis_client.ttl(lock_key)
                
                return {
                    "status": "locked" if lock_value else "unlocked",
                    "lock_key": lock_key,
                    "lock_value": lock_value.decode() if lock_value else None,
                    "ttl_seconds": ttl if ttl >= 0 else None,
                    "timestamp": time.time()
                }
                
        except RedisError as e:
            logger.warning(f"Redis error getting lock info for {account_id}: {e}")
            return {"status": "redis_error", "error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error getting lock info for {account_id}: {e}")
            return {"status": "error", "error": str(e)}

    @staticmethod
    async def force_unlock_account(account_id: str) -> bool:
        """
        Force unlock an account (admin operation)
        
        Args:
            account_id: Broker account identifier
            
        Returns:
            bool: True if lock was removed, False otherwise
        """
        lock_key = AccountLockManager.generate_account_lock_key(account_id)
        
        try:
            with get_redis_connection() as redis_client:
                if not redis_client:
                    return True
                
                result = redis_client.delete(lock_key)
                logger.info(f"Force unlocked account {account_id}, result: {result}")
                return bool(result)
                
        except RedisError as e:
            logger.warning(f"Redis error force unlocking {account_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error force unlocking {account_id}: {e}")
            return False