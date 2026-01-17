"""
Session Management - Clean Token-Based Authentication with Secure Token Hashing
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..database import get_db
from ..database.models import Session as DBSession, User
from ..utils.logger import setup_logger
from ..utils import (
    generate_session_token,
    hash_token,
    verify_token,
    encrypt_token,
    decrypt_token
)
from .audit import log_auth_event, AuditEventType

logger = setup_logger(__name__)
security = HTTPBearer()


async def create_session(
    db,  # Can be Session or AsyncSession
    user_id: int,
    gmail_access_token: str,
    gmail_refresh_token: Optional[str] = None,
    token_expiry: Optional[datetime] = None,
    granted_scopes: Optional[list] = None,
    days: int = 7,
    request: Optional[Request] = None
) -> DBSession:
    """
    Create a new user session with secure token hashing and encryption
    
    Security:
        - Generates cryptographically secure random token
        - Stores only SHA-256 hash in database (never stores raw session token)
        - Encrypts Gmail tokens before storing (Fernet encryption)
        - Returns session object with raw token for client
        - Logs session creation event
    
    Args:
        db: Database session
        user_id: User ID
        gmail_access_token: Gmail API access token (will be encrypted)
        gmail_refresh_token: Gmail API refresh token (will be encrypted)
        token_expiry: Token expiration time
        granted_scopes: List of OAuth scopes granted by user (e.g., ['openid', 'email', 'calendar'])
        days: Session duration in days
        request: FastAPI request (for audit logging)
        
    Returns:
        Session object with raw token (only time raw token is available)
    """
    # Generate secure token and its hash
    raw_token, hashed_token = generate_session_token()
    
    # Encrypt Gmail tokens before storage
    try:
        encrypted_access_token = encrypt_token(gmail_access_token)
        encrypted_refresh_token = encrypt_token(gmail_refresh_token) if gmail_refresh_token else None
    except Exception as e:
        logger.error(f"Failed to encrypt Gmail tokens: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to secure tokens"
        )
    
    # Convert scopes list to comma-separated string for storage
    scopes_str = ",".join(granted_scopes) if granted_scopes else None
    
    # Create session with HASHED session token and ENCRYPTED Gmail tokens
    db_session = DBSession(
        user_id=user_id,
        session_token=hashed_token,  # Store HASH, not raw token
        gmail_access_token=encrypted_access_token,  # Store ENCRYPTED token
        gmail_refresh_token=encrypted_refresh_token,  # Store ENCRYPTED token
        granted_scopes=scopes_str,  # Store granted OAuth scopes
        token_expiry=token_expiry,
        expires_at=datetime.utcnow() + timedelta(days=days)
    )
    
    db.add(db_session)
    
    # Store the session ID before commit (for logging)
    # Note: ID might be None until flush/commit
    # Check if this is an async session
    if hasattr(db, 'flush') and hasattr(db.flush, '__call__'):
        try:
            # Try async flush
            await db.flush()
        except TypeError:
            # Fall back to sync flush (shouldn't happen with AsyncSession)
            pass
    
    session_id = db_session.id
    expires_at_iso = db_session.expires_at.isoformat()
    
    # Commit the session
    await db.commit()
    
    # IMPORTANT: Expunge (detach) the session from SQLAlchemy tracking
    # This prevents any further modifications from being auto-committed
    db.expunge(db_session)
    
    # Log session creation
    await log_auth_event(
        db=db,
        event_type=AuditEventType.SESSION_CREATED,
        user_id=user_id,
        success=True,
        request=request,
        session_id=session_id,
        expires_at=expires_at_iso,
        tokens_encrypted=True
    )
    
    # IMPORTANT: NOW replace hashed token with raw token for client
    # Since we expunged the object, this change won't be saved to DB
    db_session.session_token = raw_token
    
    logger.debug(f"Session created for user_id: {user_id}, token: {raw_token[:8]}... (tokens encrypted and hashed)")
    return db_session


def get_session(db: Session, session_token: str) -> Optional[DBSession]:
    """
    Get session by token (with secure hash verification)
    
    Security:
        - Hashes the incoming raw token
        - Compares hash against stored hash in database
        - Never stores or logs raw tokens
    
    Args:
        db: Database session
        session_token: Raw session token from client
        
    Returns:
        Session object or None if expired/not found
    """
    logger.debug(f"Looking up session - token length: {len(session_token)}")
    
    # Hash the incoming token to match stored hash
    hashed_token = hash_token(session_token)
    logger.debug(f"Hashed token (first 20 chars): {hashed_token[:20]}...")
    
    # Query by hashed token
    session = db.query(DBSession).filter(
        DBSession.session_token == hashed_token
    ).first()
    
    if not session:
        logger.debug(f"No session found for hashed token")
        return None
    
    logger.debug(f"Found session: id={session.id}, user_id={session.user_id}, expires_at={session.expires_at}")
    
    if session.is_expired():
        logger.info(f"Session expired: {session.id}")
        return None
    
    logger.debug(f"Session valid: {session.id}")
    return session


async def get_session_async(db, session_token: str) -> Optional[DBSession]:
    """
    Get session by token (ASYNC version with non-blocking database queries)
    
    Use this version in async contexts to avoid blocking the event loop.
    
    Security:
        - Hashes the incoming raw token
        - Compares hash against stored hash in database
        - Never stores or logs raw tokens
    
    Args:
        db: AsyncSession database session
        session_token: Raw session token from client
        
    Returns:
        Session object or None if expired/not found
    """
    from sqlalchemy import select
    from datetime import datetime
    
    logger.debug(f"[ASYNC] Looking up session - token length: {len(session_token)}")
    
    # Hash the incoming token to match stored hash
    hashed_token = hash_token(session_token)
    logger.debug(f"[ASYNC] Hashed token (first 20 chars): {hashed_token[:20]}...")
    
    # Query by hashed token using async select
    stmt = select(DBSession).where(
        DBSession.session_token == hashed_token,
        DBSession.expires_at > datetime.utcnow()
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        logger.debug(f"[ASYNC] No valid session found for hashed token")
        return None
    
    logger.debug(f"[ASYNC] Found session: id={session.id}, user_id={session.user_id}")
    return session


from sqlalchemy import select

async def delete_session(db: Session, session_token: str, request: Optional[Request] = None) -> bool:
    """
    Delete a session (logout) with secure hash verification
    """
    hashed_token = hash_token(session_token)
    stmt = select(DBSession).where(DBSession.session_token == hashed_token)
    
    is_async = False
    try:
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        is_async = True
    except (AttributeError, TypeError):
        result = db.execute(stmt)
        session = result.scalar_one_or_none()
    
    if session:
        user_id = session.user_id
        session_id = session.id
        
        db.delete(session) # Sync operation on both
        
        if is_async:
            await db.commit()
        else:
            db.commit()
        
        # Log session deletion
        await log_auth_event(
            db=db,
            event_type=AuditEventType.LOGOUT,
            user_id=user_id,
            success=True,
            request=request,
            session_id=session_id
        )
        
        logger.info(f"Deleted session: {session_id}")
        return True
    
    return False


async def delete_user_sessions(db: Session, user_id: int, request: Optional[Request] = None) -> int:
    """
    Delete all sessions for a user (logout all devices)
    """
    stmt = select(DBSession).where(DBSession.user_id == user_id)
    
    is_async = False
    try:
        result = await db.execute(stmt)
        sessions = result.scalars().all()
        is_async = True
    except (AttributeError, TypeError):
        result = db.execute(stmt)
        sessions = result.scalars().all()
        
    count = len(sessions)
    
    for session in sessions:
        db.delete(session) # Sync operation
    
    if is_async:
        await db.commit()
    else:
        db.commit()
    
    # Log logout event
    await log_auth_event(
        db=db,
        event_type=AuditEventType.LOGOUT,
        user_id=user_id,
        success=True,
        request=request,
        sessions_deleted=count
    )
    
    logger.info(f"Deleted {count} sessions for user_id: {user_id}")
    return count


async def invalidate_other_sessions(
    db: Session,
    user_id: int,
    current_session_id: int,
    reason: str = "security_action",
    request: Optional[Request] = None
) -> int:
    """
    Invalidate all sessions except the current one.
    """
    stmt = select(DBSession).where(
        DBSession.user_id == user_id,
        DBSession.id != current_session_id
    )
    
    is_async = False
    try:
        result = await db.execute(stmt)
        other_sessions = result.scalars().all()
        is_async = True
    except (AttributeError, TypeError):
        result = db.execute(stmt)
        other_sessions = result.scalars().all()
    
    count = len(other_sessions)
    
    for session in other_sessions:
        db.delete(session)
    
    if is_async:
        await db.commit()
    else:
        db.commit()
    
    # Log the event
    await log_auth_event(
        db=db,
        event_type=AuditEventType.SESSION_REVOKED,
        user_id=user_id,
        success=True,
        request=request,
        sessions_invalidated=count,
        reason=reason,
        kept_session_id=current_session_id
    )
    
    logger.info(
        f"Invalidated {count} other sessions for user_id: {user_id} (kept session {current_session_id}). "
        f"Reason: {reason}"
    )
    return count


async def invalidate_all_sessions_except(
    db: Session,
    user_id: int,
    except_session_token: Optional[str] = None,
    reason: str = "security_action",
    request: Optional[Request] = None
) -> int:
    """
    Invalidate all sessions for a user, optionally keeping one by token.
    """
    if except_session_token:
        # Hash the token to find the session to keep
        hashed_token = hash_token(except_session_token)
        
        stmt = select(DBSession).where(DBSession.session_token == hashed_token)
        
        # We need check usage here too, but can reuse helper logic or just try/except
        try:
            result = await db.execute(stmt)
            current_session = result.scalar_one_or_none()
        except (AttributeError, TypeError):
            result = db.execute(stmt)
            current_session = result.scalar_one_or_none()
        
        if current_session:
            return await invalidate_other_sessions(
                db, user_id, current_session.id, reason, request
            )
    
    # If no token or session not found, invalidate all
    return await delete_user_sessions(db, user_id, request)


def rotate_session_token(
    db: Session,
    session: DBSession,
    reason: str = "periodic",
    request: Optional[Request] = None
) -> str:
    """
    Rotate session token for enhanced security
    
    This generates a new session token and replaces the old one.
    Should be called:
    - Periodically (e.g., every 24 hours)
    - After privilege escalation
    - After password change
    - For high-risk actions
    
    Args:
        db: Database session
        session: Session to rotate
        reason: Reason for rotation (for audit log)
        request: FastAPI request (for audit logging)
        
    Returns:
        New raw token (to send to client)
    """
    # Generate new token
    raw_token, hashed_token = generate_session_token()
    
    # Store old session info for logging
    old_session_id = session.id
    user_id = session.user_id
    
    # Update session with new token
    session.session_token = hashed_token
    
    db.commit()
    db.refresh(session)
    
    # Note: Audit logging should be done by the caller
    # since this is a sync function and log_auth_event is async
    
    logger.info(
        f"Rotated session token for session {old_session_id} (user {user_id}). "
        f"Reason: {reason}"
    )
    
    return raw_token


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user from Bearer token or session cookie
    
    OPTIMIZED: First checks request.state (populated by SessionMiddleware with caching)
    before falling back to database lookup. This avoids redundant DB queries.
    
    Supports two authentication methods:
    1. Bearer token in Authorization header (preferred for API calls)
    2. Session cookie (fallback for browser-based flows)
    
    Usage in endpoints:
        async def my_endpoint(user: User = Depends(get_current_user)):
            ...
    
    Args:
        request: HTTP request
        credentials: HTTP Bearer token (optional)
        db: Database session
        
    Returns:
        Authenticated User object
        
    Raises:
        HTTPException 401: If authentication fails
    """
    # FAST PATH: Check if SessionMiddleware already populated user in request.state
    # This avoids redundant database queries when middleware cache is working
    if hasattr(request.state, 'user') and request.state.user is not None:
        logger.debug(f"Using cached user from middleware: user_id={request.state.user.id}")
        return request.state.user
    
    # SLOW PATH: Fallback to database lookup (only if middleware didn't populate)
    session_token = None
    auth_method = None
    
    # Debug logging
    logger.debug(f"Auth attempt - Headers: {dict(request.headers)}")
    logger.debug(f"Auth attempt - Cookies: {dict(request.cookies)}")
    logger.debug(f"Auth attempt - Credentials present: {credentials is not None}")
    
    # Try to get token from Authorization header first
    if credentials:
        session_token = credentials.credentials
        auth_method = "Bearer token"
        logger.debug(f"Using Bearer token (length: {len(session_token)})")
    # Fallback to cookie
    elif "session_token" in request.cookies:
        session_token = request.cookies.get("session_token")
        auth_method = "Cookie"
        logger.debug(f"Using Cookie (length: {len(session_token)})")
    
    if not session_token:
        logger.warning(
            f"No authentication provided. "
            f"Headers: {dict(request.headers)}, "
            f"Cookies: {dict(request.cookies)}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please provide Bearer token or session cookie.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.info(f"Authenticating via {auth_method} (middleware cache miss)")
    
    # Get session
    session = get_session(db, session_token)
    if not session:
        logger.warning(f"Invalid or expired session token (via {auth_method})")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        logger.error(f"Session found but user {session.user_id} not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.info(f"Authenticated user {user.id} ({user.email}) via {auth_method}")
    return user



async def get_admin_user(
    user: User = Depends(get_current_user)
) -> User:
    """
    Get current authenticated user and verify admin access
    
    Usage in endpoints:
        async def admin_endpoint(admin: User = Depends(get_admin_user)):
            ...
    
    Args:
        user: Current authenticated user (from get_current_user)
        
    Returns:
        Authenticated User object with admin privileges
        
    Raises:
        HTTPException 403: If user is not an admin
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return user
