"""
Authentication routes for Google OAuth
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional
import secrets
import hashlib

from src.database import get_db
from src.auth.oauth import get_authorization_url, exchange_code_for_tokens
from src.auth.audit import log_auth_event, AuditEventType
from src.utils import encrypt_token
from src.utils.logger import setup_logger
from src.database.models import Session as DBSession

logger = setup_logger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/google")
async def auth_google(request: Request, db: Session = Depends(get_db)):
    """
    Initiate Google OAuth flow
    
    Redirects user to Google's OAuth consent screen for Gmail, Calendar, and Tasks access
    """
    from src.database.models import OAuthState
    
    # Generate OAuth URL with state for CSRF protection
    authorization_url, state = get_authorization_url()
    
    # Store state in DATABASE (not in-memory!)
    # This persists across server restarts and works with multiple workers
    oauth_state = OAuthState(
        state=state,
        expires_at=datetime.utcnow() + timedelta(minutes=10)  # OAuth states expire after 10 minutes
    )
    db.add(oauth_state)
    db.commit()
    
    logger.info(f"Created OAuth state: {state[:10]}... (expires in 10 minutes)")
    
    # Redirect with state in URL
    return RedirectResponse(url=authorization_url)


@router.get("/google/callback")
async def auth_google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Handle Google OAuth callback
    
    Exchanges authorization code for access and refresh tokens,
    encrypts them, and stores in the database
    """
    # Handle OAuth errors
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    
    # Verify state to prevent CSRF attacks using DATABASE
    from src.database.models import OAuthState
    
    if state:
        oauth_state = db.query(OAuthState).filter(
            OAuthState.state == state,
            OAuthState.used == False,
            OAuthState.expires_at > datetime.utcnow()
        ).first()
        
        if oauth_state:
            # Mark state as used to prevent replay attacks
            oauth_state.used = True
            db.commit()
            logger.info(f"Valid OAuth state verified from database: {state[:10]}...")
        else:
            # State is invalid, expired, or already used
            logger.warning(f"Invalid OAuth state: {state[:10] if state else 'None'}...")
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired OAuth state. Please try authenticating again."
            )
    else:
        # No state provided
        logger.error("OAuth callback missing state parameter")
        raise HTTPException(
            status_code=400,
            detail="Missing state parameter. Possible security issue."
        )
    
    try:
        # Exchange authorization code for tokens
        credentials = exchange_code_for_tokens(code)
        
        # Get user info from Google to identify/create user
        from src.auth.oauth import GoogleOAuthHandler
        oauth_handler = GoogleOAuthHandler()
        user_info = oauth_handler.get_user_info(credentials.token)
        
        # Import User model
        from src.database.models import User
        
        # Look up or create user based on Google email
        user = db.query(User).filter(User.email == user_info['email']).first()
        
        is_new_user = False
        if not user:
            # Create new user
            user = User(
                email=user_info['email'],
                name=user_info.get('name'),
                picture_url=user_info.get('picture_url'),
                google_id=user_info.get('google_id')
            )
            db.add(user)
            db.flush()
            is_new_user = True
            logger.info(f"Created new user: {user.email} (id={user.id})")
        else:
            # Update existing user info
            user.name = user_info.get('name') or user.name
            user.picture_url = user_info.get('picture_url') or user.picture_url
            user.google_id = user_info.get('google_id') or user.google_id
            logger.info(f"Found existing user: {user.email} (id={user.id})")
        
        user_id = user.id
        logger.info(f"OAuth callback for user_id={user_id}, email={user.email}")
        
        # IMPORTANT: ALWAYS create a NEW session for OAuth callback
        # This ensures fresh credentials are stored in a clean session
        # Generate a session token (required by database schema)
        
        # Generate raw token for cookie
        session_token_raw = secrets.token_urlsafe(32)
        
        # Hash the token for database storage (same as SessionMiddleware does)
        session_token_hashed = hashlib.sha256(session_token_raw.encode()).hexdigest()
        
        # Store HASHED token in database
        db_session = DBSession(user_id=user_id, session_token=session_token_hashed)
        db.add(db_session)
        db.flush()
        logger.info(f"Created new session for OAuth: session_id={db_session.id}, user_id={user_id}")
        
        # Encrypt and store tokens in the new session
        db_session.gmail_access_token = encrypt_token(credentials.token)
        if credentials.refresh_token:
            db_session.gmail_refresh_token = encrypt_token(credentials.refresh_token)
        db_session.token_expiry = credentials.expiry.replace(tzinfo=None) if credentials.expiry else None
        
        db.commit()
        db.refresh(db_session)
        
        # Log successful authentication
        await log_auth_event(
            db=db,
            event_type=AuditEventType.LOGIN_SUCCESS,
            user_id=user_id,
            success=True,
            session_id=db_session.id,
            ip_address=request.client.host if request.client else None
        )
        
        # Start real-time email indexing for authenticated users
        try:
            from src.services.indexing.indexer import start_user_background_indexing
            from src.services.gmail_watch_helper import setup_gmail_watch_for_user
            from src.core.email.google_client import GoogleGmailClient
            from google.oauth2.credentials import Credentials
            from api.dependencies import AppState
            import os
            
            # Get config and RAG engine
            config = AppState.get_config()
            rag_engine = AppState.get_rag_engine()
            
            # Create Google client from credentials
            client_id = os.getenv('GOOGLE_CLIENT_ID')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
            
            if client_id and client_secret:
                google_credentials = Credentials(
                    token=credentials.token,
                    refresh_token=credentials.refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=credentials.scopes
                )
                
                google_client = GoogleGmailClient(config=config, credentials=google_credentials)
                
                # Start background indexing (runs continuously)
                try:
                    await start_user_background_indexing(
                        user_id=user_id,
                        config=config,
                        rag_engine=rag_engine,
                        google_client=google_client,
                        initial_batch_size=300 if is_new_user else 50  # Larger batch for new users
                    )
                    logger.info(f"✅ Started background email indexing for user {user_id}")
                    
                    # Update user indexing status
                    user = db.query(User).filter(User.id == user_id).first()
                    if user:
                        user.indexing_status = 'running'
                        user.indexing_started_at = datetime.utcnow()
                        db.commit()
                        
                except Exception as indexing_error:
                    logger.error(f"Failed to start background indexing for user {user_id}: {indexing_error}", exc_info=True)
                    # Fallback to Celery task
                    try:
                        from src.workers.tasks.indexing_tasks import index_user_emails
                        from src.workers.worker_manager import ensure_celery_worker_running
                        
                        if ensure_celery_worker_running(auto_start=True):
                            task = index_user_emails.delay(str(user_id))
                            logger.info(f"Fallback: Queued email indexing task for user {user_id}, task_id={task.id}")
                    except Exception:
                        pass
                
                # Set up Gmail watch for push notifications (real-time indexing)
                try:
                    watch_result = await setup_gmail_watch_for_user(
                        user_id=user_id,
                        google_client=google_client,
                        config=config,
                        label_ids=['INBOX']
                    )
                    
                    if watch_result.get('success'):
                        logger.info(f"✅ Gmail watch set up for user {user_id} - real-time indexing enabled")
                        logger.info(f"   Watch expires: {watch_result.get('expiration_datetime')}")
                    else:
                        logger.warning(f"⚠️ Gmail watch setup failed for user {user_id}: {watch_result.get('error')}")
                        logger.info(f"   Will use polling fallback for real-time indexing")
                        
                except Exception as watch_error:
                    logger.warning(f"Failed to set up Gmail watch for user {user_id}: {watch_error}")
                    logger.info("   Will use polling fallback for real-time indexing")
                    
            else:
                logger.warning("GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set - cannot start real-time indexing")
                
        except Exception as e:
            # Don't fail OAuth if indexing setup fails - just log the error
            logger.error(f"Failed to set up email indexing for user {user_id}: {e}", exc_info=True)
            # Try fallback to Celery task
            try:
                from src.workers.tasks.indexing_tasks import index_user_emails
                from src.workers.worker_manager import ensure_celery_worker_running
                
                if ensure_celery_worker_running(auto_start=True):
                    task = index_user_emails.delay(str(user_id))
                    logger.info(f"Fallback: Queued email indexing task for user {user_id}, task_id={task.id}")
            except Exception:
                pass
        
        # Return session token in URL for frontend to extract
        # This solves cross-origin cookie issues between localhost:3000 (frontend) and localhost:8000 (backend)
        redirect_url = f"http://localhost:3000/?auth=success&session_token={session_token_raw}"
        response = RedirectResponse(url=redirect_url)
        
        # Also set cookie for backwards compatibility (Swagger UI, direct backend access, etc.)
        response.set_cookie(
            key="session_token",
            value=session_token_raw,  # Send RAW token to browser (it will be hashed when sent back)
            httponly=True,
            max_age=30 * 24 * 60 * 60,  # 30 days
            samesite="lax"
        )
        return response
        
    except Exception as e:
        # Log authentication failure
        try:
            user_id_local = user_id if 'user_id' in locals() else None
            await log_auth_event(
                db=db,
                event_type=AuditEventType.LOGIN_FAILURE,
                user_id=user_id_local,
                success=False,
                error_message=str(e),
                ip_address=request.client.host if request.client else None
            )
        except:
            pass
        
        raise HTTPException(
            status_code=500,
            detail=f"Authentication failed: {str(e)}"
        )


