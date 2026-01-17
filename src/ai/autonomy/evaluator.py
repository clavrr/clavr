"""
Context Evaluator

Analyzes the user's current context (time, location, recent events) 
to propose proactive actions.
"""
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from ...utils.logger import setup_logger

from .autonomy_config import (
    MORNING_BRIEF_HOURS,
    EOD_SUMMARY_HOURS,
    MEETING_PREP_MINUTES,
    BRIEFING_WEEKDAYS,
)

logger = setup_logger(__name__)

class ContextEvaluator:
    """
    Evaluates the 'World State' to determine if the agent should act.
    """
    
    def __init__(self, 
                 config: Dict[str, Any], 
                 calendar_service: Optional[Any] = None,
                 semantic_memory: Optional[Any] = None):
        self.config = config
        self.calendar = calendar_service
        self.memory = semantic_memory
        
    async def evaluate_context(self, user_id: int) -> Dict[str, Any]:
        """
        Check current context and return a proposed plan/action.
        """
        # Robust timezone handling
        try:
            from src.utils.config import get_timezone, load_config
            import pytz
            
            # Use cached config or load fresh
            if not hasattr(self, '_cached_config'):
                self._cached_config = load_config()
                
            tz_name = get_timezone(self._cached_config)
            user_tz = pytz.timezone(tz_name)
            now_local = datetime.now(user_tz)
            logger.debug(f"[ContextEvaluator] Using timezone: {tz_name}")
        except Exception as e:
            logger.debug(f"[ContextEvaluator] Timezone fetch failed, using UTC: {e}")
            now_local = datetime.now(timezone.utc)
        
        hour_local = now_local.hour
        weekday = now_local.weekday()
        
        # 0. Check User Preferences (Async Semantic Memory)
        if self.memory:
            try:
                # Check for "Do Not Disturb"
                facts = await self.memory.get_facts(user_id, category="preference", limit=20)
                for fact in facts:
                    content = fact['content'].lower()
                    # Heuristic check
                    if "no notifications" in content and "after 6pm" in content and hour_local >= 18:
                         return {
                            "action_needed": False,
                            "reason": "User preference: No notifications after 6pm",
                            "proposed_action": None,
                            "priority": "none"
                        }
            except Exception as e:
                logger.warning(f"[Evaluator] Preference check failed: {e}")

        # 1. Calendar Triggers (High Priority: Upcoming Meetings)
        if self.calendar:
            try:
                # RUN SYNC code in thread to avoid blocking loop
                # We need to fetch enough events to find immediate ones.
                upcoming = await asyncio.to_thread(
                    self.calendar.get_upcoming_events, 
                    limit=5
                )
                
                for event in upcoming:
                    start_str = event.get('start', {}).get('dateTime')
                    if not start_str: continue
                    
                    # Parse start time (Robust Formatting)
                    # We expect ISO8601. We normalize to UTC aware.
                    try:
                        if 'Z' in start_str:
                             start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                        else:
                             start_dt = datetime.fromisoformat(start_str)
                             if start_dt.tzinfo is None:
                                 start_dt = start_dt.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue

                    # Current time must be comparable (UTC)
                    now_check = datetime.now(timezone.utc)
                    
                    # Calculate minutes until start
                    # (Start - Now). If negative, it already started.
                    delta = start_dt - now_check
                    delta_minutes = delta.total_seconds() / 60
                    
                    # Logic: If meeting starts within POSITIVE prep window (e.g. 0 to 15 mins)
                    if 0 < delta_minutes <= MEETING_PREP_MINUTES:
                         # State Tracking: Prevent double-briefing
                         # We check if we've already generated a brief for this event_id
                         already_briefed = await self._check_briefing_state(user_id, event.get("id"))
                         if already_briefed:
                             continue

                         return {
                            "action_needed": True,
                            "reason": f"Meeting '{event.get('summary', 'Unknown')}' starts in {int(delta_minutes)}m",
                            "proposed_action": "prepare_meeting_brief",
                            "priority": "high",
                            "context_data": {"event_id": event.get("id")}
                        }
            except Exception as e:
                logger.warning(f"[Evaluator] Calendar check failed: {e}")

        # 2. Morning Briefing Rule (Medium Priority)
        morning_start, morning_end = MORNING_BRIEF_HOURS
        if weekday in BRIEFING_WEEKDAYS and morning_start <= hour_local < morning_end:
            # We rely on an external "Frequency Cap" (Redis/DB) to ensure this doesn't fire every minute.
            # The worker calling this (proactive_think) typically runs every X minutes.
            return {
                "action_needed": True,
                "reason": "Weekday Morning",
                "proposed_action": "generate_morning_briefing",
                "priority": "medium"
            }
            
        # 3. End of Day Summary Rule (Low Priority)
        eod_start, eod_end = EOD_SUMMARY_HOURS
        if weekday in BRIEFING_WEEKDAYS and eod_start <= hour_local < eod_end:
            return {
                "action_needed": True,
                "reason": "End of Work Day",
                "proposed_action": "generate_daily_summary",
                "priority": "low"
            }
            
        return {
            "action_needed": False,
            "reason": "No context trigger matched",
            "proposed_action": None,
            "priority": "none"
        }

    async def _check_briefing_state(self, user_id: int, event_id: str) -> bool:
        """
        Check if an event has already been briefed for the user.
        Uses SemanticMemory to store/retrieve briefing history.
        """
        if not self.memory or not event_id:
            return False
            
        try:
            # Check for a specific fact about this event
            query = f"Already prepared brief for event {event_id}"
            facts = await self.memory.search_facts(query, user_id, limit=1)
            
            for fact in facts:
                if event_id in fact.get('content', '') and fact.get('confidence', 0) > 0.8:
                    logger.debug(f"[Evaluator] Event {event_id} already briefed.")
                    return True
            return False
        except Exception as e:
            logger.warning(f"[Evaluator] State check failed: {e}")
            return False

    async def mark_event_as_briefed(self, user_id: int, event_id: str):
        """
        Record that an event brief was successfully generated.
        """
        if not self.memory or not event_id:
            return
            
        try:
            content = f"Already prepared brief for event {event_id}"
            await self.memory.learn_fact(
                user_id=user_id,
                content=content,
                category="internal_state",
                source="context_evaluator",
                validate=True
            )
            logger.info(f"[Evaluator] Event {event_id} marked as briefed.")
        except Exception as e:
            logger.error(f"[Evaluator] Failed to mark event as briefed: {e}")
