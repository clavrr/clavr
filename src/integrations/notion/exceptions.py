"""
Notion-specific exceptions

Provides structured error handling for Notion API operations.
Uses unified base exceptions from src.integrations.base_exceptions.
"""
from typing import Optional, Dict, Any

from src.integrations.base_exceptions import (
    NotionServiceException,
    ServiceUnavailableException as BaseServiceUnavailable,
    AuthenticationException as BaseAuthException,
    ResourceNotFoundException,
    wrap_external_exception as base_wrap_exception,
)


def wrap_external_exception(
    exc: Exception,
    service_name: str = "Notion",
    operation: str = "",
    details: Optional[Dict[str, Any]] = None
) -> 'NotionServiceException':
    """
    Wrap an external exception into a NotionServiceException with context.
    """
    base_exc = base_wrap_exception(exc, service_name, operation, details)
    return NotionServiceException(
        message=base_exc.message,
        service_name=base_exc.service_name,
        details=base_exc.details,
        cause=base_exc.cause
    )


class NotionPageNotFoundException(NotionServiceException, ResourceNotFoundException):
    """Exception when a Notion page is not found"""
    pass


class NotionDatabaseNotFoundException(NotionServiceException, ResourceNotFoundException):
    """Exception when a Notion database is not found"""
    pass


class NotionAuthenticationException(NotionServiceException, BaseAuthException):
    """Exception for Notion authentication errors"""
    pass


class ServiceUnavailableException(NotionServiceException, BaseServiceUnavailable):
    """Exception when Notion service is unavailable"""
    pass
