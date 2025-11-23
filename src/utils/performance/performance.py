"""
Performance Monitoring Utilities
Track API performance, LLM latency, and database query times
"""
import time
import functools
from typing import Callable, Any, Optional, Dict
from datetime import datetime
from collections import defaultdict
from ..logger import setup_logger

logger = setup_logger(__name__)


class PerformanceMonitor:
    """
    Simple performance monitoring for tracking operation latency
    
    For production, integrate with Prometheus, DataDog, or New Relic
    """
    
    def __init__(self):
        self.metrics: Dict[str, list] = defaultdict(list)
        self.start_time = datetime.now()
        logger.info("[OK] Performance monitor initialized")
    
    def record(self, operation: str, duration: float, metadata: Optional[Dict[str, Any]] = None):
        """
        Record operation timing
        
        Args:
            operation: Operation name (e.g., "llm_invoke", "db_query", "email_list")
            duration: Duration in seconds
            metadata: Additional context
        """
        self.metrics[operation].append({
            "duration": duration,
            "timestamp": datetime.now(),
            "metadata": metadata or {}
        })
        
        # Log slow operations (> 2 seconds)
        if duration > 2.0:
            logger.warning(f"[SLOW] {operation} took {duration:.2f}s {metadata or ''}")
    
    def get_stats(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """
        Get performance statistics
        
        Args:
            operation: Specific operation or None for all
            
        Returns:
            Statistics dictionary
        """
        if operation:
            metrics = self.metrics.get(operation, [])
            if not metrics:
                return {}
            
            durations = [m["duration"] for m in metrics]
            return {
                "operation": operation,
                "count": len(durations),
                "avg_duration": sum(durations) / len(durations),
                "min_duration": min(durations),
                "max_duration": max(durations),
                "p95_duration": sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 20 else max(durations),
            }
        else:
            # All operations
            return {
                op: self.get_stats(op)
                for op in self.metrics.keys()
            }
    
    def clear(self):
        """Clear all metrics"""
        self.metrics.clear()
        logger.info("[OK] Performance metrics cleared")


# Global monitor instance
_monitor = PerformanceMonitor()


def get_monitor() -> PerformanceMonitor:
    """Get global performance monitor instance"""
    return _monitor


def track_performance(operation_name: Optional[str] = None, log_threshold: float = 1.0):
    """
    Decorator to track function performance
    
    Args:
        operation_name: Custom operation name (defaults to function name)
        log_threshold: Log if duration exceeds this (seconds)
    
    Usage:
        @track_performance("my_operation")
        def my_function():
            ...
        
        @track_performance(log_threshold=0.5)
        async def async_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        op_name = operation_name or f"{func.__module__}.{func.__name__}"
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                _monitor.record(op_name, duration)
                
                if duration > log_threshold:
                    logger.info(f"[PERF] {op_name} took {duration:.2f}s")
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                _monitor.record(op_name, duration)
                
                if duration > log_threshold:
                    logger.info(f"[PERF] {op_name} took {duration:.2f}s")
        
        # Return appropriate wrapper based on function type
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class PerformanceContext:
    """
    Context manager for tracking operation performance
    
    Usage:
        with PerformanceContext("database_query") as perf:
            result = db.query(...)
        
        async with PerformanceContext("api_call"):
            response = await client.get(...)
    """
    
    def __init__(self, operation: str, metadata: Optional[Dict[str, Any]] = None):
        self.operation = operation
        self.metadata = metadata
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            _monitor.record(self.operation, duration, self.metadata)
    
    async def __aenter__(self):
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            _monitor.record(self.operation, duration, self.metadata)


# Metrics specific to common operations
class Metrics:
    """Common metric names for consistency"""
    
    # API endpoints
    API_CHAT = "api.chat"
    API_EMAIL_LIST = "api.email.list"
    API_EMAIL_SEND = "api.email.send"
    API_CALENDAR_CREATE = "api.calendar.create"
    API_CALENDAR_LIST = "api.calendar.list"
    
    # LLM operations
    LLM_INVOKE = "llm.invoke"
    LLM_STREAM = "llm.stream"
    LLM_EMBED = "llm.embed"
    
    # Database operations
    DB_QUERY = "db.query"
    DB_INSERT = "db.insert"
    DB_UPDATE = "db.update"
    DB_DELETE = "db.delete"
    
    # RAG operations
    RAG_SEARCH = "rag.search"
    RAG_INDEX = "rag.index"
    RAG_CHUNK = "rag.chunk"
    
    # External API calls
    GMAIL_API = "gmail.api"
    CALENDAR_API = "calendar.api"
    TASKS_API = "tasks.api"
    
    # Agent operations
    AGENT_EXECUTE = "agent.execute"
    AGENT_PARSE = "agent.parse"
    AGENT_ORCHESTRATE = "agent.orchestrate"


# Example usage in code:
"""
# Note: These are re-exported from this module, no need to import

# Using decorator:
@track_performance(Metrics.LLM_INVOKE, log_threshold=2.0)
async def invoke_llm(prompt: str):
    response = await llm.ainvoke(prompt)
    return response

# Using context manager:
async def search_emails(query: str):
    with PerformanceContext(Metrics.RAG_SEARCH, {"query_length": len(query)}):
        results = await rag_engine.search(query)
    return results

# Manual recording:
# Note: get_monitor is defined in this module

start = time.time()
result = expensive_operation()
get_monitor().record("custom_operation", time.time() - start, {"result_count": len(result)})
"""
