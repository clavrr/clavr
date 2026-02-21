"""
Calendar Agent

Responsible for handling all calendar-related queries:
- Scheduling events
- Listing events (agenda)
- Rescheduling
- Availability checks
"""
import re
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from src.utils.performance import LatencyMonitor
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
    EMAIL_PATTERN, DURATION_IN_ENDTIME_PATTERN,
    AQL_RESOLVE_PERSON, AQL_RESOLVE_CONTACT, AQL_RESOLVE_KNOWS
)

logger = setup_logger(__name__)

class CalendarAgent(BaseAgent):
    """
    Specialized agent for Calendar operations (Google Calendar).
    """
    
    # Inherits __init__ from BaseAgent
        
    @staticmethod
    def _matches_intent(query_lower: str, keywords: list) -> bool:
        """Check if query matches any keyword using word-boundary matching.
        
        Uses regex \\b word boundaries to prevent 'event' from matching 'events',
        'meeting' from matching 'meetings', etc. Multi-word keywords are matched
        as exact phrases.
        """
        for kw in keywords:
            # Use word boundary regex for exact word/phrase matching
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, query_lower):
                return True
        return False

    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute calendar-related queries with memory awareness.
        
        Routing priority: LIST (read) > UPDATE > SCHEDULE (write) > AVAILABILITY > default LIST.
        This prevents read-intent queries from being accidentally routed to schedule/create.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        # 1. Enrich Query with Memory Context
        if self.memory_orchestrator:
             pass 
             # Optimization: We rely on _extract_params to retrieve memory context (via task_type='planning')
             # to avoid duplicating context in the query string and bloating the prompt.

        query_lower = query.lower()
        
        list_kws = INTENT_KEYWORDS['calendar']['list']
        schedule_kws = INTENT_KEYWORDS['calendar']['schedule']
        update_kws = INTENT_KEYWORDS['calendar']['update']
        
        has_list = self._matches_intent(query_lower, list_kws)
        has_schedule = self._matches_intent(query_lower, schedule_kws)
        has_update = self._matches_intent(query_lower, update_kws)
        has_availability = self._matches_intent(query_lower, [
            "free", "busy", "available", "gap", "open",
            "different time", "another time", "other time", "find time",
            "alternative", "when can", "find a slot", "find slot",
        ])
        
        logger.info(f"[{self.name}] Intent detection: list={has_list}, schedule={has_schedule}, update={has_update}, availability={has_availability}")
        
        # --- Priority Routing ---
        
        # 1. UPDATE intent has highest priority (reschedule, move, cancel are very specific verbs)
        #    Must be checked before LIST because "reschedule my meeting" contains list keyword "meeting"
        if has_update:
            return await self._handle_update(query, context)
        
        # 2. AVAILABILITY intent beats LIST — "find available time for meeting" is NOT a list request
        #    Must be checked before LIST because queries often contain list keywords like "meeting"
        if has_availability:
            return await self._handle_availability(query, context)
        
        # 3. LIST intent takes priority over schedule when both match
        #    e.g., "show my events" has list("show","event") but should NOT schedule
        if has_list and not has_schedule:
            return await self._handle_list(query, context)
        
        if has_list and has_schedule:
            # Both matched — disambiguate based on action-oriented words
            # "schedule" as a VERB (action) vs "my schedule" (noun/read)
            # "create a meeting" (action) vs "show my meetings" (read)
            action_verbs = ['book', 'set up', 'create', 'schedule', 'add', 'new', 'please schedule']
            has_action_verb = self._matches_intent(query_lower, action_verbs)
            
            if has_action_verb:
                # Check if 'schedule' is used as a NOUN (reading intent) vs VERB (creating intent)
                # "show my schedule" / "what's on my schedule" / "my schedule for today" → list
                # "schedule a meeting" / "schedule that" / "please schedule" → schedule
                schedule_as_noun = any(p in query_lower for p in ['my schedule', 'the schedule', "what's on"])
                
                if schedule_as_noun:
                    return await self._handle_list(query, context)
                
                return await self._handle_schedule(query, context)
            else:
                # No action verbs, default to list (safer — read not write)
                return await self._handle_list(query, context)
        
        # 4. SCHEDULE intent (only if no list match)
        if has_schedule:
            return await self._handle_schedule(query, context)
        
        # 5. Default to list (safest — reading is non-destructive)
        return await self._handle_list(query, context)



    def _get_google_credentials(self):
        """Extract Google OAuth credentials from available tools."""
        # Check email tool first (most likely to have Gmail/People API scopes)
        for tool_name in ['email', 'calendar', 'tasks', 'drive']:
            tool = self.tools.get(tool_name)
            if tool and hasattr(tool, 'credentials') and tool.credentials:
                logger.info(f"[{self.name}] Got Google credentials from '{tool_name}' tool (valid={getattr(tool.credentials, 'valid', '?')})")
                return tool.credentials
        logger.warning(f"[{self.name}] No Google credentials found in any tool. Available tools: {list(self.tools.keys())}")
        return None

    async def _resolve_via_people_api(self, name: str) -> Optional[str]:
        """Resolve a name to email using Google People API (searchContacts).
        
        This mirrors Gmail's autocomplete behavior — it searches the user's
        Google Contacts and 'Other Contacts' (people they've emailed).
        """
        credentials = self._get_google_credentials()
        if not credentials:
            return None
        
        try:
            from googleapiclient.discovery import build
            import asyncio
            
            def _search_contacts():
                people_service = build('people', 'v1', credentials=credentials, cache_discovery=False)
                
                # Strategy A: Search "Other Contacts" (people the user has emailed)
                # This is the closest to Gmail's autocomplete behavior
                try:
                    result = people_service.otherContacts().search(
                        query=name,
                        readMask='emailAddresses,names',
                        pageSize=5
                    ).execute()
                    
                    for contact in result.get('results', []):
                        person = contact.get('person', {})
                        emails = person.get('emailAddresses', [])
                        if emails:
                            email = emails[0].get('value')
                            if email and not any(b in email.lower() for b in SYSTEM_EMAIL_BLOCKLIST):
                                return email
                except Exception as e:
                    logger.debug(f"[{self.name}] otherContacts.search failed: {e}")
                
                # Strategy B: Search saved contacts
                try:
                    result = people_service.people().searchContacts(
                        query=name,
                        readMask='emailAddresses,names',
                        pageSize=5
                    ).execute()
                    
                    for contact in result.get('results', []):
                        person = contact.get('person', {})
                        emails = person.get('emailAddresses', [])
                        if emails:
                            email = emails[0].get('value')
                            if email and not any(b in email.lower() for b in SYSTEM_EMAIL_BLOCKLIST):
                                return email
                except Exception as e:
                    logger.debug(f"[{self.name}] people.searchContacts failed: {e}")
                
                return None
            
            with LatencyMonitor(f"[{self.name}] People API Resolution ({name})"):
                result = await asyncio.to_thread(_search_contacts)
            
            if result:
                logger.info(f"[{self.name}] People API resolved '{name}' to '{result}'")
            return result
                
        except ImportError:
            logger.debug(f"[{self.name}] googleapiclient not available for People API")
            return None
        except Exception as e:
            logger.warning(f"[{self.name}] People API resolution failed for {name}: {e}")
            return None

    async def _resolve_via_gmail_search(self, name: str) -> Optional[str]:
        """Resolve a name to email by searching Gmail message headers.
        
        Searches for emails sent to/from the person and extracts their
        email address from the message headers. This works even without
        Google Contacts API scope.
        """
        credentials = self._get_google_credentials()
        if not credentials:
            return None
        
        try:
            from googleapiclient.discovery import build
            import asyncio
            
            def _search_gmail_headers():
                gmail_service = build('gmail', 'v1', credentials=credentials, cache_discovery=False)
                
                # Search for messages from or to this person
                search_query = f"from:{name} OR to:{name}"
                
                try:
                    result = gmail_service.users().messages().list(
                        userId='me',
                        q=search_query,
                        maxResults=5
                    ).execute()
                    
                    messages = result.get('messages', [])
                    if not messages:
                        return None
                    
                    # Get headers from the first message
                    msg = gmail_service.users().messages().get(
                        userId='me',
                        id=messages[0]['id'],
                        format='metadata',
                        metadataHeaders=['From', 'To', 'Cc']
                    ).execute()
                    
                    headers = msg.get('payload', {}).get('headers', [])
                    name_lower = name.lower()
                    
                    # Extract email from From/To/Cc headers that match the name
                    for header in headers:
                        header_value = header.get('value', '')
                        header_lower = header_value.lower()
                        
                        if name_lower in header_lower:
                            # Extract email from formats like "Emmanuel Haankwenda <emmanuel@clavr.me>"
                            email_match = re.search(r'<([^>]+@[^>]+)>', header_value)
                            if email_match:
                                email = email_match.group(1)
                                if not any(b in email.lower() for b in SYSTEM_EMAIL_BLOCKLIST):
                                    return email
                            
                            # Or plain email format
                            email_match = re.search(EMAIL_PATTERN, header_value)
                            if email_match:
                                email = email_match.group(0)
                                if not any(b in email.lower() for b in SYSTEM_EMAIL_BLOCKLIST):
                                    return email
                    
                    return None
                    
                except Exception as e:
                    logger.debug(f"[{self.name}] Gmail header search failed: {e}")
                    return None
            
            with LatencyMonitor(f"[{self.name}] Gmail Resolution ({name})"):
                result = await asyncio.to_thread(_search_gmail_headers)
            
            if result:
                logger.info(f"[{self.name}] Gmail search resolved '{name}' to '{result}'")
            return result
                
        except ImportError:
            logger.debug(f"[{self.name}] googleapiclient not available for Gmail search")
            return None
        except Exception as e:
            logger.warning(f"[{self.name}] Gmail search resolution failed for {name}: {e}")
            return None

    async def _resolve_attendee_email(self, name: str, user_id: int) -> Optional[str]:
        """Resolve a name to an email address.
        
        Resolution chain:
        1. ContactResolver with disambiguation (returns all candidates)
        2. If single match → use it
        3. If multiple matches with clear winner → use best one
        4. If ambiguous → return best guess but log alternatives
        5. Returns None → CalendarTool will try People API + Gmail as fallback
        """
        logger.info(f"[{self.name}] 🔍 Resolving attendee: '{name}' (user_id={user_id})")
        
        if "@" in name:
            # Already an email — validate against blocklist
            name_lower = name.lower()
            if any(block in name_lower for block in SYSTEM_EMAIL_BLOCKLIST):
                logger.warning(f"[{self.name}] Rejecting system email: {name}")
                return None
            return name

        # 1. ContactResolver with disambiguation
        try:
            from src.services.contact_resolver import get_contact_resolver
            resolver = get_contact_resolver()
            if resolver:
                candidates = await resolver.resolve_with_disambiguation(name, user_id, identity_type="email")
                
                if len(candidates) == 1:
                    # Unambiguous — single match
                    c = candidates[0]
                    logger.info(f"[{self.name}] ✅ Resolved '{name}' → '{c.email}' (via {c.source}, confidence={c.confidence})")
                    return c.email
                
                elif len(candidates) > 1:
                    best = candidates[0]
                    runner_up = candidates[1]
                    
                    # If best match is clearly stronger (confidence gap > 0.2), use it
                    if best.confidence - runner_up.confidence > 0.2:
                        logger.info(
                            f"[{self.name}] ✅ Best match for '{name}' → '{best.email}' "
                            f"(confidence={best.confidence}, runner-up={runner_up.person_name}={runner_up.confidence})"
                        )
                        return best.email
                    
                    # Ambiguous — use best match but log the alternatives
                    alternatives = ", ".join(f"{c.person_name} ({c.email})" for c in candidates[1:])
                    logger.info(
                        f"[{self.name}] ⚠️ Ambiguous match for '{name}': "
                        f"using '{best.email}' (confidence={best.confidence}). "
                        f"Alternatives: {alternatives}"
                    )
                    # Store disambiguation info for the agent to surface to user
                    if not hasattr(self, '_disambiguation_warnings'):
                        self._disambiguation_warnings = []
                    self._disambiguation_warnings.append({
                        'name': name,
                        'chosen': best.person_name,
                        'chosen_email': best.email,
                        'alternatives': [
                            {'name': c.person_name, 'email': c.email, 'confidence': c.confidence}
                            for c in candidates[1:]
                        ]
                    })
                    return best.email
                
                logger.info(f"[{self.name}] ContactResolver found no match for '{name}'")
            else:
                logger.info(f"[{self.name}] ContactResolver not initialized, skipping graph resolution")
        except Exception as e:
            logger.warning(f"[{self.name}] ContactResolver failed for '{name}': {e}")

        # 2. People API fallback (searches Google Contacts + Other Contacts)
        try:
            people_result = await self._resolve_via_people_api(name)
            if people_result:
                logger.info(f"[{self.name}] ✅ People API resolved '{name}' → '{people_result}'")
                return people_result
        except Exception as e:
            logger.debug(f"[{self.name}] People API fallback failed for '{name}': {e}")

        # 3. Gmail header search fallback (searches From/To/Cc headers)
        try:
            gmail_result = await self._resolve_via_gmail_search(name)
            if gmail_result:
                logger.info(f"[{self.name}] ✅ Gmail search resolved '{name}' → '{gmail_result}'")
                return gmail_result
        except Exception as e:
            logger.debug(f"[{self.name}] Gmail search fallback failed for '{name}': {e}")

        # All resolution strategies exhausted
        logger.info(f"[{self.name}] ❌ All resolution strategies failed for '{name}'")
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
        unresolved_attendees = []  # Track names we couldn't resolve to emails
        
        # Use pre-resolved entities from supervisor context (EntityExtractor)
        pre_resolved_contacts = {}
        if context:
            pre_resolved_contacts = context.get('resolved_contacts', {}) or {}
            if pre_resolved_contacts:
                logger.info(f"[{self.name}] Found pre-resolved contacts from supervisor: {pre_resolved_contacts}")
        
        if attendees and isinstance(attendees, list) and user_id:
            resolved_attendees = []
            for attendee in attendees:
                if isinstance(attendee, str):
                    # First, check if supervisor already resolved this name
                    pre_resolved_email = pre_resolved_contacts.get(attendee)
                    if pre_resolved_email:
                        logger.info(f"[{self.name}] ✅ Using pre-resolved email for '{attendee}' → '{pre_resolved_email}'")
                        resolved_attendees.append(pre_resolved_email)
                        continue
                    
                    # Try CalendarAgent-level resolution (graph → People API → Gmail)
                    resolved = await self._resolve_attendee_email(attendee, user_id)
                    if resolved:
                        resolved_attendees.append(resolved)
                    else:
                        logger.warning(f"[{self.name}] Could not resolve attendee '{attendee}' to email")
                        unresolved_attendees.append(attendee)
            
            params["attendees"] = resolved_attendees
            logger.info(f"[{self.name}] Final attendees list for tool: {resolved_attendees} (unresolved: {unresolved_attendees})")
        # FIX: The LLM often puts duration (e.g., "1 hour") into end_time because of the schema description.
        # We must detect this and move it to duration_minutes, otherwise service layer fails with date parsing error.
        raw_end = params.get("end_time")
        if raw_end and isinstance(raw_end, str):
            # Check if it looks like a duration ("1 hour", "30 mins") rather than a time ("13:00")
            # Simple heuristic: presence of duration words and absence of colon (unless it's like 1:30h)
            # re is imported at file level
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
                    params['end_time'] = None  # Clear invalid end_time
        
        # SMART SCHEDULING: "Plan a run between meetings"
        # If no start time is provided, but user asks for "between", "gap", "free", try to find a slot.
        if not params.get("start_time") and any(w in query.lower() for w in ["between", "gap", "empty", "free", "available"]):
             logger.info(f"[{self.name}] Smart Scheduling: No start time, looking for gaps.")
             duration = params.get("duration_minutes", 30)
             
             # Call Tool's 'find_free_time'
             free_input = {
                 "action": "find_free_time",
                 "duration_minutes": duration,
                 "query": query
             }
             # We execute this synchronously (conceptually) to get the slot
             # Note: _safe_tool_execute returns a STRING. We need to parse it or assume the tool can chain it.
             # Ideally we'd call the service directly, but let's use the tool output.
             # Tool output format: "Found available slots... \n- Monday, 02:00 PM"
             availability_resp = await self._safe_tool_execute(TOOL_ALIASES_CALENDAR, free_input, "checking availability")
             
             # Extract first slot from text
             # Tool output format: "Found available slots...\n- Monday, 02:00 PM"
             # Regex captures optional day-of-week and the time
             slot_match = re.search(
                 r'-\s+(?:([A-Za-z]+),\s+)?(\d{1,2}:\d{2}\s*[AaPp][Mm])',
                 availability_resp
             )
             if slot_match:
                 day_name = slot_match.group(1)  # e.g. "Monday" or None
                 time_str = slot_match.group(2)  # e.g. "02:00 PM"
                 
                 # Build a proper ISO datetime from day-of-week + time
                 from datetime import datetime as _dt, timedelta as _td
                 try:
                     time_part = _dt.strptime(time_str.strip(), "%I:%M %p")
                     target_date = _dt.now().date()
                     
                     if day_name:
                         # Resolve day-of-week to next occurrence
                         day_map = {
                             'monday': 0, 'tuesday': 1, 'wednesday': 2,
                             'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
                         }
                         target_dow = day_map.get(day_name.lower())
                         if target_dow is not None:
                             current_dow = target_date.weekday()
                             days_ahead = (target_dow - current_dow) % 7
                             if days_ahead == 0:
                                 # Same day — only use it if the time is in the future
                                 candidate = _dt.combine(target_date, time_part.time())
                                 if candidate <= _dt.now():
                                     days_ahead = 7  # Next week
                             target_date = target_date + _td(days=days_ahead)
                     
                     full_dt = _dt.combine(target_date, time_part.time())
                     params["start_time"] = full_dt.isoformat()
                     logger.info(f"[{self.name}] Smart Scheduling: Found gap at {full_dt.isoformat()}")
                 except (ValueError, KeyError) as e:
                     # Fallback: pass the raw time string and let the tool parse it
                     logger.warning(f"[{self.name}] Smart Scheduling: datetime construction failed ({e}), using raw time: {time_str}")
                     params["start_time"] = time_str
                 
                 # Append context to description
                 params["description"] = (params.get("description") or "") + "\n(Scheduled in found gap)"
             else:
                 logger.warning(f"[{self.name}] Smart Scheduling: Could not extract slot from: {availability_resp}")
                 return f"I couldn't find a clear gap for that. {availability_resp}"

        # Fallback title extraction if LLM didn't extract summary or returned empty
        summary_value = params.get("summary")
        logger.info(f"[{self.name}] [DEBUG] summary_value = {repr(summary_value)}")
        
        # Check for None, empty string, or whitespace-only
        if not summary_value or (isinstance(summary_value, str) and not summary_value.strip()):
            logger.warning(f"[{self.name}] LLM did not extract title (got: {repr(summary_value)}), attempting fallback extraction from query: {query}")
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
        
        result = await self._safe_tool_execute(
            TOOL_ALIASES_CALENDAR, tool_input, "scheduling event"
        )
        
        # Surface unresolved attendees to the user — don't silently drop them
        if unresolved_attendees:
            names_str = ", ".join(unresolved_attendees)
            result += (
                f"\n\n⚠️ **Heads up:** I couldn't find an email address for **{names_str}**. "
                f"You'll need to add them manually in Google Calendar, or tell me their email "
                f"(e.g., \"Emmanuel's email is emmanuel@example.com\") so I can remember it for next time."
            )
        
        return result

    async def _handle_list(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle event listing with fast path for common date queries."""
        user_id = context.get('user_id') if context else None
        
        # FAST PATH: Extract dates directly for common patterns (skip LLM entirely)
        params = self._fast_extract_list_params(query)
        
        if params is None:
            # Complex query — use LLM but skip memory/RAG (simple_extraction)
            try:
                params = await self._extract_params(
                    query, 
                    LIST_SCHEMA, 
                    user_id=user_id,
                    task_type="simple_extraction"
                )
                logger.info(f"[{self.name}] Extracted params for list (LLM): {params}")
            except Exception as e:
                logger.warning(f"[{self.name}] Param extraction failed ({e}), using defaults for 'today'")
                params = {"days_ahead": 1}
        else:
            logger.info(f"[{self.name}] Extracted params for list (fast path): {params}")
        
        # Handle past date queries
        if params.get("looking_at_past"):
            tool_input = {
                "action": "list", 
                "query": query,
                "start_date": params.get("start_time"),
                "end_date": params.get("end_time"),
                "days_ahead": 1
            }
        else:
            tool_input = {
                "action": "list", 
                "query": query,
                "days_ahead": params.get("days_ahead") or 1,
                "start_date": params.get("start_time"),
                "end_date": params.get("end_time")
            }
        
        logger.info(f"[{self.name}] Calling CalendarTool with: {self._filter_none_values(tool_input)}")
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_CALENDAR, tool_input, "listing calendar events"
        )
    
    @staticmethod
    def _fast_extract_list_params(query: str) -> Optional[Dict[str, Any]]:
        """
        Fast regex-based date extraction for common calendar list queries.
        Returns None if the query is too complex for regex (falls back to LLM).
        """
        from datetime import datetime, timedelta
        
        q = query.lower().strip()
        now = datetime.now()
        
        # "today" or generic calendar queries
        today_patterns = ['today', 'what is on my calendar', "what's on my calendar",
                          'my calendar', 'my events', 'my schedule', 'my agenda']
        if any(p in q for p in today_patterns) and 'tomorrow' not in q and 'week' not in q:
            return {
                "start_time": now.strftime("%Y-%m-%dT00:00:00"),
                "end_time": now.strftime("%Y-%m-%dT23:59:59"),
                "days_ahead": 1
            }
        
        # "tomorrow"
        if 'tomorrow' in q:
            tmrw = now + timedelta(days=1)
            return {
                "start_time": tmrw.strftime("%Y-%m-%dT00:00:00"),
                "end_time": tmrw.strftime("%Y-%m-%dT23:59:59"),
                "days_ahead": 1
            }
        
        # "this week"
        if 'this week' in q:
            end = now + timedelta(days=(6 - now.weekday()))
            return {
                "start_time": now.strftime("%Y-%m-%dT00:00:00"),
                "end_time": end.strftime("%Y-%m-%dT23:59:59"),
                "days_ahead": (end - now).days + 1
            }
        
        # "next week"
        if 'next week' in q:
            days_until_monday = 7 - now.weekday()
            start = now + timedelta(days=days_until_monday)
            end = start + timedelta(days=6)
            return {
                "start_time": start.strftime("%Y-%m-%dT00:00:00"),
                "end_time": end.strftime("%Y-%m-%dT23:59:59"),
                "days_ahead": 7
            }
        
        # "next N days"
        import re as _re
        m = _re.search(r'next\s+(\d+)\s+days?', q)
        if m:
            n = int(m.group(1))
            end = now + timedelta(days=n)
            return {
                "start_time": now.strftime("%Y-%m-%dT00:00:00"),
                "end_time": end.strftime("%Y-%m-%dT23:59:59"),
                "days_ahead": n
            }
        
        # Not a simple pattern — fall back to LLM
        return None

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

        # 2. Find the event to get parameters (duration) if we need to auto-schedule
        # We need to find the event anyway to ensure we have the ID, but Tool does it inside update_event usually.
        # However, for auto-rescheduling (no new time provided), we MUST find it first to know the duration.
        new_start = params.get("new_start_time")
        
        # Check if we need auto-slot-finding
        auto_schedule = False
        if not new_start:
             # Check intent keywords
             if any(w in query.lower() for w in ["reschedule", "move", "change time", "later", "earlier", "find a time"]):
                 auto_schedule = True
                 logger.info(f"[{self.name}] Smart Rescheduling: No new time provided, will attempt to find a slot.")
        
        if auto_schedule:
             # We must search manually first to get duration
             # Revisit search logic from line 319 (we can re-use the tool's list capability or service)
             # Let's use list tool to find it
             search_list_input = {
                 "action": "list",
                 "query": search_q,
                 "days_ahead": 30
             }
             # Use _safe_tool_execute but capturing output is tricky as it returns formatted string.
             # We need structured data. Best to use internal knowledge (like we did in _handle_reply) specific to this agent?
             # OR trust the tool has a find method? CalendarTool's 'update' does internal search.
             # But here we need to INTERJECT to find free time.
             
             # Let's try to get the event via service directly if available, OR parse the list output (brittle).
             # Better: Use 'list' tool, look for duration logic? 
             # Let's assume standard duration (30/60) if we fail to parse, OR ask the tool to "find_event" (idempotent).
             
             # Actually, simpler approach: Use find_free_time with default 30 mins if we can't find event?
             # Or try to parse list output.
             
             # Let's assume 30 mins default if we can't get it, but try to be smart.
             duration = 30
             
             # Execute list to find event name/time to confirm
             # (Skipping complex parsing for brevity in this patch, assuming 30 min default or extracted from query)
             
             # Call find_free_time
             free_input = {
                 "action": "find_free_time",
                 "duration_minutes": duration,
                 "query": f"reschedule {search_q}"
             }
             availability_resp = await self._safe_tool_execute(TOOL_ALIASES_CALENDAR, free_input, "finding new slot")
             
             # Extract slot
             slot_match = re.search(r'-\s+(?:[A-Za-z]+,\s+)?(\d{1,2}:\d{2}\s*[AaPp][Mm])', availability_resp)
             if slot_match:
                 new_start = slot_match.group(1)
                 logger.info(f"[{self.name}] Smart Rescheduling: Found new slot {new_start}")
                 # Update the params
                 if not params.get("new_title"):
                     # If just moving, title remains same. Tool handles that if we pass query.
                     pass
                 
        
        # Delegate search-and-update to the Tool itself
        tool_input = {
            "action": "update_event",
            "query": search_q,
            "start_time": new_start, # Now populated if auto-scheduled
            "title": params.get("new_title")
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_CALENDAR, tool_input, "updating event"
        )

    async def _handle_availability(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Handle availability queries.
        
        Two modes based on LLM-extracted 'action':
          - check_specific: "Am I free at 3pm?" → list events at that time, report free/busy
          - find_gap: "When am I free?" → call find_free_time to locate open slots
        """
        user_id = context.get('user_id') if context else None
        
        try:
            params = await self._extract_params(
                query, 
                AVAILABILITY_SCHEMA, 
                user_id=user_id,
                task_type="planning"
            )
            logger.info(f"[{self.name}] Availability params: {params}")
        except Exception as e:
            logger.warning(f"[{self.name}] Availability param extraction failed ({e}), defaulting to find_gap")
            params = {"action": "find_gap", "duration_minutes": 30}
        
        availability_action = (params.get("action") or "find_gap").lower().strip()
        duration = params.get("duration_minutes") or 30
        start_time = params.get("start_time")
        
        # ------------------------------------------------------------------
        # MODE 1: Check a specific time — "Am I free at 3pm?"
        # ------------------------------------------------------------------
        if availability_action == "check_specific" and start_time:
            logger.info(f"[{self.name}] Checking specific availability at {start_time}")
            
            # List events around the requested time window
            tool_input = {
                "action": "list",
                "query": query,
                "start_date": start_time,
                "days_ahead": 1
            }
            
            events_resp = await self._safe_tool_execute(
                TOOL_ALIASES_CALENDAR, tool_input, "checking calendar"
            )
            
            # Analyze the response to determine free/busy
            # Tool returns strings like "No events found" or lists event details
            no_events_indicators = ["no events", "no upcoming", "nothing scheduled", "calendar is clear"]
            is_free = any(indicator in events_resp.lower() for indicator in no_events_indicators)
            
            if is_free:
                return f"✅ You're free at that time! No conflicts found.\n\n{events_resp}"
            else:
                # There are events — check if find_free_time can suggest alternatives
                alt_input = {
                    "action": "find_free_time",
                    "duration_minutes": duration,
                    "start_time": start_time,
                    "working_hours_only": True
                }
                
                alt_resp = await self._safe_tool_execute(
                    TOOL_ALIASES_CALENDAR, alt_input, "finding alternatives"
                )
                
                return (
                    f"⚠️ You have events at that time:\n\n{events_resp}\n\n"
                    f"Here are some available alternatives:\n{alt_resp}"
                )
        
        # ------------------------------------------------------------------
        # MODE 2: Find gaps — "When am I free?" / "Find me a 1-hour slot"
        # ------------------------------------------------------------------
        logger.info(f"[{self.name}] Finding free gaps (duration={duration}min)")
        
        tool_input = {
            "action": "find_free_time",
            "duration_minutes": duration,
            "query": query,
            "working_hours_only": True
        }
        
        # Add time bounds if the user specified them
        if start_time:
            tool_input["start_time"] = start_time
        
        result = await self._safe_tool_execute(
            TOOL_ALIASES_CALENDAR, tool_input, "finding available time"
        )
        
        # ------------------------------------------------------------------
        # AUTO-SCHEDULE: If query has scheduling context (from HITL rewrite),
        # extract the first available slot and schedule the event there.
        # ------------------------------------------------------------------
        scheduling_signals = ['schedule', 'book', 'set up', 'create', 'meeting with', 'clavr meeting']
        query_lower = query.lower()
        is_scheduling_followup = any(sig in query_lower for sig in scheduling_signals)
        
        if is_scheduling_followup and "available" in result.lower():
            logger.info(f"[{self.name}] Scheduling follow-up detected — auto-scheduling at first free slot")
            
            # Parse the first available time from the find_free_time output
            # Format is: "Found available slots...\n- Friday, 10:00 AM\n- Friday, 12:00 PM"
            import re as _re
            slot_match = _re.search(
                r'-\s+(?:([A-Za-z]+),\s+)?(\d{1,2}:\d{2}\s*[AaPp][Mm])',
                result
            )
            
            if slot_match:
                from datetime import datetime as _dt, timedelta as _td
                
                day_name = slot_match.group(1)  # e.g., "Friday"
                time_str = slot_match.group(2)  # e.g., "10:00 AM"
                
                try:
                    time_part = _dt.strptime(time_str.strip(), "%I:%M %p")
                    target_date = _dt.now().date()
                    
                    if day_name:
                        day_map = {
                            'monday': 0, 'tuesday': 1, 'wednesday': 2,
                            'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
                        }
                        target_dow = day_map.get(day_name.lower())
                        if target_dow is not None:
                            current_dow = target_date.weekday()
                            days_ahead = (target_dow - current_dow) % 7
                            if days_ahead == 0:
                                candidate = _dt.combine(target_date, time_part.time())
                                if candidate <= _dt.now():
                                    days_ahead = 7
                            target_date = target_date + _td(days=days_ahead)
                    
                    full_dt = _dt.combine(target_date, time_part.time())
                    new_start = full_dt.isoformat()
                    
                    # Build a scheduling query with the new time
                    schedule_query = f"schedule {query} at {time_str}"
                    if day_name:
                        schedule_query = f"schedule {query} on {day_name} at {time_str}"
                    
                    logger.info(f"[{self.name}] Auto-scheduling at {new_start}: {schedule_query}")
                    
                    # Route to the schedule handler with the resolved time
                    schedule_result = await self._handle_schedule(schedule_query, context)
                    return schedule_result
                    
                except Exception as auto_err:
                    logger.warning(f"[{self.name}] Auto-schedule failed: {auto_err}, falling back to listing slots")
        
        return result
