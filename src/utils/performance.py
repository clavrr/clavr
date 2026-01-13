"""
Performance Tracking Utilities

Provides context managers and utilities for tracking execution time
and performance metrics of code blocks.
"""
import time
from typing import Optional, Callable, Any
from contextlib import contextmanager
from functools import wraps

from .logger import setup_logger

logger = setup_logger(__name__)



class PerformanceContext:
    """
    Context manager for tracking execution time of code blocks
    
    Usage:
        with PerformanceContext("operation_name"):
            # code to measure
            pass
        
        # Or with threshold warning:
        with PerformanceContext("slow_operation", warn_threshold=5.0):
            # warns if takes > 5 seconds
            pass
    """
    
    def __init__(
        self,
        operation_name: str,
        warn_threshold: Optional[float] = None,
        log_start: bool = False,
        log_end: bool = True,
        use_ms: bool = False
    ):
        """
        Initialize performance context
        
        Args:
            operation_name: Name to identify this operation in logs
            warn_threshold: Log warning if execution exceeds this many seconds (or ms if use_ms=True)
            log_start: Whether to log when context is entered
            log_end: Whether to log when context exits
            use_ms: If True, log in milliseconds and treat warn_threshold as milliseconds
        """
        self.operation_name = operation_name
        self.warn_threshold = warn_threshold
        self.log_start = log_start
        self.log_end = log_end
        self.use_ms = use_ms
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.duration: Optional[float] = None
    
    def __enter__(self) -> 'PerformanceContext':
        """Start timing"""
        self.start_time = time.perf_counter()
        if self.log_start:
            logger.debug(f"Starting: {self.operation_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timing and log results"""
        self.end_time = time.perf_counter()
        if self.start_time is not None:
            self.duration = self.end_time - self.start_time
        else:
            self.duration = 0.0
        
        if self.log_end:
            duration_fmt = f"{self.duration * 1000:.2f}ms" if self.use_ms else f"{self.duration:.3f}s"
            threshold_fmt = f"{self.warn_threshold:.2f}ms" if self.use_ms else f"{self.warn_threshold:.3f}s"
            
            is_slow = False
            if self.warn_threshold:
                if self.use_ms:
                    is_slow = (self.duration * 1000) > self.warn_threshold
                else:
                    is_slow = self.duration > self.warn_threshold

            if exc_type is not None:
                logger.warning(
                    f"Failed: {self.operation_name} after {duration_fmt} - {exc_type.__name__}: {exc_val}"
                )
            elif is_slow:
                logger.warning(
                    f"Slow operation: {self.operation_name} took {duration_fmt} "
                    f"(threshold: {threshold_fmt})"
                )
            else:
                logger.debug(f"Completed: {self.operation_name} in {duration_fmt}")
    
    def elapsed(self) -> float:
        """Get elapsed time so far (or total if completed)"""
        if self.duration is not None:
            return self.duration
        if self.start_time is not None:
            return time.perf_counter() - self.start_time
        return 0.0


class LatencyMonitor(PerformanceContext):
    """
    Backward compatible wrapper for LatencyMonitor.
    Now inherits from PerformanceContext.
    Default threshold is 5000ms (5 seconds) - suitable for API calls.
    """
    def __init__(self, operation_name: str, threshold_ms: int = 5000):
        super().__init__(
            operation_name=operation_name,
            warn_threshold=float(threshold_ms),
            use_ms=True
        )


@contextmanager
def track_time(operation_name: str, warn_threshold: Optional[float] = None):
    """
    Simple context manager for timing code blocks
    """
    ctx = PerformanceContext(operation_name, warn_threshold=warn_threshold)
    with ctx:
        yield ctx


def timed(name: Optional[str] = None, warn_threshold: Optional[float] = None):
    """
    Decorator for timing function execution
    """
    def decorator(func: Callable) -> Callable:
        op_name = name or func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            with PerformanceContext(op_name, warn_threshold=warn_threshold):
                return func(*args, **kwargs)
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            with PerformanceContext(op_name, warn_threshold=warn_threshold):
                return await func(*args, **kwargs)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper
    
    return decorator

