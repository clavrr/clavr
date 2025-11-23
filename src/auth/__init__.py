"""
Authentication and authorization
"""

from .oauth import GoogleOAuthHandler
from .session import (
    create_session,
    get_session,
    delete_session,
    delete_user_sessions,
    get_current_user,
    get_admin_user,
    rotate_session_token
)
from .audit import (
    log_auth_event,
    AuditEventType,
    get_user_audit_logs,
    get_failed_login_attempts,
    get_security_summary
)
from .token_refresh import (
    refresh_token_if_needed,
    refresh_token_with_retry,
    get_valid_credentials
)

__all__ = [
    'GoogleOAuthHandler',
    'create_session',
    'get_session',
    'delete_session',
    'delete_user_sessions',
    'get_current_user',
    'get_admin_user',
    'rotate_session_token',
    'log_auth_event',
    'AuditEventType',
    'get_user_audit_logs',
    'get_failed_login_attempts',
    'get_security_summary',
    'refresh_token_if_needed',
    'refresh_token_with_retry',
    'get_valid_credentials'
]

