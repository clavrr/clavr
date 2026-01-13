"""
Security Headers Middleware

Adds essential security headers to all HTTP responses to protect against
common web vulnerabilities (XSS, clickjacking, MIME sniffing, etc.)
"""
from typing import Callable, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all responses.
    
    Headers added:
    - X-Frame-Options: Prevent clickjacking
    - X-Content-Type-Options: Prevent MIME sniffing
    - X-XSS-Protection: XSS filter (legacy browsers)
    - Content-Security-Policy: Control resource loading
    - Strict-Transport-Security: Force HTTPS
    - Referrer-Policy: Control referrer information
    - Permissions-Policy: Control browser features
    """
    
    def __init__(
        self,
        app,
        enable_hsts: bool = True,
        hsts_max_age: int = 31536000,
        csp_policy: Optional[str] = None,
        frame_options: str = "DENY",
        referrer_policy: str = "strict-origin-when-cross-origin",
        sensitive_paths: Optional[list] = None
    ):
        """
        Initialize security headers middleware.
        
        Args:
            app: FastAPI application
            enable_hsts: Enable Strict-Transport-Security (disable for local dev)
            hsts_max_age: HSTS max-age in seconds
            csp_policy: Custom Content-Security-Policy (None for default)
            frame_options: X-Frame-Options value (DENY, SAMEORIGIN)
            referrer_policy: Referrer-Policy value
            sensitive_paths: List of sensitive path prefixes for cache control
        """
        super().__init__(app)
        self.enable_hsts = enable_hsts
        self.hsts_max_age = hsts_max_age
        self.frame_options = frame_options
        self.referrer_policy = referrer_policy
        self.sensitive_paths = sensitive_paths or [
            "/auth", "/api/auth", "/api/chat", "/api/emails",
            "/api/calendar", "/api/tasks", "/api/profile",
            "/api/admin", "/api/export"
        ]
        
        # Default CSP - restrictive but functional
        self.csp_policy = csp_policy or (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://apis.google.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https://apis.google.com https://*.googleapis.com wss:; "
            "frame-src 'self' https://accounts.google.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        
        logger.info("[OK] Security headers middleware initialized")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to response."""
        response = await call_next(request)
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = self.frame_options
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # XSS protection for legacy browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = self.csp_policy
        
        # Strict Transport Security (HTTPS only)
        if self.enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self.hsts_max_age}; includeSubDomains; preload"
            )
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = self.referrer_policy
        
        # Permissions Policy (formerly Feature-Policy)
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), "
            "camera=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "microphone=(), "
            "payment=(), "
            "usb=()"
        )
        
        # Cache control for sensitive endpoints
        if self._is_sensitive_endpoint(request.url.path):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        
        return response
    
    def _is_sensitive_endpoint(self, path: str) -> bool:
        """Check if endpoint contains sensitive data."""
        return any(path.startswith(prefix) for prefix in self.sensitive_paths)
