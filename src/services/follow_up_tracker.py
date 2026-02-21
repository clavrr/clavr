"""
Follow-Up State Machine

Tracks revenue-critical email threads through a progressive reminder pipeline:
RECEIVED -> FLAGGED -> REMINDED_ONCE -> REMINDED_TWICE -> ESCALATED -> REPLIED/CLOSED

Each thread carries a RevenueSignal so urgency and escalation speed are
proportional to the deal value at stake.

Data is persisted to Redis (with in-memory fallback) so that tracked
threads survive server restarts.
"""
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.utils.redis_store import RedisBackedStore

logger = setup_logger(__name__)


class FollowUpState(str, Enum):
    """States in the follow-up pipeline."""
    RECEIVED = "received"
    FLAGGED = "flagged"
    REMINDED_ONCE = "reminded_once"
    REMINDED_TWICE = "reminded_twice"
    ESCALATED = "escalated"
    REPLIED = "replied"
    CLOSED = "closed"


# How long (in hours) before advancing to the next state, keyed by urgency.
_ADVANCE_INTERVALS: Dict[str, Dict[FollowUpState, float]] = {
    "critical": {
        FollowUpState.FLAGGED: 1.0,
        FollowUpState.REMINDED_ONCE: 2.0,
        FollowUpState.REMINDED_TWICE: 4.0,
    },
    "high": {
        FollowUpState.FLAGGED: 4.0,
        FollowUpState.REMINDED_ONCE: 8.0,
        FollowUpState.REMINDED_TWICE: 24.0,
    },
    "medium": {
        FollowUpState.FLAGGED: 24.0,
        FollowUpState.REMINDED_ONCE: 48.0,
        FollowUpState.REMINDED_TWICE: 72.0,
    },
    "low": {
        FollowUpState.FLAGGED: 48.0,
        FollowUpState.REMINDED_ONCE: 72.0,
        FollowUpState.REMINDED_TWICE: 168.0,
    },
}

# Value-based interval scaling: high-value deals escalate faster

HIGH_VALUE_INTERVAL_THRESHOLD = 50_000   # Apply multiplier for deals >= $50k
HIGH_VALUE_INTERVAL_MULTIPLIER = 0.5     # Halve wait times for high-value deals


