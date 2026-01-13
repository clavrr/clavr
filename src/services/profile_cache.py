"""
Profile Cache Service

Provides in-memory caching for user writing profiles to improve performance
and reduce database load.

Features:
- LRU cache with configurable size
- TTL-based expiration
- Cache invalidation on profile updates
- Thread-safe operations
- Metrics tracking
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from collections import OrderedDict
import threading
from dataclasses import dataclass, field

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with metadata"""
    profile_data: Dict[str, Any]
    user_id: int
    cached_at: datetime
    hit_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.utcnow)


class ProfileCache:
    """
    LRU cache for user writing profiles with TTL expiration
    
    Thread-safe cache that stores user profiles in memory to reduce
    database queries. Automatically evicts least recently used entries
    when capacity is reached.
    
    Attributes:
        max_size: Maximum number of profiles to cache
        ttl_seconds: Time-to-live for cached entries in seconds
        cache: OrderedDict storing cache entries
        lock: Thread lock for thread-safe operations
        metrics: Cache performance metrics
    """
    
    def __init__(self, max_size: Optional[int] = None, ttl_seconds: Optional[int] = None):
        """
        Initialize profile cache
        
        Args:
            max_size: Maximum number of profiles to cache (default: 1000)
            ttl_seconds: Cache entry TTL in seconds (default: 3600 = 1 hour)
        """
        from .service_constants import SERVICE_CONSTANTS
        
        self.max_size = max_size or SERVICE_CONSTANTS.PROFILE_CACHE_MAX_SIZE
        self.ttl_seconds = ttl_seconds or SERVICE_CONSTANTS.PROFILE_CACHE_TTL_SECONDS
        self.cache: OrderedDict[int, CacheEntry] = OrderedDict()
        self.lock = threading.Lock()
        
        # Metrics
        self.metrics = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'invalidations': 0,
            'total_requests': 0,
            'current_size': 0
        }
        
        logger.info(
            f"ProfileCache initialized with max_size={self.max_size}, "
            f"ttl_seconds={self.ttl_seconds}"
        )
    
    async def get(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get profile from cache
        
        Args:
            user_id: User ID to lookup
            
        Returns:
            Profile data if cached and not expired, None otherwise
        """
        with self.lock:
            self.metrics['total_requests'] += 1
            
            if user_id not in self.cache:
                self.metrics['misses'] += 1
                logger.debug(f"Cache miss for user {user_id}")
                return None
            
            entry = self.cache[user_id]
            
            # Check if expired
            age = (datetime.utcnow() - entry.cached_at).total_seconds()
            if age > self.ttl_seconds:
                logger.debug(
                    f"Cache entry for user {user_id} expired "
                    f"(age: {age:.1f}s, TTL: {self.ttl_seconds}s)"
                )
                del self.cache[user_id]
                self.metrics['misses'] += 1
                self.metrics['current_size'] = len(self.cache)
                return None
            
            # Cache hit - move to end (most recently used)
            self.cache.move_to_end(user_id)
            entry.hit_count += 1
            entry.last_accessed = datetime.utcnow()
            self.metrics['hits'] += 1
            
            logger.debug(
                f"Cache hit for user {user_id} "
                f"(age: {age:.1f}s, hits: {entry.hit_count})"
            )
            
            return entry.profile_data
    
    async def set(self, user_id: int, profile_data: Dict[str, Any]) -> None:
        """
        Store profile in cache
        
        Args:
            user_id: User ID
            profile_data: Profile data to cache
        """
        with self.lock:
            # Check if we need to evict
            if len(self.cache) >= self.max_size and user_id not in self.cache:
                # Remove least recently used (first item)
                evicted_user_id, evicted_entry = self.cache.popitem(last=False)
                self.metrics['evictions'] += 1
                logger.debug(
                    f"Evicted cache entry for user {evicted_user_id} "
                    f"(hits: {evicted_entry.hit_count})"
                )
            
            # Add or update entry
            entry = CacheEntry(
                profile_data=profile_data,
                user_id=user_id,
                cached_at=datetime.utcnow()
            )
            self.cache[user_id] = entry
            self.cache.move_to_end(user_id)  # Mark as most recently used
            self.metrics['current_size'] = len(self.cache)
            
            logger.debug(f"Cached profile for user {user_id}")
    
    async def invalidate(self, user_id: int) -> bool:
        """
        Invalidate (remove) cached profile for user
        
        Args:
            user_id: User ID to invalidate
            
        Returns:
            True if entry was removed, False if not found
        """
        with self.lock:
            if user_id in self.cache:
                del self.cache[user_id]
                self.metrics['invalidations'] += 1
                self.metrics['current_size'] = len(self.cache)
                logger.debug(f"Invalidated cache for user {user_id}")
                return True
            return False
    
    async def clear(self) -> int:
        """
        Clear all cached profiles
        
        Returns:
            Number of entries cleared
        """
        with self.lock:
            count = len(self.cache)
            self.cache.clear()
            self.metrics['current_size'] = 0
            logger.info(f"Cleared {count} cache entries")
            return count
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        
        Returns:
            Dictionary with cache performance metrics
        """
        with self.lock:
            total_requests = self.metrics['total_requests']
            hits = self.metrics['hits']
            
            hit_rate = (hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'max_size': self.max_size,
                'current_size': len(self.cache),
                'ttl_seconds': self.ttl_seconds,
                'total_requests': total_requests,
                'hits': hits,
                'misses': self.metrics['misses'],
                'hit_rate': round(hit_rate, 2),
                'evictions': self.metrics['evictions'],
                'invalidations': self.metrics['invalidations']
            }
    
    async def cleanup_expired(self) -> int:
        """
        Remove all expired entries from cache
        
        Returns:
            Number of entries removed
        """
        with self.lock:
            now = datetime.utcnow()
            expired_users = []
            
            for user_id, entry in self.cache.items():
                age = (now - entry.cached_at).total_seconds()
                if age > self.ttl_seconds:
                    expired_users.append(user_id)
            
            for user_id in expired_users:
                del self.cache[user_id]
            
            self.metrics['current_size'] = len(self.cache)
            
            if expired_users:
                logger.info(f"Cleaned up {len(expired_users)} expired cache entries")
            
            return len(expired_users)


# Global cache instance
_profile_cache: Optional[ProfileCache] = None


def get_profile_cache() -> ProfileCache:
    """
    Get global profile cache instance (singleton)
    
    Returns:
        Global ProfileCache instance
    """
    global _profile_cache
    if _profile_cache is None:
        from .service_constants import SERVICE_CONSTANTS
        _profile_cache = ProfileCache(
            max_size=SERVICE_CONSTANTS.PROFILE_CACHE_MAX_SIZE,
            ttl_seconds=SERVICE_CONSTANTS.PROFILE_CACHE_TTL_SECONDS
        )
    return _profile_cache


async def start_cache_cleanup_task():
    """
    Background task to periodically clean up expired cache entries
    
    Runs every 5 minutes to remove expired entries and free memory.
    """
    cache = get_profile_cache()
    
    from .service_constants import SERVICE_CONSTANTS
    
    while True:
        try:
            await asyncio.sleep(SERVICE_CONSTANTS.PROFILE_CACHE_CLEANUP_INTERVAL)
            removed = await cache.cleanup_expired()
            if removed > 0:
                logger.info(f"Cache cleanup removed {removed} expired entries")
        except Exception as e:
            logger.error(f"Error in cache cleanup task: {e}")
