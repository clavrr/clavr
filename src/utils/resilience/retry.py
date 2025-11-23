"""
Retry Logic Utilities for External API Calls
Provides configurable retry strategies with exponential backoff
"""
import logging
from typing import Callable, Optional, Type, Union, Tuple
from functools import wraps
import time

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    retry_if_exception,
    before_sleep_log,
    after_log,
    RetryError
)
from googleapiclient.errors import HttpError

from ..logger import setup_logger

logger = setup_logger(__name__)


# ============================================
# RETRY CONFIGURATIONS
# ============================================

class RetryConfig:
    """Retry configuration constants"""
    
    # Gmail API retry settings
    GMAIL_MAX_ATTEMPTS = 5
    GMAIL_MIN_WAIT = 1  # seconds
    GMAIL_MAX_WAIT = 60  # seconds
    GMAIL_MULTIPLIER = 2  # exponential backoff multiplier
    
    # Calendar API retry settings
    CALENDAR_MAX_ATTEMPTS = 5
    CALENDAR_MIN_WAIT = 1
    CALENDAR_MAX_WAIT = 60
    CALENDAR_MULTIPLIER = 2
    
    # Tasks API retry settings
    TASKS_MAX_ATTEMPTS = 3
    TASKS_MIN_WAIT = 1
    TASKS_MAX_WAIT = 30
    TASKS_MULTIPLIER = 2
    
    # Generic API retry settings
    DEFAULT_MAX_ATTEMPTS = 3
    DEFAULT_MIN_WAIT = 1
    DEFAULT_MAX_WAIT = 30
    DEFAULT_MULTIPLIER = 2


# ============================================
# RETRY CONDITION FUNCTIONS
# ============================================

def is_retryable_http_error(exception: Exception) -> bool:
    """
    Check if an HttpError is retryable
    
    Retryable errors:
    - 429 (Rate Limit Exceeded)
    - 500 (Internal Server Error)
    - 502 (Bad Gateway)
    - 503 (Service Unavailable)
    - 504 (Gateway Timeout)
    
    Non-retryable errors:
    - 400 (Bad Request)
    - 401 (Unauthorized)
    - 403 (Forbidden)
    - 404 (Not Found)
    
    Args:
        exception: Exception to check
        
    Returns:
        True if error should be retried
    """
    if not isinstance(exception, HttpError):
        return False
    
    status_code = exception.resp.status
    
    # Retryable status codes
    retryable_codes = {429, 500, 502, 503, 504}
    
    if status_code in retryable_codes:
        logger.warning(f"Retryable HTTP error {status_code}: {exception}")
        return True
    
    # Non-retryable errors
    logger.error(f"Non-retryable HTTP error {status_code}: {exception}")
    return False


def is_rate_limit_error(exception: Exception) -> bool:
    """
    Check if exception is a rate limit error (429)
    
    Args:
        exception: Exception to check
        
    Returns:
        True if rate limit error
    """
    if isinstance(exception, HttpError):
        return exception.resp.status == 429
    return False


def is_server_error(exception: Exception) -> bool:
    """
    Check if exception is a server error (5xx)
    
    Args:
        exception: Exception to check
        
    Returns:
        True if server error
    """
    if isinstance(exception, HttpError):
        return 500 <= exception.resp.status < 600
    return False


# ============================================
# RETRY DECORATORS
# ============================================

def retry_gmail_api(
    max_attempts: int = RetryConfig.GMAIL_MAX_ATTEMPTS,
    min_wait: int = RetryConfig.GMAIL_MIN_WAIT,
    max_wait: int = RetryConfig.GMAIL_MAX_WAIT
) -> Callable:
    """
    Decorator for Gmail API calls with retry logic
    
    Features:
    - Exponential backoff
    - Retry on rate limits and server errors
    - Detailed logging
    
    Args:
        max_attempts: Maximum retry attempts
        min_wait: Minimum wait time in seconds
        max_wait: Maximum wait time in seconds
        
    Returns:
        Decorated function with retry logic
        
    Example:
        @retry_gmail_api(max_attempts=3)
        def list_messages(self):
            return self.service.users().messages().list(...).execute()
    """
    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(
                multiplier=RetryConfig.GMAIL_MULTIPLIER,
                min=min_wait,
                max=max_wait
            ),
            retry=retry_if_exception(is_retryable_http_error),
            before_sleep=before_sleep_log(logger, logging.INFO),
            after=after_log(logger, logging.INFO),
            reraise=True
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                logger.debug(f"Calling Gmail API: {func.__name__}")
                result = func(*args, **kwargs)
                logger.debug(f"Gmail API call successful: {func.__name__}")
                return result
            except HttpError as e:
                if not is_retryable_http_error(e):
                    # Non-retryable error, log and raise immediately
                    logger.error(f"Non-retryable Gmail API error in {func.__name__}: {e}")
                    raise
                # Retryable error will be handled by tenacity
                raise
            except Exception as e:
                logger.error(f"Unexpected error in Gmail API call {func.__name__}: {e}")
                raise
        
        return wrapper
    return decorator


