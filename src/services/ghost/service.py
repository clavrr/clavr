"""
Ghost Service

The autonomous background worker that monitors user state and updates "Outer World" interfaces (Slack, etc).
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from src.utils.logger import setup_logger
from src.database.models import User
from src.core.async_credential_provider import AsyncCredentialFactory
from src.features.protection.deep_work import DeepWorkLogic, ProtectionLevel
from src.tools.slack.tool import SlackTool

logger = setup_logger(__name__)

class GhostService:
    """
    Background service for checking user state and applying protections.
    """
    
    def __init__(self, db_session, config):
        self.db = db_session
        self.config = config
        self.logic = DeepWorkLogic()

    async def run_ghost_check(self, user_id: int):
        """
        Run a full protection check for a user.
        """
        logger.info(f"[Ghost] Running check for user {user_id}")
        
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning(f"[Ghost] User {user_id} not found")
            return

        # 1. Get Calendar Events
        events = await self._get_upcoming_events(user)
        if events is None:
            logger.info(f"[Ghost] No calendar access for user {user_id}")
            return

        # 2. Analyze State
        now = datetime.utcnow()
        window_end = now + timedelta(hours=2) # Check next 2 hours
        
        # Check for explicit Focus blocks first
        level = self.logic.analyze_event_types(events)
        
        if level == ProtectionLevel.NORMAL:
            # Fallback to density check
            score = self.logic.calculate_busyness_score(events, now, window_end)
            level = self.logic.determine_protection_level(score)
            logger.info(f"[Ghost] Busyness score regarding user {user_id}: {score:.2f} -> {level}")

        # 3. Apply Protections (Slack Status)
        await self._apply_slack_status(user, level)

    async def _get_upcoming_events(self, user: User) -> Optional[List[Dict[str, Any]]]:
        """Fetch events for next 2 hours."""
        try:
            factory = AsyncCredentialFactory(self.config, self.db, user)
            calendar_service = await factory.get_calendar_service()
            
            if not calendar_service:
                return None
                
            # Fetch slightly more to be safe
            events = await calendar_service.get_upcoming_events(limit=20)
            return events
        except Exception as e:
            logger.error(f"[Ghost] Failed to fetch events: {e}")
            return None

    async def _apply_slack_status(self, user: User, level: ProtectionLevel):
        """Update Slack status based on level."""
        try:
            # Initialize Slack Tool
            # We assume user has a stored slack_id or we resolve it via email
            slack_tool = SlackTool(config=self.config, user_id=user.id)
            
            if not slack_tool.slack_client:
                return

            # Resolve Slack User ID using the tool's robust logic
            # This handles DB caching and API fallback automatically
            slack_user_id = await asyncio.to_thread(slack_tool._resolve_slack_user_id)
            if not slack_user_id:
                logger.warning(f"[Ghost] Could not resolve Slack ID for {user.email}")
                return

            # Define Statuses
            status_text = ""
            status_emoji = ""
            expiration = 0 # 0 = don't expire automatically
            
            if level == ProtectionLevel.DEEP_WORK:
                status_text = "Deep Work Mode"
                status_emoji = ":lock:"
                expiration = int((datetime.utcnow() + timedelta(minutes=60)).timestamp())
            elif level == ProtectionLevel.MEETING_HEAVY:
                status_text = "In Meetings"
                status_emoji = ":calendar:"
                expiration = int((datetime.utcnow() + timedelta(minutes=30)).timestamp())
            else:
                # Normal mode - clear status
                # We clear the status by setting empty strings
                status_text = ""
                status_emoji = ""
                logger.info(f"[Ghost] Clearing protection status for {user.email}")

            # Apply via tool
            if level != ProtectionLevel.NORMAL:
                logger.info(f"[Ghost] Setting protection status for {user.email}: {status_text}")
            
            await slack_tool._arun(
                action="set_status",
                user=slack_user_id,
                status_text=status_text,
                status_emoji=status_emoji,
                expiration=expiration
            )

        except Exception as e:
            logger.error(f"[Ghost] Failed to set Slack status: {e}")

    async def _resolve_slack_user(self, tool, email: str) -> Optional[str]:
        """
        DEPRECATED: Use tool._resolve_slack_user_id() instead.
        """
        return await asyncio.to_thread(tool._resolve_slack_user_id)
