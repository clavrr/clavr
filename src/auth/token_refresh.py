"""
Automatic Token Refresh Service

Handles automatic refresh of expired or soon-to-expire OAuth tokens
and persists them back to the database with encryption.
"""
import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Tuple, cast, List
from sqlalchemy.orm import Session

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from ..database.models import Session as DBSession
from ..utils.logger import setup_logger
from ..utils import decrypt_token, encrypt_token
from .oauth import LOGIN_SCOPES, SCOPES
from .audit import log_auth_event, AuditEventType

logger = setup_logger(__name__)


async def refresh_token_with_retry(
    db: Session,
    session: DBSession,
    scopes: Optional[List[str]] = None,
    refresh_threshold_minutes: int = 5,
    max_retries: int = 3,
    backoff_factor: float = 2.0
) -> Tuple[bool, Optional[Credentials]]:
    """
    Refresh token with exponential backoff retry logic
    
    This handles transient network errors by retrying failed refresh attempts
    with exponential backoff (2^attempt seconds). Automatically decrypts tokens
    from database and encrypts refreshed tokens before storage.
    
    Args:
        db: Database session
        session: Database session object
        refresh_threshold_minutes: Refresh token if it expires within this many minutes
        max_retries: Maximum number of retry attempts (default: 3)
        backoff_factor: Multiplier for each retry delay (default: 2.0)
        
    Returns:
        (was_refreshed, credentials) tuple
        - was_refreshed: True if token was refreshed
        - credentials: Credentials object (refreshed or original)
    """
    if scopes is None:
        # Fallback 1: Use granted_scopes from session if available
        if hasattr(session, 'granted_scopes') and session.granted_scopes:
            scopes = session.granted_scopes.split(',')
            logger.debug(f"Using granted_scopes from session: {scopes}")
        else:
            # Fallback 2: Use minimal login scopes instead of the full monolithic list
            # This prevents invalid_scope errors for users who haven't granted all permissions
            scopes = LOGIN_SCOPES
            logger.debug(f"No scopes provided or found in session, using LOGIN_SCOPES: {scopes}")

    if not session.gmail_refresh_token:
        logger.debug(f"Session {session.id} has no refresh token - cannot refresh")
        return False, None
    
    # Check if we've already determined this token is invalid (to avoid repeated attempts)
    # This prevents spam warnings for known invalid tokens
    if hasattr(session, '_token_invalid') and session._token_invalid:
        logger.debug(f"Session {session.id} token already known to be invalid - skipping refresh attempt")
        return False, None
    
    # Decrypt tokens from database
    try:
        access_token = decrypt_token(session.gmail_access_token)
        refresh_token = decrypt_token(session.gmail_refresh_token)
    except Exception as e:
        # Decryption failed - token may be encrypted with different key or corrupted
        # This is expected for stale sessions or after encryption key changes
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else "Unknown decryption error"
        logger.debug(
            f"Failed to decrypt tokens for session {session.id} (stale/corrupted token): "
            f"{error_type} - {error_msg}. Session will need re-authentication."
        )
        await log_auth_event(
            db=db,
            event_type=AuditEventType.TOKEN_REFRESH_FAILURE,
            user_id=session.user_id,
            success=False,
            error_message=f"Token decryption failed: {error_type} - {error_msg}",
            session_id=session.id
        )
        return False, None
    
    # Create credentials object
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        logger.warning("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET not configured")
        return False, None
    
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes
    )
    
    # Set expiry from database if available
    if session.token_expiry:
        credentials.expiry = session.token_expiry
    
    # Check if token needs refresh
    needs_refresh = False
    
    if credentials.expired:
        logger.info(f"Token expired for session {session.id} - refreshing")
        needs_refresh = True
    elif session.token_expiry:
        # Check if token expires within threshold
        # Handle both timezone-aware and naive datetimes
        expiry = session.token_expiry
        if expiry.tzinfo:
            # Timezone-aware: use UTC now
            from datetime import timezone
            now = datetime.now(timezone.utc)
            time_until_expiry = expiry - now
        else:
            # Naive datetime: treat as UTC and compare with utcnow()
            now = datetime.utcnow()
            time_until_expiry = expiry - now
        if time_until_expiry < timedelta(minutes=refresh_threshold_minutes):
            logger.info(f"Token expires in {time_until_expiry.total_seconds()/60:.1f} minutes - refreshing proactively")
            needs_refresh = True
    
    if not needs_refresh:
        return False, credentials
    
    # Refresh the token with retry logic
    for attempt in range(max_retries):
        try:
            credentials.refresh(Request())
            logger.info(f"Successfully refreshed token for session {session.id} (attempt {attempt + 1})")
            
            # Encrypt and save refreshed tokens to database
            # Google may rotate the refresh token, so we should check for it
            encrypted_access_token = encrypt_token(credentials.token)
            session.gmail_access_token = cast(str, encrypted_access_token)
            
            if credentials.refresh_token and credentials.refresh_token != refresh_token:
                logger.info(f"Refresh token rotated for session {session.id} - saving new token")
                session.gmail_refresh_token = cast(str, encrypt_token(credentials.refresh_token))
            
            if credentials.expiry:
                session.token_expiry = credentials.expiry.replace(tzinfo=None)
            
            db.commit()
            db.refresh(session)
            
            # Log successful token refresh
            await log_auth_event(
                db=db,
                event_type=AuditEventType.TOKEN_REFRESH_SUCCESS,
                user_id=session.user_id,
                success=True,
                session_id=session.id,
                attempt=attempt + 1,
                encrypted=True
            )
            
            logger.info(f"Saved encrypted refreshed token to database for session {session.id}")
            return True, credentials
            
        except Exception as e:
            error_str = str(e)
            error_type = type(e).__name__
            
            # Log the error details for debugging (before determining error type)
            logger.debug(
                f"Token refresh attempt {attempt + 1} failed for session {session.id}: "
                f"{error_type}: {error_str}"
            )
            
            # Check if it's an invalid_scope error
            if "invalid_scope" in error_str.lower() and scopes is not None:
                logger.debug(f"Refresh for session {session.id} failed with invalid_scope. Retrying with implicit scopes...")
                try:
                    # Re-initialize credentials without explicit scopes
                    credentials = Credentials(
                        token=access_token,
                        refresh_token=refresh_token,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=client_id,
                        client_secret=client_secret,
                        scopes=None
                    )
                    credentials.refresh(Request())
                    logger.info(f"Successfully refreshed token for session {session.id} using implicit scopes")
                    
                    # Update tokens in database
                    encrypted_access_token = encrypt_token(credentials.token)
                    session.gmail_access_token = cast(str, encrypted_access_token)
                    
                    if credentials.refresh_token and credentials.refresh_token != refresh_token:
                        session.gmail_refresh_token = cast(str, encrypt_token(credentials.refresh_token))
                    
                    if credentials.expiry:
                        session.token_expiry = credentials.expiry.replace(tzinfo=None)
                    
                    db.commit()
                    db.refresh(session)
                    
                    # Log successful token refresh
                    await log_auth_event(
                        db=db,
                        event_type=AuditEventType.TOKEN_REFRESH_SUCCESS,
                        user_id=session.user_id,
                        success=True,
                        session_id=session.id,
                        attempt=attempt + 1,
                        encrypted=True
                    )
                    return True, credentials
                except Exception as retry_err:
                    logger.debug(f"Implicit refresh retry also failed: {retry_err}")
                    # Fall through to standard error handling and retry logic
            
            # Check if it's an invalid_grant error (permanent - token revoked/expired)
            # Google OAuth can raise various exceptions, check for invalid_grant in multiple ways
            # Common exception types: RefreshError, OAuth2Error, or generic Exception with invalid_grant message
            is_invalid_grant = False
            
            # Check error message first (most reliable)
            if "invalid_grant" in error_str.lower():
                is_invalid_grant = True
                logger.debug(f"Detected invalid_grant from error message: {error_str[:100]}")
            # Check exception type (RefreshError from google.auth.exceptions is almost always invalid_grant)
            elif "RefreshError" in error_type:
                is_invalid_grant = True
                logger.debug(f"Detected invalid_grant from exception type: {error_type}")
            # Check for OAuth2Error with invalid_grant
            elif "OAuth2Error" in error_type and "invalid_grant" in error_str.lower():
                is_invalid_grant = True
                logger.debug(f"Detected invalid_grant from OAuth2Error: {error_str[:100]}")
            # Check exception attributes
            elif hasattr(e, 'error_code') and str(e.error_code) == 'invalid_grant':
                is_invalid_grant = True
                logger.debug(f"Detected invalid_grant from error_code attribute: {e.error_code}")
            elif hasattr(e, 'status_code') and e.status_code == 400:
                # 400 with invalid_grant in message is likely invalid_grant
                if "invalid_grant" in error_str.lower():
                    is_invalid_grant = True
                    logger.debug(f"Detected invalid_grant from 400 status with message: {error_str[:100]}")
            
            # Check if it's a network/connection error
            is_network_error = (
                not is_invalid_grant and (
                    "TransportError" in error_type or
                    "Unable to find the server" in error_str or
                    "Connection" in error_type or
                    "network" in error_str.lower() or
                    "timeout" in error_str.lower() or
                    "DNS" in error_str
                )
            )
            
            # Don't retry on invalid_grant - it's a permanent error
            if is_invalid_grant:
                # Mark session as having invalid token to prevent future refresh attempts
                session._token_invalid = True
                
                # Use DEBUG level for expected scenarios (token revoked/expired)
                # Only log once per session to avoid spam - this is expected behavior
                if not hasattr(session, '_invalid_token_logged'):
                    logger.info(
                    f"Refresh token invalid for session {session.id} (user_id={session.user_id}): "
                    f"Token has been revoked or expired. User needs to re-authenticate. "
                    f"This is expected when: user changes password, revokes access, or token expires after 6 months of inactivity."
                )
                    session._invalid_token_logged = True
                else:
                    logger.debug(
                        f"Refresh token invalid for session {session.id} (user_id={session.user_id}) - "
                        f"already logged, skipping duplicate warning"
                    )
                
                # Log token refresh failure (audit log should still record it, but only once)
                if not hasattr(session, '_audit_logged'):
                    await log_auth_event(
                        db=db,
                        event_type=AuditEventType.TOKEN_REFRESH_FAILURE,
                        user_id=session.user_id,
                        success=False,
                        error_message=f"invalid_grant: Refresh token revoked or expired. Re-authentication required.",
                        session_id=session.id,
                        attempts=attempt + 1
                    )
                    session._audit_logged = True
                
                db.rollback()
                return False, None
            
            wait_time = backoff_factor ** attempt
            
            if attempt < max_retries - 1:
                if is_network_error:
                    logger.warning(
                        f"Network error during token refresh for session {session.id} "
                        f"(attempt {attempt + 1}/{max_retries}): {error_type}: {error_str}. "
                        f"This is likely a transient network issue. Retrying in {wait_time}s..."
                    )
                else:
                    logger.warning(
                        f"Token refresh failed for session {session.id} "
                        f"(attempt {attempt + 1}/{max_retries}): {error_type}: {error_str}. "
                        f"Retrying in {wait_time}s..."
                    )
                await asyncio.sleep(wait_time)
            else:
                if is_network_error:
                    logger.error(
                        f"Token refresh failed for session {session.id} "
                        f"after {max_retries} attempts due to network error: {error_type}: {error_str}. "
                        f"Please check your internet connection."
                    )
                else:
                    # Only log full traceback for unexpected errors (not invalid_grant)
                    logger.error(
                        f"Token refresh failed for session {session.id} "
                        f"after {max_retries} attempts: {error_type}: {error_str}"
                    )
                
                # Log token refresh failure
                await log_auth_event(
                    db=db,
                    event_type=AuditEventType.TOKEN_REFRESH_FAILURE,
                    user_id=session.user_id,
                    success=False,
                    error_message=str(e),
                    session_id=session.id,
                    attempts=max_retries
                )
                
                db.rollback()
                # Return original credentials if available (don't fail completely on network errors)
                if is_network_error and credentials and not credentials.expired:
                    logger.info(f"Using existing credentials despite network error (token still valid)")
                    return False, credentials
                return False, None
    
    return False, None


