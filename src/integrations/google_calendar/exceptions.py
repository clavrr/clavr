"""
Google Calendar-specific exceptions

Provides structured error handling for Google Calendar API operations.
"""
from typing import Optional, Dict, Any
import traceback


def wrap_external_exception(
    exc: Exception,
    service_name: str,
    operation: str,
    details: Optional[Dict[str, Any]] = None
) -> 'CalendarServiceException':
    """
    Wrap an external exception into a CalendarServiceException with context.
    
    Args:
        exc: The original exception to wrap
        service_name: Name of the service where error occurred
        operation: The operation that failed
        details: Optional additional details
        
    Returns:
        CalendarServiceException with full context
    """
    error_details = details or {}
    error_details.update({
        'operation': operation,
        'original_error': str(exc),
        'error_type': type(exc).__name__,
        'traceback': traceback.format_exc()
    })
    
    return CalendarServiceException(
        message=f"{service_name} operation '{operation}' failed: {str(exc)}",
        service_name=service_name,
        details=error_details,
        cause=exc
    )


class CalendarServiceException(Exception):
    """Exception for calendar service operations"""
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "GoogleCalendar",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        self.message = message
        self.service_name = service_name
        self.details = details or {}
        self.cause = cause
        super().__init__(self.message)


class EventNotFoundException(CalendarServiceException):
    """Exception raised when calendar event is not found"""
    pass


class SchedulingConflictException(CalendarServiceException):
    """Exception raised when there's a scheduling conflict"""
    pass


class InvalidTimeRangeException(CalendarServiceException):
    """Exception raised for invalid time ranges"""
    pass


class CalendarIntegrationException(CalendarServiceException):
    """Exception for calendar integration operations"""
    pass


class ServiceUnavailableException(CalendarServiceException):
    """Exception raised when Calendar service is unavailable"""
    pass


class AuthenticationException(CalendarServiceException):
    """Exception raised for Calendar authentication failures"""
    pass


class ConfigurationException(CalendarServiceException):
    """Exception raised for Calendar configuration issues"""
    pass
