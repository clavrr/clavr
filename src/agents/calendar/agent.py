"""
Calendar Agent

Responsible for handling all calendar-related queries:
- Scheduling events
- Listing events (agenda)
- Rescheduling
- Availability checks
"""
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import (
    TOOL_ALIASES_CALENDAR,
    INTENT_KEYWORDS,
    ERROR_NO_EVENT_TITLE,
    ERROR_AMBIGUOUS_UPDATE
)
from .schemas import (
    SCHEDULE_SCHEMA, LIST_SCHEMA, UPDATE_SCHEMA, AVAILABILITY_SCHEMA
)
from .constants import (
    SYSTEM_EMAIL_BLOCKLIST, TITLE_FALLBACK_PATTERNS, 
    EMAIL_PATTERN, DURATION_IN_ENDTIME_PATTERN, AQL_RESOLVE_PERSON
)

logger = setup_logger(__name__)

class CalendarAgent(BaseAgent):
    """
    Specialized agent for Calendar operations (Google Calendar).
    """
    
    # Inherits __init__ from BaseAgent
        
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute calendar-related queries with memory awareness.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        # 1. Enrich Query with Memory Context
        if self.memory_orchestrator:
             pass 
             # Optimization: We rely on _extract_params to retrieve memory context (via task_type='planning')
             # to avoid duplicating context in the query string and bloating the prompt.


        query_lower = query.lower()
        
        # Routing logic - prioritize schedule and update over list
        if any(w in query_lower for w in INTENT_KEYWORDS['calendar']['schedule']):
            # Special check: if it contains "list" or "show", it might still be a list request
            # e.g., "show my schedule" vs "schedule a meeting"
            if "schedule" in query_lower and any(w in query_lower for w in ["show", "list", "my"]):
                return await self._handle_list(query, context)
            return await self._handle_schedule(query, context)
            
        elif any(w in query_lower for w in INTENT_KEYWORDS['calendar']['update']):
            return await self._handle_update(query, context)
            
        elif any(w in query_lower for w in INTENT_KEYWORDS['calendar']['list']):
            return await self._handle_list(query, context)
            
        elif any(w in query_lower for w in ["free", "busy", "available", "gap", "open"]):
            return await self._handle_availability(query, context)
        else:
            # Default to agenda/list
            return await self._handle_list(query, context)



    async def _resolve_attendee_email(self, name: str, user_id: int) -> Optional[str]:
        """Resolve a name to an email address using domain context."""
        if "@" in name:
            # Block list for system emails
            block_list = SYSTEM_EMAIL_BLOCKLIST
            name_lower = name.lower()
            if any(block in name_lower for block in block_list):
                logger.warning(f"[{self.name}] Rejecting system email: {name}")
                return None
            return name
            
        if not self.domain_context:
            logger.warning(f"[{self.name}] No domain context for email resolution")
            return None

        # 1. Try Graph Search (Primary) - Look for Person node
        if self.domain_context.graph_manager:
            try:
                # Search for Person with matching name (case-insensitive fuzzy match)
                with LatencyMonitor(f"[{self.name}] Graph Resolution ({name})"):
                    # execute_query returns List[Dict]
                    results = await self.domain_context.graph_manager.execute_query(
                        query=AQL_RESOLVE_PERSON, 
                        params={"name": name}
                    )
                
                if results and len(results) > 0:
                    person = results[0]
                    # Check for email property
                    email = person.get('email')
                    if email:
                        # Double check if the resolved email is a system email
                        if any(block in email.lower() for block in SYSTEM_EMAIL_BLOCKLIST):
                             logger.warning(f"[{self.name}] Graph resolved to system email, rejecting: {email}")
                             return None
                             
                        logger.info(f"[{self.name}] Graph resolved '{name}' to '{email}' (Person.email)")
                        return email
                        
            except Exception as e:
                logger.warning(f"[{self.name}] Graph resolution failed for {name}: {e}")

        # 2. Fallback to Vector Search
        if not self.domain_context.vector_store:
             return None

        try:
            query = f"email address for {name}"
            with LatencyMonitor(f"[{self.name}] Email Resolution ({name})"):
                results = await self.domain_context.vector_store.asearch(
                    query=query,
                    filters={"user_id": user_id},
                    k=3,
                    min_confidence=0.75
                )
            
            for res in results:
                content = res.get('content', '')
                matches = re.findall(EMAIL_PATTERN, content)
                if matches:
                    logger.info(f"[{self.name}] Resolved '{name}' to '{matches[0]}'")
                    return matches[0]
                    
            return None
            
        except Exception as e:
            logger.error(f"[{self.name}] Failed to resolve email for {name}: {e}")
            return None

    async def _handle_schedule(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle event scheduling with LLM extraction"""
        user_id = context.get('user_id') if context else None
        
        try:
            params = await self._extract_params(
                query, 
                SCHEDULE_SCHEMA, 
                user_id=user_id,
                task_type="planning"
            )
            logger.info(f"[{self.name}] [DEBUG] Extracted params: {params}")
        except Exception as e:
            logger.error(f"[{self.name}] Parameter extraction failed for schedule: {e}")
            return "I had trouble understanding the details for the meeting. Could you please try again?"

        # Resolve attendees
        attendees = params.get("attendees")
        if attendees and isinstance(attendees, list) and user_id:
            resolved_attendees = []
            for attendee in attendees:
                if isinstance(attendee, str):
                    # Always try to resolve/validate, even if it looks like an email.
                    # This ensures system emails (notifications@, noreply@) are filtered out via blocklist.
                    resolved = await self._resolve_attendee_email(attendee, user_id)
                    if resolved:
                        resolved_attendees.append(resolved)
                    else:
                        logger.warning(f"[{self.name}] Dropping invalid/unresolved attendee: {attendee}")
            
            # Always update the attendees list with the resolved/validated version
            # This handles both filtering (dropping invalid) and resolution (name -> email)
            if resolved_attendees != attendees:
                 logger.info(f"[{self.name}] Resolved/Validated attendees: {attendees} -> {resolved_attendees}")
                 params["attendees"] = resolved_attendees

        # FIX: The LLM often puts duration (e.g., "1 hour") into end_time because of the schema description.
        # We must detect this and move it to duration_minutes, otherwise service layer fails with date parsing error.
        raw_end = params.get("end_time")
        if raw_end and isinstance(raw_end, str):
            # Check if it looks like a duration ("1 hour", "30 mins") rather than a time ("13:00")
            # Simple heuristic: presence of duration words and absence of colon (unless it's like 1:30h)
            import re
            duration_match = re.search(DURATION_IN_ENDTIME_PATTERN, raw_end, re.IGNORECASE)
            is_iso = 'T' in raw_end or ':' in raw_end
            
            if duration_match and not is_iso:
                logger.info(f"[{self.name}] Detected duration in end_time: '{raw_end}'. Moving to duration_minutes.")
                # We let the Tool's duration parser handle the specific string "1 hour" via kwargs if we pass it? 
                # Or better, we parse it here.
                
                minutes = 0
                # Parse hours
                h_match = re.search(r'(\d+)\s*(?:h|hr|hour)', raw_end, re.IGNORECASE)
                if h_match:
                    minutes += int(h_match.group(1)) * 60
                
                # Parse minutes
                m_match = re.search(r'(\d+)\s*(?:m|min)', raw_end, re.IGNORECASE)
                if m_match:
                    minutes += int(m_match.group(1))
                
                if minutes > 0:
                    params['duration_minutes'] = minutes
                    params['end_time'] = None # Clear invalid end_time
        
        # Fallback title extraction if LLM didn't extract summary or returned empty
        summary_value = params.get("summary")
        logger.info(f"[{self.name}] [DEBUG] summary_value = {repr(summary_value)}")
        
        # Check for None, empty string, or whitespace-only
        if not summary_value or (isinstance(summary_value, str) and not summary_value.strip()):
            logger.warning(f"[{self.name}] LLM did not extract title (got: {repr(summary_value)}), attempting fallback extraction from query: {query}")
            import re
            # Try to extract title from common patterns like "schedule X meeting", "book a X session"
            for pattern in TITLE_FALLBACK_PATTERNS:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    extracted_title = match.group(1).strip()
                    if extracted_title and len(extracted_title) < 100:
                        params["summary"] = extracted_title.title()  # e.g., "therapy" -> "Therapy"
                        logger.info(f"[{self.name}] Fallback extracted title: {params['summary']}")
                        break
            
            # Ultimate fallback - use the query text before time references
            if not params.get("summary") or (isinstance(params.get("summary"), str) and not params.get("summary").strip()):
                # Remove time-related phrases and use what's left
                title_candidate = re.sub(r'\b(?:tomorrow|today|at\s+\d+\s*(?:am|pm)?|for\s+\d+\s*(?:hour|minute|min)s?)\b', '', query, flags=re.IGNORECASE)
                title_candidate = re.sub(r'\b(?:schedule|book|create|set up|add|please|can you)\b', '', title_candidate, flags=re.IGNORECASE)
                title_candidate = title_candidate.strip()
                if title_candidate and len(title_candidate) > 3:
                    params["summary"] = title_candidate.title()
                    logger.info(f"[{self.name}] Ultimate fallback title: {params['summary']}")
        
        # Final validation - require non-empty summary
        final_summary = params.get("summary")
        if not final_summary or (isinstance(final_summary, str) and not final_summary.strip()):
            logger.error(f"[{self.name}] Could not extract event title from query: {query}")
            return ERROR_NO_EVENT_TITLE
            
        tool_input = {
            "action": "create_event",
            "title": params["summary"],
            "start_time": params.get("start_time"),
            "end_time": params.get("end_time"),
            "attendees": params.get("attendees"),
            "location": params.get("location"),
            "description": params.get("description"),
            "timezone_reference": params.get("timezone_reference"),  # For cross-timezone scheduling
            "check_conflicts": params.get("check_conflicts") if params.get("check_conflicts") is not None else True  # Hard default
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_CALENDAR, tool_input, "scheduling event"
        )

    async def _handle_list(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle event listing with robust fallback for param extraction failures."""
        user_id = context.get('user_id') if context else None
        
        try:
            params = await self._extract_params(
                query, 
                LIST_SCHEMA, 
                user_id=user_id,
                task_type="planning"
            )
            logger.info(f"[{self.name}] Extracted params for list: {params}")
        except Exception as e:
            # Fallback: default to today's events if param extraction fails
            logger.warning(f"[{self.name}] Param extraction failed ({e}), using defaults for 'today'")
            params = {"days_ahead": 1}  # Default: show today's events
        
        # Handle past date queries
        if params.get("looking_at_past"):
            tool_input = {
                "action": "list", 
                "query": query,
                "start_date": params.get("start_time"),
                "end_date": params.get("end_time"),
                "days_ahead": 1  # When we have explicit dates, set days_ahead to 1
            }
        else:
            tool_input = {
                "action": "list", 
                "query": query,
                "days_ahead": params.get("days_ahead") or 1,  # Default to 1 day
                "start_date": params.get("start_time"),
                "end_date": params.get("end_time")
            }
        
        logger.info(f"[{self.name}] Calling CalendarTool with: {self._filter_none_values(tool_input)}")
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_CALENDAR, tool_input, "listing calendar events"
        )

    async def _handle_update(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Handle event updates (reschedule/move/edit).
        Strategy: Search first to get ID, then update.
        """
        user_id = context.get('user_id') if context else None
        
        params = await self._extract_params(
            query, 
            UPDATE_SCHEMA, 
            user_id=user_id,
            task_type="planning"
        )
        
        search_q = params.get("search_criteria")
        if not search_q:
            return ERROR_AMBIGUOUS_UPDATE.format(item_type="event")

        # 2. Find the event
        logger.info(f"[{self.name}] Searching for event to update: '{search_q}'")
        search_input = {
            "action": "list",
            "query": search_q,
            "days_ahead": 30  # Look ahead to find the event
        }
        
        # Delegate search-and-update to the Tool itself
        tool_input = {
            "action": "update_event",
            "query": search_q,
            "start_time": params.get("new_start_time"),
            "title": params.get("new_title")
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_CALENDAR, tool_input, "updating event"
        )

    async def _handle_availability(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle availability queries (Am I free?)"""
        user_id = context.get('user_id') if context else None
        
        params = await self._extract_params(
            query, 
            AVAILABILITY_SCHEMA, 
            user_id=user_id,
            task_type="planning"
        )
        # We rely on list logic for now as specialized tool actions 'find_free' are internal to service
        # but not fully exposed in 'list/search' actions of the tool.
        # Mapping to list allows LLM to see the gap.
        
        tool_input = {
            "action": "list", 
            "query": query,
            "days_ahead": 1,
            "start_date": params.get("start_time")
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_CALENDAR, tool_input, "checking availability"
        )
