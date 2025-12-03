"""
API Middleware
Custom middleware for session management, error handling, logging, and CSRF protection
"""
from typing import Callable, Optional
from datetime import datetime
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from src.database import get_db
from src.database.models import Session as DBSession, User
from src.utils.logger import setup_logger
from src.utils import hash_token

logger = setup_logger(__name__)


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF Protection Middleware
    
    Implements Double Submit Cookie pattern:
    1. Generates CSRF token and stores in cookie (httponly=False for JS access)
    2. Client must send token in X-CSRF-Token header for state-changing requests
    3. Validates token matches for POST/PUT/PATCH/DELETE requests
    
    Protects against CSRF attacks by ensuring requests originate from your frontend.
    """
    
    # Safe methods that don't need CSRF protection
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
    
    # Endpoints to exclude from CSRF protection (public endpoints)
    EXCLUDED_PATHS = {
        "/health",
        "/",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/metrics",
        "/auth/google",  # OAuth initiation endpoint (GET request)
        "/auth/google/login",
        "/auth/google/callback",
    }
    
    def __init__(self, app, secret_key: str, token_expires: int = 3600):
        """
        Initialize CSRF middleware
        
        Args:
            app: FastAPI application
            secret_key: Secret key for signing tokens
            token_expires: Token expiration time in seconds (default: 1 hour)
        """
        super().__init__(app)
        self.serializer = URLSafeTimedSerializer(secret_key, salt="csrf-protection")
        self.token_expires = token_expires
        logger.info("[OK] CSRF protection middleware initialized")
    
    def _should_protect(self, request: Request) -> bool:
        """Check if request should be CSRF protected"""
        # Skip safe methods
        if request.method in self.SAFE_METHODS:
            return False
        
        # Skip excluded paths
        path = request.url.path
        if path in self.EXCLUDED_PATHS:
            return False
        
        # Skip paths starting with excluded prefixes
        for excluded in self.EXCLUDED_PATHS:
            if path.startswith(excluded):
                return False
        
        return True
    
    def _generate_token(self, session_id: Optional[str] = None) -> str:
        """
        Generate CSRF token
        
        Args:
            session_id: Optional session ID to bind token to specific session
            
        Returns:
            Signed CSRF token
        """
        # Use session_id if available, otherwise use timestamp
        data = session_id or str(datetime.utcnow().timestamp())
        return self.serializer.dumps(data)
    
    def _validate_token(self, token: str, session_id: Optional[str] = None) -> bool:
        """
        Validate CSRF token
        
        Args:
            token: CSRF token to validate
            session_id: Optional session ID to verify token binding
            
        Returns:
            True if valid, False otherwise
        """
        try:
            data = self.serializer.loads(token, max_age=self.token_expires)
            
            # If session_id provided, verify token is bound to this session
            if session_id and data != session_id:
                logger.warning(f"CSRF token session mismatch: expected {session_id}, got {data}")
                return False
            
            return True
        except SignatureExpired:
            logger.warning("CSRF token expired")
            return False
        except BadSignature:
            logger.warning("CSRF token has invalid signature")
            return False
        except Exception as e:
            logger.error(f"CSRF token validation error: {e}")
            return False
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with CSRF protection"""
        
        # For safe methods, generate token and add to response
        if request.method in self.SAFE_METHODS:
            response = await call_next(request)
            
            # Generate CSRF token (bind to session if available)
            session_id = getattr(request.state, 'session_id', None)
            csrf_token = self._generate_token(session_id)
            
            # Add token to cookie (httponly=False so JS can read it)
            response.set_cookie(
                key="csrf_token",
                value=csrf_token,
                max_age=self.token_expires,
                httponly=False,  # Allow JavaScript to read
                secure=True,  # HTTPS only in production
                samesite="lax"  # Prevent CSRF from external sites
            )
            
            # Also add to header for convenience
            response.headers["X-CSRF-Token"] = csrf_token
            
            return response
        
        # For unsafe methods, validate CSRF token
        if self._should_protect(request):
            # Get token from header or form data
            token_from_header = request.headers.get("X-CSRF-Token")
            token_from_cookie = request.cookies.get("csrf_token")
            
            # Try to get from form data (for traditional form submissions)
            token_from_form = None
            if request.method == "POST":
                try:
                    form = await request.form()
                    token_from_form = form.get("csrf_token")
                except Exception:
                    pass
            
            # Token must be provided
            provided_token = token_from_header or token_from_form
            if not provided_token:
                logger.warning(f"CSRF token missing for {request.method} {request.url.path}")
                raise HTTPException(
                    status_code=403,
                    detail="CSRF token missing. Please include X-CSRF-Token header."
                )
            
            # Token from cookie must exist
            if not token_from_cookie:
                logger.warning(f"CSRF cookie missing for {request.method} {request.url.path}")
                raise HTTPException(
                    status_code=403,
                    detail="CSRF cookie missing. Please refresh the page."
                )
            
            # Tokens must match (Double Submit Cookie pattern)
            if provided_token != token_from_cookie:
                logger.warning(f"CSRF token mismatch for {request.method} {request.url.path}")
                raise HTTPException(
                    status_code=403,
                    detail="CSRF token mismatch. Security violation detected."
                )
            
            # Validate token signature and expiration
            session_id = getattr(request.state, 'session_id', None)
            if not self._validate_token(provided_token, session_id):
                logger.warning(f"CSRF token validation failed for {request.method} {request.url.path}")
                raise HTTPException(
                    status_code=403,
                    detail="Invalid or expired CSRF token. Please refresh the page."
                )
            
            logger.debug(f"CSRF token validated for {request.method} {request.url.path}")
        
        # Process request
        response = await call_next(request)
        return response


