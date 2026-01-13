"""
Gmail-specific exceptions

Provides structured error handling for Gmail API operations.
Uses unified base exceptions from src.integrations.base_exceptions.
"""
from typing import Optional, Dict, Any

from src.integrations.base_exceptions import (
    EmailServiceException,
    ServiceUnavailableException as BaseServiceUnavailable,
    AuthenticationException as BaseAuthException,
    ConfigurationException as BaseConfigException,
    ResourceNotFoundException,
    wrap_external_exception as base_wrap_exception,
)


def wrap_external_exception(
    exc: Exception,
    service_name: str = "Gmail",
    operation: str = "",
    details: Optional[Dict[str, Any]] = None
) -> 'EmailServiceException':
    """
    Wrap an external exception into an EmailServiceException with context.
    
    This is a thin wrapper around the base wrap_external_exception that
    returns an EmailServiceException for backward compatibility.
    """
    base_exc = base_wrap_exception(exc, service_name, operation, details)
    return EmailServiceException(
        message=base_exc.message,
        service_name=base_exc.service_name,
        details=base_exc.details,
        cause=base_exc.cause
    )


# Re-export EmailServiceException from base for imports
# (already imported above, just documenting)


class EmailNotFoundException(EmailServiceException, ResourceNotFoundException):
    """Exception raised when email is not found"""
    pass


class EmailSendException(EmailServiceException):
    """Exception raised when email sending fails"""
    pass


class EmailSearchException(EmailServiceException):
    """Exception raised when email search fails"""
    pass


class EmailIntegrationException(EmailServiceException):
    """Exception for email integration operations"""
    pass


class ServiceUnavailableException(EmailServiceException, BaseServiceUnavailable):
    """Exception raised when Gmail service is unavailable"""
    pass


class AuthenticationException(EmailServiceException, BaseAuthException):
    """Exception raised for Gmail authentication failures"""
    pass


class ConfigurationException(EmailServiceException, BaseConfigException):
    """Exception raised for Gmail configuration issues"""
    pass
