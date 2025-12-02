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
        log_end: bool = True
    ):
        """
        Initialize performance context
        
        Args:
            operation_name: Name to identify this operation in logs
            warn_threshold: Log warning if execution exceeds this many seconds
            log_start: Whether to log when context is entered
            log_end: Whether to log when context exits
        """
        self.operation_name = operation_name
        self.warn_threshold = warn_threshold
        self.log_start = log_start
        self.log_end = log_end
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.duration: Optional[float] = None
    
    def __enter__(self) -> 'PerformanceContext':
        """Start timing"""
        self.start_time = time.time()
        if self.log_start:
            logger.debug(f"Starting: {self.operation_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timing and log results"""
        self.end_time = time.time()
        if self.start_time is not None:
            self.duration = self.end_time - self.start_time
        else:
            # Should not happen if __enter__ was called, but handle gracefully
            self.duration = 0.0
        
        if self.log_end:
            if exc_type is not None:
                logger.warning(
                    f"Failed: {self.operation_name} after {self.duration:.3f}s - {exc_type.__name__}: {exc_val}"
                )
            elif self.warn_threshold and self.duration > self.warn_threshold:
                logger.warning(
                    f"Slow operation: {self.operation_name} took {self.duration:.3f}s "
                    f"(threshold: {self.warn_threshold}s)"
                )
            else:
                logger.debug(f"Completed: {self.operation_name} in {self.duration:.3f}s")
    
    def elapsed(self) -> float:
        """Get elapsed time so far (or total if completed)"""
        if self.duration is not None:
            return self.duration
        if self.start_time is not None:
            return time.time() - self.start_time
        return 0.0


@contextmanager
def track_time(operation_name: str, warn_threshold: Optional[float] = None):
    """
    Simple context manager for timing code blocks
    
    Usage:
        with track_time("my_operation"):
            # code to measure
            pass
    """
    ctx = PerformanceContext(operation_name, warn_threshold=warn_threshold)
    with ctx:
        yield ctx


def timed(name: Optional[str] = None, warn_threshold: Optional[float] = None):
    """
    Decorator for timing function execution
    
    Usage:
        @timed("expensive_calculation")
        def calculate():
            pass
        
        @timed(warn_threshold=5.0)
        def slow_function():
            pass
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
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper
    
    return decorator

