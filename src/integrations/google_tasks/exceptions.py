"""
Google Tasks-specific exceptions

Provides structured error handling for Google Tasks API operations.
"""
from typing import Optional, Dict, Any
import traceback


def wrap_external_exception(
    exc: Exception,
    service_name: str,
    operation: str,
    details: Optional[Dict[str, Any]] = None
) -> 'TaskServiceException':
    """
    Wrap an external exception into a TaskServiceException with context.
    
    Args:
        exc: The original exception to wrap
        service_name: Name of the service where error occurred
        operation: The operation that failed
        details: Optional additional details
        
    Returns:
        TaskServiceException with full context
    """
    error_details = details or {}
    error_details.update({
        'operation': operation,
        'original_error': str(exc),
        'error_type': type(exc).__name__,
        'traceback': traceback.format_exc()
    })
    
    return TaskServiceException(
        message=f"{service_name} operation '{operation}' failed: {str(exc)}",
        service_name=service_name,
        details=error_details,
        cause=exc
    )


class TaskServiceException(Exception):
    """Exception for task service operations"""
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "GoogleTasks",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        self.message = message
        self.service_name = service_name
        self.details = details or {}
        self.cause = cause
        super().__init__(self.message)


class TaskNotFoundException(TaskServiceException):
    """Exception raised when task is not found"""
    pass


class TaskValidationException(TaskServiceException):
    """Exception raised when task validation fails"""
    pass


class TaskIntegrationException(TaskServiceException):
    """Exception for task integration operations"""
    pass


class ServiceUnavailableException(TaskServiceException):
    """Exception raised when Tasks service is unavailable"""
    pass


class AuthenticationException(TaskServiceException):
    """Exception raised for Tasks authentication failures"""
    pass


class ConfigurationException(TaskServiceException):
    """Exception raised for Tasks configuration issues"""
    pass