class SessionMiddleware(BaseHTTPMiddleware):
    """
    Middleware for automatic session management
    
    Attaches user and session to request.state for easy access
    Eliminates manual session queries in every endpoint
    """
    
    def _extract_bearer_token(self, request: Request) -> Optional[str]:
        """Extract Bearer token from Authorization header"""
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]  # Remove 'Bearer ' prefix
        return None
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and attach session if available (with secure token hashing)"""
        
        # Get session token from multiple sources (header, cookie, or Authorization Bearer)
        raw_session_token = (
            request.headers.get('X-Session-Token') or 
            request.cookies.get('session_token') or
            self._extract_bearer_token(request)
        )
        
        if raw_session_token:
            # Get database session
            db = next(get_db())
            try:
                # Hash the raw token to match stored hash
                hashed_token = hash_token(raw_session_token)
                
                # Query for session using hashed token
                db_session = db.query(DBSession).filter(
                    DBSession.session_token == hashed_token,
                    DBSession.expires_at > datetime.utcnow()
                ).first()
                
                if db_session:
                    # Attach to request state
                    request.state.session = db_session
                    request.state.user = db_session.user
                    request.state.user_id = db_session.user_id
                    request.state.session_id = raw_session_token  # Store raw token for CSRF binding
                    logger.debug(f"Session attached: user_id={db_session.user_id}")
                else:
                    # No valid session
                    request.state.session = None
                    request.state.user = None
                    request.state.user_id = None
                    request.state.session_id = None
            finally:
                db.close()
        else:
            # No session token provided
            request.state.session = None
            request.state.user = None
            request.state.user_id = None
            request.state.session_id = None
        
        # Process request
        response = await call_next(request)
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for consistent error handling
    
    Catches all exceptions and returns properly formatted error responses
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with error handling"""
        import uuid
        from datetime import datetime
        from api.exceptions import APIException, InternalServerError, create_error_response
        
        # Generate request ID for tracing
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        
        try:
            response = await call_next(request)
            return response
        
        except APIException as e:
            # Custom API exceptions - format properly
            logger.error(f"API Error [{request_id}] in {request.url.path}: {e.error}", exc_info=True)
            return create_error_response(
                error_type=e.error,
                message=e.message or str(e.detail),
                details=e.details,
                status_code=e.status_code
            )
        
        except HTTPException as e:
            # FastAPI HTTPException - format consistently
            logger.error(f"HTTP Error [{request_id}] {e.status_code} in {request.url.path}: {e.detail}")
            return create_error_response(
                error_type="http_error",
                message=str(e.detail),
                status_code=e.status_code
            )
        
        except Exception as e:
            # Unexpected error - log and return formatted response
            logger.error(f"Unexpected error [{request_id}] in {request.url.path}: {e}", exc_info=True)
            
            # Don't expose internal error details to clients
            return create_error_response(
                error_type="internal_server_error",
                message="An unexpected error occurred. Please try again later.",
                status_code=500
            )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request/response logging
    
    Logs all API requests with timing information and metadata
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response with metadata"""
        start_time = datetime.now()
        request_id = getattr(request.state, 'request_id', 'unknown')
        
        # Get user info if available
        user_info = ""
        if hasattr(request.state, 'user') and request.state.user:
            user_info = f" | user={request.state.user.id}"
        
        # Log request
        logger.info(f"[{request_id}] → {request.method} {request.url.path}{user_info}")
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        
        # Get response size if available
        response_size = ""
        if hasattr(response, 'headers') and 'content-length' in response.headers:
            size_kb = int(response.headers['content-length']) / 1024
            response_size = f" | size={size_kb:.1f}KB"
        
        # Log response
        logger.info(
            f"[{request_id}] ← {request.method} {request.url.path} - "
            f"{response.status_code} ({duration:.2f}s){response_size}"
        )
        
        return response


# ============================================
# DEPENDENCY FOR SESSION ACCESS
# ============================================

def require_session(request: Request) -> DBSession:
    """
    FastAPI dependency that requires valid session
    
    Usage:
        @app.get("/protected")
        def endpoint(session: DBSession = Depends(require_session)):
            user_id = session.user_id
            ...
    
    Raises:
        HTTPException: If no valid session
    """
    if not hasattr(request.state, 'session') or request.state.session is None:
        raise HTTPException(
            status_code=401,
            detail="No active session - please log in"
        )
    
    return request.state.session


def get_current_user(request: Request) -> Optional[User]:
    """
    FastAPI dependency to get current user (optional)
    
    Usage:
        @app.get("/profile")
        def profile(user: User = Depends(get_current_user)):
            if user:
                return user.email
            return "Not logged in"
    
    Returns:
        User object or None if not logged in
    """
    if hasattr(request.state, 'user'):
        return request.state.user
    return None

