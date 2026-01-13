"""
Distributed Rate Limiter with Redis Support

Provides rate limiting that works across multiple server instances.
Falls back to in-memory limiting if Redis is not available.
"""
import os
import time
import asyncio
from typing import Dict, Tuple, Optional
from collections import defaultdict
from abc import ABC, abstractmethod
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class RateLimitStorage(ABC):
    """Abstract base class for rate limit storage backends."""
    
    @abstractmethod
    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Check if request is allowed and record it.
        
        Args:
            key: Unique identifier for the client
            limit: Maximum requests allowed in window
            window_seconds: Time window in seconds
            
        Returns:
            (is_allowed, current_count) tuple
        """
        pass
    
    @abstractmethod
    async def get_stats(self, key: str, window_seconds: int) -> int:
        """Get current request count for key within window."""
        pass


class InMemoryStorage(RateLimitStorage):
    """In-memory rate limit storage (single server only)."""
    
    def __init__(self):
        self.buckets: Dict[str, list] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    def _clean_old_requests(self, key: str, window_seconds: int):
        """Remove requests older than the time window."""
        cutoff = time.time() - window_seconds
        self.buckets[key] = [ts for ts in self.buckets[key] if ts > cutoff]
    
    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        async with self._lock:
            self._clean_old_requests(key, window_seconds)
            current_count = len(self.buckets[key])
            
            if current_count >= limit:
                return False, current_count
            
            self.buckets[key].append(time.time())
            return True, current_count + 1
    
    async def get_stats(self, key: str, window_seconds: int) -> int:
        async with self._lock:
            self._clean_old_requests(key, window_seconds)
            return len(self.buckets[key])


class RedisStorage(RateLimitStorage):
    """Redis-backed rate limit storage (distributed)."""
    
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._client = None
    
    async def _get_client(self):
        """Lazy-load Redis client."""
        if self._client is None:
            try:
                import redis.asyncio as redis
                self._client = redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
                # Test connection
                await self._client.ping()
                logger.info("[OK] Redis rate limiter connected")
            except ImportError:
                logger.warning("redis package not installed, falling back to in-memory")
                return None
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}, falling back to in-memory")
                return None
        return self._client
    
    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        client = await self._get_client()
        if client is None:
            return True, 0  # Allow if Redis unavailable
        
        try:
            redis_key = f"ratelimit:{key}:{window_seconds}"
            current_time = int(time.time())
            window_start = current_time - window_seconds
            
            # Use Redis pipeline for atomic operations
            async with client.pipeline(transaction=True) as pipe:
                # Remove old entries
                pipe.zremrangebyscore(redis_key, 0, window_start)
                # Add current request
                pipe.zadd(redis_key, {str(current_time): current_time})
                # Count requests in window
                pipe.zcard(redis_key)
                # Set TTL
                pipe.expire(redis_key, window_seconds + 1)
                
                results = await pipe.execute()
                current_count = results[2]
            
            if current_count > limit:
                # Remove the request we just added (over limit)
                await client.zrem(redis_key, str(current_time))
                return False, current_count - 1
            
            return True, current_count
            
        except Exception as e:
            logger.error(f"Redis rate limit error: {e}")
            return True, 0  # Allow on error
    
    async def get_stats(self, key: str, window_seconds: int) -> int:
        client = await self._get_client()
        if client is None:
            return 0
        
        try:
            redis_key = f"ratelimit:{key}:{window_seconds}"
            current_time = int(time.time())
            window_start = current_time - window_seconds
            
            # Count entries in time window
            count = await client.zcount(redis_key, window_start, current_time)
            return count
        except Exception as e:
            logger.error(f"Redis stats error: {e}")
            return 0


class DistributedRateLimiter:
    """
    Distributed rate limiter with Redis support.
    
    Features:
    - Dual limits: per-minute and per-hour
    - Automatic fallback to in-memory if Redis unavailable
    - Smart client identification (user > session > IP)
    """
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        redis_url: Optional[str] = None
    ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        
        # Initialize storage backend
        redis_url = redis_url or os.getenv("REDIS_URL")
        
        if redis_url:
            self.storage = RedisStorage(redis_url)
            self._fallback_storage = InMemoryStorage()
            logger.info(f"[OK] Distributed rate limiter initialized (Redis: {redis_url[:30]}...)")
        else:
            self.storage = InMemoryStorage()
            self._fallback_storage = None
            logger.info("[OK] Rate limiter initialized (in-memory mode)")
    
    async def is_allowed(self, client_id: str) -> Tuple[bool, str]:
        """
        Check if request is allowed for client.
        
        Args:
            client_id: Unique client identifier
            
        Returns:
            (is_allowed, reason) tuple
        """
        try:
            # Check minute limit
            minute_key = f"{client_id}:minute"
            allowed_minute, minute_count = await self.storage.is_allowed(
                minute_key, self.requests_per_minute, 60
            )
            
            if not allowed_minute:
                return False, f"Rate limit exceeded: {self.requests_per_minute} requests per minute"
            
            # Check hour limit
            hour_key = f"{client_id}:hour"
            allowed_hour, hour_count = await self.storage.is_allowed(
                hour_key, self.requests_per_hour, 3600
            )
            
            if not allowed_hour:
                return False, f"Rate limit exceeded: {self.requests_per_hour} requests per hour"
            
            return True, ""
            
        except Exception as e:
            logger.error(f"Rate limiter error: {e}")
            # Allow on error to prevent blocking legitimate traffic
            return True, ""
    
    async def get_stats(self, client_id: str) -> Dict[str, int]:
        """Get current usage stats for client."""
        try:
            minute_count = await self.storage.get_stats(f"{client_id}:minute", 60)
            hour_count = await self.storage.get_stats(f"{client_id}:hour", 3600)
            
            return {
                "requests_last_minute": minute_count,
                "requests_last_hour": hour_count,
                "limit_per_minute": self.requests_per_minute,
                "limit_per_hour": self.requests_per_hour
            }
        except Exception as e:
            logger.error(f"Rate limiter stats error: {e}")
            return {
                "requests_last_minute": 0,
                "requests_last_hour": 0,
                "limit_per_minute": self.requests_per_minute,
                "limit_per_hour": self.requests_per_hour
            }


class DistributedRateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for distributed rate limiting.
    """
    
    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        redis_url: Optional[str] = None,
        excluded_paths: Optional[list] = None
    ):
        super().__init__(app)
        self.rate_limiter = DistributedRateLimiter(
            requests_per_minute=requests_per_minute,
            requests_per_hour=requests_per_hour,
            redis_url=redis_url
        )
        self.excluded_paths = set(excluded_paths) if excluded_paths else {
            "/health", "/docs", "/openapi.json", "/redoc", "/metrics",
            "/auth/google/login", "/auth/google/callback",
            "/api/auth/google/login", "/api/auth/google/callback",
            "/integrations/status", "/api/integrations/status",
            "/auth/session/status", "/api/auth/session/status",
            "/auth/me", "/api/auth/me", "/api/conversations"
        }
    
    async def dispatch(self, request: Request, call_next):
        """Process request and apply rate limiting."""
        
        # Skip rate limiting for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)
        
        # Get client identifier
        client_id = self._get_client_id(request)
        
        # Check rate limit
        is_allowed, reason = await self.rate_limiter.is_allowed(client_id)
        
        if not is_allowed:
            logger.warning(f"[RATE LIMIT] Blocked request from {client_id}: {reason}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": reason},
                headers={"Retry-After": "60"}
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        stats = await self.rate_limiter.get_stats(client_id)
        response.headers["X-RateLimit-Limit-Minute"] = str(stats["limit_per_minute"])
        response.headers["X-RateLimit-Limit-Hour"] = str(stats["limit_per_hour"])
        response.headers["X-RateLimit-Remaining-Minute"] = str(
            max(0, stats["limit_per_minute"] - stats["requests_last_minute"])
        )
        response.headers["X-RateLimit-Remaining-Hour"] = str(
            max(0, stats["limit_per_hour"] - stats["requests_last_hour"])
        )
        
        return response
    
    def _get_client_id(self, request: Request) -> str:
        """
        Get unique client identifier.
        
        Priority:
        1. Authenticated user ID
        2. Session ID
        3. API key
        4. Client IP address
        """
        # Check for authenticated user
        if hasattr(request.state, 'user') and request.state.user:
            return f"user:{request.state.user.id}"
        
        # Check for session
        if hasattr(request.state, 'session') and request.state.session:
            return f"session:{request.state.session.id}"
        
        # Check for API key
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"apikey:{api_key[:16]}"  # Use prefix for privacy
        
        # Fallback to IP address
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        
        return f"ip:{client_ip}"


# Backward compatibility - keep old class name
RateLimitMiddleware = DistributedRateLimitMiddleware