def retry_calendar_api(
    max_attempts: int = RetryConfig.CALENDAR_MAX_ATTEMPTS,
    min_wait: int = RetryConfig.CALENDAR_MIN_WAIT,
    max_wait: int = RetryConfig.CALENDAR_MAX_WAIT
) -> Callable:
    """
    Decorator for Calendar API calls with retry logic
    
    Features:
    - Exponential backoff
    - Retry on rate limits and server errors
    - Detailed logging
    
    Args:
        max_attempts: Maximum retry attempts
        min_wait: Minimum wait time in seconds
        max_wait: Maximum wait time in seconds
        
    Returns:
        Decorated function with retry logic
        
    Example:
        @retry_calendar_api(max_attempts=3)
        def create_event(self, event):
            return self.service.events().insert(...).execute()
    """
    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(
                multiplier=RetryConfig.CALENDAR_MULTIPLIER,
                min=min_wait,
                max=max_wait
            ),
            retry=retry_if_exception(is_retryable_http_error),
            before_sleep=before_sleep_log(logger, logging.INFO),
            after=after_log(logger, logging.INFO),
            reraise=True
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                logger.debug(f"Calling Calendar API: {func.__name__}")
                result = func(*args, **kwargs)
                logger.debug(f"Calendar API call successful: {func.__name__}")
                return result
            except HttpError as e:
                if not is_retryable_http_error(e):
                    # Check for invalid_grant error (refresh token expired/invalid)
                    error_details = e.error_details if hasattr(e, 'error_details') else {}
                    error_reason = error_details.get('error', '') if isinstance(error_details, dict) else str(error_details)
                    error_message = str(e)
                    
                    if e.resp.status == 401 and ('invalid_grant' in error_message.lower() or 'invalid_grant' in str(error_reason).lower()):
                        logger.error(f"Calendar API authentication error in {func.__name__}: {e}")
                        logger.error("Your refresh token has expired or been revoked. Please re-authenticate.")
                        logger.error("This usually happens when:")
                        logger.error("  - You changed your Google account password")
                        logger.error("  - You revoked access to the app")
                        logger.error("  - The refresh token expired (after 6 months of inactivity)")
                        logger.error("Solution: Please log out and log back in to refresh your credentials.")
                    else:
                        logger.error(f"Non-retryable Calendar API error in {func.__name__}: {e}")
                    raise
                raise
            except Exception as e:
                error_message = str(e)
                # Check for invalid_grant in exception message (Google auth library wraps it)
                if 'invalid_grant' in error_message.lower():
                    logger.error(f"Calendar API authentication error in {func.__name__}: {e}")
                    logger.error("Your refresh token has expired or been revoked. Please re-authenticate.")
                    logger.error("Solution: Please log out and log back in to refresh your credentials.")
                else:
                    logger.error(f"Unexpected error in Calendar API call {func.__name__}: {e}")
                raise
        
        return wrapper
    return decorator