@router.get("/status")
async def auth_status(request: Request, db: Session = Depends(get_db)):
    """
    Check current authentication status
    
    Returns information about the current user's authentication state
    """
    user_id = request.state.user_id if hasattr(request.state, 'user_id') else 2
    
    db_session = db.query(DBSession).filter(DBSession.user_id == user_id).first()
    
    if not db_session or not db_session.gmail_access_token:
        return {
            "authenticated": False,
            "user_id": user_id,
            "message": "Not authenticated. Please visit /auth/google to authenticate."
        }
    
    is_expired = False
    if db_session.token_expiry:
        is_expired = db_session.token_expiry < datetime.utcnow()
    
    return {
        "authenticated": True,
        "user_id": user_id,
        "session_id": db_session.id,
        "token_expired": is_expired,
        "token_expiry": db_session.token_expiry.isoformat() if db_session.token_expiry else None,
        "has_refresh_token": bool(db_session.gmail_refresh_token)
    }


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """
    Logout and clear tokens
    
    Removes stored OAuth tokens from the database
    """
    user_id = request.state.user_id if hasattr(request.state, 'user_id') else 2
    
    db_session = db.query(DBSession).filter(DBSession.user_id == user_id).first()
    
    if db_session:
        # Clear tokens
        db_session.gmail_access_token = None
        db_session.gmail_refresh_token = None
        db_session.token_expiry = None
        db.commit()
        
        # Log logout event
        await log_auth_event(
            db=db,
            event_type=AuditEventType.LOGOUT,
            user_id=user_id,
            success=True,
            session_id=db_session.id
        )
    
    return {"message": "Logged out successfully"}


