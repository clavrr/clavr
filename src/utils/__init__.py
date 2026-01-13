"""
Utils Package - Common utilities and helper functions

Exports commonly used utilities for easy importing.
"""
from .security import (
    generate_session_token,
    hash_token,
    verify_token,
    generate_api_key,
    constant_time_compare
)
from .encryption import (
    encrypt_token,
    decrypt_token,
    TokenEncryption,
    get_encryption,
    generate_key
)
from .config import (
    Config,
    RAGConfig,
    AIConfig,
    DatabaseConfig,
    AgentConfig,
    load_config,
    get_timezone,
    get_frontend_url,
    _replace_env_vars
)
from .retry import (
    retry_gmail_api,
    retry_calendar_api,
    retry_tasks_api,
    retry_generic_api,
    RetryConfig,
    is_retryable_http_error,
    is_rate_limit_error,
    is_server_error,
    is_retryable_error_code
)
from .resilience import (
    with_gmail_circuit_breaker,
    with_calendar_circuit_breaker,
    with_tasks_circuit_breaker,
    calendar_list_fallback,
    gmail_list_fallback,
    tasks_list_fallback,
    ServiceUnavailableError,
    CircuitBreaker
)
from .api import (
    get_api_url_with_fallback,
    get_api_base_url,
    build_api_url
)
from .performance import (
    PerformanceContext,
    track_time,
    timed,
    LatencyMonitor
)
from .attachment_processor import AttachmentProcessor
from .sanitization import (
    sanitize_html,
    sanitize_string,
    sanitize_email,
    sanitize_url,
    sanitize_filename,
    sanitize_dict,
    create_html_sanitizer,
    create_string_sanitizer
)
from .secrets import (
    SecretsManager,
    get_secrets_manager,
    get_secret,
    get_required_secret
)
from .user.user_utils import extract_first_name
from .datetime import FlexibleDateParser

__all__ = [
    # Security functions
    'generate_session_token',
    'hash_token',
    'verify_token',
    'generate_api_key',
    'constant_time_compare',
    # Encryption functions
    'encrypt_token',
    'decrypt_token',
    'TokenEncryption',
    'get_encryption',
    'generate_key',
    # Config classes and functions
    'Config',
    'RAGConfig',
    'AIConfig',
    'DatabaseConfig',
    'AgentConfig',
    'load_config',
    'get_timezone',
    'get_frontend_url',
    '_replace_env_vars',
    # Retry utilities
    'retry_gmail_api',
    'retry_calendar_api',
    'retry_tasks_api',
    'retry_generic_api',
    'RetryConfig',
    'is_retryable_http_error',
    'is_rate_limit_error',
    'is_server_error',
    'is_retryable_error_code',
    # Resilience utilities
    'with_gmail_circuit_breaker',
    'with_calendar_circuit_breaker',
    'with_tasks_circuit_breaker',
    'calendar_list_fallback',
    'gmail_list_fallback',
    'tasks_list_fallback',
    'ServiceUnavailableError',
    'CircuitBreaker',
    # API utilities
    'get_api_url_with_fallback',
    'get_api_base_url',
    'build_api_url',
    # Performance utilities
    'PerformanceContext',
    'track_time',
    'timed',
    'LatencyMonitor',
    # Attachment processor
    'AttachmentProcessor',
    # Sanitization utilities
    'sanitize_html',
    'sanitize_string',
    'sanitize_email',
    'sanitize_url',
    'sanitize_filename',
    'sanitize_dict',
    'create_html_sanitizer',
    'create_string_sanitizer',
    # Secrets utilities
    'SecretsManager',
    'get_secrets_manager',
    'get_secret',
    'get_required_secret',
    # User utilities
    'extract_first_name',
    # DateTime utilities
    'FlexibleDateParser',
]