async def refresh_token_if_needed(
    db: Session,
    session: DBSession,
    scopes: Optional[List[str]] = None,
    refresh_threshold_minutes: int = 5
) -> Tuple[bool, Optional[Credentials]]:
    """
    Refresh token if expired or about to expire, and save to database.
    
    Args:
        db: Database session
        session: Database session object
        refresh_threshold_minutes: Refresh token if it expires within this many minutes
        
    Returns:
        (was_refreshed, credentials) tuple
        - was_refreshed: True if token was refreshed
        - credentials: Credentials object (refreshed or original)
    """
    return await refresh_token_with_retry(db, session, scopes=scopes, refresh_threshold_minutes=refresh_threshold_minutes)


def get_valid_credentials(
    db: Session,
    session: DBSession,
    scopes: Optional[List[str]] = None,
    auto_refresh: bool = True,
    refresh_threshold_minutes: int = 5
) -> Optional[Credentials]:
    """
    Get valid credentials, automatically refreshing if needed.
    Decrypts tokens from database before use.
    
    Args:
        db: Database session
        session: Database session object
        auto_refresh: Whether to automatically refresh expired tokens
        refresh_threshold_minutes: Refresh token if it expires within this many minutes
        
    Returns:
        Valid Credentials object or None if refresh failed
    """
    if not session.gmail_access_token:
        return None
    
    # Decrypt tokens from database
    try:
        access_token = decrypt_token(session.gmail_access_token)
        refresh_token = decrypt_token(session.gmail_refresh_token) if session.gmail_refresh_token else None
    except Exception as e:
        # Decryption failed - token may be encrypted with different key or corrupted
        # This is expected for stale sessions or after encryption key changes
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else "Unknown decryption error"
        logger.debug(
            f"Failed to decrypt tokens for session {session.id} (stale/corrupted token): "
            f"{error_type} - {error_msg}. Session will need re-authentication."
        )
        return None
    
    if not auto_refresh:
        # Just create credentials without refreshing
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            return None
        
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes or (session.granted_scopes.split(',') if hasattr(session, 'granted_scopes') and session.granted_scopes else LOGIN_SCOPES)
        )
        
        # CRITICAL: Set expiry from database to prevent unnecessary refresh attempts
        if session.token_expiry:
            credentials.expiry = session.token_expiry
            logger.debug(f"Set credentials expiry from database: {session.token_expiry}")
        
        return credentials

    # Auto-refresh if needed
    # IMPORTANT: In async contexts (running event loop), skip auto-refresh to avoid blocking
    # The caller should use get_valid_credentials_async() instead
    import asyncio
    
    try:
        # Check if we're in an async context
        asyncio.get_running_loop()
        # We're in an async context - return credentials without refresh
        # to avoid "asyncio.run() cannot be called from a running event loop" error
        logger.debug("Skipping auto-refresh in async context - use get_valid_credentials_async() for refresh")
        
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            return None
        
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes or (session.granted_scopes.split(',') if hasattr(session, 'granted_scopes') and session.granted_scopes else LOGIN_SCOPES)
        )
        
        # Set expiry from database
        if session.token_expiry:
            credentials.expiry = session.token_expiry
        
        return credentials
    except RuntimeError:
        # No running event loop - we can use asyncio.run safely
        was_refreshed, credentials = asyncio.run(
            refresh_token_with_retry(db, session, scopes=scopes, refresh_threshold_minutes=refresh_threshold_minutes)
        )
        return credentials


