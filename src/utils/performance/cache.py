"""
Response Caching Utilities
Provides intelligent caching for API responses using Redis and in-memory fallback
"""
import os
import json
import hashlib
import fnmatch
from typing import Any, Optional, Callable, TypeVar, Union, List
from functools import wraps
from datetime import timedelta
import asyncio

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None  # type: ignore

from ..logger import setup_logger

logger = setup_logger(__name__)

# Type variable for generic functions
T = TypeVar('T')

class CacheConfig:
    """Cache configuration"""
    # Redis connection settings
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    REDIS_ENABLED = os.getenv('CACHE_ENABLED', 'false').lower() == 'true'
    
    # Redis connection timeouts (in seconds)
    REDIS_CONNECT_TIMEOUT = 5  # Socket connection timeout
    REDIS_SOCKET_TIMEOUT = 5  # Socket operation timeout
    REDIS_ENCODING = 'utf-8'  # Default encoding for Redis responses
    
    # Cache TTLs (in seconds)
    DEFAULT_TTL = int(os.getenv('CACHE_DEFAULT_TTL', '300'))  # 5 minutes
    EMAIL_LIST_TTL = int(os.getenv('CACHE_EMAIL_LIST_TTL', '60'))  # 1 minute
    EMAIL_SEARCH_TTL = int(os.getenv('CACHE_EMAIL_SEARCH_TTL', '300'))  # 5 minutes
    CALENDAR_LIST_TTL = int(os.getenv('CACHE_CALENDAR_LIST_TTL', '300'))  # 5 minutes
    USER_PROFILE_TTL = int(os.getenv('CACHE_USER_PROFILE_TTL', '600'))  # 10 minutes
    LLM_RESPONSE_TTL = int(os.getenv('CACHE_LLM_RESPONSE_TTL', '3600'))  # 1 hour
    
    # In-memory cache settings
    MAX_MEMORY_CACHE_SIZE = int(os.getenv('CACHE_MAX_MEMORY_SIZE', '1000'))
    
    # Cache key generation settings
    MAX_CACHE_KEY_LENGTH = 200  # Maximum cache key length before hashing
    CACHE_KEY_HASH_LENGTH = 16  # Length of hash suffix for long keys
    
    # Cache key prefixes
    PREFIX_EMAIL = "email:"
    PREFIX_CALENDAR = "calendar:"
    PREFIX_LLM = "llm:"
    PREFIX_USER = "user:"
    PREFIX_SEARCH = "search:"
    
    # User cache invalidation pattern
    USER_CACHE_PATTERN_TEMPLATE = "*:user{user_id}:*"  # Pattern for user cache invalidation


class InMemoryCache:
    """Simple in-memory LRU cache as fallback"""
    
    def __init__(self, max_size: int = CacheConfig.MAX_MEMORY_CACHE_SIZE):
        self.cache = {}
        self.max_size = max_size
        self.access_order = []
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from cache"""
        if key in self.cache:
            # Update access order (LRU)
            self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        return None
    
    async def set(self, key: str, value: str, ttl: int = None) -> None:
        """Set value in cache"""
        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size and key not in self.cache:
            oldest = self.access_order.pop(0)
            del self.cache[oldest]
        
        self.cache[key] = value
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
    
    async def delete(self, key: str) -> None:
        """Delete value from cache"""
        if key in self.cache:
            del self.cache[key]
            self.access_order.remove(key)
    
    async def clear(self) -> None:
        """Clear all cache"""
        self.cache.clear()
        self.access_order.clear()
    
    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete cache entries matching pattern
        
        Args:
            pattern: Cache key pattern (e.g., 'email:user123:*')
            
        Returns:
            Number of keys deleted
        """
        deleted_count = 0
        keys_to_delete = [
            key for key in self.cache.keys()
            if fnmatch.fnmatch(key, pattern)
        ]
        
        for key in keys_to_delete:
            if key in self.cache:
                del self.cache[key]
                if key in self.access_order:
                    self.access_order.remove(key)
                deleted_count += 1
        
        return deleted_count
    
    async def close(self) -> None:
        """Close cache (no-op for in-memory)"""
        pass


