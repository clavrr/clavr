"""
Authentication module - OAuth, sessions, security, and user management
"""
from .oauth import GoogleOAuthHandler
from .session import (
    create_session,
    get_current_user,
    delete_user_sessions,
    get_session,
    get_session_async,
    delete_session,
    rotate_session_token,
    get_admin_user,
    invalidate_other_sessions,
    invalidate_all_sessions_except
)
from .brute_force import (
    BruteForceProtection,
    get_brute_force_protection
)
from .api_keys import (
    APIKey,
    APIScopes,
    create_api_key,
    verify_api_key,
    revoke_api_key,
    list_api_keys,
    get_api_key_user,
    require_api_key
)
from .audit import (
    AuditEventType,
    log_auth_event,
    get_user_audit_logs,
    get_failed_login_attempts,
    get_security_summary
)
from .rotation_middleware import TokenRotationMiddleware
from .constants import (
    MAX_FAILED_ATTEMPTS,
    LOCKOUT_DURATION_MINUTES,
    DEFAULT_ROTATION_INTERVAL_HOURS,
    DEFAULT_SESSION_DAYS,
    DEFAULT_REFRESH_THRESHOLD_MINUTES
)

__all__ = [
    # OAuth
    'GoogleOAuthHandler',
    # Session management
    'create_session',
    'get_current_user',
    'delete_user_sessions',
    'get_session',
    'get_session_async',
    'delete_session',
    'rotate_session_token',
    'get_admin_user',
    'invalidate_other_sessions',
    'invalidate_all_sessions_except',
    # Brute force protection
    'BruteForceProtection',
    'get_brute_force_protection',
    # API keys
    'APIKey',
    'APIScopes',
    'create_api_key',
    'verify_api_key',
    'revoke_api_key',
    'list_api_keys',
    'get_api_key_user',
    'require_api_key',
    # Audit
    'AuditEventType',
    'log_auth_event',
    'get_user_audit_logs',
    'get_failed_login_attempts',
    'get_security_summary',
    # Middleware
    'TokenRotationMiddleware',
    # Constants
    'MAX_FAILED_ATTEMPTS',
    'LOCKOUT_DURATION_MINUTES',
    'DEFAULT_ROTATION_INTERVAL_HOURS',
    'DEFAULT_SESSION_DAYS',
    'DEFAULT_REFRESH_THRESHOLD_MINUTES',
]

