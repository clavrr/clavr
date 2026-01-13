"""
Performance Optimizations for RAG

Provides caching, connection pooling, and other performance enhancements.
"""
import hashlib
import time
import asyncio
from typing import Dict, Any, Optional, List, Callable, TypeVar, Awaitable
from datetime import datetime, timedelta
from functools import lru_cache
from collections import OrderedDict
from threading import RLock

from ....utils.logger import setup_logger

logger = setup_logger(__name__)

T = TypeVar('T')


class QueryResultCache:
    """
    LRU cache for query results to avoid redundant searches.
    
    Caches search results with configurable TTL to improve response times
    for repeated or similar queries. Thread-safe implementation.
    """
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        Initialize query result cache.
        
        Args:
            max_size: Maximum number of cached queries
            ttl_seconds: Time-to-live for cached results in seconds
        """
        self.max_size = max_size
        self.ttl = timedelta(seconds=ttl_seconds)
        self._cache: OrderedDict[str, tuple[datetime, List[Dict[str, Any]]]] = OrderedDict()
        self._lock = RLock()
    
    def _get_cache_key(self, query: str, k: int, filters: Optional[Dict[str, Any]]) -> str:
        """Generate cache key from query parameters."""
        filter_str = str(sorted(filters.items())) if filters else ""
        content = f"{query.lower().strip()}:{k}:{filter_str}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, query: str, k: int, filters: Optional[Dict[str, Any]] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Get cached results if available and valid.
        
        Args:
            query: Search query
            k: Number of results
            filters: Optional filters
            
        Returns:
            Cached results or None if not found/expired
        """
        cache_key = self._get_cache_key(query, k, filters)
        
        with self._lock:
            if cache_key in self._cache:
                timestamp, results = self._cache[cache_key]
                if datetime.now() - timestamp < self.ttl:
                    # Move to end (most recently used)
                    self._cache.move_to_end(cache_key)
                    return results
                else:
                    # Expired, remove
                    del self._cache[cache_key]
        
        return None
    
    def set(self, query: str, k: int, results: List[Dict[str, Any]], 
            filters: Optional[Dict[str, Any]] = None) -> None:
        """
        Cache query results.
        
        Args:
            query: Search query
            k: Number of results
            results: Results to cache
            filters: Optional filters
        """
        cache_key = self._get_cache_key(query, k, filters)
        
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)  # Remove oldest
            
            self._cache[cache_key] = (datetime.now(), results)
    
    def clear(self) -> None:
        """Clear all cached results."""
        with self._lock:
            self._cache.clear()
            logger.info("Query result cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'ttl_seconds': self.ttl.total_seconds()
            }


class CircuitBreaker:
    """
    Circuit breaker pattern for resilient RAG operations.
    
    Prevents cascading failures by stopping requests to failing services
    and allowing them to recover. Supports both sync and async operations.
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60,
                 expected_exception: type = Exception):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type to catch
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = 'closed'  # closed, open, half_open
        self._lock = RLock()
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute synchronous function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open or function fails
        """
        self._check_state()
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    async def acall(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        """
        Execute ASYNC function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open or function fails
        """
        self._check_state()
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def _check_state(self) -> None:
        """Check if call should proceed based on circuit state."""
        with self._lock:
            if self.state == 'open':
                if self._should_attempt_reset():
                    self.state = 'half_open'
                    logger.info("Circuit breaker: Attempting recovery (half-open)")
                else:
                    raise Exception(f"Circuit breaker is OPEN. Service unavailable. "
                                  f"Will retry after {self.recovery_timeout}s")
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self.last_failure_time is None:
            return True
        
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout
    
    def _on_success(self) -> None:
        """Handle successful call."""
        with self._lock:
            if self.state == 'half_open':
                logger.info("Circuit breaker: Recovery successful, closing circuit")
                self.state = 'closed'
            
            self.failure_count = 0
    
    def _on_failure(self) -> None:
        """Handle failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            
            if self.failure_count >= self.failure_threshold:
                if self.state != 'open':
                    self.state = 'open'
                    logger.warning(f"Circuit breaker: OPENED after {self.failure_count} failures")
    
    def reset(self) -> None:
        """Manually reset circuit breaker."""
        with self._lock:
            self.state = 'closed'
            self.failure_count = 0
            self.last_failure_time = None
            logger.info("Circuit breaker manually reset")
    
    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state."""
        with self._lock:
            return {
                'state': self.state,
                'failure_count': self.failure_count,
                'last_failure_time': self.last_failure_time.isoformat() if self.last_failure_time else None
            }

