"""
Retry utilities with exponential backoff for API calls
"""
import time
import functools
from typing import Callable, Any, Optional, Type, Tuple
from dataclasses import dataclass

from .config import ConfigDefaults


@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_retries: int = ConfigDefaults.RETRY_MAX_RETRIES
    base_delay: float = ConfigDefaults.RETRY_BASE_DELAY
    max_delay: float = ConfigDefaults.RETRY_MAX_DELAY
    exponential_base: float = ConfigDefaults.RETRY_EXPONENTIAL_BASE
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)


def is_retryable_http_error(status_code: int) -> bool:
    """Check if HTTP status code is retryable"""
    return status_code in (429, 500, 502, 503, 504)


def is_rate_limit_error(status_code: int) -> bool:
    """Check if error is a rate limit error"""
    return status_code == 429


def is_server_error(status_code: int) -> bool:
    """Check if error is a server error"""
    return 500 <= status_code < 600


def is_retryable_error_code(error_code: str) -> bool:
    """Check if error code is retryable"""
    retryable_codes = {
        'RATE_LIMIT_EXCEEDED',
        'SERVICE_UNAVAILABLE',
        'INTERNAL_ERROR',
        'BACKEND_ERROR',
        'TIMEOUT',
    }
    return error_code.upper() in retryable_codes


def _retry_decorator(config: RetryConfig) -> Callable:
    """Create a retry decorator with the given config"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e
                    if attempt < config.max_retries:
                        delay = min(
                            config.base_delay * (config.exponential_base ** attempt),
                            config.max_delay
                        )
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator



def retry_gmail_api(
    max_retries: int = ConfigDefaults.RETRY_MAX_RETRIES,
    base_delay: float = ConfigDefaults.RETRY_BASE_DELAY
) -> Callable:
    """Retry decorator for Gmail API calls"""
    return retry_generic_api(max_retries=max_retries, base_delay=base_delay)


def retry_calendar_api(
    max_retries: int = ConfigDefaults.RETRY_MAX_RETRIES,
    base_delay: float = ConfigDefaults.RETRY_BASE_DELAY
) -> Callable:
    """Retry decorator for Calendar API calls"""
    return retry_generic_api(max_retries=max_retries, base_delay=base_delay)


def retry_tasks_api(
    max_retries: int = ConfigDefaults.RETRY_MAX_RETRIES,
    base_delay: float = ConfigDefaults.RETRY_BASE_DELAY
) -> Callable:
    """Retry decorator for Tasks API calls"""
    return retry_generic_api(max_retries=max_retries, base_delay=base_delay)


def retry_generic_api(
    max_retries: int = ConfigDefaults.RETRY_MAX_RETRIES,
    base_delay: float = ConfigDefaults.RETRY_BASE_DELAY,
    max_delay: float = ConfigDefaults.RETRY_MAX_DELAY,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable:
    """Generic retry decorator for API calls"""
    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        retryable_exceptions=exceptions
    )
    return _retry_decorator(config)

