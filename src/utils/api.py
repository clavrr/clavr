"""
API URL utilities
"""
import os
from typing import Optional
from urllib.parse import urljoin


def get_api_base_url() -> str:
    """
    Get the base API URL from environment or default
    
    Returns:
        Base API URL
    """
    return os.getenv("API_BASE_URL", "http://localhost:8000")


def get_api_url_with_fallback(
    primary_url: Optional[str] = None,
    fallback_url: Optional[str] = None
) -> str:
    """
    Get API URL with fallback
    
    Args:
        primary_url: Primary URL to use
        fallback_url: Fallback URL if primary not available
        
    Returns:
        API URL
    """
    if primary_url:
        return primary_url
    if fallback_url:
        return fallback_url
    return get_api_base_url()


def build_api_url(
    path: str,
    base_url: Optional[str] = None,
    version: str = "v1"
) -> str:
    """
    Build a full API URL
    
    Args:
        path: API path (e.g., "/users")
        base_url: Optional base URL override
        version: API version (default "v1")
        
    Returns:
        Full API URL
    """
    base = base_url or get_api_base_url()
    
    # Ensure base ends without slash
    base = base.rstrip('/')
    
    # Ensure path starts with slash
    if not path.startswith('/'):
        path = '/' + path
    
    # Add version if not already in path
    if version and not path.startswith(f'/api/{version}') and not path.startswith(f'/{version}'):
        path = f'/api/{version}{path}'
    
    return f"{base}{path}"

