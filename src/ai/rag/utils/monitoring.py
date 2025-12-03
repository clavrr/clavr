"""
RAG Monitoring & Metrics Module

Production-grade monitoring and metrics collection for RAG system.
Tracks performance, quality, and operational metrics.

Features:
- Real-time performance tracking (latency, throughput)
- Cache effectiveness monitoring
- Search quality metrics
- Error tracking and alerting
- Prometheus-compatible metric export
- Dashboard-ready statistics
"""
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Deque
from statistics import mean, median, stdev

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class MetricSnapshot:
    """Snapshot of metrics at a point in time"""
    timestamp: datetime
    search_latency_p50: float
    search_latency_p95: float
    search_latency_p99: float
    cache_hit_rate: float
    avg_results_per_query: float
    error_rate: float
    total_searches: int
    total_indexes: int


@dataclass
class RAGMetrics:
    """Container for RAG performance metrics"""
    
    # Search performance
    search_latencies: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    search_count: int = 0
    search_errors: int = 0
    
    # Cache metrics
    cache_hits: int = 0
    cache_misses: int = 0
    cache_invalidations: int = 0
    
    # Indexing metrics
    index_latencies: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    index_count: int = 0
    index_errors: int = 0
    
    # Result quality
    results_per_query: Deque[int] = field(default_factory=lambda: deque(maxlen=1000))
    avg_relevance_scores: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    # Component-specific metrics
    hybrid_search_usage: int = 0
    reranking_usage: int = 0
    diversity_usage: int = 0
    
    # Timing breakdowns
    embedding_time: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    vector_search_time: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    reranking_time: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    # Error tracking
    error_types: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Start time for uptime calculation
    start_time: datetime = field(default_factory=datetime.utcnow)


