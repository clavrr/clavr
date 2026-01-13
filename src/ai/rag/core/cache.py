"""
Cache utilities for RAG core module.

Provides thread-safe caching mechanisms with TTL and size limits.
"""
import time
from typing import Dict, Any, Optional, Tuple, TypeVar, Generic
from collections import OrderedDict
from datetime import datetime, timedelta
import threading

T = TypeVar('T')

class TTLCache(Generic[T]):
    """
    Thread-safe cache with Time-To-Live (TTL) and maximum size.
    """
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        Initialize TTL cache.
        
        Args:
            max_size: Maximum number of items in cache
            ttl_seconds: Time to live in seconds
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, Tuple[T, float]] = OrderedDict()
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[T]:
        """Get item from cache if exists and not expired."""
        with self._lock:
            if key not in self._cache:
                return None
            
            value, timestamp = self._cache[key]
            
            # Check expiration
            if time.time() - timestamp > self.ttl_seconds:
                del self._cache[key]
                return None
            
            # Move to end (LRU)
            self._cache.move_to_end(key)
            return value
    
    def set(self, key: str, value: T):
        """Set item in cache."""
        with self._lock:
            # Evict if full
            if len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            
            self._cache[key] = (value, time.time())
    
    def clear(self):
        """Clear cache."""
        with self._lock:
            self._cache.clear()
            
    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
            
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds
            }