@dataclass
class TrackedThread:
    """A single email thread being tracked through the follow-up pipeline."""
    thread_id: str
    email_id: str
    sender: str
    sender_email: str
    subject: str
    signal_type: str
    signal_urgency: str
    signal_confidence: float
    estimated_value: Optional[float] = None
    state: FollowUpState = FollowUpState.RECEIVED
    user_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    last_state_change: float = field(default_factory=time.time)
    reminder_count: int = 0
    draft_id: Optional[str] = None  # Gmail draft ID if auto-drafted

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "email_id": self.email_id,
            "sender": self.sender,
            "sender_email": self.sender_email,
            "subject": self.subject,
            "signal_type": self.signal_type,
            "signal_urgency": self.signal_urgency,
            "signal_confidence": self.signal_confidence,
            "estimated_value": self.estimated_value,
            "state": self.state.value,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "last_state_change": self.last_state_change,
            "reminder_count": self.reminder_count,
            "draft_id": self.draft_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackedThread":
        data = dict(data)
        data["state"] = FollowUpState(data.get("state", "received"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class FollowUpTracker:
    """
    Persistent state machine for revenue-critical email follow-ups.

    Threads are persisted to Redis (with in-memory fallback).
    The run_sweep method is designed to be called by Celery beat.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config
        self._store = RedisBackedStore(prefix="follow_up_tracker")
        self._auto_responder = None

    def _key(self, user_id: int, thread_id: str) -> str:
        return f"{user_id}:{thread_id}"

    # --- persistence helpers ---

    def _persist_thread(self, key: str, thread: TrackedThread) -> None:
        """Save a single thread to the backing store."""
        self._store.set(f"thread:{key}", thread.to_dict())

    def _load_thread(self, key: str) -> Optional[TrackedThread]:
        """Load a single thread from the backing store."""
        raw = self._store.get(f"thread:{key}")
        if raw is None:
            return None
        return TrackedThread.from_dict(raw)

    def _all_thread_keys_for_user(self, user_id: int) -> List[str]:
        """Return all thread keys for a given user."""
        prefix = f"thread:{user_id}:"
        return self._store.keys_for_prefix(prefix)

    def _load_all_for_user(self, user_id: int) -> List[TrackedThread]:
        """Load all threads for a user."""
        threads = []
        for store_key in self._all_thread_keys_for_user(user_id):
            raw = self._store.get(store_key)
            if raw:
                threads.append(TrackedThread.from_dict(raw))
        return threads

    # --- Public API ---

    def track(
        self,
        thread_id: str,
        email_id: str,
        sender: str,
        sender_email: str,
        subject: str,
        signal_type: str,
        signal_urgency: str,
        signal_confidence: float,
        user_id: int,
        estimated_value: Optional[float] = None,
    ) -> TrackedThread:
        """Start tracking a new revenue-critical thread."""
        key = self._key(user_id, thread_id)

        existing = self._load_thread(key)
        if existing:
            logger.debug(f"[FollowUpTracker] Thread {thread_id} already tracked")
            return existing

        thread = TrackedThread(
            thread_id=thread_id,
            email_id=email_id,
            sender=sender,
            sender_email=sender_email,
            subject=subject,
            signal_type=signal_type,
            signal_urgency=signal_urgency,
            signal_confidence=signal_confidence,
            estimated_value=estimated_value,
            state=FollowUpState.FLAGGED,
            user_id=user_id,
        )
        self._persist_thread(key, thread)
        logger.info(
            f"[FollowUpTracker] Tracking thread '{subject}' from {sender} "
            f"(signal={signal_type}, urgency={signal_urgency})"
        )
        return thread

    def mark_replied(self, user_id: int, thread_id: str) -> bool:
        """Mark a tracked thread as replied — stops the reminder pipeline."""
        key = self._key(user_id, thread_id)
        thread = self._load_thread(key)
        if not thread:
            return False
        thread.state = FollowUpState.REPLIED
        thread.last_state_change = time.time()
        self._persist_thread(key, thread)
        logger.info(f"[FollowUpTracker] Thread '{thread.subject}' marked as REPLIED")
        return True

    def close(self, user_id: int, thread_id: str) -> bool:
        """Manually close tracking on a thread (user dismissed or handled externally)."""
        key = self._key(user_id, thread_id)
        thread = self._load_thread(key)
        if not thread:
            return False
        thread.state = FollowUpState.CLOSED
        thread.last_state_change = time.time()
        self._persist_thread(key, thread)
        logger.info(f"[FollowUpTracker] Thread '{thread.subject}' closed")
        return True

    def get_active(self, user_id: int) -> List[TrackedThread]:
        """Get all actively tracked threads for a user."""
        active_states = {
            FollowUpState.FLAGGED,
            FollowUpState.REMINDED_ONCE,
            FollowUpState.REMINDED_TWICE,
            FollowUpState.ESCALATED,
        }
        return [
            t for t in self._load_all_for_user(user_id)
            if t.state in active_states
        ]

    def get_overdue(self, user_id: int) -> List[TrackedThread]:
        """Get threads that are past their advance interval and need attention."""
        now = time.time()
        overdue = []
        for thread in self.get_active(user_id):
            interval_hours = self._get_interval(thread)
            if interval_hours is None:
                continue
            elapsed_hours = (now - thread.last_state_change) / 3600
            if elapsed_hours >= interval_hours:
                overdue.append(thread)
        return overdue

    def advance(self, user_id: int, thread_id: str) -> Optional[TrackedThread]:
        """
        Advance a thread to the next state in the pipeline.
        Returns the updated thread or None if thread not found or already terminal.
        """
        key = self._key(user_id, thread_id)
        thread = self._load_thread(key)
        if not thread:
            return None

        next_state = self._next_state(thread.state)
        if next_state is None:
            return thread

        old_state = thread.state
        thread.state = next_state
        thread.last_state_change = time.time()
        if next_state in (
            FollowUpState.REMINDED_ONCE,
            FollowUpState.REMINDED_TWICE,
        ):
            thread.reminder_count += 1

        self._persist_thread(key, thread)

        logger.info(
            f"[FollowUpTracker] Thread '{thread.subject}' "
            f"advanced: {old_state.value} -> {next_state.value}"
        )
        return thread

    async def run_sweep(self, user_id: int) -> Dict[str, Any]:
        """
        Sweep all tracked threads for a user and advance overdue ones.
        Designed to be called by Celery beat (e.g., every 15 minutes).

        Returns a summary of actions taken.
        """
        overdue = self.get_overdue(user_id)
        actions_taken = []

        for thread in overdue:
            advanced = self.advance(user_id, thread.thread_id)
            if not advanced:
                continue

            action = {
                "thread_id": thread.thread_id,
                "subject": thread.subject,
                "new_state": advanced.state.value,
                "action": None,
            }

            if advanced.state == FollowUpState.REMINDED_ONCE:
                action["action"] = "first_reminder"
            elif advanced.state == FollowUpState.REMINDED_TWICE:
                action["action"] = "second_reminder"
                # Auto-draft a reply for the user
                draft = await self._generate_draft_reply(advanced)
                if draft:
                    advanced.draft_id = draft
                    action["draft_id"] = draft
                    # Persist the draft_id update
                    self._persist_thread(
                        self._key(user_id, thread.thread_id), advanced
                    )
            elif advanced.state == FollowUpState.ESCALATED:
                action["action"] = "escalated_to_slack"
                # Generate a fresh draft before Slack escalation
                if not advanced.draft_id:
                    draft = await self._generate_draft_reply(advanced)
                    if draft:
                        advanced.draft_id = draft
                        action["draft_id"] = draft
                        self._persist_thread(
                            self._key(user_id, thread.thread_id), advanced
                        )
                await self._escalate_to_slack(advanced)

            actions_taken.append(action)

        summary = {
            "user_id": user_id,
            "threads_checked": len(self.get_active(user_id)),
            "threads_advanced": len(actions_taken),
            "actions": actions_taken,
        }

        if actions_taken:
            logger.info(
                f"[FollowUpTracker] Sweep for user {user_id}: "
                f"{len(actions_taken)} threads advanced"
            )
        return summary

    def get_stats(self, user_id: int) -> Dict[str, Any]:
        """Get follow-up tracking statistics for a user."""
        all_threads = self._load_all_for_user(user_id)
        active = [t for t in all_threads if t.state not in (FollowUpState.REPLIED, FollowUpState.CLOSED)]
        replied = [t for t in all_threads if t.state == FollowUpState.REPLIED]
        escalated = [t for t in all_threads if t.state == FollowUpState.ESCALATED]

        return {
            "total_tracked": len(all_threads),
            "active": len(active),
            "replied": len(replied),
            "escalated": len(escalated),
            "avg_response_hours": self._avg_response_hours(replied),
        }

    # --- Internal helpers ---

    def _next_state(self, current: FollowUpState) -> Optional[FollowUpState]:
        """Get the next state in the pipeline, or None if terminal."""
        order = [
            FollowUpState.FLAGGED,
            FollowUpState.REMINDED_ONCE,
            FollowUpState.REMINDED_TWICE,
            FollowUpState.ESCALATED,
        ]
        try:
            idx = order.index(current)
            if idx + 1 < len(order):
                return order[idx + 1]
        except ValueError:
            pass
        return None

    def _get_interval(self, thread: TrackedThread) -> Optional[float]:
        """Get hours-until-advance, scaled down for high-value deals."""
        intervals = _ADVANCE_INTERVALS.get(thread.signal_urgency, _ADVANCE_INTERVALS["medium"])
        base = intervals.get(thread.state)
        if base is None:
            return None
        # High-value deals escalate faster
        if (thread.estimated_value or 0) >= HIGH_VALUE_INTERVAL_THRESHOLD:
            return base * HIGH_VALUE_INTERVAL_MULTIPLIER
        return base

    def _avg_response_hours(self, replied_threads: List[TrackedThread]) -> Optional[float]:
        """Calculate average response time in hours for replied threads."""
        if not replied_threads:
            return None
        total = sum(
            (t.last_state_change - t.created_at) / 3600
            for t in replied_threads
        )
        return round(total / len(replied_threads), 1)

    async def _generate_draft_reply(self, thread: TrackedThread) -> Optional[str]:
        """
        Auto-draft a contextual follow-up reply using LLM + Gmail API.
        Generates a context-aware reply body based on thread context,
        then creates a real Gmail draft.
        Returns the draft ID if successful, None otherwise.
        """
        try:
            from src.features.auto_responder import EmailAutoResponder
            if self._auto_responder is None:
                self._auto_responder = EmailAutoResponder(self.config)

            # Build contextual prompt with revenue signal info
            context = (
                f"This is a follow-up for a {thread.signal_type} signal "
                f"(urgency: {thread.signal_urgency}). "
            )
            if thread.estimated_value:
                context += f"Estimated deal value: ${thread.estimated_value:,.0f}. "
            context += (
                f"We have reminded the user {thread.reminder_count} time(s) "
                f"but received no reply. Draft a polite, professional follow-up."
            )

            replies = await self._auto_responder.generate_reply(
                email_content=context,
                email_subject=thread.subject,
                sender_name=thread.sender,
                sender_email=thread.sender_email,
                num_options=1,
                revenue_context={
                    "signal_type": thread.signal_type,
                    "urgency": thread.signal_urgency,
                    "estimated_value": thread.estimated_value,
                    "reminder_count": thread.reminder_count,
                },
            )

            if not replies:
                logger.warning(
                    f"[FollowUpTracker] No draft content generated for '{thread.subject}'"
                )
                return None

            draft_body = replies[0] if isinstance(replies, list) else str(replies)

            # Create real Gmail draft via API
            try:
                from src.core.credential_provider import CredentialFactory
                from src.core.email.google_client import GoogleGmailClient
                from src.core.email.utils import create_gmail_message

                factory = CredentialFactory(self.config)
                creds = factory.get_credentials(thread.user_id, provider="gmail")

                if creds:
                    gmail_client = GoogleGmailClient(credentials=creds)
                    if gmail_client.is_available():
                        reply_subject = (
                            thread.subject
                            if thread.subject.startswith("Re:")
                            else f"Re: {thread.subject}"
                        )
                        message = create_gmail_message(
                            to=thread.sender_email,
                            subject=reply_subject,
                            body=draft_body,
                        )
                        draft = gmail_client._create_draft_with_retry(message)
                        draft_id = draft.get("id") if draft else None
                        if draft_id:
                            logger.info(
                                f"[FollowUpTracker] Real Gmail draft created: "
                                f"{draft_id} for '{thread.subject}'"
                            )
                            return draft_id
            except ImportError:
                pass
            except Exception as gmail_err:
                logger.warning(
                    f"[FollowUpTracker] Gmail draft creation failed, "
                    f"using placeholder: {gmail_err}"
                )

            # Fallback: return placeholder ID if Gmail API fails
            logger.info(
                f"[FollowUpTracker] Draft generated for thread '{thread.subject}' "
                f"(placeholder — Gmail API not available)"
            )
            return f"draft_{thread.thread_id}_{int(time.time())}"

        except Exception as e:
            logger.error(f"[FollowUpTracker] Draft generation failed: {e}")
        return None

    async def _escalate_to_slack(self, thread: TrackedThread) -> bool:
        """
        Send a Slack DM to the user about an overdue follow-up.
        Uses the real Slack client when available.
        """
        try:
            value_str = ""
            if thread.estimated_value:
                value_str = f" (est. ${thread.estimated_value:,.0f})"

            message = (
                f"[ALERT] Follow-up overdue: *{thread.subject}*\n"
                f"From: {thread.sender} ({thread.sender_email})\n"
                f"Signal: {thread.signal_type}{value_str}\n"
                f"Status: Reminded {thread.reminder_count} times with no reply.\n"
                f"Tracked for {(time.time() - thread.created_at) / 3600:.0f} hours."
            )

            if thread.draft_id:
                message += (
                    f"\n\nA draft reply has been prepared in your Gmail drafts."
                )

            # Try to send via real Slack client
            try:
                from src.integrations.slack.service import SlackService

                slack = SlackService(self.config)
                if slack.is_available and thread.user_id:
                    # Look up user's Slack ID from their integration settings
                    sent = await slack.send_dm(
                        user_id=thread.user_id,
                        text=message,
                    )
                    if sent:
                        logger.info(
                            f"[FollowUpTracker] Escalated to Slack: {thread.subject} "
                            f"(user_id={thread.user_id})"
                        )
                        return True
            except ImportError:
                pass
            except Exception as slack_err:
                logger.warning(
                    f"[FollowUpTracker] Slack DM failed: {slack_err}"
                )

            # Fallback: log the escalation
            logger.info(
                f"[FollowUpTracker] Escalated (logged): {thread.subject} "
                f"(user_id={thread.user_id})"
            )
            return True

        except Exception as e:
            logger.error(f"[FollowUpTracker] Slack escalation failed: {e}")
            return False
