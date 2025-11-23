"""
API Utilities

Provides pagination and validation utilities for API endpoints.
"""
import os
from typing import Optional, Any

from .pagination import (
    PaginationParams,
    PageInfo,
    PaginatedResponse,
    paginate_list,
    get_pagination_links,
    EmailListItem,
    PaginatedEmailResponse,
    CalendarEventItem,
    PaginatedCalendarResponse
)
from .validation import (
    ValidationLimits,
    DangerousPatterns,
    validate_length,
    validate_no_dangerous_patterns,
    sanitize_text,
    validate_email_address,
    validate_url,
    validate_list_length,
    validate_integer_range,
    validate_query_input,
    validate_email_body,
    validate_request_size
)
from ..config import get_api_base_url, ConfigDefaults

def get_api_url_with_fallback(obj: Optional[Any] = None) -> str:
    """
    Get API URL with consistent fallback logic.
    
    This utility function provides a consistent way to get the API base URL
    across the codebase, handling cases where config might not exist or be None.
    
    Args:
        obj: Optional object that may have a `config` attribute, or a Config instance,
             or None. If None, falls back to environment variable or default.
    
    Returns:
        API base URL string, falling back to environment variable or default.
    
    Examples:
        >>> # Object with config attribute (most common case)
        >>> get_api_url_with_fallback(self)  # self.config will be used if exists
        
        >>> # Direct config object
        >>> get_api_url_with_fallback(config)
        
        >>> # None fallback
        >>> get_api_url_with_fallback(None)
    """
    # Extract config from object if it has a config attribute
    config = None
    if obj is not None:
        if hasattr(obj, 'config'):
            config = obj.config
        elif hasattr(obj, 'server'):  # Might be a Config object directly
            config = obj
        else:
            # Assume it's a Config-like object, try to use it directly
            config = obj
    
    # get_api_base_url already handles None properly
    return get_api_base_url(config)


__all__ = [
    # Pagination
    "PaginationParams",
    "PageInfo",
    "PaginatedResponse",
    "paginate_list",
    "get_pagination_links",
    "EmailListItem",
    "PaginatedEmailResponse",
    "CalendarEventItem",
    "PaginatedCalendarResponse",
    # Validation
    "ValidationLimits",
    "DangerousPatterns",
    "validate_length",
    "validate_no_dangerous_patterns",
    "sanitize_text",
    "validate_email_address",
    "validate_url",
    "validate_list_length",
    "validate_integer_range",
    "validate_query_input",
    "validate_email_body",
    "validate_request_size",
    # API URL utilities
    "get_api_url_with_fallback",
]