@router.get("/get-session-for-swagger")
async def get_session_for_swagger(request: Request, db: Session = Depends(get_db)):
    """
    Get session token for Swagger UI testing
    
    After logging in via /auth/google, use this endpoint to get your session token.
    Then click "Authorize" in Swagger UI and paste the token as a Bearer token.
    
    This is a development convenience endpoint - not for production use!
    """
    # Try to get session token from cookie
    session_token = request.cookies.get('session_token')
    
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="No session found. Please login first via /auth/google"
        )
    
    # Verify the session exists and is valid
    hashed_token = hashlib.sha256(session_token.encode()).hexdigest()
    
    db_session = db.query(DBSession).filter(
        DBSession.session_token == hashed_token
    ).first()
    
    if not db_session:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session. Please login again via /auth/google"
        )
    
    # Get user info
    from src.database.models import User
    user = db.query(User).filter(User.id == db_session.user_id).first()
    
    return {
        "message": "Session token retrieved successfully",
        "instructions": [
            "1. Copy the 'session_token' value below",
            "2. Click the 'Authorize' button at the top of Swagger UI",
            "3. Paste the token in the 'Value' field (it will be added as 'Bearer <token>')",
            "4. Click 'Authorize' and then 'Close'",
            "5. You can now use authenticated endpoints!"
        ],
        "session_token": session_token,
        "user_info": {
            "id": user.id,
            "email": user.email,
            "name": user.name
        },
        "expires_at": db_session.expires_at.isoformat() if db_session.expires_at else None
    }
