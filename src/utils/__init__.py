"""
Utility modules - Shared utilities for the application

This module should NEVER import from other src modules (ai, core, services, agent, features)
to maintain the import hierarchy and prevent circular dependencies.

All utilities are exported here for consistent access across the application.
"""

# ============================================
# CONFIGURATION
# ============================================
from .config import Config, load_config, get_timezone, get_api_base_url, get_frontend_url

# ============================================
# LOGGING
# ============================================
from .logger import setup_logger

# ============================================
# DATE/TIME PARSING
# ============================================
from .datetime import (
    FlexibleDateParser,
    parse_natural_time,
    normalize_datetime_start,
    normalize_datetime_end,
    get_time_of_day_range,
    days_until_weekday
)

# ============================================
# FINANCIAL/RECEIPT PARSING
# ============================================
from .financial import (
    ReceiptParser,
    FinancialAggregator,
    CurrencyValidationConfig,
    BASE_CURRENCY_PATTERNS,
    PAYMENT_PATTERNS,
    SUBSCRIPTION_PATTERNS,
    CURRENCY_PATTERNS,
    ENHANCED_CURRENCY_PATTERNS
)

# ============================================
# USER UTILITIES
# ============================================
from .user import extract_first_name

# ============================================
# SECURITY & ENCRYPTION
# ============================================
from .security import (
    generate_session_token,
    hash_token,
    verify_token,
    generate_api_key,
    constant_time_compare,
    TokenEncryption,
    get_encryption,
    generate_key,
    encrypt_token,
    decrypt_token
)

# ============================================
# RESILIENCE (RETRY & CIRCUIT BREAKER)
# ============================================
from .resilience import (
    RetryConfig,
    is_retryable_http_error,
    is_rate_limit_error,
    is_server_error,
    retry_gmail_api,
    retry_calendar_api,
    retry_tasks_api,
    retry_generic_api,
    RetryContext,
    is_retryable_error_code,
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

# ============================================
# PERFORMANCE (CACHING, STATS, MONITORING)
# ============================================
from .performance import (
    PerformanceMonitor,
    get_monitor,
    track_performance,
    PerformanceContext,
    Metrics,
    CacheConfig,
    CacheManager,
    get_cache_manager,
    generate_cache_key,
    cached,
    invalidate_cache,
    invalidate_user_cache,
    CacheStats,
    APIStats,
    StatsTracker,
    get_stats_tracker,
    shutdown_stats_tracker
)

# ============================================
# API UTILITIES (PAGINATION & VALIDATION)
# ============================================
from .api import (
    PaginationParams,
    PageInfo,
    PaginatedResponse,
    paginate_list,
    get_pagination_links,
    EmailListItem,
    PaginatedEmailResponse,
    CalendarEventItem,
    PaginatedCalendarResponse,
    ValidationLimits,
    DangerousPatterns,
    validate_length,
    validate_no_dangerous_patterns,
    sanitize_text,
    validate_email_address,
    validate_url,
    validate_list_length,
    validate_integer_range,
    validate_query_input,
    validate_email_body,
    validate_request_size
)

# ============================================
# INTENT KEYWORDS
# ============================================
from .intent import (
    IntentKeywords,
    get_intent_keywords,
    load_intent_keywords
)

# Note: AttachmentProcessor removed - use AttachmentParser from services.indexing.parsers instead

__all__ = [
    # Config
    "Config",
    "load_config",
    "get_timezone",
    "get_api_base_url",
    "get_frontend_url",
    # Logging
    "setup_logger",
    # Date/time parsing
    "FlexibleDateParser",
    "parse_natural_time",
    "normalize_datetime_start",
    "normalize_datetime_end",
    "get_time_of_day_range",
    "days_until_weekday",
    # Financial/receipt parsing
    "ReceiptParser",
    "FinancialAggregator",
    "CurrencyValidationConfig",
    "BASE_CURRENCY_PATTERNS",
    "PAYMENT_PATTERNS",
    "SUBSCRIPTION_PATTERNS",
    "CURRENCY_PATTERNS",
    "ENHANCED_CURRENCY_PATTERNS",
    # User utilities
    "extract_first_name",
    # Security
    "generate_session_token",
    "hash_token",
    "verify_token",
    "generate_api_key",
    "constant_time_compare",
    # Encryption
    "TokenEncryption",
    "get_encryption",
    "generate_key",
    "encrypt_token",
    "decrypt_token",
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
    # Performance monitoring
    "PerformanceMonitor",
    "get_monitor",
    "track_performance",
    "PerformanceContext",
    "Metrics",
    # Validation
    "ValidationLimits",
    "DangerousPatterns",
    "validate_length",
    "validate_no_dangerous_patterns",
    "sanitize_text",
    "validate_email_address",
    "validate_url",
    "validate_list_length",
    "validate_integer_range",
    "validate_query_input",
    "validate_email_body",
    "validate_request_size",
    # Pagination
    "PaginationParams",
    "PageInfo",
    "PaginatedResponse",
    "paginate_list",
    "get_pagination_links",
    "EmailListItem",
    "PaginatedEmailResponse",
    "CalendarEventItem",
    "PaginatedCalendarResponse",
    # Intent keywords
    "IntentKeywords",
    "get_intent_keywords",
    "load_intent_keywords",
]