class RedisCache:
    """Redis-based cache"""
    
    def __init__(self, redis_url: str = CacheConfig.REDIS_URL):
        self.redis_url = redis_url
        self._client: Optional["aioredis.Redis"] = None  # type: ignore
    
    async def _get_client(self) -> "aioredis.Redis":  # type: ignore
        """Get or create Redis client"""
        if self._client is None:
            if not REDIS_AVAILABLE or aioredis is None:
                raise ImportError("redis package not installed")
            self._client = aioredis.from_url(
                self.redis_url,
                encoding=CacheConfig.REDIS_ENCODING,
                decode_responses=True,
                socket_connect_timeout=CacheConfig.REDIS_CONNECT_TIMEOUT,
                socket_timeout=CacheConfig.REDIS_SOCKET_TIMEOUT
            )
        return self._client
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from Redis"""
        try:
            client = await self._get_client()
            return await client.get(key)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None
    
    async def set(self, key: str, value: str, ttl: int = None) -> None:
        """Set value in Redis with TTL"""
        try:
            client = await self._get_client()
            if ttl:
                await client.setex(key, ttl, value)
            else:
                await client.set(key, value)
        except Exception as e:
            logger.warning(f"Redis set error: {e}")
    
    async def delete(self, key: str) -> None:
        """Delete value from Redis"""
        try:
            client = await self._get_client()
            await client.delete(key)
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")
    
    async def clear(self) -> None:
        """Clear all cache"""
        try:
            client = await self._get_client()
            await client.flushdb()
        except Exception as e:
            logger.warning(f"Redis clear error: {e}")
    
    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete cache entries matching pattern using Redis SCAN
        
        Args:
            pattern: Cache key pattern (e.g., 'email:user123:*')
            
        Returns:
            Number of keys deleted
        """
        deleted_count = 0
        try:
            client = await self._get_client()
            # Use SCAN to iterate through keys matching pattern
            async for key in client.scan_iter(match=pattern):
                await client.delete(key)
                deleted_count += 1
        except Exception as e:
            logger.warning(f"Redis delete_pattern error: {e}")
        
        return deleted_count
    
    async def close(self) -> None:
        """Close Redis connection"""
        if self._client:
            await self._client.close()


class CacheManager:
    """Unified cache manager with automatic fallback"""
    
    def __init__(self):
        self._cache = None
        self._initialized = False
    
    async def _initialize(self):
        """Initialize cache backend"""
        if self._initialized:
            return
        
        if not CacheConfig.REDIS_ENABLED:
            logger.info("Cache disabled via CACHE_ENABLED=false")
            self._cache = None
            self._initialized = True
            return
        
        if REDIS_AVAILABLE:
            try:
                self._cache = RedisCache()
                # Test connection
                await self._cache.get("test")
                logger.info("Redis cache initialized successfully")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}, falling back to in-memory cache")
                self._cache = InMemoryCache()
        else:
            logger.warning("redis package not installed, using in-memory cache")
            self._cache = InMemoryCache()
        
        self._initialized = True
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from cache"""
        await self._initialize()
        if self._cache is None:
            return None
        return await self._cache.get(key)
    
    async def set(self, key: str, value: str, ttl: int = CacheConfig.DEFAULT_TTL) -> None:
        """Set value in cache with TTL"""
        await self._initialize()
        if self._cache is None:
            return
        await self._cache.set(key, value, ttl)
    
    async def delete(self, key: str) -> None:
        """Delete value from cache"""
        await self._initialize()
        if self._cache is None:
            return
        await self._cache.delete(key)
    
    async def clear(self) -> None:
        """Clear all cache"""
        await self._initialize()
        if self._cache is None:
            return
        await self._cache.clear()
    
    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete cache entries matching pattern
        
        Args:
            pattern: Cache key pattern (e.g., 'email:user123:*')
            
        Returns:
            Number of keys deleted
        """
        await self._initialize()
        if self._cache is None:
            return 0
        return await self._cache.delete_pattern(pattern)
    
    async def close(self) -> None:
        """Close cache connection"""
        if self._cache:
            await self._cache.close()


