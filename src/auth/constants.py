"""
Auth Module Constants

Centralized constants for authentication and security configuration.
"""

# ============================================================================
# Brute Force Protection
# ============================================================================
MAX_FAILED_ATTEMPTS = 5  # Lock account after this many failed attempts
LOCKOUT_DURATION_MINUTES = 30  # Lock for this duration
PROGRESSIVE_DELAY_ENABLED = True  # Add delays after failed attempts
PROGRESSIVE_DELAY_BASE_SECONDS = 1  # Base delay (doubles each attempt)
MAX_DELAY_SECONDS = 30  # Maximum delay cap

# ============================================================================
# Token Rotation
# ============================================================================
DEFAULT_ROTATION_INTERVAL_HOURS = 24  # Rotate session tokens after this period

# ============================================================================
# Session Defaults
# ============================================================================
DEFAULT_SESSION_DAYS = 7  # Session duration in days
DEFAULT_REFRESH_THRESHOLD_MINUTES = 5  # Refresh token when expiring within this time

# ============================================================================
# API Keys
# ============================================================================
DEFAULT_API_KEY_EXPIRY_DAYS = 365  # Default API key expiration (1 year)

# ============================================================================
# Audit Logging
# ============================================================================
DEFAULT_AUDIT_LOG_LIMIT = 100  # Default limit for audit log queries
FAILED_LOGIN_WINDOW_HOURS = 1  # Time window for failed login tracking
SECURITY_SUMMARY_HOURS = 24  # Default time window for security summary
