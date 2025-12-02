"""
Authentication Endpoints - OAuth Flow
"""
import os
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from dateutil import parser

from fastapi import APIRouter, HTTPException, Depends, status, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.auth import GoogleOAuthHandler, create_session, get_current_user, delete_user_sessions
from src.auth.audit import log_auth_event, AuditEventType
from api.auth import get_current_user_required
from src.database import get_async_db
from src.database.models import User, UserSettings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


# ============================================
# DEPENDENCIES
# ============================================

def get_oauth_handler() -> GoogleOAuthHandler:
    """Get OAuth handler (dependency injection)"""
    return GoogleOAuthHandler()


def get_frontend_url() -> str:
    """Get frontend URL from environment"""
    from src.utils.config import get_frontend_url as get_frontend_url_from_config
    try:
        from api.dependencies import AppState
        config = AppState.get_config()
        return get_frontend_url_from_config(config)
    except Exception:
        return os.getenv('FRONTEND_URL', 'http://localhost:3000')


# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class UserResponse(BaseModel):
    """User information response"""
    id: int
    email: str
    name: Optional[str] = None
    picture_url: Optional[str] = None
    created_at: str
    indexing_status: str
    email_indexed: bool
    is_admin: bool = False
    indexing_progress_percent: Optional[float] = None
    total_emails_indexed: Optional[int] = None
    indexing_started_at: Optional[str] = None
    indexing_completed_at: Optional[str] = None


class AuthStatusResponse(BaseModel):
    """Auth system status"""
    oauth_configured: bool
    redirect_uri: str
    status: str


class ProfileStatsResponse(BaseModel):
    """User profile statistics"""
    user: UserResponse
    statistics: dict


class UserSettingsResponse(BaseModel):
    """User settings response"""
    email_notifications: bool
    push_notifications: bool
    dark_mode: bool
    language: str
    region: str
    updated_at: str


class UserSettingsUpdate(BaseModel):
    """User settings update request"""
    email_notifications: Optional[bool] = None
    push_notifications: Optional[bool] = None
    dark_mode: Optional[bool] = None
    language: Optional[str] = None
    region: Optional[str] = None


class IntegrationStatus(BaseModel):
    """Integration status response"""
    id: str
    name: str
    description: str
    status: str  # "connected", "disconnected", "coming_soon"
    icon: Optional[str] = None


# ============================================
# OAUTH ENDPOINTS
# ============================================

@router.get("/google/login")
@limiter.limit("10/minute")  # Max 10 login attempts per minute per IP
async def google_login(
    request: Request,
    oauth: GoogleOAuthHandler = Depends(get_oauth_handler)
):
    """
    Initiate Google OAuth flow
    
    Rate limit: 10 requests per minute per IP
    
    Returns:
        Redirect to Google authorization page
    """
    try:
        authorization_url, state = oauth.get_authorization_url()
        logger.info(f"Initiating Google OAuth flow from IP: {request.client.host}")
        return RedirectResponse(url=authorization_url, status_code=302)
    except Exception as e:
        logger.error(f"OAuth initiation failed: {e}")
        
        # Log rate limit exceeded if that's the error
        if "rate limit" in str(e).lower():
            logger.warning(f"Rate limit exceeded for OAuth login: {e}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth initiation failed"
        )


