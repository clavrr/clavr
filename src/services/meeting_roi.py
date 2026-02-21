"""
Meeting ROI Scoring

Scores calendar events by estimated revenue impact so the user can
distinguish between high-value client calls and low-value status meetings.
Supports per-event scoring, day-level summaries, and auto-decline
suggestions for low-ROI meetings that conflict with deep work.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


class MeetingType(str, Enum):
    CLIENT_CALL = "client_call"
    SALES = "sales"
    STRATEGY = "strategy"
    INTERNAL_STANDUP = "internal_standup"
    INTERNAL_OTHER = "internal_other"
    ONE_ON_ONE = "one_on_one"
    EXTERNAL_OTHER = "external_other"
    UNKNOWN = "unknown"


# Base ROI score by meeting type
_TYPE_BASE_SCORES: Dict[MeetingType, float] = {
    MeetingType.CLIENT_CALL: 75.0,
    MeetingType.SALES: 90.0,
    MeetingType.STRATEGY: 60.0,
    MeetingType.INTERNAL_STANDUP: 15.0,
    MeetingType.INTERNAL_OTHER: 25.0,
    MeetingType.ONE_ON_ONE: 35.0,
    MeetingType.EXTERNAL_OTHER: 50.0,
    MeetingType.UNKNOWN: 30.0,
}


@dataclass
class MeetingROI:
    """ROI score for a single calendar event."""
    event_title: str
    event_id: str
    roi_score: float  # 0-100
    meeting_type: MeetingType
    reasoning: str
    attendee_deal_value: float = 0.0
    suggest_decline: bool = False
    decline_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_title": self.event_title,
            "event_id": self.event_id,
            "roi_score": round(self.roi_score, 1),
            "meeting_type": self.meeting_type.value,
            "reasoning": self.reasoning,
            "attendee_deal_value": self.attendee_deal_value,
            "suggest_decline": self.suggest_decline,
            "decline_reason": self.decline_reason,
        }


@dataclass
class DayROISummary:
    """ROI summary for an entire day of meetings."""
    date: str
    total_meetings: int
    high_value_count: int  # ROI >= 60
    low_value_count: int   # ROI < 30
    total_meeting_hours: float
    high_value_hours: float
    low_value_hours: float
    roi_ratio: float  # high_value_hours / total_meeting_hours
    meetings: List[MeetingROI] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "total_meetings": self.total_meetings,
            "high_value_count": self.high_value_count,
            "low_value_count": self.low_value_count,
            "total_meeting_hours": round(self.total_meeting_hours, 1),
            "high_value_hours": round(self.high_value_hours, 1),
            "low_value_hours": round(self.low_value_hours, 1),
            "roi_ratio": round(self.roi_ratio, 2),
            "meetings": [m.to_dict() for m in self.meetings],
        }


# Keywords for meeting type classification
_TYPE_KEYWORDS: Dict[MeetingType, List[str]] = {
    MeetingType.CLIENT_CALL: [
        "client", "customer", "account review", "qbr", "quarterly",
        "check-in", "check in",
    ],
    MeetingType.SALES: [
        "demo", "sales", "pitch", "prospect", "discovery",
        "pricing", "proposal", "closing", "pipeline",
    ],
    MeetingType.STRATEGY: [
        "strategy", "planning", "roadmap", "vision", "offsite",
        "brainstorm", "kickoff",
    ],
    MeetingType.INTERNAL_STANDUP: [
        "standup", "stand-up", "daily sync", "scrum", "sprint",
        "retro", "retrospective",
    ],
    MeetingType.ONE_ON_ONE: [
        "1:1", "1-1", "one on one", "1 on 1", "catch up",
    ],
}

# Revenue keywords that boost ROI score
_REVENUE_KEYWORDS = [
    "contract", "revenue", "deal", "renewal", "budget", "pricing",
    "invoice", "payment", "expansion", "upsell", "partnership",
]


class MeetingROIService:
    """
    Scores calendar events by estimated revenue impact.
    """

    def __init__(self, config: Optional[Config] = None, db_session=None):
        self.config = config
        self.db = db_session

    async def score_event(
        self, event: Dict[str, Any], user_id: int
    ) -> MeetingROI:
        """
        Score a single calendar event for revenue impact.
        
        Scoring factors:
        1. Meeting type classification (base score)
        2. Attendee deal association (bonus if attendee is linked to a deal)
        3. Revenue keyword presence in title/description
        4. Meeting duration penalty (long low-value meetings score lower)
        """
        title = event.get("summary", event.get("title", "")).lower()
        description = event.get("description", "").lower()
        event_id = event.get("id", "unknown")
        attendees = event.get("attendees", [])
        combined_text = f"{title} {description}"

        # 1. Classify meeting type
        meeting_type = self._classify_meeting_type(title, description, attendees, user_id)

        # 2. Start with base score for this type
        score = _TYPE_BASE_SCORES.get(meeting_type, 30.0)

        # 3. Check if any attendee is associated with a deal
        deal_value = await self._attendee_deal_value(attendees, user_id)
        if deal_value > 0:
            score = min(score + 25, 100.0)

        # 4. Revenue keyword bonus
        revenue_hits = [kw for kw in _REVENUE_KEYWORDS if kw in combined_text]
        if revenue_hits:
            score = min(score + len(revenue_hits) * 5, 100.0)

        # 5. Duration penalty for low-value long meetings
        duration_hours = self._event_duration_hours(event)
        if score < 40 and duration_hours > 1.0:
            score = max(score - 10, 0.0)

        # Build reasoning
        reasons = [f"Type: {meeting_type.value} (base {_TYPE_BASE_SCORES.get(meeting_type, 30):.0f})"]
        if deal_value > 0:
            reasons.append(f"Attendee linked to deal (${deal_value:,.0f})")
        if revenue_hits:
            reasons.append(f"Revenue keywords: {', '.join(revenue_hits[:3])}")

        return MeetingROI(
            event_title=event.get("summary", event.get("title", "Unknown")),
            event_id=event_id,
            roi_score=score,
            meeting_type=meeting_type,
            reasoning="; ".join(reasons),
            attendee_deal_value=deal_value,
        )

    async def score_day(
        self, user_id: int, date: Optional[str] = None
    ) -> DayROISummary:
        """
        Score all meetings for a given day and return a summary with
        high-value vs low-value time allocation.
        """
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        events = await self._get_events_for_day(user_id, date)
        scored = []

        for event in events:
            roi = await self.score_event(event, user_id)
            scored.append(roi)

        high_value = [m for m in scored if m.roi_score >= 60]
        low_value = [m for m in scored if m.roi_score < 30]

        total_hours = sum(
            self._event_duration_hours(e) for e in events
        )
        hv_hours = sum(
            self._event_duration_hours(events[i])
            for i, m in enumerate(scored)
            if m.roi_score >= 60 and i < len(events)
        )
        lv_hours = sum(
            self._event_duration_hours(events[i])
            for i, m in enumerate(scored)
            if m.roi_score < 30 and i < len(events)
        )

        return DayROISummary(
            date=date,
            total_meetings=len(scored),
            high_value_count=len(high_value),
            low_value_count=len(low_value),
            total_meeting_hours=total_hours,
            high_value_hours=hv_hours,
            low_value_hours=lv_hours,
            roi_ratio=hv_hours / total_hours if total_hours > 0 else 0.0,
            meetings=scored,
        )

    async def suggest_declines(
        self, user_id: int, date: Optional[str] = None
    ) -> List[MeetingROI]:
        """
        Find low-ROI meetings that could be declined or shortened,
        especially if they conflict with deep work blocks.
        """
        day_summary = await self.score_day(user_id, date)

        suggestions = []
        for meeting in day_summary.meetings:
            if meeting.roi_score < 25:
                meeting.suggest_decline = True
                meeting.decline_reason = (
                    f"Low ROI ({meeting.roi_score:.0f}/100). "
                    f"Consider declining or requesting async update."
                )
                suggestions.append(meeting)

        return suggestions

    def _classify_meeting_type(
        self,
        title: str,
        description: str,
        attendees: List[Dict[str, Any]],
        user_id: int,
    ) -> MeetingType:
        """Classify a meeting by its type based on title, description, and attendees."""
        combined = f"{title} {description}"

        # Check keywords for each type
        for meeting_type, keywords in _TYPE_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                return meeting_type

        # Check attendee count and domains for internal vs external
        if len(attendees) <= 2:
            return MeetingType.ONE_ON_ONE

        # If we can detect the user's domain, classify internal vs external
        user = None
        if self.db:
            from src.database.models import User
            user = self.db.query(User).filter(User.id == user_id).first()

        if user and "@" in user.email:
            user_domain = user.email.split("@")[1].lower()
            external = [
                a for a in attendees
                if "@" in a.get("email", "")
                and a.get("email", "").split("@")[1].lower() != user_domain
            ]
            if external:
                return MeetingType.EXTERNAL_OTHER
            return MeetingType.INTERNAL_OTHER

        return MeetingType.UNKNOWN

    async def _attendee_deal_value(
        self, attendees: List[Dict[str, Any]], user_id: int
    ) -> float:
        """
        Check if any attendee is associated with an active deal.
        Returns the highest deal value found.
        """
        if not attendees:
            return 0.0

        try:
            from src.services.indexing.graph.manager import KnowledgeGraphManager

            kg = KnowledgeGraphManager()
            max_value = 0.0

            for attendee in attendees:
                email = attendee.get("email", "")
                if not email:
                    continue

                domain = email.split("@")[1].lower() if "@" in email else ""
                if not domain:
                    continue

                query = """
                    FOR d IN entities
                        FILTER d.type == 'Deal'
                        AND d.user_id == @user_id
                        AND CONTAINS(LOWER(d.company), LOWER(@domain))
                        AND d.stage NOT IN ['closed_won', 'closed_lost']
                        RETURN d.value
                """
                results = await asyncio.to_thread(
                    kg.execute_query,
                    query,
                    {"user_id": str(user_id), "domain": domain.split(".")[0]},
                )

                for val in (results or []):
                    if val and float(val) > max_value:
                        max_value = float(val)

            return max_value
        except Exception as e:
            logger.warning(f"[MeetingROI] Deal value lookup failed: {e}")
            return 0.0

    async def _get_events_for_day(
        self, user_id: int, date: str
    ) -> List[Dict[str, Any]]:
        """Fetch calendar events for a specific day."""
        try:
            from src.integrations.google_calendar.service import CalendarService
            from src.core.credential_provider import CredentialFactory

            creds = CredentialFactory.get_credentials(user_id, "google")
            if not creds:
                return []

            calendar = CalendarService(creds)
            day_start = f"{date}T00:00:00Z"
            day_end = f"{date}T23:59:59Z"

            events = await asyncio.to_thread(
                calendar.get_events,
                time_min=day_start,
                time_max=day_end,
            )
            return events or []
        except Exception as e:
            logger.warning(f"[MeetingROI] Calendar fetch failed: {e}")
            return []

    def _event_duration_hours(self, event: Dict[str, Any]) -> float:
        """Calculate event duration in hours."""
        try:
            start = event.get("start", {}).get("dateTime", "")
            end = event.get("end", {}).get("dateTime", "")
            if not start or not end:
                return 0.5  # Default 30 min
            
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return max(0.0, (end_dt - start_dt).total_seconds() / 3600)
        except (ValueError, TypeError):
            return 0.5
