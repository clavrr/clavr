"""
Performance Utilities

Provides caching, statistics tracking, and performance monitoring utilities.
"""

from .performance import (
    PerformanceMonitor,
    get_monitor,
    track_performance,
    PerformanceContext,
    Metrics
)
from .cache import (
    CacheConfig,
    CacheManager,
    get_cache_manager,
    generate_cache_key,
    cached,
    invalidate_cache,
    invalidate_user_cache,
    CacheStats
)
from .stats import (
    APIStats,
    StatsTracker,
    get_stats_tracker,
    shutdown_stats_tracker
)

__all__ = [
    # Performance monitoring
    "PerformanceMonitor",
    "get_monitor",
    "track_performance",
    "PerformanceContext",
    "Metrics",
    # Caching
    "CacheConfig",
    "CacheManager",
    "get_cache_manager",
    "generate_cache_key",
    "cached",
    "invalidate_cache",
    "invalidate_user_cache",
    "CacheStats",
    # Statistics
    "APIStats",
    "StatsTracker",
    "get_stats_tracker",
    "shutdown_stats_tracker",
]