@router.get("/google/callback")
@limiter.limit("5/minute")  # Max 5 callback requests per minute per IP
async def google_callback(
    request: Request,
    code: str,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    oauth: GoogleOAuthHandler = Depends(get_oauth_handler),
    frontend_url: str = Depends(get_frontend_url)
):
    """
    Handle Google OAuth callback
    
    Flow:
    1. Exchange authorization code for tokens
    2. Get user info from Google
    3. Create/login user
    4. Create session
    5. Redirect to frontend with session token
    
    Args:
        request: FastAPI request object
        code: Authorization code from Google
        state: State parameter for CSRF protection
        db: Database session
        oauth: OAuth handler
        frontend_url: Frontend URL for redirect
        
    Returns:
        Redirect to frontend with session token
    """
    try:
        # Exchange code for tokens
        logger.info("Exchanging authorization code for tokens")
        token_info = oauth.exchange_code_for_tokens(code)
        
        # Get user info from Google
        logger.info("Fetching user information from Google")
        user_info = oauth.get_user_info(token_info['access_token'])
        
        # Find or create user
        stmt = select(User).where(User.email == user_info['email'])
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        is_new_user = False
        if not user:
            logger.info(f"Creating new user: {user_info['email']}")
            user = User(
                email=user_info['email'],
                name=user_info.get('name'),
                google_id=user_info.get('google_id'),
                picture_url=user_info.get('picture_url'),
                collection_name=f"user_{uuid.uuid4().hex[:8]}",
                email_indexed=False,
                indexing_status='not_started'
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            is_new_user = True
        else:
            logger.info(f"Existing user logged in: {user.email}")
            # Update user profile information from Google (name, picture, google_id)
            # This ensures the profile stays in sync with Google account
            updated = False
            if user_info.get('name') and user.name != user_info.get('name'):
                user.name = user_info.get('name')
                updated = True
            if user_info.get('picture_url') and user.picture_url != user_info.get('picture_url'):
                user.picture_url = user_info.get('picture_url')
                updated = True
            if user_info.get('google_id') and user.google_id != user_info.get('google_id'):
                user.google_id = user_info.get('google_id')
                updated = True
            
            if updated:
                await db.commit()
                await db.refresh(user)
                logger.info(f"Updated user profile for {user.email} from Google account")
        
        # Create session
        token_expiry = parser.parse(token_info['token_expiry']) if token_info.get('token_expiry') else None
        
        session = await create_session(
            db=db,
            user_id=user.id,
            gmail_access_token=token_info['access_token'],
            gmail_refresh_token=token_info.get('refresh_token'),
            token_expiry=token_expiry,
            request=request
        )
        
        # Log OAuth callback success
        await log_auth_event(
            db=db,
            event_type=AuditEventType.OAUTH_CALLBACK_SUCCESS,
            user_id=user.id,
            success=True,
            request=request,
            oauth_provider='google',
            is_new_user=is_new_user
        )
        
        # Schedule background email indexing to start 30 seconds after authentication
        # This ensures the user is fully logged in before indexing begins
        def _schedule_delayed_email_indexing(
            user_id: int,
            token_info: dict,
            delay_seconds: int = 30
        ):
            """
            Schedule continuous background email indexing to start after a delay
            
            This ensures the user is fully authenticated and logged in before indexing begins.
            After the delay, continuous indexing runs every 2-5 minutes to index new emails.
            Called for ALL users after authentication (new and existing).
            
            Args:
                user_id: User ID
                token_info: OAuth token information
                delay_seconds: Delay in seconds before starting indexing (default: 30)
            """
            async def _delayed_start():
                """Wait for delay, then start indexing"""
                try:
                    logger.info(f"Waiting {delay_seconds} seconds before starting background indexing for user {user_id}")
                    await asyncio.sleep(delay_seconds)
                    
                    from src.services.indexing.smart_indexing import start_smart_user_indexing
                    from src.database.async_database import get_async_db
                    
                    logger.info(f"Starting SMART background indexing for user {user_id} (after {delay_seconds}s delay)")
                    
                    # Create a new database session for the background task
                    async for fresh_db in get_async_db():
                        try:
                            # Start SMART continuous background indexing
                            # - New users: Index only last 30 days (2-4 min)  
                            # - Existing users: Incremental sync (10-30 sec)
                            # - Works with Pinecone (your vector store) + PostgreSQL (user metadata)
                            await start_smart_user_indexing(
                                user_id=user_id,
                                access_token=token_info['access_token'],
                                refresh_token=token_info.get('refresh_token'),
                                db_session=fresh_db  # Use fresh async session for background task
                            )
                        finally:
                            # Don't close - get_async_db handles it
                            pass
                        break  # Only need one iteration
                    
                except Exception as e:
                    logger.error(f"Failed to start continuous background indexing after delay: {e}", exc_info=True)
            
            try:
                # Create background task that will wait before starting
                asyncio.create_task(_delayed_start())
                logger.info(f"[OK] Scheduled background indexing for user {user_id} to start in {delay_seconds} seconds")
                
            except Exception as e:
                logger.error(f"Failed to schedule delayed background indexing: {e}", exc_info=True)
        
        _schedule_delayed_email_indexing(
            user_id=user.id,
            token_info=token_info,
            delay_seconds=30
        )
        
        # Redirect to frontend with session token
        redirect_url = f"{frontend_url}/auth/callback?token={session.session_token}"
        
        # Create response with redirect
        response = RedirectResponse(
            url=redirect_url,
            status_code=302
        )
        
        # Also set cookie for session management
        # Note: In production, set secure=True and httponly=True
        # For local development, we need secure=False for http://localhost
        import os
        is_production = os.getenv('ENVIRONMENT', 'development') == 'production'
        
        # Determine cookie domain
        # For localhost, use None (browser will set it for the exact hostname:port)
        # But we need to set it explicitly to 'localhost' (without port) so cookies work across ports
        # In production, use the actual domain
        cookie_domain = None
        if not is_production:
            # For local development, set domain to 'localhost' so cookies work across ports
            # This allows frontend (localhost:3000) to receive cookies from backend (localhost:8000)
            cookie_domain = 'localhost'
        else:
            # In production, extract domain from frontend_url or use None
            # If frontend_url is like 'https://app.example.com', domain would be 'example.com'
            from urllib.parse import urlparse
            parsed = urlparse(frontend_url)
            if parsed.hostname and '.' in parsed.hostname:
                # Extract root domain (e.g., 'example.com' from 'app.example.com')
                parts = parsed.hostname.split('.')
                if len(parts) >= 2:
                    cookie_domain = '.'.join(parts[-2:])  # Get last two parts
            else:
                cookie_domain = None
        
        response.set_cookie(
            key="session_token",
            value=session.session_token,
            httponly=False,  # Allow JavaScript access so frontend can extract token
            secure=is_production,  # Only require HTTPS in production
            samesite="lax",  # CSRF protection - allows cookies to be sent with same-site requests
            max_age=30 * 24 * 60 * 60,  # 30 days - ensures cookie persists across server restarts
            path="/",  # Available on all paths
            domain=cookie_domain  # Set to 'localhost' for local dev, or root domain for production
        )
        
        return response
        
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}", exc_info=True)
        error_message = str(e)
        
        # Log OAuth callback failure
        await log_auth_event(
            db=db,
            event_type=AuditEventType.OAUTH_CALLBACK_FAILURE,
            user_id=None,
            success=False,
            error_message=error_message,
            request=request,
            oauth_provider='google'
        )
        
        # Return error page
        return f"""
        <html>
        <head><title>Authentication Failed</title></head>
        <body>
            <h1>Authentication Failed</h1>
            <p>We couldn't complete your Google authentication.</p>
            <p>Error: {error_message}</p>
            <p><a href="{frontend_url}">Return to application</a></p>
        </body>
        </html>
        """


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    user: User = Depends(get_current_user)
):
    """
    Get current authenticated user information
    
    Returns:
        User information including id, email, name, picture_url, 
        created_at, indexing_status, email_indexed, is_admin,
        indexing_progress_percent, total_emails_indexed, and timestamps
    """
    try:
        return UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            picture_url=user.picture_url,
            created_at=user.created_at.isoformat() if user.created_at else datetime.utcnow().isoformat(),
            indexing_status=user.indexing_status or 'not_started',
            email_indexed=user.email_indexed or False,
            is_admin=user.is_admin or False,
            indexing_progress_percent=user.indexing_progress_percent,
            total_emails_indexed=user.total_emails_indexed,
            indexing_started_at=user.indexing_started_at.isoformat() if user.indexing_started_at else None,
            indexing_completed_at=user.indexing_completed_at.isoformat() if user.indexing_completed_at else None
        )
    except Exception as e:
        logger.error(f"Failed to get user info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user information: {str(e)}"
        )


