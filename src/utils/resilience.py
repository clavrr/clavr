"""
Resilience utilities - Circuit breaker patterns and fallback handlers
"""
import time
import functools
from typing import Callable, Any, Optional, List, Dict
from enum import Enum
from dataclasses import dataclass, field

from .config import ConfigDefaults


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class ServiceUnavailableError(Exception):
    """Raised when a service is unavailable due to circuit breaker"""
    pass


@dataclass
class CircuitBreaker:
    """Circuit breaker implementation"""
    name: str
    failure_threshold: int = ConfigDefaults.CIRCUIT_BREAKER_FAILURE_THRESHOLD
    recovery_timeout: float = ConfigDefaults.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
    half_open_max_calls: int = ConfigDefaults.CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS
    
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state"""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    def record_success(self):
        """Record a successful call"""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self):
        """Record a failed call"""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    def allow_request(self) -> bool:
        """Check if request should be allowed"""
        state = self.state  # This may transition from OPEN to HALF_OPEN
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True
        return False  # OPEN state


# Global circuit breakers
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def _get_circuit_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Get or create a circuit breaker"""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name=name, **kwargs)
    return _circuit_breakers[name]



def with_service_circuit_breaker(
    service_name: str,
    failure_threshold: int = ConfigDefaults.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    recovery_timeout: float = ConfigDefaults.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
) -> Callable:
    """Generic circuit breaker decorator factory for service API calls"""
    cb = _get_circuit_breaker(service_name, failure_threshold=failure_threshold, recovery_timeout=recovery_timeout)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if not cb.allow_request():
                raise ServiceUnavailableError(f"{service_name.capitalize()} service unavailable (circuit open)")
            try:
                result = func(*args, **kwargs)
                cb.record_success()
                return result
            except Exception as e:
                cb.record_failure()
                raise
        return wrapper
    return decorator


def with_gmail_circuit_breaker(
    failure_threshold: int = ConfigDefaults.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    recovery_timeout: float = ConfigDefaults.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
) -> Callable:
    """Circuit breaker decorator factory for Gmail API calls"""
    return with_service_circuit_breaker("gmail", failure_threshold, recovery_timeout)


def with_calendar_circuit_breaker(
    failure_threshold: int = ConfigDefaults.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    recovery_timeout: float = ConfigDefaults.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
) -> Callable:
    """Circuit breaker decorator factory for Calendar API calls"""
    return with_service_circuit_breaker("calendar", failure_threshold, recovery_timeout)


def with_tasks_circuit_breaker(
    failure_threshold: int = ConfigDefaults.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    recovery_timeout: float = ConfigDefaults.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
) -> Callable:
    """Circuit breaker decorator factory for Tasks API calls"""
    return with_service_circuit_breaker("tasks", failure_threshold, recovery_timeout)


# Fallback functions
def gmail_list_fallback() -> List[Dict[str, Any]]:
    """Fallback for Gmail list operations"""
    return []


def calendar_list_fallback() -> List[Dict[str, Any]]:
    """Fallback for Calendar list operations"""
    return []


def tasks_list_fallback() -> List[Dict[str, Any]]:
    """Fallback for Tasks list operations"""
    return []

