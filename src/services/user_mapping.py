"""
User Mapping Service

Resolves external platform user IDs (Slack, email) to internal Clavr user IDs.
Uses an LRU cache to avoid redundant API calls.
"""
from functools import lru_cache
from typing import Optional, Dict

from sqlalchemy.orm import Session

from src.database.models import User
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# In-memory cache of slack_user_id → clavr_user_id
_slack_user_cache: Dict[str, Optional[int]] = {}

# Default user ID to use when no mapping is found (configurable)
DEFAULT_USER_ID: int = 1


class UserMappingService:
    """Resolves external platform user identifiers to internal Clavr user IDs."""

    def __init__(self, db_session: Session):
        self.db = db_session

    def resolve_slack_user(
        self,
        slack_user_id: str,
        slack_client=None,
    ) -> Optional[int]:
        """
        Map a Slack user ID to a Clavr user ID.

        Strategy:
        1. Check in-memory cache.
        2. Call Slack API to get the user's email.
        3. Match email against User.email in the database.
        4. Cache the result and return.

        Args:
            slack_user_id: Slack user ID (e.g. "U05ABC123").
            slack_client: Optional SlackClient instance for API lookups.

        Returns:
            Clavr user_id or None if not found.
        """
        # 1. Cache hit
        if slack_user_id in _slack_user_cache:
            return _slack_user_cache[slack_user_id]

        email = None

        # 2. Slack API lookup
        if slack_client:
            try:
                user_info = slack_client.get_user_info(slack_user_id)
                if user_info:
                    profile = user_info.get("profile", {})
                    email = profile.get("email") or user_info.get("email")
            except Exception as e:
                logger.warning(
                    f"[UserMapping] Slack API lookup failed for {slack_user_id}: {e}"
                )

        # 3. Database lookup by email
        if email:
            user = (
                self.db.query(User)
                .filter(User.email == email)
                .first()
            )
            if user:
                _slack_user_cache[slack_user_id] = user.id
                logger.info(
                    f"[UserMapping] Mapped Slack user {slack_user_id} → Clavr user {user.id} ({email})"
                )
                return user.id

        # 4. Not found — cache as None to avoid repeated lookups
        _slack_user_cache[slack_user_id] = None
        logger.debug(
            f"[UserMapping] No Clavr user found for Slack user {slack_user_id}"
        )
        return None

    def resolve_email_user(self, email_address: str) -> Optional[int]:
        """
        Map an email address to a Clavr user ID.

        Args:
            email_address: Email address to look up.

        Returns:
            Clavr user_id or None.
        """
        if not email_address:
            return None

        user = (
            self.db.query(User)
            .filter(User.email == email_address.lower())
            .first()
        )
        return user.id if user else None

    def resolve_or_default(
        self,
        slack_user_id: Optional[str] = None,
        email_address: Optional[str] = None,
        slack_client=None,
    ) -> int:
        """
        Best-effort resolution with fallback to DEFAULT_USER_ID.

        Tries Slack mapping first, then email, then returns the default.
        """
        if slack_user_id:
            user_id = self.resolve_slack_user(slack_user_id, slack_client)
            if user_id is not None:
                return user_id

        if email_address:
            user_id = self.resolve_email_user(email_address)
            if user_id is not None:
                return user_id

        logger.debug(
            f"[UserMapping] Falling back to default user {DEFAULT_USER_ID}"
        )
        return DEFAULT_USER_ID

    @staticmethod
    def clear_cache():
        """Clear the Slack user cache (useful for tests)."""
        _slack_user_cache.clear()