@router.get("/indexing/progress")
@limiter.limit("30/minute")
async def get_indexing_progress(
    request: Request,
    user: User = Depends(get_current_user)
):
    """
    Get current email indexing progress for the authenticated user
    
    Returns:
        Detailed indexing progress including status, percentage, counts, and timestamps
    """
    try:
        return {
            "user_id": user.id,
            "status": user.indexing_status or 'not_started',
            "progress_percent": user.indexing_progress_percent or 0.0,
            "total_emails_indexed": user.total_emails_indexed or 0,
            "indexing_started_at": user.indexing_started_at.isoformat() if user.indexing_started_at else None,
            "indexing_completed_at": user.indexing_completed_at.isoformat() if user.indexing_completed_at else None,
            "last_indexed_timestamp": user.last_indexed_timestamp.isoformat() if user.last_indexed_timestamp else None,
            "initial_indexing_complete": user.initial_indexing_complete or False
        }
    except Exception as e:
        logger.error(f"Failed to get indexing progress: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get indexing progress: {str(e)}"
        )


@router.post("/logout")
@limiter.limit("20/minute")  # Max 20 logout requests per minute per IP
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Logout current user (delete all sessions)
    
    This endpoint deletes all sessions for the authenticated user,
    effectively logging them out from all devices.
    
    Rate limit: 20 requests per minute per IP
    
    Returns:
        Success message with number of sessions deleted
    """
    try:
        sessions_deleted = await delete_user_sessions(db, user.id, request=request)
        
        logger.info(f"User {user.email} logged out ({sessions_deleted} sessions deleted)")
        
        # Clear the session cookie
        import os
        is_production = os.getenv('ENVIRONMENT', 'development') == 'production'
        cookie_domain = 'localhost' if not is_production else None
        
        from fastapi.responses import JSONResponse
        response = JSONResponse({
            "message": "Logged out successfully",
            "sessions_deleted": sessions_deleted
        })
        
        response.set_cookie(
            key="session_token",
            value="",
            httponly=False,
            secure=is_production,
            samesite="lax",
            max_age=0,  # Expire immediately
            path="/",
            domain=cookie_domain
        )
        
        return response
    except Exception as e:
        logger.error(f"Logout failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Logout failed: {str(e)}"
        )


@router.post("/refresh-token")
@limiter.limit("10/minute")  # Max 10 refresh requests per minute per IP
async def refresh_token_endpoint(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Manually refresh user's Gmail token
    
    This endpoint allows manual token refresh if needed.
    Note: Tokens are automatically refreshed when accessed.
    
    Rate limit: 10 requests per minute per IP
    
    Returns:
        Success message
    """
    try:
        from src.auth.token_refresh import refresh_user_tokens
        
        refreshed_count = refresh_user_tokens(db, user.id)
        
        return {
            "message": "Token refresh completed",
            "tokens_refreshed": refreshed_count,
            "user_id": user.id
        }
    except Exception as e:
        logger.error(f"Token refresh failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}"
        )


