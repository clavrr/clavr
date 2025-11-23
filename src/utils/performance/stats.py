"""
API Usage Statistics Tracker
Redis-backed statistics collection for monitoring and analytics
"""
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from ..logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class APIStats:
    """API statistics data class"""
    total_queries: int = 0
    active_users_today: int = 0
    active_users_this_week: int = 0
    uptime_hours: float = 0.0
    cache_hit_rate: float = 0.0
    avg_response_time_ms: float = 0.0


class StatsTracker:
    """
    Track API usage statistics with Redis backend
    
    Features:
    - Query counting (total and per-user)
    - Active user tracking (daily and weekly)
    - Uptime calculation
    - Cache hit rate monitoring
    - Response time tracking
    
    Example:
        tracker = StatsTracker()
        await tracker.increment_query_count(user_id=123)
        stats = await tracker.get_stats()
    """
    
    def __init__(self, redis_url: Optional[str] = None, start_time: Optional[datetime] = None):
        """
        Initialize stats tracker
        
        Args:
            redis_url: Redis connection URL (defaults to REDIS_URL env var)
            start_time: API start time for uptime calculation (defaults to now)
        """
        self.redis_url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self.start_time = start_time or datetime.now()
        self.redis_client: Optional[aioredis.Redis] = None
        self._fallback_stats = {
            'total_queries': 0,
            'active_users': set()
        }
    
    async def initialize(self) -> None:
        """Initialize Redis connection"""
        if not REDIS_AVAILABLE:
            logger.warning("Redis not available - using in-memory stats fallback")
            return
        
        try:
            self.redis_client = await aioredis.from_url(
                self.redis_url,
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("Stats tracker initialized with Redis backend")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis for stats: {e}. Using fallback.")
            self.redis_client = None
    
    async def close(self) -> None:
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
    
    async def increment_query_count(self, user_id: Optional[int] = None) -> None:
        """
        Increment total query count and optionally per-user count
        
        Args:
            user_id: Optional user ID for per-user tracking
        """
        try:
            if self.redis_client:
                # Increment total queries
                await self.redis_client.incr("stats:total_queries")
                
                # Increment per-user queries if user_id provided
                if user_id:
                    await self.redis_client.incr(f"stats:user:{user_id}:queries")
                    
                logger.debug(f"Incremented query count (user_id={user_id})")
            else:
                # Fallback
                self._fallback_stats['total_queries'] += 1
        except Exception as e:
            logger.error(f"Failed to increment query count: {e}")
    
    async def record_active_user(self, user_id: int) -> None:
        """
        Record an active user for today and this week
        
        Args:
            user_id: User ID to record
        """
        try:
            if self.redis_client:
                today = datetime.now().strftime("%Y-%m-%d")
                week = datetime.now().strftime("%Y-W%U")
                
                # Add to daily active users set
                await self.redis_client.sadd(f"stats:active_users:day:{today}", str(user_id))
                
                # Add to weekly active users set
                await self.redis_client.sadd(f"stats:active_users:week:{week}", str(user_id))
                
                # Set expiry on daily key (keep for 7 days)
                await self.redis_client.expire(f"stats:active_users:day:{today}", 7 * 24 * 3600)
                
                # Set expiry on weekly key (keep for 4 weeks)
                await self.redis_client.expire(f"stats:active_users:week:{week}", 28 * 24 * 3600)
                
                logger.debug(f"Recorded active user {user_id}")
            else:
                # Fallback
                self._fallback_stats['active_users'].add(user_id)
        except Exception as e:
            logger.error(f"Failed to record active user: {e}")
    
    async def record_response_time(self, duration_ms: float) -> None:
        """
        Record API response time for averaging
        
        Args:
            duration_ms: Response duration in milliseconds
        """
        try:
            if self.redis_client:
                # Use sorted set with timestamp as score for time-based cleanup
                timestamp = datetime.now().timestamp()
                await self.redis_client.zadd(
                    "stats:response_times",
                    {str(duration_ms): timestamp}
                )
                
                # Keep only last 1000 response times
                await self.redis_client.zremrangebyrank("stats:response_times", 0, -1001)
        except Exception as e:
            logger.error(f"Failed to record response time: {e}")
    
    async def increment_cache_hit(self) -> None:
        """Increment cache hit counter"""
        try:
            if self.redis_client:
                await self.redis_client.incr("stats:cache_hits")
        except Exception as e:
            logger.error(f"Failed to increment cache hit: {e}")
    
    async def increment_cache_miss(self) -> None:
        """Increment cache miss counter"""
        try:
            if self.redis_client:
                await self.redis_client.incr("stats:cache_misses")
        except Exception as e:
            logger.error(f"Failed to increment cache miss: {e}")
    
    async def get_stats(self) -> APIStats:
        """
        Get current API statistics
        
        Returns:
            APIStats object with current statistics
        """
        try:
            if self.redis_client:
                # Get all stats from Redis
                total_queries = await self.redis_client.get("stats:total_queries") or "0"
                
                today = datetime.now().strftime("%Y-%m-%d")
                week = datetime.now().strftime("%Y-W%U")
                active_users_today = await self.redis_client.scard(f"stats:active_users:day:{today}")
                active_users_week = await self.redis_client.scard(f"stats:active_users:week:{week}")
                
                # Calculate cache hit rate
                cache_hits = int(await self.redis_client.get("stats:cache_hits") or "0")
                cache_misses = int(await self.redis_client.get("stats:cache_misses") or "0")
                total_cache_requests = cache_hits + cache_misses
                cache_hit_rate = (cache_hits / total_cache_requests * 100) if total_cache_requests > 0 else 0.0
                
                # Calculate average response time
                response_times = await self.redis_client.zrange("stats:response_times", 0, -1)
                avg_response_time = sum(float(t) for t in response_times) / len(response_times) if response_times else 0.0
                
                # Calculate uptime
                uptime = (datetime.now() - self.start_time).total_seconds() / 3600
                
                return APIStats(
                    total_queries=int(total_queries),
                    active_users_today=active_users_today,
                    active_users_this_week=active_users_week,
                    uptime_hours=round(uptime, 2),
                    cache_hit_rate=round(cache_hit_rate, 2),
                    avg_response_time_ms=round(avg_response_time, 2)
                )
            else:
                # Fallback
                uptime = (datetime.now() - self.start_time).total_seconds() / 3600
                return APIStats(
                    total_queries=self._fallback_stats['total_queries'],
                    active_users_today=len(self._fallback_stats['active_users']),
                    active_users_this_week=len(self._fallback_stats['active_users']),
                    uptime_hours=round(uptime, 2),
                    cache_hit_rate=0.0,
                    avg_response_time_ms=0.0
                )
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return APIStats()
    
    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Get statistics for a specific user
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary with user-specific statistics
        """
        try:
            if self.redis_client:
                total_queries = await self.redis_client.get(f"stats:user:{user_id}:queries") or "0"
                
                return {
                    "user_id": user_id,
                    "total_queries": int(total_queries)
                }
            else:
                return {"user_id": user_id, "total_queries": 0}
        except Exception as e:
            logger.error(f"Failed to get user stats: {e}")
            return {"user_id": user_id, "total_queries": 0, "error": str(e)}


# Global stats tracker instance
_stats_tracker: Optional[StatsTracker] = None


async def get_stats_tracker() -> StatsTracker:
    """Get or create global stats tracker instance"""
    global _stats_tracker
    
    if _stats_tracker is None:
        _stats_tracker = StatsTracker()
        await _stats_tracker.initialize()
    
    return _stats_tracker


async def shutdown_stats_tracker() -> None:
    """Shutdown global stats tracker"""
    global _stats_tracker
    
    if _stats_tracker:
        await _stats_tracker.close()
        _stats_tracker = None
