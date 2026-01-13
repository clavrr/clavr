"""
Rate Limiting Middleware for API Protection
Prevents abuse and DoS attacks
"""
import time
from typing import Dict, Tuple
from collections import defaultdict
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class RateLimiter:
    """
    Simple in-memory rate limiter using token bucket algorithm
    
    For production, consider using Redis for distributed rate limiting.
    """
    
    def __init__(self, requests_per_minute: int = 300, requests_per_hour: int = 5000):
        """
        Initialize rate limiter
        
        Args:
            requests_per_minute: Maximum requests per minute per client
            requests_per_hour: Maximum requests per hour per client
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        
        # Track requests: {client_id: [(timestamp, count), ...]}
        self.minute_buckets: Dict[str, list] = defaultdict(list)
        self.hour_buckets: Dict[str, list] = defaultdict(list)
        
        logger.info(f"[OK] Rate limiter initialized: {requests_per_minute}/min, {requests_per_hour}/hour")
    
    def _clean_old_requests(self, bucket: Dict[str, list], window_seconds: int):
        """Remove requests older than the time window"""
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        for client_id in list(bucket.keys()):
            # Remove old timestamps
            bucket[client_id] = [ts for ts in bucket[client_id] if ts > cutoff_time]
            
            # Clean up empty entries
            if not bucket[client_id]:
                del bucket[client_id]
    
    def is_allowed(self, client_id: str) -> Tuple[bool, str]:
        """
        Check if request is allowed for client
        
        Args:
            client_id: Unique client identifier (IP, user ID, API key)
            
        Returns:
            (is_allowed, reason) tuple
        """
        current_time = time.time()
        
        # Clean old requests
        self._clean_old_requests(self.minute_buckets, 60)
        self._clean_old_requests(self.hour_buckets, 3600)
        
        # Check minute limit
        minute_requests = len(self.minute_buckets[client_id])
        if minute_requests >= self.requests_per_minute:
            return False, f"Rate limit exceeded: {self.requests_per_minute} requests per minute"
        
        # Check hour limit
        hour_requests = len(self.hour_buckets[client_id])
        if hour_requests >= self.requests_per_hour:
            return False, f"Rate limit exceeded: {self.requests_per_hour} requests per hour"
        
        # Record request
        self.minute_buckets[client_id].append(current_time)
        self.hour_buckets[client_id].append(current_time)
        
        return True, ""
    
    def get_stats(self, client_id: str) -> Dict[str, int]:
        """Get current usage stats for client"""
        return {
            "requests_last_minute": len(self.minute_buckets.get(client_id, [])),
            "requests_last_hour": len(self.hour_buckets.get(client_id, [])),
            "limit_per_minute": self.requests_per_minute,
            "limit_per_hour": self.requests_per_hour
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting
    """
    
    def __init__(self, app, requests_per_minute: int = 300, requests_per_hour: int = 5000):
        super().__init__(app)
        self.rate_limiter = RateLimiter(requests_per_minute, requests_per_hour)
        
        # Endpoints to exclude from rate limiting
        self.excluded_paths = {
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/auth/me",  # Temporarily exclude during development
            "/auth/google/login",
            "/auth/google/callback",
            "/auth/session/status",  # Lightweight polling endpoint
        }
    
    async def dispatch(self, request: Request, call_next):
        """
        Process request and apply rate limiting
        """
        # Skip rate limiting for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)
        
        # Get client identifier (prefer user_id, fallback to IP)
        client_id = self._get_client_id(request)
        
        # Check rate limit
        is_allowed, reason = self.rate_limiter.is_allowed(client_id)
        
        if not is_allowed:
            logger.warning(f"[RATE LIMIT] Blocked request from {client_id}: {reason}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=reason,
                headers={"Retry-After": "60"}
            )
        
        # Add rate limit headers to response
        response = await call_next(request)
        stats = self.rate_limiter.get_stats(client_id)
        
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
        Get unique client identifier
        
        Priority:
        1. Authenticated user ID
        2. API key (if present)
        3. Client IP address
        """
        # Check for authenticated user
        if hasattr(request.state, 'user') and request.state.user:
            return f"user:{request.state.user.id}"
        
        # Check for session
        if hasattr(request.state, 'session') and request.state.session:
            return f"session:{request.state.session.id}"
        
        # Fallback to IP address
        # Handle proxies (X-Forwarded-For header)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Get first IP in chain (actual client)
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        
        return f"ip:{client_ip}"
