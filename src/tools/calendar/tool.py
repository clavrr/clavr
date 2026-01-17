"""
Calendar Tool - Calendar management capabilities
"""
import asyncio
import re
from datetime import datetime, timedelta
from langchain.tools import BaseTool
from pydantic import Field, BaseModel
from typing import Optional, Any, List, Dict, Type

from ...utils.logger import setup_logger
from ...utils.config import Config, ConfigDefaults
from ...utils.datetime.flexible_date_parser import FlexibleDateParser

logger = setup_logger(__name__)


class CalendarInput(BaseModel):
    """Input for CalendarTool."""
    action: str = Field(description="Action to perform (create, list, search, list_calendars, find_free_time, etc.)")
    query: Optional[str] = Field(default="", description="Query or details for the action.")
    start_time: Optional[str] = Field(default=None, description="Start time (ISO format)")
    end_time: Optional[str] = Field(default=None, description="End time (ISO format)")
    calendar_id: Optional[str] = Field(default="primary", description="Calendar ID")
    event_id: Optional[str] = Field(default=None, description="Event ID")
    attendees: Optional[List[str]] = Field(default=None, description="List of attendee emails")
    location: Optional[str] = Field(default=None, description="Event location")
    description: Optional[str] = Field(default=None, description="Event description")
    title: Optional[str] = Field(default=None, description="Event title (alias for summary)")
    summary: Optional[str] = Field(default=None, description="Event summary/title")
    duration_minutes: Optional[int] = Field(default=None, description="Event duration in minutes")
    check_conflicts: Optional[bool] = Field(default=True, description="Check for scheduling conflicts before creating")
    limit: Optional[int] = Field(default=10, description="Result limit")

from ..base import WorkflowEventMixin


