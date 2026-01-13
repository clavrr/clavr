"""
Google Keep Exceptions

Custom exceptions for Keep service operations.
"""
from src.integrations.base_exceptions import (
    IntegrationServiceException,
    ResourceNotFoundException,
    ValidationException,
    AuthenticationException,
    ServiceUnavailableException
)


class KeepServiceException(IntegrationServiceException):
    """Base exception for Keep service errors"""
    
    def __init__(self, message: str, details: dict = None, cause: Exception = None):
        super().__init__(
            message=message,
            service_name="GoogleKeep",
            details=details,
            cause=cause
        )


class NoteNotFoundException(IntegrationServiceException):
    """Exception raised when a note is not found"""
    
    def __init__(self, note_id: str, message: str = None):
        super().__init__(
            message=message or f"Note not found: {note_id}",
            service_name="GoogleKeep",
            details={'note_id': note_id}
        )


class NoteValidationException(IntegrationServiceException):
    """Exception raised when note data is invalid"""
    
    def __init__(self, message: str, field: str = None, value: any = None):
        details = {}
        if field:
            details['field'] = field
        if value is not None:
            details['value'] = str(value)
        super().__init__(
            message=message,
            service_name="GoogleKeep",
            details=details
        )


class KeepAuthenticationException(AuthenticationException):
    """Exception raised for Keep authentication errors"""
    
    def __init__(self, message: str = None):
        super().__init__(
            message=message or "Google Keep authentication failed. Requires Google Workspace Enterprise.",
            service_name="GoogleKeep"
        )


class KeepUnavailableException(ServiceUnavailableException):
    """Exception raised when Keep service is unavailable"""
    
    def __init__(self, message: str = None, cause: Exception = None):
        super().__init__(
            message=message or "Google Keep service is unavailable",
            service_name="GoogleKeep",
            cause=cause
        )
