"""
Circuit Breaker Pattern Implementation for Trading System

Prevents cascading failures by temporarily disabling strategies that are 
repeatedly failing, allowing time for recovery and preventing system overload.
"""

import time
import asyncio
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from ..core.correlation import CorrelationLogger
from ..core.redis_manager import get_redis_connection
from redis.exceptions import RedisError
import json

logger = CorrelationLogger(__name__)

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failures detected, circuit is open
    HALF_OPEN = "half_open"  # Testing if service has recovered

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5  # Number of failures to open circuit
    recovery_timeout: int = 60  # Seconds to wait before testing recovery
    test_request_timeout: int = 30  # Timeout for test requests in half-open state
    success_threshold: int = 2  # Successful requests needed to close circuit
    sliding_window_size: int = 10  # Size of sliding window for failure tracking
    min_requests: int = 3  # Minimum requests before circuit can open

@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker"""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    total_requests: int = 0
    requests_blocked: int = 0
    state_changed_at: float = field(default_factory=time.time)

class CircuitBreaker:
    """
    Circuit breaker implementation for individual strategies or services
    """
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        self._failure_window = deque(maxlen=config.sliding_window_size)
        
    async def call(self, func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection
        
        Args:
            func: Async function to execute
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Function result if successful
            
        Raises:
            CircuitBreakerOpenError: If circuit is open
            Original exception: If function fails and circuit should remain closed
        """
        async with self._lock:
            self.stats.total_requests += 1
            
            # Check if circuit should be opened
            if self._should_open_circuit():
                self._open_circuit()
            
            # Handle different circuit states
            if self.stats.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._set_half_open()
                else:
                    self.stats.requests_blocked += 1
                    logger.warning(f"Circuit breaker OPEN for {self.name}, blocking request")
                    raise CircuitBreakerOpenError(f"Circuit breaker is open for {self.name}")
            
        # Execute the function
        try:
            logger.debug(f"Executing request through circuit breaker: {self.name}")
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.config.test_request_timeout if self.stats.state == CircuitState.HALF_OPEN else None
            )
            
            # Record success
            await self._record_success()
            return result
            
        except Exception as e:
            # Record failure
            await self._record_failure(e)
            raise
    
    def _should_open_circuit(self) -> bool:
        """Check if circuit should be opened based on failure rate"""
        if len(self._failure_window) < self.config.min_requests:
            return False
        
        failure_rate = sum(1 for success in self._failure_window if not success) / len(self._failure_window)
        failure_threshold_rate = self.config.failure_threshold / self.config.sliding_window_size
        
        return failure_rate >= failure_threshold_rate
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        if self.stats.last_failure_time is None:
            return True
        
        return time.time() - self.stats.last_failure_time >= self.config.recovery_timeout
    
    def _open_circuit(self):
        """Open the circuit breaker"""
        if self.stats.state != CircuitState.OPEN:
            logger.warning(f"Opening circuit breaker for {self.name}")
            self.stats.state = CircuitState.OPEN
            self.stats.state_changed_at = time.time()
    
    def _set_half_open(self):
        """Set circuit to half-open state for testing"""
        logger.info(f"Setting circuit breaker to HALF_OPEN for {self.name}")
        self.stats.state = CircuitState.HALF_OPEN
        self.stats.state_changed_at = time.time()
        self.stats.success_count = 0  # Reset success count for half-open test
    
    def _close_circuit(self):
        """Close the circuit breaker (normal operation)"""
        logger.info(f"Closing circuit breaker for {self.name} - service recovered")
        self.stats.state = CircuitState.CLOSED
        self.stats.state_changed_at = time.time()
        self.stats.failure_count = 0
        self._failure_window.clear()
    
    async def _record_success(self):
        """Record a successful request"""
        async with self._lock:
            self.stats.success_count += 1
            self.stats.last_success_time = time.time()
            self._failure_window.append(True)  # True = success
            
            # If in half-open state, check if we can close the circuit
            if (self.stats.state == CircuitState.HALF_OPEN and 
                self.stats.success_count >= self.config.success_threshold):
                self._close_circuit()
    
    async def _record_failure(self, error: Exception):
        """Record a failed request"""
        async with self._lock:
            self.stats.failure_count += 1
            self.stats.last_failure_time = time.time()
            self._failure_window.append(False)  # False = failure
            
            logger.warning(f"Circuit breaker recorded failure for {self.name}: {str(error)}")
            
            # If in half-open state, immediately open the circuit
            if self.stats.state == CircuitState.HALF_OPEN:
                self._open_circuit()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current circuit breaker statistics"""
        return {
            "name": self.name,
            "state": self.stats.state.value,
            "failure_count": self.stats.failure_count,
            "success_count": self.stats.success_count,
            "total_requests": self.stats.total_requests,
            "requests_blocked": self.stats.requests_blocked,
            "last_failure_time": self.stats.last_failure_time,
            "last_success_time": self.stats.last_success_time,
            "state_changed_at": self.stats.state_changed_at,
            "failure_rate": (
                sum(1 for success in self._failure_window if not success) / len(self._failure_window)
                if self._failure_window else 0
            ),
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "success_threshold": self.config.success_threshold
            }
        }

class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and blocking requests"""
    pass

