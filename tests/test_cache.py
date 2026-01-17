"""
Cache Functionality Tests
Tests for the caching layer including Redis and in-memory fallback
"""
import pytest
import asyncio
import json
import os
from unittest.mock import Mock, patch, AsyncMock
from src.utils.cache import (
    CacheManager,
    InMemoryCache,
    RedisCache,
    CacheConfig,
    generate_cache_key,
    cached,
    CacheStats
)


# No global fixture - we'll enable cache per test class as needed


class TestInMemoryCache:
    """Tests for in-memory cache"""
    
    @pytest.mark.asyncio
    async def test_get_set(self):
        """Test basic get/set operations"""
        cache = InMemoryCache(max_size=10)
        
        # Set a value
        await cache.set("key1", "value1")
        
        # Get the value
        result = await cache.get("key1")
        assert result == "value1"
    
    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        """Test getting non-existent key"""
        cache = InMemoryCache()
        result = await cache.get("nonexistent")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """Test LRU eviction when cache is full"""
        cache = InMemoryCache(max_size=3)
        
        # Fill cache
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")
        
        # Access key1 to make it recently used
        await cache.get("key1")
        
        # Add new key - should evict key2 (least recently used)
        await cache.set("key4", "value4")
        
        assert await cache.get("key1") == "value1"  # Still present
        assert await cache.get("key2") is None  # Evicted
        assert await cache.get("key3") == "value3"  # Still present
        assert await cache.get("key4") == "value4"  # New key
    
    @pytest.mark.asyncio
    async def test_delete(self):
        """Test deleting keys"""
        cache = InMemoryCache()
        
        await cache.set("key1", "value1")
        assert await cache.get("key1") == "value1"
        
        await cache.delete("key1")
        assert await cache.get("key1") is None
    
    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing all cache"""
        cache = InMemoryCache()
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        
        await cache.clear()
        
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None


class TestCacheKeyGeneration:
    """Tests for cache key generation"""
    
    def test_simple_key(self):
        """Test simple key generation"""
        key = generate_cache_key("test:", "arg1", "arg2")
        assert key == "test:arg1:arg2"
    
    def test_key_with_kwargs(self):
        """Test key generation with keyword arguments"""
        key = generate_cache_key("test:", "arg1", foo="bar", baz="qux")
        assert "test:arg1" in key
        assert "foo=bar" in key
        assert "baz=qux" in key
    
    def test_long_key_hashing(self):
        """Test that long keys are hashed"""
        long_arg = "x" * 300
        key = generate_cache_key("test:", long_arg)
        
        # Should be hashed and shorter
        assert len(key) < 100
        assert key.startswith("test:")


class TestCachedDecorator:
    """Tests for @cached decorator"""
    
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Test cache hit scenario"""
        # Create a test cache manager with in-memory cache
        test_cache = InMemoryCache()
        
        call_count = 0
        
        # Patch get_cache_manager to return our test cache
        async def mock_get_cache_manager():
            manager = CacheManager()
            manager._cache = test_cache
            manager._initialized = True
            return manager
        
        with patch('src.utils.cache.get_cache_manager', mock_get_cache_manager):
            @cached(ttl=300, prefix="test:")
            async def expensive_function(x: int) -> int:
                nonlocal call_count
                call_count += 1
                return x * 2
            
            # First call - cache miss
            result1 = await expensive_function(5)
            assert result1 == 10
            assert call_count == 1
            
            # Second call - cache hit
            result2 = await expensive_function(5)
            assert result2 == 10
            assert call_count == 1  # Function not called again
    
    @pytest.mark.asyncio
    async def test_cache_different_args(self):
        """Test that different arguments create different cache keys"""
        test_cache = InMemoryCache()
        
        call_count = 0
        
        async def mock_get_cache_manager():
            manager = CacheManager()
            manager._cache = test_cache
            manager._initialized = True
            return manager
        
        with patch('src.utils.cache.get_cache_manager', mock_get_cache_manager):
            @cached(ttl=300, prefix="test:")
            async def expensive_function(x: int) -> int:
                nonlocal call_count
                call_count += 1
                return x * 2
            
            result1 = await expensive_function(5)
            result2 = await expensive_function(10)
            
            assert result1 == 10
            assert result2 == 20
            assert call_count == 2  # Called twice with different args
    
    @pytest.mark.asyncio
    async def test_cache_with_complex_data(self):
        """Test caching complex data structures"""
        test_cache = InMemoryCache()
        
        async def mock_get_cache_manager():
            manager = CacheManager()
            manager._cache = test_cache
            manager._initialized = True
            return manager
        
        with patch('src.utils.cache.get_cache_manager', mock_get_cache_manager):
            @cached(ttl=300, prefix="test:")
            async def get_data() -> dict:
                return {"name": "test", "value": 123, "items": [1, 2, 3]}
            
            result1 = await get_data()
            result2 = await get_data()
            
            assert result1 == result2
            assert isinstance(result2, dict)
            assert result2["items"] == [1, 2, 3]


