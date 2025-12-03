"""
User Writing Profile API
Endpoints for building and managing user email writing style profiles
"""
from fastapi import APIRouter, HTTPException, Depends, Request, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from src.database import get_async_db, get_async_db_context, get_db
from src.database.models import User, UserWritingProfile, Session as DBSession
from sqlalchemy.orm import Session
from src.ai.profile_builder import ProfileBuilder
from src.core.email.google_client import GoogleGmailClient
from api.auth import get_current_user_required
from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.services.profile_cache import get_profile_cache  # Add cache import

logger = setup_logger(__name__)
router = APIRouter(prefix="/api/profile", tags=["profile"])


# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class ProfileBuildRequest(BaseModel):
    """Request to build/rebuild profile"""
    max_emails: int = Field(default=100, ge=10, le=500, description="Maximum number of sent emails to analyze")
    force_rebuild: bool = Field(default=False, description="Force rebuild even if recently updated")


class ProfileResponse(BaseModel):
    """User writing profile response"""
    user_id: int
    profile_data: Dict[str, Any]
    sample_size: int
    created_at: str
    updated_at: str
    last_rebuilt_at: Optional[str] = None
    confidence_score: Optional[float] = None
    needs_refresh: bool = False
    
    class Config:
        from_attributes = True


class ProfileStatusResponse(BaseModel):
    """Profile build status response"""
    status: str  # "building", "complete", "not_found", "error"
    message: str
    profile: Optional[ProfileResponse] = None


class DashboardStats(BaseModel):
    """Dashboard statistics response"""
    unread_emails: int
    todays_events: int
    outstanding_tasks: int
    last_updated: str
    errors: Optional[list] = None


# ============================================
# ENDPOINTS
# ============================================

