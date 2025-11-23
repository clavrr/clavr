"""
Circuit Breaker Pattern for External API Calls
Prevents cascading failures by stopping requests to failing services
"""
from typing import Callable, Optional, Any
from functools import wraps

import pybreaker
from googleapiclient.errors import HttpError

from ..logger import setup_logger

logger = setup_logger(__name__)


# ============================================
# CIRCUIT BREAKER CONFIGURATIONS
# ============================================

class CircuitBreakerConfig:
    """Circuit breaker configuration constants"""
    
    # Circuit breaker state names (from pybreaker library)
    STATE_CLOSED = 'closed'  # Normal operation
    STATE_OPEN = 'open'  # Circuit is open, blocking requests
    STATE_HALF_OPEN = 'half_open'  # Testing recovery
    
    # Service names for logging
    SERVICE_NAME_GMAIL = "Gmail API"
    SERVICE_NAME_CALENDAR = "Calendar API"
    SERVICE_NAME_TASKS = "Tasks API"
    
    # Gmail API circuit breaker settings
    GMAIL_FAIL_MAX = 5  # Open circuit after 5 consecutive failures
    GMAIL_TIMEOUT = 60  # Keep circuit open for 60 seconds
    GMAIL_EXPECTED_EXCEPTION = HttpError
    
    # Calendar API circuit breaker settings
    CALENDAR_FAIL_MAX = 5
    CALENDAR_TIMEOUT = 60
    CALENDAR_EXPECTED_EXCEPTION = HttpError
    
    # Tasks API circuit breaker settings
    TASKS_FAIL_MAX = 3
    TASKS_TIMEOUT = 45
    TASKS_EXPECTED_EXCEPTION = HttpError
    
    # Generic API circuit breaker settings
    DEFAULT_FAIL_MAX = 3
    DEFAULT_TIMEOUT = 30
    DEFAULT_EXPECTED_EXCEPTION = Exception


# ============================================
# CIRCUIT BREAKER LISTENERS
# ============================================

class CircuitBreakerListener(pybreaker.CircuitBreakerListener):
    """
    Listener for circuit breaker state changes
    Logs all state transitions for monitoring
    """
    
    def __init__(self, service_name: str):
        """
        Initialize listener
        
        Args:
            service_name: Name of the service (for logging)
        """
        self.service_name = service_name
    
    def state_change(self, cb, old_state, new_state):
        """Called when circuit breaker changes state"""
        logger.warning(
            f"[{self.service_name}] Circuit breaker state change: "
            f"{old_state.name} → {new_state.name}"
        )
        
        if new_state.name == CircuitBreakerConfig.STATE_OPEN:
            logger.error(
                f"[{self.service_name}] Circuit OPEN - Service appears to be down. "
                f"Blocking requests for {cb._reset_timeout}s"
            )
        elif new_state.name == CircuitBreakerConfig.STATE_HALF_OPEN:
            logger.info(
                f"[{self.service_name}] Circuit HALF-OPEN - Testing service recovery"
            )
        elif new_state.name == CircuitBreakerConfig.STATE_CLOSED:
            logger.info(
                f"[{self.service_name}] Circuit CLOSED - Service recovered, normal operation resumed"
            )
    
    def before_call(self, cb, func, *args, **kwargs):
        """Called before executing the protected function"""
        logger.debug(f"[{self.service_name}] Circuit breaker state: {cb.current_state}")
    
    def success(self, cb):
        """Called when a call succeeds"""
        logger.debug(f"[{self.service_name}] Call successful, failure count reset")
    
    def failure(self, cb, exc):
        """Called when a call fails"""
        logger.warning(
            f"[{self.service_name}] Call failed: {exc}. "
            f"Failure count: {cb.fail_counter}/{cb.fail_max}"
        )


# ============================================
# CIRCUIT BREAKER INSTANCES
# ============================================

# Gmail API circuit breaker
gmail_breaker = pybreaker.CircuitBreaker(
    fail_max=CircuitBreakerConfig.GMAIL_FAIL_MAX,
    reset_timeout=CircuitBreakerConfig.GMAIL_TIMEOUT,
    exclude=[],
    listeners=[CircuitBreakerListener(CircuitBreakerConfig.SERVICE_NAME_GMAIL)],
    name=CircuitBreakerConfig.SERVICE_NAME_GMAIL
)

# Calendar API circuit breaker
calendar_breaker = pybreaker.CircuitBreaker(
    fail_max=CircuitBreakerConfig.CALENDAR_FAIL_MAX,
    reset_timeout=CircuitBreakerConfig.CALENDAR_TIMEOUT,
    exclude=[],
    listeners=[CircuitBreakerListener(CircuitBreakerConfig.SERVICE_NAME_CALENDAR)],
    name=CircuitBreakerConfig.SERVICE_NAME_CALENDAR
)

# Tasks API circuit breaker
tasks_breaker = pybreaker.CircuitBreaker(
    fail_max=CircuitBreakerConfig.TASKS_FAIL_MAX,
    reset_timeout=CircuitBreakerConfig.TASKS_TIMEOUT,
    exclude=[],
    listeners=[CircuitBreakerListener(CircuitBreakerConfig.SERVICE_NAME_TASKS)],
    name=CircuitBreakerConfig.SERVICE_NAME_TASKS
)


