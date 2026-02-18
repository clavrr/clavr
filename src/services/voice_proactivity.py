"""
Voice Proactivity Service

Monitors for proactive nudge-worthy events and pushes voice notifications
to connected users. Integrates with the existing ProactiveContextService,
ConnectionManager, and Ghost agent system.

Trigger types:
  - meeting_imminent:     Meeting starting in <5 minutes
  - urgent_email:         High-priority email from a VIP contact
  - ghost_draft_ready:    Ghost agent completed a draft
  - deadline_approaching: Task deadline within 1 hour
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


# Enums & Data Classes

class NudgeTriggerType(str, Enum):
    MEETING_IMMINENT = "meeting_imminent"
    URGENT_EMAIL = "urgent_email"
    GHOST_DRAFT_READY = "ghost_draft_ready"
    DEADLINE_APPROACHING = "deadline_approaching"


@dataclass
class VoiceNudge:
    """A proactive voice nudge ready for delivery."""
    trigger_type: NudgeTriggerType
    title: str
    spoken_text: str
    priority: int = 1            # 1 = highest
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": "voice_nudge",
            "trigger_type": self.trigger_type.value,
            "title": self.title,
            "spoken_text": self.spoken_text,
            "priority": self.priority,
            "context": self.context,
            "created_at": self.created_at,
        }


@dataclass
class NudgePreferences:
    """Per-user nudge preferences."""
    enabled: bool = True
    meeting_nudges: bool = True
    email_nudges: bool = True
    ghost_nudges: bool = True
    deadline_nudges: bool = True
    quiet_hours_start: Optional[int] = 22   # 10 PM
    quiet_hours_end: Optional[int] = 7      # 7 AM
    cooldown_minutes: int = 15

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "meeting_nudges": self.meeting_nudges,
            "email_nudges": self.email_nudges,
            "ghost_nudges": self.ghost_nudges,
            "deadline_nudges": self.deadline_nudges,
            "quiet_hours_start": self.quiet_hours_start,
            "quiet_hours_end": self.quiet_hours_end,
            "cooldown_minutes": self.cooldown_minutes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NudgePreferences":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Default Timing Constants

MEETING_MINUTES_BEFORE = 5
DEADLINE_MINUTES_BEFORE = 60
DEFAULT_COOLDOWN_MINUTES = 15


# VoiceProactivityService

class VoiceProactivityService:
    """
    Monitors for nudge-worthy events and generates spoken notifications.

    This is designed to be called periodically (via Celery beat) or on-demand
    from the proactive WebSocket endpoint.
    """

    def __init__(self, config=None, db_session=None):
        self.config = config
        self.db_session = db_session

        # In-memory stores (per-user)
        self._user_preferences: Dict[int, NudgePreferences] = {}
        self._last_nudge_time: Dict[int, float] = {}
        self._delivered_nudge_keys: Dict[int, set] = {}  # dedup

    # Preferences

    def get_preferences(self, user_id: int) -> NudgePreferences:
        """Get nudge preferences for a user (defaults if not set)."""
        return self._user_preferences.get(user_id, NudgePreferences())

    def update_preferences(self, user_id: int, prefs: NudgePreferences) -> NudgePreferences:
        """Update nudge preferences for a user."""
        self._user_preferences[user_id] = prefs
        logger.info(f"[VoiceProactivity] Updated preferences for user {user_id}")
        return prefs

    # Core: Check Triggers

    async def check_proactive_triggers(self, user_id: int) -> List[VoiceNudge]:
        """
        Evaluate all trigger types for a user and return any pending nudges.

        Returns:
            List of VoiceNudge objects sorted by priority.
        """
        prefs = self.get_preferences(user_id)

        if not prefs.enabled:
            return []

        # Quiet hours check
        if self._is_quiet_hours(prefs):
            return []

        # Cooldown check
        if self._is_in_cooldown(user_id, prefs):
            return []

        nudges: List[VoiceNudge] = []

        # --- Meeting check ---
        if prefs.meeting_nudges:
            try:
                meeting_nudge = await self._check_meeting_trigger(user_id)
                if meeting_nudge:
                    nudges.append(meeting_nudge)
            except Exception as e:
                logger.debug(f"[VoiceProactivity] Meeting trigger error: {e}")

        # --- Urgent email check ---
        if prefs.email_nudges:
            try:
                email_nudge = await self._check_email_trigger(user_id)
                if email_nudge:
                    nudges.append(email_nudge)
            except Exception as e:
                logger.debug(f"[VoiceProactivity] Email trigger error: {e}")

        # --- Ghost draft check ---
        if prefs.ghost_nudges:
            try:
                ghost_nudge = await self._check_ghost_trigger(user_id)
                if ghost_nudge:
                    nudges.append(ghost_nudge)
            except Exception as e:
                logger.debug(f"[VoiceProactivity] Ghost trigger error: {e}")

        # --- Deadline check ---
        if prefs.deadline_nudges:
            try:
                deadline_nudge = await self._check_deadline_trigger(user_id)
                if deadline_nudge:
                    nudges.append(deadline_nudge)
            except Exception as e:
                logger.debug(f"[VoiceProactivity] Deadline trigger error: {e}")

        # Deduplicate
        nudges = self._deduplicate(user_id, nudges)

        # Sort by priority (1 = highest)
        nudges.sort(key=lambda n: n.priority)

        return nudges

    async def get_proactive_greeting(
        self,
        user_id: int,
        trigger_type: Optional[NudgeTriggerType] = None,
    ) -> str:
        """
        Generate a context-aware greeting for a voice session triggered
        by a nudge or wake-word.
        """
        if trigger_type == NudgeTriggerType.MEETING_IMMINENT:
            nudge = await self._check_meeting_trigger(user_id)
            if nudge:
                return nudge.spoken_text
            return "You have a meeting coming up soon."

        if trigger_type == NudgeTriggerType.URGENT_EMAIL:
            nudge = await self._check_email_trigger(user_id)
            if nudge:
                return nudge.spoken_text
            return "You have an urgent email that might need attention."

        if trigger_type == NudgeTriggerType.GHOST_DRAFT_READY:
            return "I've prepared a draft for you. Want me to walk you through it?"

        if trigger_type == NudgeTriggerType.DEADLINE_APPROACHING:
            nudge = await self._check_deadline_trigger(user_id)
            if nudge:
                return nudge.spoken_text
            return "You have a deadline coming up soon."

        # Generic wake-word greeting
        return ""

    def record_nudge_delivered(self, user_id: int) -> None:
        """Record that a nudge was delivered (for cooldown)."""
        self._last_nudge_time[user_id] = time.time()

    # Trigger Checkers

    async def _check_meeting_trigger(self, user_id: int) -> Optional[VoiceNudge]:
        """Check for meetings starting within MEETING_MINUTES_BEFORE."""
        try:
            from api.dependencies import AppState
            brief_svc = AppState.get_brief_service(user_id=user_id)
            events = await brief_svc.get_upcoming_events(
                user_id=user_id,
                minutes_ahead=MEETING_MINUTES_BEFORE,
            )

            if not events:
                return None

            event = events[0]  # Most imminent
            title = event.get("summary", event.get("title", "Untitled meeting"))
            minutes = event.get("minutes_until", MEETING_MINUTES_BEFORE)
            attendees = event.get("attendees", [])

            # Build spoken text
            if attendees:
                names = [a.get("name", a.get("email", "someone")) for a in attendees[:3]]
                people = ", ".join(names)
                spoken = f"Heads up — your meeting \"{title}\" with {people} starts in about {minutes} minutes."
            else:
                spoken = f"Heads up — \"{title}\" starts in about {minutes} minutes."

            return VoiceNudge(
                trigger_type=NudgeTriggerType.MEETING_IMMINENT,
                title=f"Meeting: {title}",
                spoken_text=spoken,
                priority=1,
                context={"event": event},
            )

        except Exception as e:
            logger.debug(f"[VoiceProactivity] Meeting trigger check failed: {e}")
            return None

    async def _check_email_trigger(self, user_id: int) -> Optional[VoiceNudge]:
        """Check for urgent unread emails from VIP contacts."""
        try:
            from api.dependencies import AppState
            brief_svc = AppState.get_brief_service(user_id=user_id)
            urgent = await brief_svc.get_urgent_emails(user_id=user_id, limit=1)

            if not urgent:
                return None

            email = urgent[0]
            sender = email.get("from_name", email.get("from", "someone"))
            subject = email.get("subject", "No subject")

            spoken = f"You got an urgent email from {sender} about \"{subject}\". Want me to read it?"

            return VoiceNudge(
                trigger_type=NudgeTriggerType.URGENT_EMAIL,
                title=f"Urgent: {subject}",
                spoken_text=spoken,
                priority=2,
                context={"email": email},
            )

        except Exception as e:
            logger.debug(f"[VoiceProactivity] Email trigger check failed: {e}")
            return None

    async def _check_ghost_trigger(self, user_id: int) -> Optional[VoiceNudge]:
        """Check for pending Ghost agent drafts."""
        try:
            from api.dependencies import AppState
            ghost_svc = AppState.get_ghost_service(user_id=user_id)
            pending = await ghost_svc.get_pending_drafts(user_id=user_id)

            if not pending:
                return None

            draft = pending[0]
            topic = draft.get("topic", draft.get("title", "a Slack thread"))
            draft_type = draft.get("type", "issue")

            spoken = f"By the way, I've drafted a {draft_type} for that thread about \"{topic}\". Want me to walk you through it?"

            return VoiceNudge(
                trigger_type=NudgeTriggerType.GHOST_DRAFT_READY,
                title=f"Ghost Draft: {topic}",
                spoken_text=spoken,
                priority=3,
                context={"draft": draft},
            )

        except Exception as e:
            logger.debug(f"[VoiceProactivity] Ghost trigger check failed: {e}")
            return None

    async def _check_deadline_trigger(self, user_id: int) -> Optional[VoiceNudge]:
        """Check for tasks with approaching deadlines."""
        try:
            from api.dependencies import AppState
            brief_svc = AppState.get_brief_service(user_id=user_id)
            tasks = await brief_svc.get_upcoming_deadlines(
                user_id=user_id,
                minutes_ahead=DEADLINE_MINUTES_BEFORE,
            )

            if not tasks:
                return None

            task = tasks[0]
            title = task.get("title", "Untitled task")
            minutes = task.get("minutes_until", DEADLINE_MINUTES_BEFORE)

            spoken = f"Quick reminder — \"{title}\" is due in about {minutes} minutes."

            return VoiceNudge(
                trigger_type=NudgeTriggerType.DEADLINE_APPROACHING,
                title=f"Deadline: {title}",
                spoken_text=spoken,
                priority=2,
                context={"task": task},
            )

        except Exception as e:
            logger.debug(f"[VoiceProactivity] Deadline trigger check failed: {e}")
            return None
            
    # Helpers

    def _is_quiet_hours(self, prefs: NudgePreferences) -> bool:
        """Check if current time falls within quiet hours."""
        if prefs.quiet_hours_start is None or prefs.quiet_hours_end is None:
            return False

        try:
            from src.core.calendar.utils import get_user_timezone
            import pytz

            tz_name = get_user_timezone(self.config) if self.config else "UTC"
            tz = pytz.timezone(tz_name)
            now_hour = datetime.now(tz).hour

            start = prefs.quiet_hours_start
            end = prefs.quiet_hours_end

            if start <= end:
                return start <= now_hour < end
            else:
                # Wraps midnight (e.g., 22-7)
                return now_hour >= start or now_hour < end

        except Exception:
            return False

    def _is_in_cooldown(self, user_id: int, prefs: NudgePreferences) -> bool:
        """Check if the user is in nudge cooldown."""
        last = self._last_nudge_time.get(user_id, 0)
        cooldown_sec = prefs.cooldown_minutes * 60
        return (time.time() - last) < cooldown_sec

    def _deduplicate(self, user_id: int, nudges: List[VoiceNudge]) -> List[VoiceNudge]:
        """Remove nudges that have already been delivered recently."""
        if user_id not in self._delivered_nudge_keys:
            self._delivered_nudge_keys[user_id] = set()

        seen = self._delivered_nudge_keys[user_id]
        unique = []

        for nudge in nudges:
            key = f"{nudge.trigger_type.value}:{nudge.title}"
            if key not in seen:
                seen.add(key)
                unique.append(nudge)

        return unique

    def clear_delivered(self, user_id: int) -> None:
        """Clear the delivered nudge set (e.g., on new day or manual reset)."""
        self._delivered_nudge_keys.pop(user_id, None)
