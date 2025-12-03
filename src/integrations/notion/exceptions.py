"""
Notion-specific exceptions

Provides structured error handling for Notion API operations.
"""
from typing import Optional, Dict, Any
import traceback


def wrap_external_exception(
    exc: Exception,
    service_name: str,
    operation: str,
    details: Optional[Dict[str, Any]] = None
) -> 'NotionServiceException':
    """
    Wrap an external exception into a NotionServiceException with context.
    
    Args:
        exc: The original exception to wrap
        service_name: Name of the service where error occurred
        operation: The operation that failed
        details: Optional additional details
        
    Returns:
        NotionServiceException with full context
    """
    error_details = details or {}
    error_details.update({
        'operation': operation,
        'original_error': str(exc),
        'error_type': type(exc).__name__,
        'traceback': traceback.format_exc()
    })
    
    return NotionServiceException(
        message=f"{service_name} operation '{operation}' failed: {str(exc)}",
        service_name=service_name,
        details=error_details,
        cause=exc
    )


class NotionServiceException(Exception):
    """Exception for Notion service operations"""
    
    def __init__(
        self, 
        message: str, 
        service_name: str = "Notion",
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        """
        Initialize Notion service exception.
        
        Args:
            message: Error message
            service_name: Service name where error occurred
            details: Optional error details
            cause: Optional original exception
        """
        super().__init__(message)
        self.message = message
        self.service_name = service_name
        self.details = details or {}
        self.cause = cause
    
    def __str__(self) -> str:
        return self.message
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary"""
        return {
            'error': self.message,
            'service': self.service_name,
            'details': self.details
        }


class NotionPageNotFoundException(NotionServiceException):
    """Exception when a Notion page is not found"""
    pass


class NotionDatabaseNotFoundException(NotionServiceException):
    """Exception when a Notion database is not found"""
    pass


class NotionAuthenticationException(NotionServiceException):
    """Exception for Notion authentication errors"""
    pass


class ServiceUnavailableException(NotionServiceException):
    """Exception when Notion service is unavailable"""
    pass