def retry_tasks_api(
    max_attempts: int = RetryConfig.TASKS_MAX_ATTEMPTS,
    min_wait: int = RetryConfig.TASKS_MIN_WAIT,
    max_wait: int = RetryConfig.TASKS_MAX_WAIT
) -> Callable:
    """
    Decorator for Tasks API calls with retry logic
    
    Args:
        max_attempts: Maximum retry attempts
        min_wait: Minimum wait time in seconds
        max_wait: Maximum wait time in seconds
        
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(
                multiplier=RetryConfig.TASKS_MULTIPLIER,
                min=min_wait,
                max=max_wait
            ),
            retry=retry_if_exception(is_retryable_http_error),
            before_sleep=before_sleep_log(logger, logging.INFO),
            after=after_log(logger, logging.INFO),
            reraise=True
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                logger.debug(f"Calling Tasks API: {func.__name__}")
                result = func(*args, **kwargs)
                logger.debug(f"Tasks API call successful: {func.__name__}")
                return result
            except HttpError as e:
                if not is_retryable_http_error(e):
                    logger.error(f"Non-retryable Tasks API error in {func.__name__}: {e}")
                    raise
                raise
            except Exception as e:
                logger.error(f"Unexpected error in Tasks API call {func.__name__}: {e}")
                raise
        
        return wrapper
    return decorator


def retry_generic_api(
    max_attempts: int = RetryConfig.DEFAULT_MAX_ATTEMPTS,
    min_wait: int = RetryConfig.DEFAULT_MIN_WAIT,
    max_wait: int = RetryConfig.DEFAULT_MAX_WAIT,
    retry_on: Optional[Union[Type[Exception], Tuple[Type[Exception], ...]]] = None
) -> Callable:
    """
    Generic retry decorator for any API call
    
    Args:
        max_attempts: Maximum retry attempts
        min_wait: Minimum wait time in seconds
        max_wait: Maximum wait time in seconds
        retry_on: Exception types to retry on (default: HttpError with retryable status)
        
    Returns:
        Decorated function with retry logic
        
    Example:
        @retry_generic_api(max_attempts=3, retry_on=(ConnectionError, TimeoutError))
        def call_external_api():
            ...
    """
    def decorator(func: Callable) -> Callable:
        # Determine retry condition
        if retry_on:
            retry_condition = retry_if_exception_type(retry_on)
        else:
            retry_condition = retry_if_exception(is_retryable_http_error)
        
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(
                multiplier=RetryConfig.DEFAULT_MULTIPLIER,
                min=min_wait,
                max=max_wait
            ),
            retry=retry_condition,
            before_sleep=before_sleep_log(logger, logging.INFO),
            after=after_log(logger, logging.INFO),
            reraise=True
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                raise
        
        return wrapper
    return decorator


# ============================================
# CONTEXT MANAGER FOR RETRIES
# ============================================

class RetryContext:
    """
    Context manager for retry logic
    
    Example:
        with RetryContext(max_attempts=3, service="gmail"):
            result = service.users().messages().list(...).execute()
    """
    
    def __init__(
        self,
        max_attempts: int = 3,
        min_wait: int = 1,
        max_wait: int = 30,
        service: str = "API"
    ):
        """
        Initialize retry context
        
        Args:
            max_attempts: Maximum retry attempts
            min_wait: Minimum wait time in seconds
            max_wait: Maximum wait time in seconds
            service: Service name for logging
        """
        self.max_attempts = max_attempts
        self.min_wait = min_wait
        self.max_wait = max_wait
        self.service = service
        self.attempt = 0
    
    def __enter__(self):
        """Enter context"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context with retry logic"""
        if exc_type is None:
            return True
        
        # Check if exception is retryable
        if isinstance(exc_val, HttpError) and is_retryable_http_error(exc_val):
            self.attempt += 1
            
            if self.attempt < self.max_attempts:
                # Calculate wait time with exponential backoff
                wait_time = min(
                    self.min_wait * (2 ** self.attempt),
                    self.max_wait
                )
                
                logger.warning(
                    f"{self.service} API error (attempt {self.attempt}/{self.max_attempts}): "
                    f"{exc_val}. Retrying in {wait_time}s..."
                )
                
                time.sleep(wait_time)
                return False  # Suppress exception, retry
            
            logger.error(
                f"{self.service} API failed after {self.max_attempts} attempts: {exc_val}"
            )
        
        return False  # Re-raise exception


# ============================================
# UTILITY FUNCTIONS
# ============================================

def get_retry_stats(func: Callable) -> dict:
    """
    Get retry statistics for a decorated function
    
    Args:
        func: Decorated function
        
    Returns:
        Dictionary with retry statistics
    """
    if hasattr(func, 'retry'):
        return {
            'has_retry': True,
            'statistics': func.retry.statistics
        }
    return {'has_retry': False}


def is_retryable_error_code(status_code: int) -> bool:
    """
    Check if HTTP status code is retryable
    
    Args:
        status_code: HTTP status code
        
    Returns:
        True if retryable
    """
    retryable_codes = {429, 500, 502, 503, 504}
    return status_code in retryable_codes