class RAGMonitor:
    """
    Production monitoring for RAG system.
    
    Tracks all metrics and provides real-time insights.
    Thread-safe for concurrent operations.
    """
    
    def __init__(self, window_size: int = 1000, snapshot_interval: int = 60):
        """
        Initialize RAG monitor.
        
        Args:
            window_size: Number of recent operations to track
            snapshot_interval: Seconds between metric snapshots
        """
        self.metrics = RAGMetrics()
        self.window_size = window_size
        self.snapshot_interval = snapshot_interval
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Historical snapshots
        self._snapshots: Deque[MetricSnapshot] = deque(maxlen=1440)  # 24 hours at 1min intervals
        self._last_snapshot = datetime.utcnow()
        
        logger.info("RAG Monitor initialized")
    
    # === Search Tracking ===
    
    def record_search(self, latency: float, num_results: int, 
                     cache_hit: bool = False, error: Optional[str] = None):
        """Record a search operation"""
        with self._lock:
            self.metrics.search_count += 1
            
            if error:
                self.metrics.search_errors += 1
                self.metrics.error_types[error] += 1
            else:
                self.metrics.search_latencies.append(latency)
                self.metrics.results_per_query.append(num_results)
            
            if cache_hit:
                self.metrics.cache_hits += 1
            else:
                self.metrics.cache_misses += 1
            
            self._maybe_snapshot()
    
    def record_search_timing(self, embedding_time: float, 
                           vector_search_time: float,
                           reranking_time: float = 0.0):
        """Record timing breakdown for search operation"""
        with self._lock:
            self.metrics.embedding_time.append(embedding_time)
            self.metrics.vector_search_time.append(vector_search_time)
            if reranking_time > 0:
                self.metrics.reranking_time.append(reranking_time)
    
    def record_relevance_score(self, avg_score: float):
        """Record average relevance score for results"""
        with self._lock:
            self.metrics.avg_relevance_scores.append(avg_score)
    
    # === Indexing Tracking ===
    
    def record_index(self, latency: float, error: Optional[str] = None):
        """Record an indexing operation"""
        with self._lock:
            self.metrics.index_count += 1
            
            if error:
                self.metrics.index_errors += 1
                self.metrics.error_types[error] += 1
            else:
                self.metrics.index_latencies.append(latency)
            
            self._maybe_snapshot()
    
    # === Cache Tracking ===
    
    def record_cache_invalidation(self):
        """Record cache invalidation event"""
        with self._lock:
            self.metrics.cache_invalidations += 1
    
    # === Feature Usage Tracking ===
    
    def record_hybrid_search(self):
        """Record hybrid search usage"""
        with self._lock:
            self.metrics.hybrid_search_usage += 1
    
    def record_reranking(self):
        """Record reranking usage"""
        with self._lock:
            self.metrics.reranking_usage += 1
    
    def record_diversity(self):
        """Record diversity filter usage"""
        with self._lock:
            self.metrics.diversity_usage += 1
    
    # === Metrics Retrieval ===
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current metrics snapshot"""
        with self._lock:
            total_cache_ops = self.metrics.cache_hits + self.metrics.cache_misses
            cache_hit_rate = (self.metrics.cache_hits / total_cache_ops * 100) if total_cache_ops > 0 else 0
            
            total_searches = self.metrics.search_count
            error_rate = (self.metrics.search_errors / total_searches * 100) if total_searches > 0 else 0
            
            latencies = list(self.metrics.search_latencies)
            
            return {
                # Performance
                "search_latency_ms": {
                    "p50": self._percentile(latencies, 50) if latencies else 0,
                    "p95": self._percentile(latencies, 95) if latencies else 0,
                    "p99": self._percentile(latencies, 99) if latencies else 0,
                    "mean": mean(latencies) if latencies else 0,
                    "median": median(latencies) if latencies else 0,
                    "stddev": stdev(latencies) if len(latencies) > 1 else 0,
                },
                "index_latency_ms": {
                    "mean": mean(self.metrics.index_latencies) if self.metrics.index_latencies else 0,
                    "p95": self._percentile(list(self.metrics.index_latencies), 95) if self.metrics.index_latencies else 0,
                },
                
                # Cache
                "cache": {
                    "hit_rate_pct": cache_hit_rate,
                    "hits": self.metrics.cache_hits,
                    "misses": self.metrics.cache_misses,
                    "invalidations": self.metrics.cache_invalidations,
                },
                
                # Throughput
                "throughput": {
                    "total_searches": self.metrics.search_count,
                    "total_indexes": self.metrics.index_count,
                    "searches_per_min": self._calculate_rate(self.metrics.search_count),
                },
                
                # Quality
                "quality": {
                    "avg_results_per_query": mean(self.metrics.results_per_query) if self.metrics.results_per_query else 0,
                    "avg_relevance_score": mean(self.metrics.avg_relevance_scores) if self.metrics.avg_relevance_scores else 0,
                },
                
                # Errors
                "errors": {
                    "error_rate_pct": error_rate,
                    "search_errors": self.metrics.search_errors,
                    "index_errors": self.metrics.index_errors,
                    "error_breakdown": dict(self.metrics.error_types),
                },
                
                # Features
                "features": {
                    "hybrid_search_usage": self.metrics.hybrid_search_usage,
                    "reranking_usage": self.metrics.reranking_usage,
                    "diversity_usage": self.metrics.diversity_usage,
                },
                
                # System
                "system": {
                    "uptime_seconds": (datetime.utcnow() - self.metrics.start_time).total_seconds(),
                    "metrics_window_size": self.window_size,
                },
            }
    
    def get_prometheus_metrics(self) -> str:
        """
        Export metrics in Prometheus format.
        
        Returns:
            Prometheus-formatted metrics string
        """
        metrics = self.get_current_metrics()
        lines = [
            "# HELP rag_search_latency_ms Search latency in milliseconds",
            "# TYPE rag_search_latency_ms summary",
            f'rag_search_latency_ms{{quantile="0.5"}} {metrics["search_latency_ms"]["p50"]}',
            f'rag_search_latency_ms{{quantile="0.95"}} {metrics["search_latency_ms"]["p95"]}',
            f'rag_search_latency_ms{{quantile="0.99"}} {metrics["search_latency_ms"]["p99"]}',
            "",
            "# HELP rag_cache_hit_rate Cache hit rate percentage",
            "# TYPE rag_cache_hit_rate gauge",
            f'rag_cache_hit_rate {metrics["cache"]["hit_rate_pct"]}',
            "",
            "# HELP rag_searches_total Total number of searches",
            "# TYPE rag_searches_total counter",
            f'rag_searches_total {metrics["throughput"]["total_searches"]}',
            "",
            "# HELP rag_error_rate Error rate percentage",
            "# TYPE rag_error_rate gauge",
            f'rag_error_rate {metrics["errors"]["error_rate_pct"]}',
            "",
        ]
        return "\n".join(lines)
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get health status for readiness/liveness probes.
        
        Returns:
            Health status dict with status and details
        """
        metrics = self.get_current_metrics()
        
        # Define health thresholds
        LATENCY_THRESHOLD_MS = 500
        ERROR_RATE_THRESHOLD = 5.0
        
        is_healthy = (
            metrics["search_latency_ms"]["p95"] < LATENCY_THRESHOLD_MS and
            metrics["errors"]["error_rate_pct"] < ERROR_RATE_THRESHOLD
        )
        
        return {
            "status": "healthy" if is_healthy else "degraded",
            "checks": {
                "latency": {
                    "status": "ok" if metrics["search_latency_ms"]["p95"] < LATENCY_THRESHOLD_MS else "warning",
                    "p95_latency_ms": metrics["search_latency_ms"]["p95"],
                    "threshold_ms": LATENCY_THRESHOLD_MS,
                },
                "errors": {
                    "status": "ok" if metrics["errors"]["error_rate_pct"] < ERROR_RATE_THRESHOLD else "warning",
                    "error_rate_pct": metrics["errors"]["error_rate_pct"],
                    "threshold_pct": ERROR_RATE_THRESHOLD,
                },
                "cache": {
                    "status": "ok",
                    "hit_rate_pct": metrics["cache"]["hit_rate_pct"],
                },
            },
            "uptime_seconds": metrics["system"]["uptime_seconds"],
        }
    
    def print_dashboard(self):
        """Print a console dashboard with current metrics"""
        metrics = self.get_current_metrics()
        
        print("\n" + "="*70)
        print("RAG MONITORING DASHBOARD".center(70))
        print("="*70)
        
        print("\nPERFORMANCE")
        print(f"  Search Latency (p50): {metrics['search_latency_ms']['p50']:.1f}ms")
        print(f"  Search Latency (p95): {metrics['search_latency_ms']['p95']:.1f}ms")
        print(f"  Search Latency (p99): {metrics['search_latency_ms']['p99']:.1f}ms")
        
        print("\nCACHE")
        print(f"  Hit Rate: {metrics['cache']['hit_rate_pct']:.1f}%")
        print(f"  Hits: {metrics['cache']['hits']:,}")
        print(f"  Misses: {metrics['cache']['misses']:,}")
        
        print("\nTHROUGHPUT")
        print(f"  Total Searches: {metrics['throughput']['total_searches']:,}")
        print(f"  Total Indexes: {metrics['throughput']['total_indexes']:,}")
        print(f"  Searches/min: {metrics['throughput']['searches_per_min']:.1f}")
        
        print("\nQUALITY")
        print(f"  Avg Results/Query: {metrics['quality']['avg_results_per_query']:.1f}")
        print(f"  Avg Relevance: {metrics['quality']['avg_relevance_score']:.3f}")
        
        print("\nERRORS")
        print(f"  Error Rate: {metrics['errors']['error_rate_pct']:.2f}%")
        print(f"  Search Errors: {metrics['errors']['search_errors']}")
        
        print("\nFEATURES")
        print(f"  Hybrid Search: {metrics['features']['hybrid_search_usage']:,} uses")
        print(f"  Reranking: {metrics['features']['reranking_usage']:,} uses")
        print(f"  Diversity: {metrics['features']['diversity_usage']:,} uses")
        
        uptime = timedelta(seconds=int(metrics["system"]["uptime_seconds"]))
        print(f"\nUPTIME: {uptime}")
        print("="*70 + "\n")
    
    # === Private Helpers ===
    
    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile from data"""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    def _calculate_rate(self, count: int) -> float:
        """Calculate rate per minute based on uptime"""
        uptime_seconds = (datetime.utcnow() - self.metrics.start_time).total_seconds()
        if uptime_seconds == 0:
            return 0.0
        return (count / uptime_seconds) * 60
    
    def _maybe_snapshot(self):
        """Create snapshot if interval has passed"""
        now = datetime.utcnow()
        if (now - self._last_snapshot).total_seconds() >= self.snapshot_interval:
            metrics = self.get_current_metrics()
            snapshot = MetricSnapshot(
                timestamp=now,
                search_latency_p50=metrics["search_latency_ms"]["p50"],
                search_latency_p95=metrics["search_latency_ms"]["p95"],
                search_latency_p99=metrics["search_latency_ms"]["p99"],
                cache_hit_rate=metrics["cache"]["hit_rate_pct"],
                avg_results_per_query=metrics["quality"]["avg_results_per_query"],
                error_rate=metrics["errors"]["error_rate_pct"],
                total_searches=metrics["throughput"]["total_searches"],
                total_indexes=metrics["throughput"]["total_indexes"],
            )
            self._snapshots.append(snapshot)
            self._last_snapshot = now
    
    def reset_metrics(self):
        """Reset all metrics (use with caution in production)"""
        with self._lock:
            self.metrics = RAGMetrics()
            logger.warning("Metrics reset")


# Global monitor instance (singleton pattern)
_global_monitor: Optional[RAGMonitor] = None


def get_monitor() -> RAGMonitor:
    """Get or create global RAG monitor instance"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = RAGMonitor()
    return _global_monitor


def reset_monitor():
    """Reset global monitor (mainly for testing)"""
    global _global_monitor
    _global_monitor = None
