"""
User Writing Profile API
Endpoints for building and managing user email writing style profiles
"""
from fastapi import APIRouter, HTTPException, Depends, Request, status, Response
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
from api.dependencies import get_current_user
from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.services.profile_cache import get_profile_cache
from src.services.profile_service import get_profile_service

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
    created_at: datetime
    updated_at: datetime
    last_rebuilt_at: Optional[datetime] = None
    confidence_score: Optional[float] = None
    needs_refresh: bool = False
    
    class Config:
        from_attributes = True


class ProfileStatusResponse(BaseModel):
    """Profile build status response"""
    status: str  # "building", "complete", "not_found", "error"
    message: str
    profile: Optional[ProfileResponse] = None






# ============================================
# ENDPOINTS
# ============================================

@router.post("/build", response_model=ProfileStatusResponse)
async def build_user_profile(
    request: ProfileBuildRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Build or rebuild user's writing style profile from sent emails.
    """
    profile_service = get_profile_service()
    
    try:
        # Check if profile exists
        stmt = select(UserWritingProfile).where(UserWritingProfile.user_id == user.id)
        result = await db.execute(stmt)
        existing_profile = result.scalar_one_or_none()
        
        # Skip if recently rebuilt (unless force_rebuild)
        if existing_profile and not request.force_rebuild:
            if existing_profile.last_rebuilt_at:
                time_since_rebuild = datetime.utcnow() - existing_profile.last_rebuilt_at
                if time_since_rebuild < timedelta(hours=24):
                    return ProfileStatusResponse(
                        status="complete",
                        message="Profile was rebuilt recently",
                        profile=ProfileResponse.from_orm(existing_profile)
                    )
        
        # Trigger background build
        await profile_service.trigger_profile_build(user.id, request.max_emails)
        
        return ProfileStatusResponse(
            status="building",
            message="Profile is being built in the background",
            profile=ProfileResponse.from_orm(existing_profile) if existing_profile else None
        )
            
    except Exception as e:
        logger.error(f"Error initiating profile build: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate profile build: {str(e)}"
        )


@router.get("", response_model=ProfileResponse)
async def get_user_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get user's current writing style profile
    """
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
        profile_response = ProfileResponse.from_orm(profile)
        
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Delete user's writing style profile
    """
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
