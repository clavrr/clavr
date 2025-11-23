"""
Gmail-specific exceptions

Provides structured error handling for Gmail API operations.
"""
from typing import Optional, Dict, Any
import traceback


def wrap_external_exception(
    exc: Exception,
    service_name: str,
    operation: str,
    details: Optional[Dict[str, Any]] = None
) -> 'EmailServiceException':
    """
    Wrap an external exception into an EmailServiceException with context.
    
    Args:
        exc: The original exception to wrap
        service_name: Name of the service where error occurred
        operation: The operation that failed
        details: Optional additional details
        
    Returns:
        EmailServiceException with full context
    """
    error_details = details or {}
    error_details.update({
        'operation': operation,
        'original_error': str(exc),
        'error_type': type(exc).__name__,
        'traceback': traceback.format_exc()
    })
    
    return EmailServiceException(
        message=f"{service_name} operation '{operation}' failed: {str(exc)}",
        service_name=service_name,
        details=error_details,
        cause=exc
    )


class EmailServiceException(Exception):
    """Exception for email service operations"""
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "Gmail",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        self.message = message
        self.service_name = service_name
        self.details = details or {}
        self.cause = cause
        super().__init__(self.message)


class EmailNotFoundException(EmailServiceException):
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


class ServiceUnavailableException(EmailServiceException):
    """Exception raised when Gmail service is unavailable"""
    pass


class AuthenticationException(EmailServiceException):
    """Exception raised for Gmail authentication failures"""
    pass


class ConfigurationException(EmailServiceException):
    """Exception raised for Gmail configuration issues"""
    pass
