"""
Resilience Utilities

Provides retry logic and circuit breaker patterns for external API calls.
"""

from .retry import (
    RetryConfig,
    is_retryable_http_error,
    is_rate_limit_error,
    is_server_error,
    retry_gmail_api,
    retry_calendar_api,
    retry_tasks_api,
    retry_generic_api,
    RetryContext,
    is_retryable_error_code
)
from .circuit_breaker import (
    CircuitBreakerConfig,
    gmail_breaker,
    calendar_breaker,
    tasks_breaker,
    with_circuit_breaker,
    with_gmail_circuit_breaker,
    with_calendar_circuit_breaker,
    with_tasks_circuit_breaker,
    ServiceUnavailableError,
    get_breaker_state,
    get_all_breaker_states,
    reset_breaker,
    reset_all_breakers,
    gmail_list_fallback,
    calendar_list_fallback,
    generic_none_fallback,
    generic_empty_dict_fallback
)

__all__ = [
    # Retry logic
    "RetryConfig",
    "is_retryable_http_error",
    "is_rate_limit_error",
    "is_server_error",
    "retry_gmail_api",
    "retry_calendar_api",
    "retry_tasks_api",
    "retry_generic_api",
    "RetryContext",
    "is_retryable_error_code",
    # Circuit breaker
    "CircuitBreakerConfig",
    "gmail_breaker",
    "calendar_breaker",
    "tasks_breaker",
    "with_circuit_breaker",
    "with_gmail_circuit_breaker",
    "with_calendar_circuit_breaker",
    "with_tasks_circuit_breaker",
    "ServiceUnavailableError",
    "get_breaker_state",
    "get_all_breaker_states",
    "reset_breaker",
    "reset_all_breakers",
    "gmail_list_fallback",
    "calendar_list_fallback",
    "generic_none_fallback",
    "generic_empty_dict_fallback",
]