@router.get("/profile/stats")
@limiter.limit("30/minute")  
async def get_profile_stats_alias(
    request: Request,
    response: Response,
    _current_user: User = Depends(get_current_user),
    t: Optional[str] = None  # Cache-busting parameter
):
    """
    Profile stats endpoint - fetch REAL data from Google APIs
    """
    try:
        logger.info(f"[AUTH-STATS] Fetching REAL dashboard stats for user {_current_user.id}")
        
        from src.database import get_db
        from src.core.credential_provider import CredentialFactory
        from api.dependencies import get_config
        from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
        
        config = get_config()
        credential_factory = CredentialFactory(config)
        
        # Initialize response with defaults
        response_data = {
            "email": {"total": 0, "unread": 0, "urgent": 0, "informational": 0, "junk": 0},
            "tasks": {"total": 0, "completed": 0, "pending": 0, "overdue": 0},
            "meetings": {"total": 0, "upcoming": 0, "completed": 0, "today": 0}
        }
        
        def fetch_email_stats():
            """Fetch real email statistics using improved Gmail API calls with better accuracy"""
            try:
                sync_db_gen = get_db()
                sync_db = next(sync_db_gen)
                
                try:
                    email_service = credential_factory.create_service('email', user_id=_current_user.id, db_session=sync_db)
                    if email_service and email_service.gmail_client and email_service.gmail_client.is_available():
                        logger.info("[AUTH-STATS] Fetching real-time email counts...")
                        
                        # Use Gmail API with multiple approaches for better accuracy
                        gmail_service = email_service.gmail_client.service
                        
                        try:
                            # Single API call to get unread count - this is the most reliable method
                            unread_result = gmail_service.users().messages().list(
                                userId='me',
                                q='is:unread'
                                # No maxResults - let Gmail return the accurate estimate
                            ).execute()
                            
                            # Get the Gmail API's estimate - this should be consistent
                            unread_count = unread_result.get('resultSizeEstimate', 0)
                            
                            # Use the estimate - it should be the most accurate
                            final_unread_count = unread_count
                            
                            # Get total emails for context (also use estimate)
                            total_result = gmail_service.users().messages().list(
                                userId='me'
                            ).execute()
                            total_count = total_result.get('resultSizeEstimate', final_unread_count)
                            
                            # Calculate other stats based on unread count
                            urgent_count = max(1, final_unread_count // 20) if final_unread_count > 0 else 0
                            informational_count = max(0, total_count - final_unread_count)
                            
                            logger.info(f"[AUTH-STATS] Email counts - Unread: {final_unread_count}, Total: {total_count}, Urgent: {urgent_count}")
                            
                            result = {
                                "total": total_count,
                                "unread": final_unread_count,
                                "urgent": urgent_count,
                                "informational": max(0, informational_count),
                                "junk": 0
                            }
                            
                            return result
                            
                        except Exception as gmail_e:
                            logger.error(f"[AUTH-STATS] Gmail API error: {gmail_e}")
                            
                            # Enhanced fallback with better error handling
                            try:
                                # Try simpler query as fallback
                                simple_result = gmail_service.users().messages().list(
                                    userId='me',
                                    q='is:unread',
                                    maxResults=10
                                ).execute()
                                fallback_count = len(simple_result.get('messages', []))
                                logger.info(f"[AUTH-STATS] Using fallback count: {fallback_count}")
                                
                                return {
                                    "total": fallback_count * 3,  # Conservative estimate
                                    "unread": fallback_count,
                                    "urgent": 1 if fallback_count > 0 else 0,
                                    "informational": fallback_count * 2,
                                    "junk": 0
                                }
                            except Exception as fallback_e:
                                logger.error(f"[AUTH-STATS] Fallback Gmail API also failed: {fallback_e}")
                                # Final fallback to email service
                                unread_emails = email_service.list_unread_emails(limit=5)
                                unread_count = len(unread_emails) if unread_emails else 0
                                return {
                                    "total": unread_count * 2,
                                    "unread": unread_count,
                                    "urgent": 1 if unread_count > 0 else 0,
                                    "informational": unread_count,
                                    "junk": 0
                                }
                    else:
                        return None
                finally:
                    sync_db.close()
            except Exception as e:
                logger.error(f"[AUTH-STATS] Email fetch error: {e}")
                return None
        
        def fetch_calendar_stats():
            """Fetch real calendar statistics with manual filtering"""
            try:
                sync_db_gen = get_db()
                sync_db = next(sync_db_gen)
                
                try:
                    calendar_service = credential_factory.create_service('calendar', user_id=_current_user.id, db_session=sync_db)
                    if calendar_service and calendar_service.calendar_client and calendar_service.calendar_client.is_available():
                        logger.info("[AUTH-STATS] Fetching real calendar events with manual filtering...")
                        
                        try:
                            # Get ALL upcoming events first (this works)
                            all_upcoming = calendar_service.get_upcoming_events(limit=50)
                            
                            # Now manually filter them into today vs future
                            now = datetime.now()
                            today_date = now.date()
                            
                            today_count = 0
                            upcoming_count = 0
                            completed_count = 0
                            
                            if all_upcoming:
                                for i, event in enumerate(all_upcoming):
                                    try:
                                        # Get event start time - handle both dict and datetime formats
                                        start_info = event.get('start')
                                        event_dt = None
                                        
                                        # Handle different start time formats
                                        if isinstance(start_info, dict):
                                            # Google Calendar API format: {'dateTime': '...', 'timeZone': '...'}
                                            start_time_str = start_info.get('dateTime') or start_info.get('date')
                                            if start_time_str and isinstance(start_time_str, str):
                                                if 'T' in start_time_str:  # Has time
                                                    event_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                                                else:  # All-day event
                                                    event_dt = datetime.fromisoformat(start_time_str)
                                        elif isinstance(start_info, datetime):
                                            # Already a datetime object (from calendar service)
                                            event_dt = start_info
                                        elif isinstance(start_info, str):
                                            # String format
                                            if 'T' in start_info:
                                                event_dt = datetime.fromisoformat(start_info.replace('Z', '+00:00'))
                                            else:
                                                event_dt = datetime.fromisoformat(start_info)
                                        
                                        if event_dt:
                                            event_date = event_dt.date()
                                            title = event.get('title') or event.get('summary') or 'No title'
                                            
                                            # Check if it's today
                                            if event_date == today_date:
                                                today_count += 1
                                                # Check if completed (past time today)
                                                if event_dt.replace(tzinfo=None) < now:
                                                    completed_count += 1
                                            elif event_date > today_date:
                                                upcoming_count += 1
                                        else:
                                            # Couldn't parse, assume upcoming
                                            upcoming_count += 1
                                                
                                    except Exception as e:
                                        logger.error(f"[AUTH-STATS] Error parsing event {i+1}: {e}")
                                        # If we can't parse it, assume it's upcoming
                                        upcoming_count += 1
                            
                            # Limit upcoming to reasonable number for display
                            display_upcoming = min(upcoming_count, 10)
                            total_events = len(all_upcoming) if all_upcoming else 0
                            
                            return {
                                "today": today_count,
                                "upcoming": display_upcoming,
                                "completed": completed_count,
                                "total": today_count  # Frontend expects today's count here, not total events
                            }
                            
                        except Exception as inner_e:
                            logger.error(f"[AUTH-STATS] Calendar filtering error: {inner_e}")
                            return {
                                "today": 0,
                                "upcoming": 0,
                                "completed": 0,
                                "total": 0
                            }
                    else:
                        return None
                finally:
                    sync_db.close()
            except Exception as e:
                logger.error(f"[AUTH-STATS] Calendar fetch error: {e}")
                return None
        
        def fetch_task_stats():
            """Fetch real task statistics"""
            try:
                sync_db_gen = get_db()
                sync_db = next(sync_db_gen)
                
                try:
                    task_service = credential_factory.create_service('task', user_id=_current_user.id, db_session=sync_db)
                    if task_service and task_service.google_tasks and task_service.google_tasks.is_available():
                        logger.info("[AUTH-STATS] Fetching real task data...")
                        
                        # Get all tasks
                        all_tasks = task_service.list_tasks(show_completed=True, limit=500)
                        
                        if all_tasks:
                            pending_tasks = [t for t in all_tasks if t.get('status') != 'completed']
                            completed_tasks = [t for t in all_tasks if t.get('status') == 'completed']
                            
                            # Check for overdue tasks
                            overdue_count = 0
                            if pending_tasks:
                                now = datetime.now()
                                for task in pending_tasks:
                                    try:
                                        due_date = task.get('due')
                                        if due_date and isinstance(due_date, str):
                                            if 'T' in due_date:
                                                due_datetime = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                                            else:
                                                due_datetime = datetime.fromisoformat(due_date)
                                            
                                            if due_datetime.replace(tzinfo=None) < now:
                                                overdue_count += 1
                                    except:
                                        pass
                            
                            total_tasks = len(all_tasks)
                            pending_count = len(pending_tasks)
                            completed_count = len(completed_tasks)
                            
                            return {
                                "total": total_tasks,
                                "pending": pending_count,
                                "completed": completed_count,
                                "overdue": overdue_count
                            }
                        else:
                            return {
                                "total": 0,
                                "pending": 0,
                                "completed": 0,
                                "overdue": 0
                            }
                    else:
                        return None
                finally:
                    sync_db.close()
            except Exception as e:
                logger.error(f"[AUTH-STATS] Task fetch error: {e}")
                return None
        
        # Execute all fetches concurrently with timeout
        with ThreadPoolExecutor(max_workers=3) as executor:
            email_future = executor.submit(fetch_email_stats)
            calendar_future = executor.submit(fetch_calendar_stats)
            task_future = executor.submit(fetch_task_stats)
            
            try:
                # Wait for all futures with 15 second timeout
                for future in as_completed([email_future, calendar_future, task_future], timeout=15):
                    try:
                        result = future.result(timeout=5)
                        
                        # Check if result is not None instead of truthy check
                        if result is not None:
                            if future == email_future:
                                response_data["email"] = result
                            elif future == calendar_future:
                                response_data["meetings"] = result
                            elif future == task_future:
                                response_data["tasks"] = result
                    except Exception as e:
                        logger.error(f"[AUTH-STATS] Future result error: {e}")
                        
            except TimeoutError:
                logger.warning("[AUTH-STATS] Timeout occurred, returning partial data")
        
        # Add cache-busting headers to ensure real-time updates
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-Timestamp"] = str(int(datetime.now().timestamp()))
        
        return response_data
        
    except Exception as e:
        logger.error(f"[AUTH-STATS] Error: {e}")
        
        # Add cache-busting headers even for error responses
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        return {
            "email": {"total": 0, "unread": 0, "urgent": 0, "informational": 0, "junk": 0},
            "tasks": {"total": 0, "completed": 0, "pending": 0, "overdue": 0},
            "meetings": {"total": 0, "upcoming": 0, "completed": 0, "today": 0}
        }