class CircuitBreakerManager:
    """
    Manages multiple circuit breakers for different strategies and services
    """
    
    def __init__(self):
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._default_config = CircuitBreakerConfig()
        self._lock = asyncio.Lock()
    
    def get_circuit_breaker(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        """Get or create a circuit breaker for the given name"""
        if name not in self._circuit_breakers:
            circuit_config = config or self._default_config
            self._circuit_breakers[name] = CircuitBreaker(name, circuit_config)
            logger.info(f"Created circuit breaker for {name}")
        
        return self._circuit_breakers[name]
    
    async def execute_with_circuit_breaker(
        self, 
        name: str, 
        func: Callable[..., Awaitable[Any]], 
        *args, 
        config: Optional[CircuitBreakerConfig] = None,
        **kwargs
    ) -> Any:
        """
        Execute function with circuit breaker protection
        
        Args:
            name: Circuit breaker name (usually strategy_id or service_name)
            func: Async function to execute
            config: Optional custom configuration
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Function result if successful
        """
        circuit_breaker = self.get_circuit_breaker(name, config)
        return await circuit_breaker.call(func, *args, **kwargs)
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all circuit breakers"""
        return {name: cb.get_stats() for name, cb in self._circuit_breakers.items()}
    
    def get_circuit_stats(self, name: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific circuit breaker"""
        if name in self._circuit_breakers:
            return self._circuit_breakers[name].get_stats()
        return None
    
    async def reset_circuit_breaker(self, name: str) -> bool:
        """Manually reset a circuit breaker (admin operation)"""
        if name in self._circuit_breakers:
            circuit_breaker = self._circuit_breakers[name]
            async with circuit_breaker._lock:
                circuit_breaker._close_circuit()
                logger.info(f"Manually reset circuit breaker: {name}")
                return True
        return False
    
    def remove_circuit_breaker(self, name: str) -> bool:
        """Remove a circuit breaker"""
        if name in self._circuit_breakers:
            del self._circuit_breakers[name]
            logger.info(f"Removed circuit breaker: {name}")
            return True
        return False

# Global circuit breaker manager instance
circuit_breaker_manager = CircuitBreakerManager()

@asynccontextmanager
async def circuit_breaker_protection(
    name: str, 
    config: Optional[CircuitBreakerConfig] = None
):
    """
    Context manager for circuit breaker protection
    
    Usage:
        async with circuit_breaker_protection("strategy_123"):
            # Your trading operation here
            result = await execute_trade()
    """
    circuit_breaker = circuit_breaker_manager.get_circuit_breaker(name, config)
    
    # Check circuit state before entering context
    if circuit_breaker.stats.state == CircuitState.OPEN:
        if not circuit_breaker._should_attempt_reset():
            circuit_breaker.stats.requests_blocked += 1
            raise CircuitBreakerOpenError(f"Circuit breaker is open for {name}")
        else:
            circuit_breaker._set_half_open()
    
    try:
        yield circuit_breaker
        await circuit_breaker._record_success()
    except Exception as e:
        await circuit_breaker._record_failure(e)
        raise