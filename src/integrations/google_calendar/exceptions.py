"""
Google Calendar-specific exceptions

Provides structured error handling for Google Calendar API operations.
Uses unified base exceptions from src.integrations.base_exceptions.
"""
from typing import Optional, Dict, Any

from src.integrations.base_exceptions import (
    CalendarServiceException,
    ServiceUnavailableException as BaseServiceUnavailable,
    AuthenticationException as BaseAuthException,
    ConfigurationException as BaseConfigException,
    ResourceNotFoundException,
    ValidationException,
    wrap_external_exception as base_wrap_exception,
)


def wrap_external_exception(
    exc: Exception,
    service_name: str = "GoogleCalendar",
    operation: str = "",
    details: Optional[Dict[str, Any]] = None
) -> 'CalendarServiceException':
    """
    Wrap an external exception into a CalendarServiceException with context.
    """
    base_exc = base_wrap_exception(exc, service_name, operation, details)
    return CalendarServiceException(
        message=base_exc.message,
        service_name=base_exc.service_name,
        details=base_exc.details,
        cause=base_exc.cause
    )


class EventNotFoundException(CalendarServiceException, ResourceNotFoundException):
    """Exception raised when calendar event is not found"""
    pass


class SchedulingConflictException(CalendarServiceException, ValidationException):
    """Exception raised when there's a scheduling conflict"""
    pass


class InvalidTimeRangeException(CalendarServiceException, ValidationException):
    """Exception raised for invalid time ranges"""
    pass


class CalendarIntegrationException(CalendarServiceException):
    """Exception for calendar integration operations"""
    pass


class ServiceUnavailableException(CalendarServiceException, BaseServiceUnavailable):
    """Exception raised when Calendar service is unavailable"""
    pass


class AuthenticationException(CalendarServiceException, BaseAuthException):
    """Exception raised for Calendar authentication failures"""
    pass


class ConfigurationException(CalendarServiceException, BaseConfigException):
    """Exception raised for Calendar configuration issues"""
    pass