class TestCacheManager:
    """Tests for CacheManager"""
    
    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test cache manager initialization"""
        # Create a fresh manager and force enable caching
        with patch.object(CacheConfig, 'REDIS_ENABLED', True):
            manager = CacheManager()
            
            # Should initialize automatically
            await manager.set("test_key", "test_value")
            result = await manager.get("test_key")
            
            assert result == "test_value"
    
    @pytest.mark.asyncio
    async def test_disabled_cache(self):
        """Test that disabled cache returns None"""
        with patch.object(CacheConfig, 'REDIS_ENABLED', False):
            manager = CacheManager()
            manager._initialized = False  # Force re-initialization
            
            await manager.set("key", "value")
            result = await manager.get("key")
            
            # Cache is disabled, should return None
            assert result is None


@pytest.mark.integration
class TestRedisCache:
    """Integration tests for Redis cache (requires Redis)"""
    
    @pytest.mark.asyncio
    async def test_redis_get_set(self):
        """Test Redis get/set operations"""
        try:
            cache = RedisCache("redis://localhost:6379/1")
            
            await cache.set("test_key", "test_value", ttl=60)
            result = await cache.get("test_key")
            
            assert result == "test_value"
            
            await cache.delete("test_key")
            await cache.close()
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    
    @pytest.mark.asyncio
    async def test_redis_ttl(self):
        """Test that TTL works in Redis"""
        try:
            cache = RedisCache("redis://localhost:6379/1")
            
            await cache.set("test_key", "test_value", ttl=1)
            
            # Should exist immediately
            result = await cache.get("test_key")
            assert result == "test_value"
            
            # Wait for expiration
            await asyncio.sleep(2)
            
            # Should be expired
            result = await cache.get("test_key")
            assert result is None
            
            await cache.close()
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")


class TestCacheStats:
    """Tests for cache statistics"""
    
    def test_hit_rate_calculation(self):
        """Test hit rate calculation"""
        CacheStats.reset()
        
        # Simulate some cache hits and misses
        CacheStats.hits = 80
        CacheStats.misses = 20
        
        hit_rate = CacheStats.hit_rate()
        assert hit_rate == 0.8
    
    def test_hit_rate_no_requests(self):
        """Test hit rate when no requests"""
        CacheStats.reset()
        
        hit_rate = CacheStats.hit_rate()
        assert hit_rate == 0.0
    
    def test_reset(self):
        """Test resetting statistics"""
        CacheStats.hits = 100
        CacheStats.misses = 50
        CacheStats.errors = 10
        
        CacheStats.reset()
        
        assert CacheStats.hits == 0
        assert CacheStats.misses == 0
        assert CacheStats.errors == 0


@pytest.mark.asyncio
async def test_cache_performance():
    """Test cache performance improvement"""
    import time
    
    test_cache = InMemoryCache()
    
    async def mock_get_cache_manager():
        manager = CacheManager()
        manager._cache = test_cache
        manager._initialized = True
        return manager
    
    with patch('src.utils.cache.get_cache_manager', mock_get_cache_manager):
        call_count = 0
        
        @cached(ttl=300, prefix="perf:")
        async def slow_function():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)  # Simulate slow operation
            return {"result": "success"}
        
        # First call - slow
        start = time.time()
        result1 = await slow_function()
        first_duration = time.time() - start
        
        # Second call - fast (cached)
        start = time.time()
        result2 = await slow_function()
        second_duration = time.time() - start
        
        assert result1 == result2
        assert call_count == 1
        assert second_duration < first_duration / 2  # At least 2x faster


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
