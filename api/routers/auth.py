"""
Auth Router - User authentication and session management.
"""
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from api.dependencies import get_db, get_auth_service, get_config
from src.utils.config import Config, get_frontend_url
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/google")
async def login_google(
    request: Request,
    auth_service = Depends(get_auth_service),
    config = Depends(get_config)
):
    """Initiate Google OAuth flow.
    
    If user is already authenticated, redirect to dashboard instead.
    """
    # Check if user is already authenticated
    user = getattr(request.state, 'user', None)
    session = getattr(request.state, 'session', None)
    
    if user and session:
        # Already logged in - redirect through /auth/callback so frontend can
        # store the session token in localStorage (required for API auth).
        # Previously this redirected directly to /dashboard, but the frontend
        # needs the token in localStorage and only /auth/callback stores it.
        import urllib.parse
        frontend_url = get_frontend_url(config)
        target_url = f"{frontend_url}/dashboard"
        raw_token = getattr(request.state, 'session_id', None)  # raw token from middleware
        if raw_token:
            redirect_url = f"{frontend_url}/auth/callback?token={raw_token}&target={urllib.parse.quote(target_url)}"
            logger.info(f"User {user.id} already authenticated, redirecting through /auth/callback")
            return RedirectResponse(url=redirect_url)
        else:
            # Fallback: no raw token available, redirect to dashboard directly
            logger.warning(f"User {user.id} authenticated but no raw token available, redirecting to dashboard")
            return RedirectResponse(url=f"{frontend_url}/dashboard")
    
    # Not authenticated - start OAuth flow
    authorization_url, state = await auth_service.get_google_auth_url()
    return RedirectResponse(url=authorization_url)

@router.get("/google/callback")
async def auth_google_callback(
    request: Request,
    code: str = Query(...),
    state: Optional[str] = Query(None),
    auth_service = Depends(get_auth_service),
    config = Depends(get_config)
):
    """Handle Google OAuth callback.
    
    This callback handles both:
    1. Login flows (state is random or missing)
    2. Integration flows (state is secure `int_...` or legacy `user_{id}_{provider}`)
    """
    try:
        # Check if this is an integration callback
        if state and (state.startswith("user_") or state.startswith("int_")):
            # Get a fresh db session
            from src.database import get_async_db_context
            async with get_async_db_context() as db:
                from api.dependencies import get_integration_service
                integration_service = get_integration_service(db)
                provider = integration_service.get_provider_hint_from_state(state)
                callback_result = await integration_service.handle_callback(provider, code, state)
                real_provider = callback_result.provider
                token_data = callback_result.token_data
                redirect_to = callback_result.redirect_to
                
                # Update active session with new scopes if available
                # This ensures the user doesn't have to log out/in to use the new integration
                current_session = getattr(request.state, 'session', None)
                if current_session and token_data.get('scope'):
                    from sqlalchemy import select
                    from src.database.models import Session as DBSession
                    
                    # Fetch the current session from the database
                    stmt = select(DBSession).where(DBSession.id == current_session.id)
                    result = await db.execute(stmt)
                    db_session = result.scalar_one_or_none()
                    
                    if db_session:
                        # Merge new scopes with existing ones
                        new_scopes = token_data.get('scope').split(' ')
                        existing_scopes = db_session.granted_scopes.split(',') if db_session.granted_scopes else []
                        
                        # Filter out empty strings and merge
                        merged_scopes = list(set(filter(None, existing_scopes + new_scopes)))
                        db_session.granted_scopes = ",".join(merged_scopes)
                        
                        await db.commit()
                        logger.info(f"Updated session {db_session.id} with new integration scopes for {real_provider}")
                
                f_url = get_frontend_url(config)
                
                if redirect_to:
                    # Ensure absolute URL for frontend
                    if not redirect_to.startswith("http"):
                        path = redirect_to if redirect_to.startswith("/") else f"/{redirect_to}"
                        final_redirect = f"{f_url}{path}"
                    else:
                        final_redirect = redirect_to
                        
                    # Add success params if not already there
                    if "?" in final_redirect:
                        final_redirect += f"&status=success&provider={real_provider}"
                    else:
                        final_redirect += f"?status=success&provider={real_provider}"
                else:
                    final_redirect = f"{f_url}/settings/integrations?status=success&provider={real_provider}"
                    
                return RedirectResponse(url=final_redirect)
        
        # Normal login flow
        user, session, is_new_user, redirect_url = await auth_service.handle_google_callback(code, request, state=state)
        response = RedirectResponse(url=redirect_url)
        
        # Set session cookie
        # Use SameSite=None to allow cross-port AJAX requests (localhost:3000 -> localhost:8000)
        # Note: In production, Secure should be True and served over HTTPS
        response.set_cookie(
            key="session_token",
            value=session.session_token,
            max_age=60 * 60 * 24 * 7,  # 7 days
            httponly=False,  # Allow frontend to read cookie for auth state
            samesite="lax",    # More reliable for Safari/local redirects
            secure=False,      # Development mode - set to True in production with HTTPS
            path="/"           # Explicitly set path to root
        )
        return response
    except Exception as e:
        logger.error(f"Auth callback failed: {e}", exc_info=True)
        # Fallback to frontend with error (config is already available from dependency)
        f_url = get_frontend_url(config)
        return RedirectResponse(url=f"{f_url}/login?error=auth_failed")

