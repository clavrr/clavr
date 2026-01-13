"""
Rate Limit Exception Handler
Logs rate limit violations to audit logs
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from src.auth.audit import log_auth_event, AuditEventType
from src.database import get_db
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom rate limit exceeded handler
    
    Logs the rate limit violation to audit logs for security monitoring
    
    Args:
        request: The FastAPI request
        exc: The RateLimitExceeded exception
        
    Returns:
        JSONResponse with 429 status code
    """
    # Extract user ID if authenticated
    user_id = None
    try:
        # Try to get user from request state (set by auth middleware)
        if hasattr(request.state, 'user') and request.state.user:
            user_id = request.state.user.id
    except Exception:
        pass
    
    # Log to audit logs
    db = next(get_db())
    try:
        await log_auth_event(
            db=db,
            event_type=AuditEventType.RATE_LIMIT_EXCEEDED,
            user_id=user_id,
            success=False,
            request=request,
            endpoint=request.url.path,
            limit=str(exc.detail)
        )
        # Note: log_auth_event handles its own commit
    except Exception as e:
        logger.error(f"Failed to log rate limit event: {e}")
    finally:
        db.close()
    
    # Log to application logs
    logger.warning(
        f"Rate limit exceeded: {request.client.host} -> {request.method} {request.url.path} "
        f"(User: {user_id or 'anonymous'})"
    )
    
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": "Too many requests. Please try again later.",
            "retry_after": getattr(exc, "retry_after", 60)
        }
    )
