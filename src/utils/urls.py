"""
Centralized URL Constants

This module provides a single source of truth for all URLs used in the application.
All services should import URLs from here instead of having hardcoded defaults.
"""
import os


class URLs:
    """
    Centralized URL constants for all services.
    
    All URLs fallback to localhost for development, but can be overridden
    via environment variables for production.
    
    Usage:
        from src.utils.urls import URLs
        
        # Use in code
        arango_uri = URLs.ARANGODB
        api_base = URLs.API_BASE
    """
    
    # Database URLs
    # Database URLs
    
    # ArangoDB URLs
    ARANGODB: str = os.getenv('ARANGODB_URL', 'http://localhost:8529')
    ARANGODB_USER: str = os.getenv('ARANGODB_USER', 'root')
    ARANGODB_PASSWORD: str = os.getenv('ARANGODB_PASSWORD', 'password')
    ARANGODB_DB: str = os.getenv('ARANGODB_DB_NAME', 'clavr')
    
    REDIS: str = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    DATABASE: str = os.getenv('DATABASE_URL', 'sqlite:///./data/emails.db')
    
    # API URLs
    API_BASE: str = os.getenv('API_BASE_URL', 'http://localhost:8000')
    FRONTEND: str = os.getenv('FRONTEND_URL', 'http://localhost:3000')
    
    # OAuth URLs
    OAUTH_REDIRECT: str = os.getenv(
        'GOOGLE_REDIRECT_URI', 
        f"{os.getenv('API_BASE_URL', 'http://localhost:8000')}/auth/google/callback"
    )
    
    # External service URLs
    GOOGLE_AUTH: str = 'https://accounts.google.com/o/oauth2/auth'
    GOOGLE_TOKEN: str = 'https://oauth2.googleapis.com/token'
    
    @classmethod
    def get_redis_host(cls) -> str:
        """Extract Redis host from REDIS URL"""
        url = cls.REDIS
        # Parse redis://host:port/db format
        if '://' in url:
            url = url.split('://')[1]
        if ':' in url:
            return url.split(':')[0]
        return url
    
    @classmethod
    def get_redis_port(cls) -> int:
        """Extract Redis port from REDIS URL"""
        url = cls.REDIS
        if '://' in url:
            url = url.split('://')[1]
        if ':' in url:
            port_part = url.split(':')[1]
            if '/' in port_part:
                port_part = port_part.split('/')[0]
            return int(port_part)
        return 6379
    
    @classmethod
    def is_development(cls) -> bool:
        """Check if running in development mode (localhost URLs)"""
        return 'localhost' in cls.API_BASE or '127.0.0.1' in cls.API_BASE


# Convenience exports

REDIS_URL = URLs.REDIS
API_BASE_URL = URLs.API_BASE
FRONTEND_URL = URLs.FRONTEND
OAUTH_REDIRECT_URI = URLs.OAUTH_REDIRECT
