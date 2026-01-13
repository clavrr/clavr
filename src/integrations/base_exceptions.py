"""
Base Integration Exceptions

Unified exception hierarchy for all integration modules.
This eliminates duplicate exception classes across gmail, google_tasks,
google_calendar, and notion integrations.

Usage:
    from src.integrations.base_exceptions import (
        IntegrationServiceException,
        ServiceUnavailableException,
        AuthenticationException,
        ConfigurationException,
        ResourceNotFoundException,
        wrap_external_exception,
    )
"""
from typing import Optional, Dict, Any
import traceback


def wrap_external_exception(
    exc: Exception,
    service_name: str,
    operation: str,
    details: Optional[Dict[str, Any]] = None
) -> 'IntegrationServiceException':
    """
    Wrap an external exception into an IntegrationServiceException with context.
    
    This is a unified wrapper function to replace the duplicated 
    wrap_external_exception functions in each integration module.
    
    Args:
        exc: The original exception to wrap
        service_name: Name of the service where error occurred (e.g., "Gmail", "Notion")
        operation: The operation that failed (e.g., "list_emails", "create_page")
        details: Optional additional details
        
    Returns:
        IntegrationServiceException with full context
    """
    error_details = details or {}
    error_details.update({
        'operation': operation,
        'original_error': str(exc),
        'error_type': type(exc).__name__,
        'traceback': traceback.format_exc()
    })
    
    return IntegrationServiceException(
        message=f"{service_name} operation '{operation}' failed: {str(exc)}",
        service_name=service_name,
        details=error_details,
        cause=exc
    )


class IntegrationServiceException(Exception):
    """
    Base exception for all integration service operations.
    
    All integration-specific exceptions should inherit from this class.
    """
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "Integration",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        self.message = message
        self.service_name = service_name
        self.details = details or {}
        self.cause = cause
        super().__init__(self.message)
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(service={self.service_name}, message={self.message})"


# ============================================================================
# Common Integration Exceptions
# ============================================================================

class ServiceUnavailableException(IntegrationServiceException):
    """Exception raised when an integration service is unavailable."""
    pass


class AuthenticationException(IntegrationServiceException):
    """Exception raised for authentication/authorization failures."""
    pass


class ConfigurationException(IntegrationServiceException):
    """Exception raised for configuration issues (missing API keys, etc.)."""
    pass


class ResourceNotFoundException(IntegrationServiceException):
    """Exception raised when a requested resource is not found."""
    pass


class RateLimitException(IntegrationServiceException):
    """Exception raised when API rate limits are exceeded."""
    pass


class ValidationException(IntegrationServiceException):
    """Exception raised for input validation failures."""
    pass


class OperationFailedException(IntegrationServiceException):
    """Exception raised when an operation fails (generic failure)."""
    pass


# ============================================================================
# Service-Specific Base Exceptions (for backward compatibility)
# ============================================================================

class EmailServiceException(IntegrationServiceException):
    """Base exception for email service (Gmail) operations."""
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "Gmail",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message, service_name, details, cause)


class TaskServiceException(IntegrationServiceException):
    """Base exception for task service (Google Tasks) operations."""
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "GoogleTasks",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message, service_name, details, cause)


class CalendarServiceException(IntegrationServiceException):
    """Base exception for calendar service (Google Calendar) operations."""
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "GoogleCalendar",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message, service_name, details, cause)


class NotionServiceException(IntegrationServiceException):
    """Base exception for Notion service operations."""
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "Notion",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message, service_name, details, cause)
