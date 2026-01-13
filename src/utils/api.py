"""
API URL utilities
"""
import os
from typing import Optional
from urllib.parse import urljoin

from .urls import URLs


from .urls import URLs


def get_api_base_url() -> str:
    """
    Get the base API URL (centralized source of truth).
    """
    return URLs.API_BASE


def get_api_url_with_fallback(
    primary_url: Optional[str] = None,
    fallback_url: Optional[str] = None
) -> str:
    """
    Get API URL with fallback.
    """
    return primary_url or fallback_url or get_api_base_url()


def build_api_url(
    path: str,
    base_url: Optional[str] = None,
    version: str = "v1"
) -> str:
    """
    Build a full API URL with proper path joining and versioning.
    """
    base = (base_url or get_api_base_url()).rstrip('/')
    
    # Ensure path starts with slash
    if not path.startswith('/'):
        path = '/' + path
    
    # Add version if not already in path
    api_prefix = f'/api/{version}'
    if version and not path.startswith(api_prefix) and not path.startswith(f'/{version}'):
        path = f'{api_prefix}{path}'
    
    return f"{base}{path}"

