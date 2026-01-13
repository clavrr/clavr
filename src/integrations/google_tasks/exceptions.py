"""
Google Tasks-specific exceptions

Provides structured error handling for Google Tasks API operations.
Uses unified base exceptions from src.integrations.base_exceptions.
"""
from typing import Optional, Dict, Any

from src.integrations.base_exceptions import (
    TaskServiceException,
    ServiceUnavailableException as BaseServiceUnavailable,
    AuthenticationException as BaseAuthException,
    ConfigurationException as BaseConfigException,
    ResourceNotFoundException,
    ValidationException,
    wrap_external_exception as base_wrap_exception,
)


def wrap_external_exception(
    exc: Exception,
    service_name: str = "GoogleTasks",
    operation: str = "",
    details: Optional[Dict[str, Any]] = None
) -> 'TaskServiceException':
    """
    Wrap an external exception into a TaskServiceException with context.
    """
    base_exc = base_wrap_exception(exc, service_name, operation, details)
    return TaskServiceException(
        message=base_exc.message,
        service_name=base_exc.service_name,
        details=base_exc.details,
        cause=base_exc.cause
    )


class TaskNotFoundException(TaskServiceException, ResourceNotFoundException):
    """Exception raised when task is not found"""
    pass


class TaskValidationException(TaskServiceException, ValidationException):
    """Exception raised when task validation fails"""
    pass


class TaskIntegrationException(TaskServiceException):
    """Exception for task integration operations"""
    pass


class ServiceUnavailableException(TaskServiceException, BaseServiceUnavailable):
    """Exception raised when Tasks service is unavailable"""
    pass


class AuthenticationException(TaskServiceException, BaseAuthException):
    """Exception raised for Tasks authentication failures"""
    pass


class ConfigurationException(TaskServiceException, BaseConfigException):
    """Exception raised for Tasks configuration issues"""
    pass
