"""
Core Base Exceptions
"""

class BaseCoreException(Exception):
    """Base exception for core modules"""
    pass

class AuthenticationExpiredError(BaseCoreException):
    """Raised when authentication credentials have expired and cannot be refreshed (invalid_grant)"""
    pass

class ServiceUnavailableError(BaseCoreException):
    """Raised when a required external service is unavailable"""
    pass