# Global cache instance
_cache_manager = CacheManager()


async def get_cache_manager() -> CacheManager:
    """Get the global cache manager"""
    return _cache_manager


def generate_cache_key(prefix: str, *args, **kwargs) -> str:
    """
    Generate a cache key from arguments
    
    Args:
        prefix: Cache key prefix (e.g., 'email:', 'calendar:')
        *args: Positional arguments to include in key
        **kwargs: Keyword arguments to include in key
    
    Returns:
        Cache key string
    """
    # Create a deterministic string from args and kwargs
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_string = ":".join(key_parts)
    
    # Hash if too long
    if len(key_string) > CacheConfig.MAX_CACHE_KEY_LENGTH:
        key_hash = hashlib.sha256(key_string.encode()).hexdigest()[:CacheConfig.CACHE_KEY_HASH_LENGTH]
        return f"{prefix}{key_hash}"
    
    return f"{prefix}{key_string}"


def cached(
    ttl: int = CacheConfig.DEFAULT_TTL,
    prefix: str = "",
    key_builder: Optional[Callable] = None
):
    """
    Decorator to cache function results
    
    Args:
        ttl: Time to live in seconds
        prefix: Cache key prefix
        key_builder: Optional custom key builder function
    
    Example:
        @cached(ttl=CacheConfig.EMAIL_LIST_TTL, prefix=CacheConfig.PREFIX_EMAIL)
        async def get_emails(user_id: str, folder: str):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # Generate cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = generate_cache_key(prefix, *args, **kwargs)
            
            # Try to get from cache
            cache_manager = await get_cache_manager()
            cached_value = await cache_manager.get(cache_key)
            
            if cached_value is not None:
                try:
                    logger.debug(f"Cache hit: {cache_key}")
                    return json.loads(cached_value)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode cached value for {cache_key}")
            
            # Cache miss - execute function
            logger.debug(f"Cache miss: {cache_key}")
            result = await func(*args, **kwargs)
            
            # Store in cache
            try:
                await cache_manager.set(cache_key, json.dumps(result), ttl)
            except (TypeError, ValueError) as e:
                logger.warning(f"Failed to cache result for {cache_key}: {e}")
            
            return result
        
        return wrapper
    return decorator


async def invalidate_cache(pattern: str) -> int:
    """
    Invalidate cache entries matching pattern
    
    Supports both Redis (using SCAN) and in-memory cache (using fnmatch).
    
    Args:
        pattern: Cache key pattern (e.g., 'email:user123:*')
    
    Returns:
        Number of cache entries invalidated
    """
    cache_manager = await get_cache_manager()
    
    try:
        deleted_count = await cache_manager.delete_pattern(pattern)
        if deleted_count > 0:
            logger.info(f"Invalidated {deleted_count} cache entries matching pattern: {pattern}")
        else:
            logger.debug(f"No cache entries found matching pattern: {pattern}")
        return deleted_count
    except Exception as e:
        logger.error(f"Failed to invalidate cache pattern '{pattern}': {e}")
        return 0


async def invalidate_user_cache(user_id: str) -> int:
    """
    Invalidate all cache for a specific user
    
    Args:
        user_id: User ID to invalidate cache for
    
    Returns:
        Number of cache entries invalidated
    """
    pattern = CacheConfig.USER_CACHE_PATTERN_TEMPLATE.format(user_id=user_id)
    return await invalidate_cache(pattern)


# Cache statistics
class CacheStats:
    """Track cache performance"""
    hits = 0
    misses = 0
    errors = 0
    
    @classmethod
    def hit_rate(cls) -> float:
        """Calculate cache hit rate"""
        total = cls.hits + cls.misses
        return cls.hits / total if total > 0 else 0.0
    
    @classmethod
    def reset(cls):
        """Reset statistics"""
        cls.hits = 0
        cls.misses = 0
        cls.errors = 0
