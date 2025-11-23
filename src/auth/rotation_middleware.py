"""
Token Rotation Middleware

Automatically rotates session tokens that are older than a specified threshold
to enhance security by limiting the lifetime of session tokens.
"""
from datetime import datetime, timedelta
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..database import get_db
from ..database.models import Session as DBSession
from ..utils.logger import setup_logger
from ..utils import hash_token

logger = setup_logger(__name__)


class TokenRotationMiddleware(BaseHTTPMiddleware):
    """
    Rotate session tokens older than specified interval
    
    When a session token is older than the rotation interval, this middleware:
    1. Generates a new session token
    2. Updates the database
    3. Returns the new token in the X-New-Session-Token header
    4. Client should update stored token
    
    Default rotation interval: 24 hours
    """
    
    def __init__(self, app, rotation_interval_hours: int = 24):
        """
        Initialize token rotation middleware
        
        Args:
            app: FastAPI application
            rotation_interval_hours: Hours before token should be rotated (default: 24)
        """
        super().__init__(app)
        self.rotation_interval = timedelta(hours=rotation_interval_hours)
        logger.info(f"[OK] Token rotation middleware initialized (interval: {rotation_interval_hours}h)")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and rotate token if needed"""
        
        # Extract session token from Authorization header
        auth_header = request.headers.get('authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return await call_next(request)
        
        session_token = auth_header.split(' ')[1]
        
        # Get database session
        db = next(get_db())
        
        try:
            # Hash token to find session
            from ..utils import hash_token
            hashed_token = hash_token(session_token)
            
            # Find session
            session = db.query(DBSession).filter(
                DBSession.session_token == hashed_token
            ).first()
            
            if not session:
                return await call_next(request)
            
            # Check if session needs rotation
            session_age = datetime.utcnow() - session.created_at
            
            if session_age > self.rotation_interval:
                # Import rotation function
                from .session import rotate_session_token
                
                logger.info(
                    f"Session {session.id} is {session_age.total_seconds() / 3600:.1f}h old "
                    f"- rotating token"
                )
                
                # Rotate token
                new_token = rotate_session_token(
                    db=db,
                    session=session,
                    reason="periodic",
                    request=request
                )
                
                # Process request
                response = await call_next(request)
                
                # Add new token to response header
                response.headers['X-New-Session-Token'] = new_token
                
                logger.info(
                    f"[OK] Rotated session token for session {session.id}. "
                    f"Client should update stored token from X-New-Session-Token header."
                )
                
                return response
        
        except Exception as e:
            logger.error(f"Error in token rotation middleware: {e}", exc_info=True)
        
        finally:
            db.close()
        
        # If no rotation needed or error occurred, proceed normally
        return await call_next(request)
