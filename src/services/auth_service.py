"""
AuthService - Centralized authentication and session management logic.
"""
import os
import uuid
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dateutil import parser

from src.database.models import User, UserSettings, Session as DBSession
from src.auth import GoogleOAuthHandler, create_session, delete_user_sessions
from src.auth.audit import log_auth_event, AuditEventType
from src.utils import hash_token
from src.utils.logger import setup_logger
from src.utils.config import Config, get_frontend_url

logger = setup_logger(__name__)

class AuthService:
    def __init__(self, db: AsyncSession, config: Config):
        self.db = db
        self.config = config
        self.oauth_handler = GoogleOAuthHandler()

    async def get_google_auth_url(self, redirect_to: Optional[str] = None) -> Tuple[str, str]:
        """Generate Google OAuth authorization URL and state.
        
        Args:
            redirect_to: Optional path to redirect to after successful login (e.g., '/chat')
        """
        import base64
        state = None
        if redirect_to:
            # Encode redirect_to in state: random_state|base64_redirect
            # We use | as a separator because it's unlikely in base64
            import secrets
            random_state = secrets.token_urlsafe(16)
            b64_redirect = base64.urlsafe_b64encode(redirect_to.encode()).decode()
            state = f"{random_state}|{b64_redirect}"
            
        return self.oauth_handler.get_authorization_url(state=state)

    async def handle_google_callback(self, code: str, request: Any, state: Optional[str] = None) -> Tuple[User, Any, bool, str]:
        """
        Handle Google OAuth callback: exchange code, find/create user, create session.
        Returns (user, session, is_new_user, redirect_url)
        """
        logger.info(f"Processing Google OAuth callback with state: {state}")
        
        # Parse potential redirect_to from state
        redirect_to = None
        if state and "|" in state:
            try:
                import base64
                parts = state.split("|")
                if len(parts) >= 2:
                    b64_redirect = parts[1]
                    redirect_to = base64.urlsafe_b64decode(b64_redirect).decode()
                    logger.info(f"Detected redirect_to in OAuth state: {redirect_to}")
            except Exception as e:
                logger.warning(f"Failed to parse redirect_to from state: {e}")

        # Exchange code for tokens
        token_info = await self.oauth_handler.exchange_code_for_tokens_async(code)
        
        # Get user info from Google
        user_info = await self.oauth_handler.get_user_info_async(token_info['access_token'])
        
        # Find or create user
        stmt = select(User).where(User.email == user_info['email'])
        result = await self.db.execute(stmt)
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
                indexing_status='in_progress',
                indexing_started_at=datetime.utcnow()
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
            is_new_user = True
        else:
            logger.info(f"Existing user logged in: {user.email}")
            # Update user profile
            updated = False
            if user_info.get('name') and user.name != user_info.get('name'):
                user.name = user_info.get('name')
                updated = True
            if user_info.get('picture_url') and user.picture_url != user_info.get('picture_url'):
                user.picture_url = user_info.get('picture_url')
                updated = True
            
            if not user.indexing_status or user.indexing_status == 'not_started':
                user.indexing_status = 'in_progress'
                if not user.indexing_started_at:
                    user.indexing_started_at = datetime.utcnow()
                updated = True
            
            if updated:
                await self.db.commit()
                await self.db.refresh(user)
        
        # Calculate token expiry
        expiry_val = token_info.get('token_expiry')
        token_expiry = None
        if expiry_val:
            if isinstance(expiry_val, int):
                token_expiry = datetime.utcnow() + timedelta(seconds=expiry_val)
            else:
                try:
                    token_expiry = parser.parse(expiry_val)
                except Exception as e:
                    logger.debug(f"Failed to parse token_expiry '{expiry_val}': {e}")
                    token_expiry = None
        
        # Create session
        session = await create_session(
            db=self.db,
            user_id=user.id,
            gmail_access_token=token_info['access_token'],
            gmail_refresh_token=token_info.get('refresh_token'),
            token_expiry=token_expiry,
            granted_scopes=token_info.get('scopes'),  # Store granted OAuth scopes
            request=request
        )
        
        # Log success
        await log_auth_event(
            db=self.db,
            event_type=AuditEventType.OAUTH_CALLBACK_SUCCESS,
            user_id=user.id,
            success=True,
            request=request,
            oauth_provider='google',
            is_new_user=is_new_user
        )
        
        # Schedule indexing
        self.schedule_indexing(user.id, token_info)
        
        # Build redirect URL - redirect to /auth/callback for proper token handling
        # The frontend's /auth/callback page will:
        # 1. Extract token from URL
        # 2. Store in localStorage
        # 3. Verify with backend
        # 4. Redirect to /dashboard
        frontend_url = get_frontend_url(self.config)
        
        # If redirect_to starts with http, it's absolute, otherwise it's relative to frontend
        if redirect_to:
            if redirect_to.startswith("http"):
                target_url = redirect_to
            else:
                # Ensure leading slash
                path = redirect_to if redirect_to.startswith("/") else f"/{redirect_to}"
                target_url = f"{frontend_url}{path}"
        else:
            target_url = f"{frontend_url}/dashboard"

        import urllib.parse
        redirect_url = f"{frontend_url}/auth/callback?token={session.session_token}&target={urllib.parse.quote(target_url)}"
        if is_new_user:
            redirect_url += "&new_user=true"
            
        return user, session, is_new_user, redirect_url

    def schedule_indexing(self, user_id: int, token_info: dict, delay_seconds: int = 30):
        """Schedule background indexing task duration."""
        try:
            from src.workers.tasks.indexing_tasks import index_user_emails
            
            # Check for Gmail scopes
            scopes = token_info.get('scopes', [])
            if isinstance(scopes, str):
                scopes = scopes.split(' ')
            
            has_gmail = any('gmail.readonly' in s for s in scopes)
            if not has_gmail:
                logger.info(f"Skipping indexing for user {user_id}: No Gmail access")
                return

            # Trigger Celery task instead of non-durable asyncio task
            # Countdown gives system time to stabilize/session to persist
            index_user_emails.apply_async(
                args=[str(user_id)],
                kwargs={'is_incremental': False},
                countdown=delay_seconds,
                queue='indexing'
            )
            logger.info(f"[AuthService] Durable indexing task queued for user {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to queue indexing for user {user_id}: {e}")

    async def logout(self, user_id: int, request: Any) -> int:
        """Delete user sessions for logout."""
        return await delete_user_sessions(self.db, user_id, request=request)

    async def get_session_status(self, request: Any, timeout_minutes: int = 60) -> Dict[str, Any]:
        """Get session status information."""
        session = getattr(request.state, 'session', None)
        user = getattr(request.state, 'user', None)
        
        if not session or not user:
            return {"valid": False, "timeout_minutes": timeout_minutes}
        
        now = datetime.utcnow()
        last_active = session.last_active_at or session.created_at
        time_since_active = now - last_active
        seconds_remaining = (timeout_minutes * 60) - int(time_since_active.total_seconds())
        
        return {
            "valid": seconds_remaining > 0,
            "user_id": user.id,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            "last_active_at": last_active.isoformat(),
            "seconds_until_timeout": max(0, seconds_remaining),
            "timeout_minutes": timeout_minutes
        }

    async def validate_session_token(self, token: str) -> Optional[User]:
        """Validate a session token and return the associated user."""
        try:
            hashed = hash_token(token)
            stmt = select(DBSession).where(
                DBSession.session_token == hashed, 
                DBSession.expires_at > datetime.utcnow()
            )
            result = await self.db.execute(stmt)
            session = result.scalars().first()
            
            if not session:
                return None
                
            # Update last active
            session.last_active_at = datetime.utcnow()
            await self.db.commit()
            
            # Fetch user
            user_stmt = select(User).where(User.id == session.user_id)
            user_res = await self.db.execute(user_stmt)
            return user_res.scalars().first()
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            return None
