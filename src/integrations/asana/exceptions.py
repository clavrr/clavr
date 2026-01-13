"""
Asana Integration Exceptions

Custom exceptions for Asana service operations.
"""
from ..base_exceptions import IntegrationServiceException


class AsanaServiceException(IntegrationServiceException):
    """Base exception for Asana service errors."""
    pass


class AsanaTaskNotFoundException(AsanaServiceException):
    """Raised when a task cannot be found."""
    
    def __init__(self, task_id: str, message: str = None):
        self.task_id = task_id
        super().__init__(message or f"Task not found: {task_id}")


class AsanaAuthenticationException(AsanaServiceException):
    """Raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication with Asana failed"):
        super().__init__(message)


class AsanaRateLimitException(AsanaServiceException):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, retry_after: int = None):
        self.retry_after = retry_after
        message = "Asana rate limit exceeded"
        if retry_after:
            message += f". Retry after {retry_after} seconds"
        super().__init__(message)


class AsanaValidationException(AsanaServiceException):
    """Raised when input validation fails."""
    
    def __init__(self, field: str, message: str = None):
        self.field = field
        super().__init__(message or f"Validation failed for field: {field}")


class AsanaProjectNotFoundException(AsanaServiceException):
    """Raised when a project cannot be found."""
    
    def __init__(self, project_id: str, message: str = None):
        self.project_id = project_id
        super().__init__(message or f"Project not found: {project_id}")