async def get_valid_credentials_async(
    db: Session,
    session: DBSession,
    scopes: Optional[List[str]] = None,
    auto_refresh: bool = True,
    refresh_threshold_minutes: int = 5
) -> Optional[Credentials]:
    """
    Async version of get_valid_credentials for use in async contexts.
    Properly handles token refresh in async environments.
    
    Args:
        db: Database session
        session: Database session object
        auto_refresh: Whether to automatically refresh expired tokens
        refresh_threshold_minutes: Refresh token if it expires within this many minutes
        
    Returns:
        Valid Credentials object or None if refresh failed
    """
    if not session.gmail_access_token:
        return None
    
    # Decrypt tokens from database
    try:
        access_token = decrypt_token(session.gmail_access_token)
        refresh_token = decrypt_token(session.gmail_refresh_token) if session.gmail_refresh_token else None
    except Exception as e:
        # Decryption failed - token may be encrypted with different key or corrupted
        # This is expected for stale sessions or after encryption key changes
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else "Unknown decryption error"
        logger.debug(
            f"Failed to decrypt tokens for session {session.id} (stale/corrupted token): "
            f"{error_type} - {error_msg}. Session will need re-authentication."
        )
        return None
    
    if not auto_refresh:
        # Just create credentials without refreshing
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            return None
        
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes or (session.granted_scopes.split(',') if hasattr(session, 'granted_scopes') and session.granted_scopes else LOGIN_SCOPES)
        )
        
        if session.token_expiry:
            credentials.expiry = session.token_expiry
        
        return credentials
    
    # Auto-refresh if needed (async version)
    was_refreshed, credentials = await refresh_token_if_needed(db, session, scopes=scopes, refresh_threshold_minutes=refresh_threshold_minutes)
    return credentials


async def refresh_user_tokens(db: Session, user_id: int) -> int:
    """
    Refresh all expired tokens for a user.
    
    Args:
        db: Database session
        user_id: User ID
        
    Returns:
        Number of tokens refreshed
    """
    sessions = db.query(DBSession).filter(
        DBSession.user_id == user_id,
        DBSession.gmail_refresh_token.isnot(None)
    ).all()
    
    refreshed_count = 0
    
    for session in sessions:
        was_refreshed, _ = await refresh_token_if_needed(db, session)
        if was_refreshed:
            refreshed_count += 1
    
    logger.info(f"Refreshed {refreshed_count}/{len(sessions)} tokens for user {user_id}")
    return refreshed_count