class CalendarTool(WorkflowEventMixin, BaseTool):
    """Calendar management tool wrapping CalendarParser"""
    name: str = "calendar"
    description: str = "Calendar management (create events, find free time, check conflicts). Use this for scheduling and calendar queries."
    args_schema: Type[BaseModel] = CalendarInput
    
    config: Optional[Config] = Field(default=None)
    user_id: Optional[int] = Field(default=None)
    credentials: Optional[Any] = Field(default=None)
    rag_engine: Optional[Any] = Field(default=None)
    _service: Optional[Any] = None
    
    def __init__(self, config: Optional[Config] = None, user_id: Optional[int] = None,
                 credentials: Optional[Any] = None, rag_engine: Optional[Any] = None, **kwargs):
        super().__init__(
            config=config,
            user_id=user_id,
            credentials=credentials,
            rag_engine=rag_engine,
            **kwargs
        )
        if credentials:
            logger.info(f"[CalendarTool] Initialized with credentials (valid={getattr(credentials, 'valid', 'unknown')})")
        else:
            logger.warning("[CalendarTool] Initialized with NO credentials")
        self._service = None
        self._date_parser = FlexibleDateParser(config)
        
    def _resolve_attendees_sync(self, attendees: List[str]) -> List[str]:
        """Resolve attendee names to emails using Graph (Sync wrapper)"""
        if not attendees:
            return []
            
        try:
            from ...services.indexing.graph.manager import KnowledgeGraphManager
            
            async def _resolve_async():
                graph = KnowledgeGraphManager()
                resolved_list = []
                
                for att in attendees:
                    # 1. Check if valid email / Blocklist
                    if "@" in att:
                        # Block list
                        email_lower = att.lower()
                        if any(b in email_lower for b in ['noreply', 'no-reply', 'notifications', 'alert', 'bounce', 'support']):
                            logger.warning(f"[CalendarTool] Dropping system email: {att}")
                            continue
                        resolved_list.append(att)
                        continue
                        
                    # 2. Graph Search
                    try:
                        name_lower = att.lower().strip()
                        aql = """
                            LET contacts = (
                                FOR c IN Contact
                                    LET name_lower = LOWER(c.name)
                                    LET email_lower = LOWER(c.email)
                                    FILTER CONTAINS(name_lower, @name) OR CONTAINS(email_lower, @name)
                                    RETURN {name: c.name, email: c.email}
                            )
                            LET people = (
                                FOR p IN Person
                                    LET name_lower = LOWER(p.name)
                                    LET email_lower = LOWER(p.email)
                                    FILTER (CONTAINS(name_lower, @name) OR CONTAINS(email_lower, @name)) AND p.email != null AND p.email != ""
                                    RETURN {name: p.name, email: p.email}
                            )
                            FOR r IN UNION(contacts, people)
                                FILTER r.email != null
                                FILTER NOT CONTAINS(LOWER(r.email), 'noreply')
                                FILTER NOT CONTAINS(LOWER(r.email), 'no-reply')
                                FILTER NOT CONTAINS(LOWER(r.email), 'notifications')
                                SORT r.name ASC 
                                LIMIT 1 
                                RETURN DISTINCT r.email
                        """
                        results = await graph.execute_query(aql, {'name': name_lower})
                        if results:
                            logger.info(f"[CalendarTool] Resolved '{att}' -> '{results[0]}'")
                            resolved_list.append(results[0])
                        else:
                            logger.warning(f"[CalendarTool] Could not resolve attendee: {att}")
                    except Exception as e:
                        logger.warning(f"[CalendarTool] Resolution error for {att}: {e}")
                        
                return resolved_list

            return asyncio.run(_resolve_async())
            
        except Exception as e:
            logger.error(f"[CalendarTool] Sync resolution failed: {e}")
            return attendees # Fallback to original

    
    def _initialize_service(self):
        """Lazy initialization of calendar service"""
        if self._service is None and self.config:
            try:
                from ...integrations.google_calendar.service import CalendarService
                # CalendarService handles its own client initialization
                self._service = CalendarService(
                    config=self.config,
                    credentials=self.credentials
                )
            except Exception as e:
                logger.error(f"Failed to initialize CalendarService: {e}")
                self._service = None

    def _run(self, action: str = "auto", query: str = "", **kwargs) -> str:
        """Execute calendar tool action"""
        workflow_emitter = kwargs.get('workflow_emitter')
        
        self._initialize_service()
        
        # Import exceptions for handling
        try:
             from ...integrations.google_calendar.service import SchedulingConflictException
        except ImportError:
             SchedulingConflictException = None

        
        # Tools initialized with just config/credentials might work for templates using DB,
        # but service is needed for Google Calendar actions
        if not self._service and action not in ["create_template", "list_templates", "delete_template"]:
             return "[INTEGRATION_REQUIRED] Calendar permission not granted. Please enable Google integration in Settings."
        
        try:
            # Emit action executing event
            if workflow_emitter:
                self.emit_action_event(workflow_emitter, 'executing', f"Processing calendar {action}", action=action)
            
            # Handle preset/template actions
            if action == "create_template":
                template_name = kwargs.get('template_name') or kwargs.get('name')
                
                if not template_name:
                    return "[ERROR] Could not identify preset name. Please specify a name for the preset."
                
                try:
                    from ...database import get_db_context
                    from ...core.calendar.presets import TemplateStorage
                    
                    if not self.user_id:
                        return "[ERROR] User ID not available. Cannot create preset."
                    
                    with get_db_context() as db:
                        storage = TemplateStorage(db, self.user_id)
                        
                        # Extract meeting details from kwargs
                        title = kwargs.get('title') or kwargs.get('event_title')
                        duration_minutes = kwargs.get('duration_minutes', 60)
                        description = kwargs.get('description', '')
                        location = kwargs.get('location', '')
                        default_attendees = kwargs.get('default_attendees') or kwargs.get('attendees', [])
                        recurrence = kwargs.get('recurrence')
                        
                        # Simple fallback for title if not provided
                        if not title and query:
                            # Heuristic: use query as title if short, or generic
                            if len(query) < 50:
                                title = query
                            else:
                                title = "Meeting"
                        
                        storage.create_template(
                            name=template_name,
                            title=title or "New Meeting",
                            duration_minutes=duration_minutes,
                            description=description,
                            location=location,
                            default_attendees=default_attendees if isinstance(default_attendees, list) else [default_attendees] if default_attendees else [],
                            recurrence=recurrence
                        )
                        
                        return f"All set! I've created the '{template_name}' meeting preset for you."
                except Exception as e:
                    logger.error(f"Failed to create meeting preset: {e}", exc_info=True)
                    return f"[ERROR] Failed to create meeting preset: {str(e)}"
            
            elif action == "use_template":
                # Use an existing meeting preset to create an event
                template_name = kwargs.get('template_name') or kwargs.get('name')
                
                if not template_name:
                    return "[ERROR] Could not identify preset name. Please specify which preset to use."
                
                try:
                    from ...database import get_db_context
                    from ...core.calendar.presets import TemplateStorage
                    
                    with get_db_context() as db:
                        storage = TemplateStorage(db, self.user_id)
                        
                        # Get preset
                        template = storage.get_template(template_name)
                        if not template:
                            return f"[ERROR] Meeting preset '{template_name}' not found."
                        
                        # Merge preset with provided parameters (provided params override preset)
                        title = kwargs.get('title') or template.get('title', '')
                        start_time = kwargs.get('start_time')
                        duration_minutes = kwargs.get('duration_minutes') or template.get('duration_minutes', 60)
                        description = kwargs.get('description') or template.get('description', '')
                        location = kwargs.get('location') or template.get('location', '')
                        attendees = kwargs.get('attendees') or template.get('default_attendees', [])
                        recurrence = kwargs.get('recurrence') or template.get('recurrence')
                        
                        if not start_time:
                            return "[ERROR] Start time is required. Please specify when the meeting should occur."
                        
                        if not self._service:
                            return "I can't access your calendar right now. Please check your calendar service connection."
                        
                        result = self._service.create_event(
                            title=title,
                            start_time=start_time,
                            end_time=kwargs.get('end_time'),
                            duration_minutes=duration_minutes,
                            description=description,
                            location=location,
                            attendees=attendees if isinstance(attendees, list) else [attendees] if attendees else [],
                            recurrence=recurrence
                        )
                        
                        if result:
                            event_title = result.get('summary') or title
                            logger.info(f"[CalendarTool] Created event from preset '{template_name}': {event_title}")
                            result_str = f"Done! I've set up your '{event_title}' from the '{template_name}' preset. You're all set!"
                            
                            if workflow_emitter:
                                self.emit_action_event(workflow_emitter, 'complete', f"Calendar event created from preset: {event_title}", action=action, result=event_title)
                            
                            return result_str
                        else:
                            return "[ERROR] Failed to create calendar event from preset."
                except Exception as e:
                    logger.error(f"Failed to use meeting preset: {e}", exc_info=True)
                    return f"[ERROR] Failed to use meeting preset: {str(e)}"

            elif action == "list_templates":
                # List all meeting presets
                try:
                    from ...database import get_db_context
                    from ...core.calendar.presets import TemplateStorage
                    
                    if not self.user_id:
                        return "[ERROR] User ID not available."
                    
                    with get_db_context() as db:
                        storage = TemplateStorage(db, self.user_id)
                        template_names = storage.list_templates()
                        
                        if not template_names:
                            return "You don't have any meeting presets yet."
                        
                        template_lines = []
                        for i, name in enumerate(template_names, 1):
                            template = storage.get_template(name)
                            title = template.get('title', '') if template else ''
                            duration = template.get('duration_minutes', 60) if template else 60
                            template_lines.append(f"{i}. {name}" + (f" - {title} ({duration} min)" if title else f" ({duration} min)"))
                        
                        return f"Your meeting presets ({len(template_names)} total):\n" + "\n".join(template_lines)
                except Exception as e:
                    logger.error(f"Failed to list meeting presets: {e}", exc_info=True)
                    return f"[ERROR] Failed to list meeting presets: {str(e)}"
            
            elif action == "delete_template":
                # Delete a meeting preset
                template_name = kwargs.get('template_name') or kwargs.get('name')
                
                if not template_name:
                    return "[ERROR] Could not identify preset name."
                
                try:
                    from ...database import get_db_context
                    from ...core.calendar.presets import TemplateStorage
                    
                    with get_db_context() as db:
                        storage = TemplateStorage(db, self.user_id)
                        storage.delete_template(template_name)
                        return f"Deleted meeting preset '{template_name}' successfully."
                except Exception as e:
                    return f"[ERROR] Failed to delete meeting preset: {str(e)}"

            # --- Core Actions via CalendarService ---
            
            if not self._service:
                 return "Error: Calendar service missing."

            if action in ["create", "create_event", "schedule"]:
                title = kwargs.get('title') or kwargs.get('event_title') or kwargs.get('summary')
                start_time = kwargs.get('start_time')
                duration_minutes = kwargs.get('duration_minutes')
                
                # VOICE INPUT FALLBACK: Parse query string if structured params not provided
                # This handles voice input like "schedule clever AI meeting 2025-12-22T10:00:00 for 1 hour"
                if not start_time and query:
                    import re
                    
                    # Try to extract ISO datetime from query (e.g., "2025-12-22T10:00:00")
                    iso_match = re.search(r'(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?)', query)
                    if iso_match:
                        start_time = iso_match.group(1)
                        logger.info(f"[CalendarTool] Extracted ISO datetime from query: {start_time}")
                    else:
                        # VOICE/SUPERVISOR INPUT CLEANUP: Strip context blocks before parsing
                        # Supervisor often passes query as "[Step 1 Result]: ... \n\nRequest: [Actual Query]" 
                        # or similar noise-heavy patterns.
                        clean_query = query
                        if "[CONTEXT]" in query and "[END CONTEXT]" in query:
                            clean_query = query.split("[END CONTEXT]")[-1].strip()
                        elif "Context from previous steps:" in query:
                            clean_query = query.split("Context from previous steps:")[0].strip()
                            # If the split removed the query (unlikely), fallback
                            if not clean_query: clean_query = query
                        
                        # Strip common supervisor prefixes
                        clean_query = re.sub(r'^(?:[Ss]tep \d+ [Rr]esult:?|\[[Ss]tep \d+ [Rr]esult\]:?|Query:?|Request:?)\s*', '', clean_query, flags=re.IGNORECASE)

                        # Use FlexibleDateParser for robust natural language parsing
                        try:
                            # Parse with future preference for scheduling context
                            result = self._date_parser.parse_date_expression(clean_query, prefer_future=True)
                            if result and result.get('start'):
                                start_time = result['start'].isoformat()
                                logger.info(f"[CalendarTool] FlexibleDateParser found datetime: {start_time}")
                        except Exception as e:
                            logger.warning(f"[CalendarTool] FlexibleDateParser failed: {e}")
                
                # Extract duration from query if not provided (e.g., "for 1 hour", "30 minutes")
                if not duration_minutes and query:
                    import re
                    # Match patterns like "for 1 hour", "1 hour", "30 minutes", "30 min"
                    duration_match = re.search(r'(?:for\s+)?(\d+)\s*(?:hour|hr|minute|min)s?', query, re.IGNORECASE)
                    if duration_match:
                        value = int(duration_match.group(0).split()[0] if 'for' not in duration_match.group(0).lower() 
                                   else duration_match.group(0).split()[1])
                        unit = duration_match.group(0).lower()
                        if 'hour' in unit or 'hr' in unit:
                            duration_minutes = value * 60
                        else:
                            duration_minutes = value
                        logger.info(f"[CalendarTool] Extracted duration from query: {duration_minutes} minutes")
                
                # Extract title from query if not provided - use the part before the date/time
                if not title and query:
                    title_text = self._clean_query_text(query)
                    if title_text and len(title_text) < 100:
                        title = title_text
                        logger.info(f"[CalendarTool] Extracted title from query: {title}")
                    elif len(query) < 50:
                        title = query
                    else:
                        title = "New Event"
                
                # Fallback: Extract 'with [Name]' from query if attendees not provided
                if not kwargs.get('attendees') and query:
                    import re
                    # Look for "with [Name] [Optional Surname]"
                    # Avoiding "with me" or "with them"
                    with_matches = re.findall(r'\bwith\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', query)
                    if with_matches:
                        extracted_names = [n for n in with_matches if n.lower() not in ['me', 'him', 'her', 'them', 'us']]
                        if extracted_names:
                            logger.info(f"[CalendarTool] Extracted potential attendees from query: {extracted_names}")
                            if 'attendees' not in kwargs:
                                kwargs['attendees'] = []
                            # We'll let _resolve_attendees_sync handle the resolution/validation
                            kwargs['attendees'].extend(extracted_names)

                try:
                    result = self._service.create_event(
                        title=title,
                        start_time=start_time,
                        end_time=kwargs.get('end_time'),
                        duration_minutes=duration_minutes or kwargs.get('duration_minutes'),
                        description=kwargs.get('description'),
                        location=kwargs.get('location'),
                        attendees=self._resolve_attendees_sync(kwargs.get('attendees')),
                        recurrence=kwargs.get('recurrence'),
                        check_conflicts=kwargs.get('check_conflicts', True)  # Default to True for conflict detection
                    )
                    
                    if result:
                        summary = result.get('summary', title)
                        return f"You're all set! I've scheduled '{summary}' for {start_time}. See you there!"
                except Exception as e:
                    error_msg = str(e)
                    # Check for "phantom" conflicts (identical event already exists)
                    if "conflicting event" in error_msg.lower():
                        # If we have conflict details, check if it's the SAME event
                        if hasattr(e, 'details') and e.details:
                            conflicts = e.details.get('conflicting_events', [])
                            for conflict in conflicts:
                                if conflict.get('summary') == title:
                                    return f"That's already on your calendar! I found an identical event '{title}' scheduled at that same time."
                        
                        return f"I found a conflict on your calendar: {error_msg}. Would you like me to find another time?"
                    
                    logger.error(f"[CalendarTool] Failed to create event: {e}")
                    return f"I ran into an issue: {error_msg}"

            elif action in ["update", "update_event", "move"]:

                event_id = kwargs.get('event_id')
                query_str = kwargs.get('query')
                start_time = kwargs.get('start_time') or kwargs.get('new_time')
                end_time = kwargs.get('end_time')
                
                # Smart resolution: if no ID but query provided, find it
                if not event_id and query_str:
                    try:
                        search_query = query_str
                        dest_part = None
                        
                        # Check for "move ... to/at ..." patterns
                        move_match = None
                        for pattern in ConfigDefaults.CALENDAR_MOVE_PATTERNS:
                            move_match = re.search(pattern, query_str, re.IGNORECASE)
                            if move_match:
                                break
                                
                        if move_match:
                            search_query = move_match.group(1).strip()
                            dest_part = move_match.group(2).strip()
                            logger.info(f"[CalendarTool] Detected move pattern: '{search_query}' -> '{dest_part}'")
                        
                        # PRE-SEARCH OPTIMIZATION: Extract date/time from search_query to narrow the window
                        list_start, list_end = None, None
                        clean_search = search_query
                        try:
                            # Try to find a date in the search query part
                            nl_search = self._date_parser.parse_date_expression(search_query)
                            if nl_search:
                                # Use the WHOLE day of the extracted date for searching
                                list_start = nl_search['start'].replace(hour=0, minute=0, second=0)
                                list_end = list_start + timedelta(days=1)
                                logger.info(f"[CalendarTool] Narrowing search window to {list_start.date()}")
                                
                                # Clean the search query of date phrases/fillers to improve text matching
                                clean_search = self._clean_query_text(search_query)
                        except (ValueError, AttributeError):
                            # Date parsing failed for search optimization, use full search
                            pass

                        # Search for the event
                        found_events = self._service.list_events(
                            query=clean_search or search_query,
                            start_date=list_start,
                            end_date=list_end,
                            days_back=ConfigDefaults.CALENDAR_SEARCH_DAYS_BACK if not list_start else 0, 
                            days_ahead=ConfigDefaults.CALENDAR_SEARCH_DAYS_AHEAD if not list_end else 0
                        )
                        
                        if not found_events:
                            return f"I couldn't find any event matching '{search_query}' to update."
                        
                        # Found exactly one match
                        if len(found_events) == 1:
                            event = found_events[0]
                            event_id = event['id']
                            logger.info(f"[CalendarTool] Resolved query '{search_query}' to event ID {event_id} ({event.get('summary')})")

                            # If it was a move pattern, resolve the destination time relative to the event's date
                            if dest_part and not start_time:
                                ref_dt = event.get('start')
                                nl_result = self._date_parser.parse_date_expression(dest_part, now=ref_dt, prefer_future=True)
                                if nl_result and nl_result.get('start'):
                                    start_time = nl_result['start'].isoformat()
                                    logger.info(f"[CalendarTool] Resolved move destination '{dest_part}' to {start_time}")
                                    
                                    # KEEP DURATION: Calculate new end_time based on old duration
                                    if event.get('start') and event.get('end'):
                                        duration = event['end'] - event['start']
                                        start_dt = nl_result['start']
                                        end_time = (start_dt + duration).isoformat()
                        else:
                            # Ambiguous - try to be helpful
                            titles = [f"- {e.get('summary', 'Unknown')} ({e.get('start', datetime.now()).strftime('%Y-%m-%d %H:%M')})" for e in found_events[:3]]
                            return f"I found multiple events matching '{search_query}'. Which one did you mean?:\n" + "\n".join(titles)
                        
                    except Exception as e:
                        logger.error(f"[CalendarTool] Error during event resolution: {e}", exc_info=True)
                        return f"Error searching for event: {str(e)}"
                
                if not event_id:
                    return "Error: event_id (or a clear search query) is required for update."
                
                result = self._service.update_event(
                    event_id=event_id,
                    title=kwargs.get('title'),
                    start_time=start_time,
                    end_time=end_time,
                    description=kwargs.get('description'),
                    location=kwargs.get('location'),
                    attendees=kwargs.get('attendees')
                )
                return "I've updated that event for you."

            elif action in ["delete", "delete_event"]:
                event_id = kwargs.get('event_id')
                if not event_id:
                    return "Error: event_id required for delete."
                
                self._service.delete_event(event_id)
                return "I've deleted that event."

            elif action in ["list", "search"]:
                # Map to list_events
                days_ahead = kwargs.get('days_ahead', 1)
                days_back = kwargs.get('days_back', 0)
                max_results = kwargs.get('max_results', 50)
                start_date = kwargs.get('start_date')
                end_date = kwargs.get('end_date')
                
                # VOICE INPUT FALLBACK: If no start_date provided, try to extract it from query (e.g., "tomorrow")
                if not start_date and query:
                    try:
                        nl_result = self._date_parser.parse_date_expression(query, prefer_future=True)
                        if nl_result and nl_result.get('start'):
                            start_date = nl_result['start'].date().isoformat()
                            # If we found a date in query, ensure end_date covers at least that day
                            if not end_date:
                                end_date = (nl_result.get('end') or nl_result['start']).date().isoformat()
                            logger.info(f"[CalendarTool] Extracted NL date from query '{query}': {start_date} to {end_date}")
                    except Exception as e:
                        logger.warning(f"[CalendarTool] NL Date parsing failed for list query '{query}': {e}")

                # Default to today if still no start_date provided
                if not start_date and days_back == 0:
                    start_date = datetime.now().date().isoformat()
                    logger.info(f"[CalendarTool] No start_date provided, defaulting to today: {start_date}")
                
                events = self._service.list_events(
                    start_date=start_date,
                    end_date=end_date,
                    days_back=days_back,
                    days_ahead=days_ahead,
                    max_results=max_results,
                    query=query if action=="search" else None
                )
                
                if not events:
                    return "I couldn't find any events for that time range."
                
                # For voice clarity and speed, limit to 5 events
                events = events[:5]
                
                # Format output with date context
                now = datetime.now()
                today = now.date()
                
                # Determine date context for the events
                date_context = ""
                if start_date:
                    try:
                        query_date = datetime.fromisoformat(start_date.replace('Z', '+00:00')).date() if isinstance(start_date, str) else start_date
                        if query_date < today:
                            days_ago = (today - query_date).days
                            if days_ago == 1:
                                date_context = " from yesterday"
                            else:
                                date_context = f" from {days_ago} days ago ({query_date.strftime('%B %d')})"
                        elif query_date == today:
                            date_context = " for today"
                        else:
                            date_context = f" for {query_date.strftime('%B %d')}"
                    except (ValueError, TypeError, AttributeError):
                        # Date context extraction failed, continue without context
                        pass
                
                lines = [f"I found {len(events)} events{date_context}:\n"]
                for event in events:
                    start_data = event.get('start')
                    end_data = event.get('end')
                    
                    def parse_time(data):
                        if not data: return None
                        if hasattr(data, 'isoformat'): return data
                        if isinstance(data, dict):
                            dt_raw = data.get('dateTime')
                            d_raw = data.get('date')
                            if dt_raw:
                                try: return datetime.fromisoformat(dt_raw.replace('Z', '+00:00'))
                                except (ValueError, TypeError): return None
                        return None

                    start_dt = parse_time(start_data)
                    end_dt = parse_time(end_data)
                    
                    time_str = "Unknown time"
                    is_ongoing = False
                    
                    if start_dt:
                        time_str = start_dt.strftime('%I:%M %p')
                        if end_dt:
                            time_str += f" - {end_dt.strftime('%I:%M %p')}"
                            # Check if ongoing
                            try:
                                check_now = now
                                # Handle naive vs aware comparison
                                if start_dt.tzinfo and not check_now.tzinfo:
                                    # If start is aware but now is naive, assume 'now' is in same timezone context for comparison
                                    check_now = check_now.replace(tzinfo=start_dt.tzinfo)
                                elif not start_dt.tzinfo and check_now.tzinfo:
                                    check_now = check_now.replace(tzinfo=None)
                                    
                                if start_dt <= check_now <= end_dt:
                                    is_ongoing = True
                            except (TypeError, AttributeError):
                                # Timezone comparison failed, skip ongoing check
                                pass
                    elif isinstance(start_data, dict) and start_data.get('date'):
                        d_raw = start_data.get('date')
                        try:
                            dt = datetime.fromisoformat(d_raw)
                            time_str = f"All Day ({dt.strftime('%a, %b %d')})"
                        except (ValueError, TypeError):
                            time_str = f"All Day ({d_raw})"
                    
                    summary = event.get('summary', event.get('title', 'No Title'))
                    status_label = " **(currently ongoing)**" if is_ongoing else ""
                    
                    lines.append(f"**{summary}**{status_label}")
                    lines.append(f"   at {time_str}")
                    
                    # Add attendees for context awareness (crucial for "email everyone in that meeting" flows)
                    attendees = event.get('attendees', [])
                    if attendees:
                        # each attendee is dict {'email': '...', 'responseStatus': '...'} or just a string
                        att_list = []
                        for att in attendees:
                            if isinstance(att, dict):
                                email = att.get('email')
                                if email and not any(block in email for block in ['noreply', 'calendar.google.com']):
                                    att_list.append(email)
                            elif isinstance(att, str):
                                att_list.append(att)
                        
                        if att_list:
                            lines.append(f"   Attendees: {', '.join(att_list)}")

                    lines.append("")
                
                return "\n".join(lines)

                return "\n".join(lines)

            elif action in ["find_free_time", "find_gap", "availability"]:
                duration = kwargs.get('duration_minutes', 30)
                # Default to today if not specified
                start_search = kwargs.get('start_time') or kwargs.get('start_date') or datetime.now().isoformat()
                
                # Default to next 24h if end not specified
                end_search = kwargs.get('end_time') or kwargs.get('end_date')
                
                free_slots = self._service.find_free_time(
                    duration_minutes=duration,
                    max_suggestions=5,
                    start_datetime=start_search if isinstance(start_search, datetime) else None,
                    end_datetime=end_search if isinstance(end_search, datetime) else None,
                    working_hours_only=kwargs.get('working_hours_only', True)
                )
                
                if not free_slots:
                    return "I couldn't find any free slots of that duration."
                
                lines = [f"Found available slots for {duration} mins:"]
                for slot in free_slots:
                    start_raw = slot.get('start', '')
                    if start_raw:
                        try:
                            start_dt = datetime.fromisoformat(start_raw.replace('Z', '+00:00'))
                            lines.append(f"- {start_dt.strftime('%A, %I:%M %p')}")
                        except Exception:
                            lines.append(f"- {start_raw}")
                            
                return "\n".join(lines)
                
            else:
                return f"Error: Unknown action '{action}'"

        except Exception as e:
            # Handle specific conflict exception cleanly without scary traceback
            if SchedulingConflictException and isinstance(e, SchedulingConflictException):
                logger.warning(f"Calendar scheduling conflict: {e}")
                if workflow_emitter:
                     # For conflicts, we treat it as an error state for the workflow but with a clean message
                     self.emit_action_event(workflow_emitter, 'error', str(e), action=action, error=str(e))
                
                # Extract conflict details to be specific
                details = getattr(e, 'details', {})
                conflicts = details.get('conflicting_events', [])
                suggestions = details.get('suggestions', [])
                conflict_titles = [c.get('summary', 'Busy') for c in conflicts]
                conflict_str = ", ".join(conflict_titles)
                
                # Format suggestions nicely for the user
                suggestion_str = ""
                if suggestions:
                    formatted_times = []
                    for s in suggestions[:3]:  # Limit to 3 suggestions
                        try:
                            start_raw = s.get('start', '')
                            if start_raw:
                                start_dt = datetime.fromisoformat(start_raw.replace('Z', '+00:00'))
                                # Format nicely: "10:00 AM", "2:30 PM"
                                formatted_times.append(start_dt.strftime('%I:%M %p').lstrip('0'))
                        except Exception:
                            formatted_times.append(start_raw[:10] if start_raw else 'Unknown')
                    
                    if formatted_times:
                        suggestion_str = f"\n\nHere are some available times today: **{', '.join(formatted_times)}**. Would you like me to schedule it for one of these times instead?"
                
                # Build the response message
                if conflict_titles:
                    response = f"There's a conflict with '{conflict_str}' at that time."
                else:
                    response = f"That time slot is already busy."
                
                # Append suggestions if available
                if suggestion_str:
                    response += suggestion_str
                else:
                    # If no suggestions from service, try to find them ourselves
                    if self._service:
                        try:
                            # Get duration from kwargs or default to 60 min
                            duration = kwargs.get('duration_minutes', 60)
                            free_slots = self._service.find_free_time(
                                duration_minutes=duration,
                                max_suggestions=3,
                                working_hours_only=True
                            )
                            if free_slots:
                                formatted_times = []
                                for slot in free_slots[:3]:
                                    try:
                                        start_raw = slot.get('start', '')
                                        if start_raw:
                                            start_dt = datetime.fromisoformat(start_raw.replace('Z', '+00:00'))
                                            formatted_times.append(start_dt.strftime('%I:%M %p').lstrip('0'))
                                    except Exception:
                                        pass
                                if formatted_times:
                                    response += f"\n\nHere are some available times: **{', '.join(formatted_times)}**. Would you like me to schedule it for one of these times instead?"
                        except Exception as find_err:
                            logger.debug(f"Could not find alternative times: {find_err}")
                            response += "\n\nWould you like me to help you find another spot?"
                    else:
                        response += "\n\nWould you like me to help you find another spot?"
                
                return response
            
            logger.error(f"CalendarTool error: {e}", exc_info=True)
            if workflow_emitter:
                self.emit_action_event(workflow_emitter, 'error', f"Calendar {action} failed: {str(e)}", action=action, error=str(e))
            return f"Error: {str(e)}"
    
    def _clean_query_text(self, text: str) -> str:
        """Helper to clean query text of date/time phrases and fillers"""
        if not text:
            return ""
        
        cleaned = text
        # Remove patterns from config
        patterns = ConfigDefaults.CALENDAR_DATE_CLEANUP_PATTERNS
        for pattern in patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            
        # Remove ISO datetimes
        cleaned = re.sub(r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?', '', cleaned)
        
        # Remove duration phrases
        cleaned = re.sub(r'(?:for\s+)?\d+\s*(?:hour|hr|minute|min)s?', '', cleaned, flags=re.IGNORECASE)
        
        # Remove filler words
        fillers = ConfigDefaults.CALENDAR_NLP_FILLER_WORDS
        for filler in fillers:
            cleaned = re.sub(rf'\b{filler}\b', '', cleaned, flags=re.IGNORECASE)
            
        return re.sub(r'\s+', ' ', cleaned).strip()

    async def _arun(self, action: str = "create", query: str = "", **kwargs) -> str:
        """Async execution"""
        # Run blocking _run method in a thread pool to avoid blocking the event loop
        return await asyncio.to_thread(self._run, action=action, query=query, **kwargs)