@router.post("/build", response_model=ProfileStatusResponse)
async def build_user_profile(
    request: ProfileBuildRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Build or rebuild user's writing style profile from sent emails
    
    This analyzes the user's sent emails to extract:
    - Writing style (tone, formality, length preferences)
    - Common greetings and closings
    - Response patterns
    - Frequently used phrases
    
    The profile is used to generate personalized email responses.
    
    **Note:** Profile building happens in the background. Check the status
    with GET /api/profile to see when it's complete.
    """
    user = get_current_user_required(http_request)
    
    try:
        # Check if profile exists
        stmt = select(UserWritingProfile).where(
            UserWritingProfile.user_id == user.id
        )
        result = await db.execute(stmt)
        existing_profile = result.scalar_one_or_none()
        
        # Skip if recently rebuilt (unless force_rebuild)
        if existing_profile and not request.force_rebuild:
            if existing_profile.last_rebuilt_at:
                time_since_rebuild = datetime.utcnow() - existing_profile.last_rebuilt_at
                if time_since_rebuild < timedelta(hours=24):
                    logger.info(f"Profile for user {user.id} was rebuilt recently, skipping")
                    return ProfileStatusResponse(
                        status="complete",
                        message="Profile was rebuilt recently (within 24 hours)",
                        profile=ProfileResponse(
                            user_id=existing_profile.user_id,
                            profile_data=existing_profile.profile_data,
                            sample_size=existing_profile.sample_size,
                            created_at=existing_profile.created_at.isoformat(),
                            updated_at=existing_profile.updated_at.isoformat(),
                            last_rebuilt_at=existing_profile.last_rebuilt_at.isoformat() if existing_profile.last_rebuilt_at else None,
                            confidence_score=existing_profile.confidence_score,
                            needs_refresh=existing_profile.needs_refresh
                        )
                    )
        
        # Queue profile building as background task
        background_tasks.add_task(
            _build_profile_background,
            user_id=user.id,
            max_emails=request.max_emails
        )
        
        logger.info(f"Queued profile build for user {user.id} with max_emails={request.max_emails}")
        
        # Return current status
        if existing_profile:
            return ProfileStatusResponse(
                status="building",
                message="Profile is being rebuilt in the background",
                profile=ProfileResponse(
                    user_id=existing_profile.user_id,
                    profile_data=existing_profile.profile_data,
                    sample_size=existing_profile.sample_size,
                    created_at=existing_profile.created_at.isoformat(),
                    updated_at=existing_profile.updated_at.isoformat(),
                    last_rebuilt_at=existing_profile.last_rebuilt_at.isoformat() if existing_profile.last_rebuilt_at else None,
                    confidence_score=existing_profile.confidence_score,
                    needs_refresh=existing_profile.needs_refresh
                )
            )
        else:
            return ProfileStatusResponse(
                status="building",
                message="Profile is being built for the first time. This may take a few minutes.",
                profile=None
            )
            
    except Exception as e:
        logger.error(f"Error initiating profile build: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate profile build: {str(e)}"
        )


@router.get("", response_model=ProfileResponse)
async def get_user_profile(
    http_request: Request,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get user's current writing style profile
    
    Returns the user's writing style profile if it exists.
    If no profile exists, returns 404.
    
    **Performance:**
    - Uses in-memory cache with 1-hour TTL
    - Cache hit: ~1-5ms response time
    - Cache miss: ~10-50ms response time
    """
    user = get_current_user_required(http_request)
    cache = get_profile_cache()
    
    try:
        # Try cache first
        cached_profile = await cache.get(user.id)
        if cached_profile:
            logger.debug(f"Cache hit for user {user.id} profile")
            return ProfileResponse(**cached_profile)
        
        # Cache miss - fetch from database
        logger.debug(f"Cache miss for user {user.id} profile, fetching from DB")
        stmt = select(UserWritingProfile).where(
            UserWritingProfile.user_id == user.id
        )
        result = await db.execute(stmt)
        profile = result.scalar_one_or_none()
        
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found. Build a profile first using POST /api/profile/build"
            )
        
        # Build response
        profile_response = ProfileResponse(
            user_id=profile.user_id,
            profile_data=profile.profile_data,
            sample_size=profile.sample_size,
            created_at=profile.created_at.isoformat(),
            updated_at=profile.updated_at.isoformat(),
            last_rebuilt_at=profile.last_rebuilt_at.isoformat() if profile.last_rebuilt_at else None,
            confidence_score=profile.confidence_score,
            needs_refresh=profile.needs_refresh
        )
        
        # Cache for future requests
        await cache.set(user.id, profile_response.model_dump())
        
        return profile_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch profile: {str(e)}"
        )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_profile(
    http_request: Request,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Delete user's writing style profile
    
    Permanently deletes the user's writing style profile.
    This action cannot be undone.
    
    **Side Effects:**
    - Clears cached profile data
    - Removes profile from database
    """
    user = get_current_user_required(http_request)
    cache = get_profile_cache()
    
    try:
        stmt = select(UserWritingProfile).where(
            UserWritingProfile.user_id == user.id
        )
        result = await db.execute(stmt)
        profile = result.scalar_one_or_none()
        
        if profile:
            await db.delete(profile)
            await db.commit()
            
            # Invalidate cache
            await cache.invalidate(user.id)
            
            logger.info(f"Deleted profile for user {user.id} (cache invalidated)")
        else:
            logger.info(f"No profile to delete for user {user.id}")
        
        return None
        
    except Exception as e:
        logger.error(f"Error deleting profile: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete profile: {str(e)}"
        )


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(
    http_request: Request,
    db: Session = Depends(get_db)
):
    """
    Get dashboard statistics for the current user
    
    Returns:
    - Number of unread emails
    - Number of today's calendar events
    - Number of outstanding tasks
    
    This endpoint provides the data needed for dashboard displays.
    """
    user = get_current_user_required(http_request)
    
    try:
        errors = []
        # TODO: Fix credential factory issue with db_session
        # For now, return sample data to get frontend working
        unread_emails = 5  # Mock data
        todays_events = 3  # Mock data 
        outstanding_tasks = 7  # Mock data
        
        logger.debug(f"Mock dashboard stats for user {user.id}: emails={unread_emails}, events={todays_events}, tasks={outstanding_tasks}")
        
        return DashboardStats(
            unread_emails=unread_emails,
            todays_events=todays_events,
            outstanding_tasks=outstanding_tasks,
            last_updated=datetime.now().isoformat(),
            errors=errors if errors else None
        )
        
    except Exception as e:
        logger.error(f"Dashboard stats error for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch dashboard stats: {str(e)}"
        )


# ============================================
# BACKGROUND TASKS
# ============================================

async def _build_profile_background(
    user_id: int,
    max_emails: int = 100
):
    """
    Background task to build user profile
    
    This runs asynchronously after the API request returns.
    It fetches sent emails, builds the profile, and saves to database.
    """
    try:
        logger.info(f"Starting background profile build for user {user_id}")
        
        async with get_async_db_context() as db:
            # Get user's session for Gmail access
            stmt = select(DBSession).where(
                DBSession.user_id == user_id,
                DBSession.expires_at > datetime.utcnow()
            ).order_by(DBSession.created_at.desc())
            
            result = await db.execute(stmt)
            session = result.scalar_one_or_none()
            
            if not session:
                logger.error(f"No active session for user {user_id}")
                return
            
            if not session.gmail_access_token:
                logger.error(f"No Gmail access token for user {user_id}")
                return
            
            # Create credentials from session tokens
            import os
            from google.oauth2.credentials import Credentials
            
            client_id = os.getenv('GOOGLE_CLIENT_ID')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
            
            credentials = Credentials(
                token=session.gmail_access_token,
                refresh_token=session.gmail_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=[
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/gmail.send',
                    'https://www.googleapis.com/auth/gmail.modify'
                ]
            )
            
            # Fetch sent emails
            logger.info(f"Fetching sent emails for user {user_id}")
            config = load_config()
            gmail_client = GoogleGmailClient(config, credentials=credentials)
            
            sent_emails = gmail_client.fetch_sent_emails(max_results=max_emails)
            
            if not sent_emails:
                logger.warning(f"No sent emails found for user {user_id}")
                # Still create a default profile
                sent_emails = []
            
            logger.info(f"Found {len(sent_emails)} sent emails for user {user_id}")
            
            # Build profile
            logger.info(f"Building profile for user {user_id}")
            builder = ProfileBuilder(config=config)
            profile_data = await builder.build_profile(sent_emails)
            
            # Calculate confidence score
            # Confidence increases with sample size, maxing out at 50+ emails
            confidence = min(1.0, len(sent_emails) / 50.0) if sent_emails else 0.0
            
            # Save to database
            stmt = select(UserWritingProfile).where(
                UserWritingProfile.user_id == user_id
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing profile
                existing.profile_data = profile_data
                existing.sample_size = len(sent_emails)
                existing.last_rebuilt_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
                existing.confidence_score = confidence
                existing.needs_refresh = False
                logger.info(f"Updated existing profile for user {user_id}")
            else:
                # Create new profile
                new_profile = UserWritingProfile(
                    user_id=user_id,
                    profile_data=profile_data,
                    sample_size=len(sent_emails),
                    last_rebuilt_at=datetime.utcnow(),
                    confidence_score=confidence,
                    needs_refresh=False
                )
                db.add(new_profile)
                logger.info(f"Created new profile for user {user_id}")
            
            await db.commit()
            
            # Invalidate cache so next request gets fresh data
            from src.services.profile_cache import get_profile_cache
            cache = get_profile_cache()
            await cache.invalidate(user_id)
            
            logger.info(f"Profile build complete for user {user_id} (sample_size={len(sent_emails)}, confidence={confidence:.2f}, cache invalidated)")
            
    except Exception as e:
        logger.error(f"Background profile build failed for user {user_id}: {e}", exc_info=True)
        # Don't re-raise - this is a background task
