"""
API Middleware
Custom middleware for session management, error handling, logging, and CSRF protection
"""
from typing import Callable, Optional
from datetime import datetime, timedelta
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
    
    def __init__(self, app, secret_key: str, token_expires: int = 3600, excluded_paths: Optional[list] = None):
        """
        Initialize CSRF middleware
        
        Args:
            app: FastAPI application
            secret_key: Secret key for signing tokens
            token_expires: Token expiration time in seconds (default: 1 hour)
            excluded_paths: List of paths to exclude from CSRF protection
        """
        super().__init__(app)
        self.serializer = URLSafeTimedSerializer(secret_key, salt="csrf-protection")
        self.token_expires = token_expires
        self.excluded_paths = set(excluded_paths) if excluded_paths else {
            "/health", "/", "/docs", "/openapi.json", "/redoc", "/metrics",
            "/auth/google", "/auth/google/login", "/auth/google/callback"
        }
        logger.info("[OK] CSRF protection middleware initialized")
    
    def _should_protect(self, request: Request) -> bool:
        """Check if request should be CSRF protected"""
        if request.method in self.SAFE_METHODS:
            return False
        
        path = request.url.path
        if path in self.excluded_paths:
            return False
        
        for excluded in self.excluded_paths:
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
    Middleware for automatic session management (ASYNC VERSION)
    
    Attaches user and session to request.state for easy access
    Eliminates manual session queries in every endpoint
    
    Performance optimizations:
    - Uses async database operations (non-blocking)
    - In-memory LRU cache with 60-second TTL to reduce DB queries
    """
    
    # Session cache: {hashed_token: (session_data, user_data, timestamp)}
    _session_cache: dict = {}
    
    def __init__(self, app, ttl_minutes: int = 60, cache_ttl_seconds: int = 60, cache_max_size: int = 1000):
        super().__init__(app)
        self.ttl_minutes = ttl_minutes
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_max_size = cache_max_size
    
    def _extract_bearer_token(self, request: Request) -> Optional[str]:
        """Extract Bearer token from Authorization header"""
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]  # Remove 'Bearer ' prefix
        return None
    
    def _get_cached_session(self, hashed_token: str):
        """Get session from cache if valid"""
        if hashed_token in self._session_cache:
            session_data, user_data, cached_at = self._session_cache[hashed_token]
            if (datetime.now() - cached_at).total_seconds() < self.cache_ttl_seconds:
                return session_data, user_data
            else:
                del self._session_cache[hashed_token]
        return None, None
    
    def _cache_session(self, hashed_token: str, session_data, user_data):
        """Store session in cache with eviction if needed"""
        if len(self._session_cache) >= self.cache_max_size:
            sorted_entries = sorted(
                self._session_cache.items(),
                key=lambda x: x[1][2]
            )
            for key, _ in sorted_entries[:self.cache_max_size // 10]:
                del self._session_cache[key]
        
        self._session_cache[hashed_token] = (session_data, user_data, datetime.now())
    
    def _invalidate_cache(self, hashed_token: str):
        """Remove session from cache"""
        if hashed_token in self._session_cache:
            del self._session_cache[hashed_token]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and attach session if available (ASYNC with caching)"""
        from sqlalchemy import select
        from src.database.async_database import get_async_session_local
        
        # Get session token from multiple sources (header, cookie, or Authorization Bearer)
        raw_session_token = None
        token_source = "unknown"
        
        if request.query_params.get('token'):
            raw_session_token = request.query_params.get('token')
            token_source = "query_param"
        elif request.headers.get('X-Session-Token'):
            raw_session_token = request.headers.get('X-Session-Token')
            token_source = "header_x_session_token"
        elif request.cookies.get('session_token'):
            raw_session_token = request.cookies.get('session_token')
            token_source = "cookie"
        else:
            bearer_token = self._extract_bearer_token(request)
            if bearer_token:
                raw_session_token = bearer_token
                token_source = "header_bearer"
        
        if raw_session_token:
            hashed_token = hash_token(raw_session_token)
            
            # DEBUG: Log raw token details to identify mystery values
            token_preview = raw_session_token
            if len(token_preview) > 20:
                token_preview = f"{token_preview[:10]}...{token_preview[-10:]}"
            logger.info(f"Middleware received RAW token from [{token_source}]: '{token_preview}' (len={len(raw_session_token)}) -> Hash: {hashed_token[:10]}...")
            
            # Check cache first (fast path)
            cached_session, cached_user = self._get_cached_session(hashed_token)
            
            if cached_session and cached_user:
                # Use cached data
                request.state.session = cached_session
                request.state.user = cached_user
                request.state.user_id = cached_user.id
                request.state.session_id = raw_session_token
                logger.debug(f"Session cache HIT: user_id={cached_user.id}")
            else:
                # Cache miss - query database asynchronously
                try:
                    AsyncSessionLocal = get_async_session_local()
                    async with AsyncSessionLocal() as db:
                        # Query for session using hashed token
                        stmt = select(DBSession).where(
                            DBSession.session_token == hashed_token,
                            DBSession.expires_at > datetime.utcnow()
                        )
                        result = await db.execute(stmt)
                        db_session = result.scalar_one_or_none()
                        
                        if db_session:
                            # CHECK INACTIVITY TIMEOUT (60 MINUTES)
                            now = datetime.utcnow()
                            last_active = db_session.last_active_at or db_session.created_at
                            
                            if (now - last_active) > timedelta(minutes=self.ttl_minutes):
                                # Session expired due to inactivity
                                logger.warning(f"Session expired due to inactivity (>{self.ttl_minutes}m): user_id={db_session.user_id}")
                                await db.delete(db_session)
                                await db.commit()
                                self._invalidate_cache(hashed_token)
                                
                                # Detach session
                                request.state.session = None
                                request.state.user = None
                                request.state.user_id = None
                                request.state.session_id = None
                            else:
                                # Session is valid - get user
                                user_stmt = select(User).where(User.id == db_session.user_id)
                                user_result = await db.execute(user_stmt)
                                user = user_result.scalar_one_or_none()
                                
                                if user:
                                    # Update last_active_at if more than 30 seconds have passed
                                    if (now - last_active) > timedelta(seconds=30):
                                        db_session.last_active_at = now
                                        await db.commit()
                                    
                                    # Cache the session and user for future requests
                                    self._cache_session(hashed_token, db_session, user)
                                    
                                    # Attach to request state
                                    request.state.session = db_session
                                    request.state.user = user
                                    request.state.user_id = db_session.user_id
                                    request.state.session_id = raw_session_token
                                    logger.debug(f"Session cache MISS, loaded from DB: user_id={db_session.user_id}")
                                else:
                                    logger.warning(f"Session found but user not found: {db_session.user_id}")
                                    request.state.session = None
                                    request.state.user = None
                                    request.state.user_id = None
                                    request.state.session_id = None
                        else:
                            # No valid session
                            logger.info(f"Invalid session token found: {hashed_token[:10]}")
                            request.state.session = None
                            request.state.user = None
                            request.state.user_id = None
                            request.state.session_id = None
                            
                            # Process request but mark/clear cookie on response
                            response = await call_next(request)
                            
                            # NUCLEAR COOKIE DELETION - Kill it everywhere
                            # But SKIP if we are on the callback route (which sets a new cookie)
                            is_callback = "/auth/google/callback" in request.url.path
                            
                            if token_source == "cookie" and not is_callback and "session_token" not in response.headers.get("set-cookie", "").lower():
                                logger.info(f"🔥 Nuke invalid cookie at multiple paths/domains (Path: {request.url.path})")
                                # Standard delete
                                response.delete_cookie("session_token")
                                response.delete_cookie("session_token", path="/")
                                response.delete_cookie("session_token", path="/api")
                                # Domain specific deletes (fixes localhost vs 127.0.0.1 issues)
                                response.delete_cookie("session_token", domain="localhost")
                                response.delete_cookie("session_token", domain="localhost", path="/")
                                response.delete_cookie("session_token", domain="127.0.0.1")
                                response.delete_cookie("session_token", domain="127.0.0.1", path="/")
                            return response
                            
                except Exception as e:
                    logger.error(f"Error in async session lookup: {e}", exc_info=True)
                    request.state.session = None
                    request.state.user = None
                    request.state.user_id = None
                    request.state.session_id = None
        else:
            # No session token provided
            logger.debug(f"No authentication token provided in request to {request.url.path}")
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