@router.post("/logout")
async def logout(
    request: Request,
    auth_service = Depends(get_auth_service)
):
    """Log out user."""
    user = getattr(request.state, 'user', None)
    if not user:
        return {"success": True}
        
    await auth_service.logout(user.id, request)
    return {"success": True}

@router.get("/status")
async def get_auth_status(
    request: Request,
    auth_service = Depends(get_auth_service),
    config: Config = Depends(get_config)
):
    """Get current authentication status."""
    ttl = getattr(getattr(config, 'security', None), 'session_ttl_minutes', 60)
    status = await auth_service.get_session_status(request, timeout_minutes=ttl)
    return status

@router.get("/me")
async def get_current_user_info(request: Request):
    """Get currently logged in user info."""
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture_url": user.picture_url,
        "indexing_status": user.indexing_status
    }

# Alias routes for frontend compatibility
@router.get("/session/status")
async def get_session_status_alias(
    request: Request,
    auth_service = Depends(get_auth_service),
    config: Config = Depends(get_config)
):
    """Alias for /auth/status - Get current session status."""
    ttl = getattr(getattr(config, 'security', None), 'session_ttl_minutes', 60)
    status = await auth_service.get_session_status(request, timeout_minutes=ttl)
    return status

@router.get("/integrations")
async def get_integrations_alias(
    request: Request,
    config = Depends(get_config)
):
    """Alias for /integrations/status - Get user integrations."""
    from api.dependencies import get_current_user, get_integration_service
    from src.database import get_async_db_context
    
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with get_async_db_context() as db:
        from src.services.integration_service import IntegrationService
        integration_service = IntegrationService(db=db, config=config)
        integrations = await integration_service.get_user_integrations(user.id)
        return {"integrations": integrations}

@router.get("/profile/stats")
async def get_profile_stats(
    request: Request,
):
    """Get user profile statistics (emails, tasks, meetings).
    
    Uses user metadata for fast response - no additional DB queries needed.
    Returns 0 if integrations are not connected.
    """
    user = getattr(request.state, 'user', None)
    session = getattr(request.state, 'session', None)
    
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Parse granted scopes from session to check which integrations are connected
    granted_scopes_str = getattr(session, 'granted_scopes', None) if session else None
    granted_scopes = set(granted_scopes_str.split(',')) if granted_scopes_str else set()
    
    # Check which integrations are connected based on scopes
    GMAIL_SCOPES = {'https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.modify'}
    CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar'
    TASKS_SCOPE = 'https://www.googleapis.com/auth/tasks'
    
    gmail_connected = bool(granted_scopes.intersection(GMAIL_SCOPES))
    calendar_connected = CALENDAR_SCOPE in granted_scopes
    tasks_connected = TASKS_SCOPE in granted_scopes
    
    # Return stats directly from user object - no extra DB queries
    return {
        "emails": user.total_emails_indexed or 0 if gmail_connected else 0,
        "tasks": 0,  # Tasks are stored in Google Tasks, not locally
        "meetings": 0,  # Calendar events are fetched from Google, not stored locally
        "integrations": {
            "gmail_connected": gmail_connected,
            "calendar_connected": calendar_connected,
            "tasks_connected": tasks_connected
        }
    }