# ============================================
# CIRCUIT BREAKER DECORATORS
# ============================================

def with_circuit_breaker(
    breaker: pybreaker.CircuitBreaker,
    fallback: Optional[Callable] = None
) -> Callable:
    """
    Decorator to wrap a function with a circuit breaker
    
    Args:
        breaker: Circuit breaker instance to use
        fallback: Optional fallback function to call when circuit is open
        
    Returns:
        Decorated function with circuit breaker protection
        
    Example:
        @with_circuit_breaker(gmail_breaker)
        def list_messages(self):
            return self.service.users().messages().list(...).execute()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                # Call function through circuit breaker
                return breaker.call(func, *args, **kwargs)
            except pybreaker.CircuitBreakerError as e:
                # Circuit is open - service is down
                logger.error(
                    f"Circuit breaker OPEN for {breaker.name}. "
                    f"Service unavailable. {e}"
                )
                
                # Call fallback if provided
                if fallback:
                    logger.info(f"Using fallback for {func.__name__}")
                    return fallback(*args, **kwargs)
                
                # Otherwise raise the error
                raise ServiceUnavailableError(
                    f"{breaker.name} is currently unavailable. "
                    f"Circuit breaker is open. Please try again later."
                ) from e
            except Exception as e:
                # Other errors pass through
                logger.error(f"Error in {func.__name__}: {e}")
                raise
        
        return wrapper
    return decorator


def with_gmail_circuit_breaker(fallback: Optional[Callable] = None) -> Callable:
    """
    Decorator for Gmail API calls with circuit breaker
    
    Args:
        fallback: Optional fallback function
        
    Returns:
        Decorated function
        
    Example:
        @with_gmail_circuit_breaker()
        def list_messages(self):
            return self.service.users().messages().list(...).execute()
    """
    return with_circuit_breaker(gmail_breaker, fallback)


def with_calendar_circuit_breaker(fallback: Optional[Callable] = None) -> Callable:
    """
    Decorator for Calendar API calls with circuit breaker
    
    Args:
        fallback: Optional fallback function
        
    Returns:
        Decorated function
        
    Example:
        @with_calendar_circuit_breaker()
        def create_event(self, event):
            return self.service.events().insert(...).execute()
    """
    return with_circuit_breaker(calendar_breaker, fallback)


def with_tasks_circuit_breaker(fallback: Optional[Callable] = None) -> Callable:
    """
    Decorator for Tasks API calls with circuit breaker
    
    Args:
        fallback: Optional fallback function
        
    Returns:
        Decorated function
    """
    return with_circuit_breaker(tasks_breaker, fallback)


# ============================================
# CUSTOM EXCEPTIONS
# ============================================

class ServiceUnavailableError(Exception):
    """Raised when a service is unavailable due to open circuit breaker"""
    pass


# ============================================
# UTILITY FUNCTIONS
# ============================================

def get_breaker_state(breaker: pybreaker.CircuitBreaker) -> dict:
    """
    Get current state of a circuit breaker
    
    Args:
        breaker: Circuit breaker instance
        
    Returns:
        Dictionary with breaker state information
    """
    return {
        'name': breaker.name,
        'state': breaker.current_state,
        'fail_counter': breaker.fail_counter,
        'fail_max': breaker.fail_max,
        'timeout': breaker._reset_timeout,
        'is_closed': breaker.current_state == CircuitBreakerConfig.STATE_CLOSED,
        'is_open': breaker.current_state == CircuitBreakerConfig.STATE_OPEN,
        'is_half_open': breaker.current_state == CircuitBreakerConfig.STATE_HALF_OPEN
    }


def get_all_breaker_states() -> dict:
    """
    Get state of all circuit breakers
    
    Returns:
        Dictionary with all breaker states
    """
    return {
        'gmail': get_breaker_state(gmail_breaker),
        'calendar': get_breaker_state(calendar_breaker),
        'tasks': get_breaker_state(tasks_breaker)
    }


def reset_breaker(breaker: pybreaker.CircuitBreaker) -> None:
    """
    Manually reset a circuit breaker to closed state
    
    Args:
        breaker: Circuit breaker to reset
    """
    logger.info(f"Manually resetting circuit breaker: {breaker.name}")
    breaker.close()


def reset_all_breakers() -> None:
    """Reset all circuit breakers to closed state"""
    logger.info("Resetting all circuit breakers")
    gmail_breaker.close()
    calendar_breaker.close()
    tasks_breaker.close()


# ============================================
# FALLBACK FUNCTIONS
# ============================================

def gmail_list_fallback(*args, **kwargs) -> list:
    """Fallback for Gmail list operations when circuit is open"""
    logger.warning("Using fallback: returning empty list for Gmail")
    return []


def calendar_list_fallback(*args, **kwargs) -> list:
    """Fallback for Calendar list operations when circuit is open"""
    logger.warning("Using fallback: returning empty list for Calendar")
    return []


def generic_none_fallback(*args, **kwargs) -> None:
    """Generic fallback that returns None"""
    logger.warning("Using fallback: returning None")
    return None


def generic_empty_dict_fallback(*args, **kwargs) -> dict:
    """Generic fallback that returns empty dict"""
    logger.warning("Using fallback: returning empty dict")
    return {}
