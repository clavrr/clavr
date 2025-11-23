"""
Background Profile Service
Automatically updates stale user writing profiles to keep them fresh
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_async_db_context
from ..database.models import User, UserWritingProfile, Session as DBSession
from ..ai.profile_builder import ProfileBuilder
from ..utils.config import load_config
from ..utils.logger import setup_logger
import os

logger = setup_logger(__name__)


class ProfileUpdateService:
    """
    Service for managing background profile updates
    
    Features:
    - Detects stale profiles (>7 days old)
    - Updates profiles for active users
    - Rate-limited to avoid API overload
    - Configurable update frequency
    """
    
    def __init__(
        self,
        stale_threshold_days: int = 7,
        max_updates_per_run: int = 10,
        update_interval_hours: int = 1
    ):
        """
        Initialize profile update service
        
        Args:
            stale_threshold_days: Consider profile stale after this many days
            max_updates_per_run: Maximum profiles to update per cycle
            update_interval_hours: Hours between update cycles
        """
        self.stale_threshold_days = stale_threshold_days
        self.max_updates_per_run = max_updates_per_run
        self.update_interval_hours = update_interval_hours
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(
            f"ProfileUpdateService initialized: "
            f"stale_threshold={stale_threshold_days}d, "
            f"max_per_run={max_updates_per_run}, "
            f"interval={update_interval_hours}h"
        )
    
    async def start(self):
        """Start the background update service"""
        if self.is_running:
            logger.warning("Profile update service already running")
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._update_loop())
        logger.info("Profile update service started")
    
    async def stop(self):
        """Stop the background update service"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Profile update service stopped")
    
    async def _update_loop(self):
        """Main update loop"""
        while self.is_running:
            try:
                await self.update_stale_profiles()
            except Exception as e:
                logger.error(f"Error in profile update loop: {e}", exc_info=True)
            
            # Wait before next cycle
            await asyncio.sleep(self.update_interval_hours * 3600)
    
    async def update_stale_profiles(self) -> int:
        """
        Update stale profiles
        
        Returns:
            Number of profiles updated
        """
        logger.info("Starting stale profile update cycle")
        
        async with get_async_db_context() as db:
            # Find stale profiles
            stale_profiles = await self._find_stale_profiles(db)
            
            if not stale_profiles:
                logger.info("No stale profiles found")
                return 0
            
            logger.info(f"Found {len(stale_profiles)} stale profiles to update")
            
            # Update each profile
            updated_count = 0
            for profile in stale_profiles:
                try:
                    success = await self._update_profile(db, profile)
                    if success:
                        updated_count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to update profile for user {profile.user_id}: {e}",
                        exc_info=True
                    )
                    continue
            
            logger.info(f"Updated {updated_count}/{len(stale_profiles)} profiles")
            return updated_count
    
    async def _find_stale_profiles(
        self,
        db: AsyncSession
    ) -> List[UserWritingProfile]:
        """
        Find profiles that need updating
        
        Criteria:
        - Last rebuilt > stale_threshold_days ago
        - OR needs_refresh flag is True
        - User has active session (logged in recently)
        
        Args:
            db: Database session
            
        Returns:
            List of stale profiles
        """
        stale_date = datetime.utcnow() - timedelta(days=self.stale_threshold_days)
        
        # Find stale profiles with active users
        # Use subquery to avoid DISTINCT with JSON columns
        subquery = (
            select(UserWritingProfile.id)
            .join(User, UserWritingProfile.user_id == User.id)
            .join(DBSession, DBSession.user_id == User.id)
            .where(
                and_(
                    or_(
                        UserWritingProfile.last_rebuilt_at < stale_date,
                        UserWritingProfile.needs_refresh == True
                    ),
                    DBSession.expires_at > datetime.utcnow()  # Active session
                )
            )
            .distinct()
            .limit(self.max_updates_per_run)
        )
        
        stmt = select(UserWritingProfile).where(UserWritingProfile.id.in_(subquery))
        
        result = await db.execute(stmt)
        profiles = result.scalars().all()
        
        return list(profiles)
    
    async def _update_profile(
        self,
        db: AsyncSession,
        profile: UserWritingProfile
    ) -> bool:
        """
        Update a single profile
        
        Args:
            db: Database session
            profile: Profile to update
            
        Returns:
            True if successful
        """
        user_id = profile.user_id
        logger.info(f"Updating profile for user {user_id}")
        
        try:
            # Get user's active session
            stmt = (
                select(DBSession)
                .where(
                    and_(
                        DBSession.user_id == user_id,
                        DBSession.expires_at > datetime.utcnow()
                    )
                )
                .order_by(DBSession.created_at.desc())
            )
            result = await db.execute(stmt)
            session = result.scalar_one_or_none()
            
            if not session:
                logger.warning(f"No active session for user {user_id}")
                return False
            
            # Fetch sent emails through service layer
            # ServiceFactory handles credential loading and validation automatically
            config = load_config()
            from ..services.factory import ServiceFactory
            
            service_factory = ServiceFactory(config=config)
            email_service = service_factory.create_email_service(
                user_id=user_id,
                db_session=db
            )
            
            if not email_service or not email_service.gmail_client:
                logger.warning(f"Gmail service not available for user {user_id}")
                return False
            
            if not email_service.gmail_client.is_available():
                logger.warning(f"Gmail client not available for user {user_id}")
                return False
            
            sent_emails = email_service.gmail_client.fetch_sent_emails(max_results=100)
            
            if not sent_emails:
                logger.warning(f"No sent emails found for user {user_id}")
                # Don't fail - keep existing profile
                return False
            
            logger.info(f"Fetched {len(sent_emails)} sent emails for user {user_id}")
            
            # Build new profile
            builder = ProfileBuilder(config=config)
            profile_data = await builder.build_profile(sent_emails)
            
            # Calculate confidence
            confidence = min(1.0, len(sent_emails) / 50.0)
            
            # Update profile
            profile.profile_data = profile_data
            profile.sample_size = len(sent_emails)
            profile.last_rebuilt_at = datetime.utcnow()
            profile.updated_at = datetime.utcnow()
            profile.confidence_score = confidence
            profile.needs_refresh = False
            
            await db.commit()
            await db.refresh(profile)
            
            logger.info(
                f"Successfully updated profile for user {user_id} "
                f"(sample_size={len(sent_emails)}, confidence={confidence:.2f})"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating profile for user {user_id}: {e}", exc_info=True)
            await db.rollback()
            return False
    
    async def mark_profile_for_refresh(self, user_id: int) -> bool:
        """
        Mark a profile as needing refresh
        
        Args:
            user_id: User ID
            
        Returns:
            True if successful
        """
        try:
            async with get_async_db_context() as db:
                stmt = select(UserWritingProfile).where(
                    UserWritingProfile.user_id == user_id
                )
                result = await db.execute(stmt)
                profile = result.scalar_one_or_none()
                
                if not profile:
                    logger.warning(f"No profile found for user {user_id}")
                    return False
                
                profile.needs_refresh = True
                profile.updated_at = datetime.utcnow()
                
                await db.commit()
                logger.info(f"Marked profile for user {user_id} for refresh")
                
                return True
                
        except Exception as e:
            logger.error(f"Error marking profile for refresh: {e}", exc_info=True)
            return False
    
    async def get_service_stats(self) -> dict:
        """
        Get service statistics
        
        Returns:
            Dictionary with stats
        """
        try:
            async with get_async_db_context() as db:
                # Total profiles
                stmt = select(UserWritingProfile)
                result = await db.execute(stmt)
                total_profiles = len(result.scalars().all())
                
                # Stale profiles
                stale_date = datetime.utcnow() - timedelta(days=self.stale_threshold_days)
                stmt = select(UserWritingProfile).where(
                    or_(
                        UserWritingProfile.last_rebuilt_at < stale_date,
                        UserWritingProfile.needs_refresh == True
                    )
                )
                result = await db.execute(stmt)
                stale_profiles = len(result.scalars().all())
                
                # Profiles needing refresh
                stmt = select(UserWritingProfile).where(
                    UserWritingProfile.needs_refresh == True
                )
                result = await db.execute(stmt)
                needs_refresh = len(result.scalars().all())
                
                return {
                    "is_running": self.is_running,
                    "total_profiles": total_profiles,
                    "stale_profiles": stale_profiles,
                    "needs_refresh": needs_refresh,
                    "stale_threshold_days": self.stale_threshold_days,
                    "max_updates_per_run": self.max_updates_per_run,
                    "update_interval_hours": self.update_interval_hours
                }
                
        except Exception as e:
            logger.error(f"Error getting service stats: {e}", exc_info=True)
            return {
                "error": str(e)
            }


# Global service instance
_profile_service: Optional[ProfileUpdateService] = None


def get_profile_service() -> ProfileUpdateService:
    """Get or create global profile service instance"""
    global _profile_service
    
    if _profile_service is None:
        # Read configuration from environment
        stale_threshold = int(os.getenv('PROFILE_STALE_THRESHOLD_DAYS', '7'))
        max_updates = int(os.getenv('PROFILE_MAX_UPDATES_PER_RUN', '10'))
        interval = int(os.getenv('PROFILE_UPDATE_INTERVAL_HOURS', '1'))
        
        _profile_service = ProfileUpdateService(
            stale_threshold_days=stale_threshold,
            max_updates_per_run=max_updates,
            update_interval_hours=interval
        )
    
    return _profile_service


async def start_profile_service():
    """Start the global profile service"""
    service = get_profile_service()
    await service.start()


async def stop_profile_service():
    """Stop the global profile service"""
    service = get_profile_service()
    await service.stop()
