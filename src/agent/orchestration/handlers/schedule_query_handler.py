"""
Schedule Query Handler - Handles schedule and time-based queries across calendar and tasks

This module provides intelligent handling of schedule-related queries that require:
- Calendar event information
- Task information
- Timezone awareness
- Time calculations (time until, time between, etc.)

Examples:
- "How much time do I have before my afternoon meeting?"
- "What time was my clavr standup meeting yesterday?"
- "What do I have between now and 8 pm?"
- "How much time is left before my next event?"

Architecture:
    Orchestrator → ScheduleQueryHandler → [CalendarTool, TaskTool] → Response Formatter
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import pytz

from ....utils.logger import setup_logger
from ....core.calendar.utils import (
    get_user_timezone,
    convert_to_user_timezone,
    get_utc_now
)
from ....utils.config import Config
from ...intent import TASK_KEYWORDS, CALENDAR_KEYWORDS
from ..config.cross_domain_config import CrossDomainConfig

logger = setup_logger(__name__)


class ScheduleQueryHandler:
    """
    Handles schedule and time-based queries that require calendar and task information
    
    Features:
    - Detects schedule-related query patterns
    - Fetches calendar events and tasks
    - Calculates time differences with timezone awareness
    - Formats natural language responses with contextual advice
    """
    
    # Configuration constants (no hardcoded values in responses)
    DEFAULT_DAYS_AHEAD = 7  # Default days to look ahead for events
    DEFAULT_DAYS_BACK = 0  # Default days to look back for events
    MAX_EVENTS_TO_FETCH = 50  # Maximum events to fetch per query
    MAX_TASKS_TO_FETCH = 50  # Maximum tasks to fetch per query
    MAX_NOTION_PAGES_TO_FETCH = 20  # Maximum Notion pages to fetch per query
    DEFAULT_NOTION_LOOKAHEAD_DAYS = 7  # Default days ahead for Notion search
    DEFAULT_TIME_RANGE_HOURS = 8  # Default hours for time range queries (only used as fallback)
    
    # Time constants
    END_OF_DAY_HOUR = 23
    END_OF_DAY_MINUTE = 59
    END_OF_DAY_SECOND = 59
    LATE_NIGHT_HOUR_THRESHOLD = 22  # 10 PM or later
    EARLY_MORNING_HOUR_THRESHOLD = 7  # Before 7 AM
    
    # LLM configuration constants
    LLM_TEMPERATURE = 0.7  # Temperature for LLM calls
    LLM_MAX_TOKENS = 4000  # Maximum tokens for LLM responses (prevents truncation)
    LLM_MAX_TOKENS_RETRY = 8000  # Higher max_tokens for retry if truncation detected
    SEMANTIC_MATCH_CONFIDENCE_THRESHOLD = 0.7  # Minimum confidence for semantic matching
    
    # Event display limits
    MAX_EVENTS_TO_DISPLAY = 10  # Maximum events to include in LLM prompt
    MAX_EVENTS_TO_DISPLAY_FALLBACK = 5  # Maximum events to display in fallback response
    MAX_DESCRIPTION_LENGTH_FOR_PROMPT = 200  # Maximum description length to include in LLM prompts
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize schedule query handler
        
        Args:
            config: Optional configuration object for timezone
        """
        self.config = config
        self.user_tz = pytz.timezone(get_user_timezone(config))
        
        # Schedule query patterns
        self.schedule_patterns = [
            {
                'pattern': r'\b(how much|how many)\s+(time|hours?|minutes?)\s+(do i have|left|until|before|till)',
                'type': 'time_until',
                'confidence': 0.9
            },
            {
                'pattern': r'\b(what|when)\s+(time|was|is)\s+(my|the)\s+.*(meeting|event|standup|call)',
                'type': 'event_time',
                'confidence': 0.85
            },
            {
                'pattern': r'\b(what|show|list)\s+(do i have|have i got|is there)\s+(between|from|until|before)',
                'type': 'time_range',
                'confidence': 0.9
            },
            {
                'pattern': r'\b(how long|how much time)\s+(until|before|till|to)\s+(my|the|next)',
                'type': 'time_until',
                'confidence': 0.85
            },
            {
                'pattern': r'\b(time|when)\s+(was|is)\s+.*(yesterday|today|tomorrow|last week)',
                'type': 'event_time',
                'confidence': 0.8
            },
            {
                'pattern': r'\b(what do i have|what have i got|what\'s on|what is on|what did i have)\s+(.*\s+)?(yesterday|today|tomorrow|last week|on my calendar)',
                'type': 'time_range',
                'confidence': 0.9
            },
            {
                'pattern': r'\b(what do i have|what have i got|what\'s on|what is on)\s+(between|from|until|before|till)',
                'type': 'time_range',
                'confidence': 0.9
            },
            {
                'pattern': r'\b(what did i have|what had i)\s+.*(yesterday|on my calendar yesterday)',
                'type': 'time_range',
                'confidence': 0.95
            },
            {
                'pattern': r'\b(how much|how many)\s+(time|hours?|minutes?)\s+(is left|until|before)',
                'type': 'time_until',
                'confidence': 0.85
            },
        ]
    
    def is_schedule_query(self, query: str) -> Tuple[bool, Optional[str], float]:
        """
        Detect if query is a schedule-related query using LLM-based understanding
        
        Args:
            query: User query
            
        Returns:
            Tuple of (is_schedule_query, query_type, confidence)
        """
        # Use LLM to understand semantic meaning, not just pattern matching
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            
            if self.config:
                llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE, max_tokens=self.LLM_MAX_TOKENS)
            else:
                llm = None
            
            if llm:
                prompt = f"""Analyze this query and determine if it's asking about TIME, SCHEDULING, or EVENT TIMES.

Query: "{query}"

CRITICAL RULES:
1. If the query explicitly mentions EMAILS (e.g., "email", "emails", "message", "inbox", "mail"), it is NOT a schedule query - it's an email query.
2. If the query explicitly mentions TASKS (e.g., "tasks", "task", "todo", "reminder"), it is NOT a schedule query - it's a task query.

Is this query asking about:
- Time until something? (e.g., "how much time before", "how long until")
- What time something is/was? (e.g., "what time is my meeting", "when was my standup")
- What events are in a time range? (e.g., "what do I have between now and 8pm")
- What events happened in the past? (e.g., "what did I have yesterday", "what was on my calendar yesterday")
- Time calculations or scheduling awareness?

EXAMPLES:
- "What new emails do I have today" → is_schedule_query: false (explicitly about emails)
- "What emails are in my inbox" → is_schedule_query: false (explicitly about emails)
- "What's on my tasks today" → is_schedule_query: false (explicitly about tasks)
- "What tasks do I have" → is_schedule_query: false (explicitly about tasks)
- "What time is my meeting" → is_schedule_query: true (asking about event time)
- "How much time before my meeting" → is_schedule_query: true (time calculation)
- "What do I have today" → is_schedule_query: true (asking about schedule, no explicit domain)
- "What did I have on my calendar yesterday" → is_schedule_query: true (asking about past events)
- "What was on my calendar yesterday" → is_schedule_query: true (asking about past events)

Respond with ONLY valid JSON:
{{
    "is_schedule_query": true/false,
    "query_type": "time_until" | "event_time" | "time_range" | null,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

                response = llm.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Ensure response_text is a string
                if not isinstance(response_text, str):
                    response_text = str(response_text) if response_text else ""
                
                # Parse JSON response
                import json
                if response_text:
                    json_match = re.search(r'\{[\s\S]*\}', response_text)
                    if json_match:
                        result = json.loads(json_match.group(0))
                        if result.get('is_schedule_query', False) or result.get('is_temporal', False):
                            query_type = result.get('query_type')
                            confidence = result.get('confidence', self.SEMANTIC_MATCH_CONFIDENCE_THRESHOLD)
                            logger.info(f"[SCHEDULE] LLM detected schedule query: '{query}' → {query_type} (confidence: {confidence})")
                            return True, query_type, confidence
        except Exception as e:
            logger.debug(f"[SCHEDULE] LLM detection failed, falling back to patterns: {e}")
        
        # Fallback to pattern matching if LLM unavailable
        query_lower = query.lower()
        
        # CRITICAL: If query explicitly mentions emails, it's NOT a schedule query
        email_keywords = ['email', 'emails', 'message', 'messages', 'inbox', 'mail', 'unread', 'new email', 'new emails']
        if any(keyword in query_lower for keyword in email_keywords):
            logger.info(f"[SCHEDULE] Query explicitly about emails, not a schedule query: '{query}'")
            return False, None, 0.0  # Not a schedule query, it's an email query
        
        # CRITICAL: If query explicitly mentions tasks, it's NOT a schedule query
        if any(keyword in query_lower for keyword in TASK_KEYWORDS):
            # Only treat as schedule query if it's asking about TIME of tasks, not listing tasks
            time_keywords = ['what time', 'when is', 'when was', 'time until', 'how long']
            if not any(time_keyword in query_lower for time_keyword in time_keywords):
                logger.info(f"[SCHEDULE] Query explicitly about tasks, not a schedule query: '{query}'")
                return False, None, 0.0  # Not a schedule query, it's a task query
        
        for pattern_info in self.schedule_patterns:
            if re.search(pattern_info['pattern'], query_lower):
                logger.info(f"[SCHEDULE] Pattern detected schedule query: '{query}' → {pattern_info['type']}")
                return True, pattern_info['type'], pattern_info['confidence']
        
        return False, None, 0.0
    
    async def handle_schedule_query(
        self,
        query: str,
        calendar_tool: Any,
        task_tool: Any,
        notion_tool: Optional[Any] = None,
        workflow_emitter: Optional[Any] = None
    ) -> str:
        """
        Handle schedule query by fetching calendar, tasks, and Notion pages, then calculating times
        
        Args:
            query: User query
            calendar_tool: Calendar tool instance
            task_tool: Task tool instance
            notion_tool: Optional Notion tool instance
            workflow_emitter: Optional workflow event emitter for streaming events
            
        Returns:
            Natural language response or None if not a schedule query
        """
        # CRITICAL: Double-check this is actually a schedule query
        # Never handle email queries - they should go to email tool
        query_lower = query.lower()
        email_keywords = ['email', 'emails', 'message', 'messages', 'inbox', 'mail', 'unread', 'new email', 'new emails']
        if any(keyword in query_lower for keyword in email_keywords):
            logger.warning(f"[SCHEDULE] CRITICAL: Email query incorrectly routed to schedule handler: '{query}' - returning None")
            return None  # This should never happen, but safety check
        
        is_schedule, query_type, confidence = self.is_schedule_query(query)
        
        if not is_schedule:
            return None  # Not a schedule query
        
        logger.info(f"[SCHEDULE] Handling schedule query: '{query}' (type: {query_type})")
        
        # Emit workflow event for schedule query processing
        if workflow_emitter:
            try:
                from ...events.workflow_events import WorkflowEventType
                await workflow_emitter.emit_action_executing(
                    f"Processing schedule query: {query_type}",
                    data={'query_type': query_type, 'query': query}
                )
            except Exception as e:
                logger.debug(f"[SCHEDULE] Failed to emit workflow event: {e}")
        
        try:
            # Get current time in user's timezone
            now_utc = get_utc_now()
            now_user = convert_to_user_timezone(now_utc, self.config)
            
            # Fetch calendar events, tasks, and Notion pages
            events = await self._fetch_events(calendar_tool, query, now_user)
            tasks = await self._fetch_tasks(task_tool, query, now_user)
            notion_pages = await self._fetch_notion(notion_tool, query, now_user) if notion_tool else []
            
            # Handle based on query type
            if query_type == 'time_until':
                return self._handle_time_until(query, events, tasks, notion_pages, now_user)
            elif query_type == 'event_time':
                return self._handle_event_time(query, events, now_user)
            elif query_type == 'time_range':
                return self._handle_time_range(query, events, tasks, notion_pages, now_user)
            else:
                return self._handle_generic_schedule(query, events, tasks, notion_pages, now_user)
                
        except Exception as e:
            logger.error(f"[SCHEDULE] Error handling schedule query: {e}", exc_info=True)
            return f"I encountered an error while processing your time-based query. Could you try rephrasing it?"
    
    async def _fetch_events(self, calendar_tool: Any, query: str, now_user: datetime) -> List[Dict[str, Any]]:
        """Fetch relevant calendar events with intelligent date range detection"""
        try:
            # Extract search criteria to determine date range
            criteria = self._extract_search_criteria(query)
            date_str = criteria.get('date')
            
            # Calculate date range based on query (dynamic, no hardcoded values)
            days_ahead = self.DEFAULT_DAYS_AHEAD
            days_back = self.DEFAULT_DAYS_BACK
            
            # CRITICAL: Check for "yesterday" FIRST, before parsing date_str
            # This ensures we always handle yesterday queries correctly
            query_lower = query.lower()
            if "yesterday" in query_lower:
                days_back = 1
                days_ahead = 0  # Don't fetch future events for yesterday queries
                logger.info(f"[SCHEDULE] Yesterday query detected in query, fetching events from {days_back} day(s) back only")
            elif date_str:
                # Parse the date to determine how far ahead/back to fetch
                target_date = self._parse_date_from_query(date_str, now_user)
                if target_date:
                    days_diff = (target_date.date() - now_user.date()).days
                    if days_diff > 0:
                        # Future date - fetch enough days ahead (dynamic based on target date)
                        days_ahead = max(days_diff + 1, self.DEFAULT_DAYS_AHEAD)
                        days_back = 0
                    elif days_diff < 0:
                        # Past date - fetch enough days back (dynamic based on target date)
                        days_back = abs(days_diff) + 1
                        days_ahead = 0  # Don't fetch future events for past dates
                        logger.info(f"[SCHEDULE] Past date query detected: '{date_str}', fetching events from {days_back} day(s) back only")
                    else:
                        # Today - only need today's events
                        days_ahead = 1
                        days_back = 0
                else:
                    # Date parsing failed, check query directly for "yesterday"
                    if "yesterday" in query_lower:
                        days_back = 1
                        days_ahead = 0
                        logger.info(f"[SCHEDULE] Yesterday query detected (date parsing failed), fetching events from {days_back} day(s) back only")
            else:
                # Extract time range from query as fallback
                end_time = self._extract_end_time(query, now_user)
                if end_time:
                    days_ahead = max(1, (end_time - now_user).days + 1)
                    days_back = 0
            
            # Get raw events from calendar client
            # CalendarTool has _parser.google_client, not calendar_service
            calendar_client = None
            
            # Try calendar_service first (if it exists - for backward compatibility)
            if hasattr(calendar_tool, 'calendar_service') and calendar_tool.calendar_service:
                calendar_client = calendar_tool.calendar_service
                logger.info("[SCHEDULE] Using calendar_service")
            else:
                # CRITICAL: Always initialize parser to ensure google_client is set
                # The parser might have been initialized without credentials earlier
                if hasattr(calendar_tool, '_initialize_parser'):
                    try:
                        calendar_tool._initialize_parser()
                        logger.info("[SCHEDULE] Parser initialized")
                    except Exception as e:
                        logger.warning(f"[SCHEDULE] Failed to initialize parser: {e}")
                
                # If parser exists but google_client is not set, try to set it now if credentials are available
                if hasattr(calendar_tool, '_parser') and calendar_tool._parser:
                    if hasattr(calendar_tool._parser, 'google_client') and calendar_tool._parser.google_client:
                        calendar_client = calendar_tool._parser.google_client
                        logger.info("[SCHEDULE] Using parser.google_client")
                    else:
                        # Parser exists but google_client not set - try to set it if credentials are available
                        if hasattr(calendar_tool, 'credentials') and calendar_tool.credentials:
                            try:
                                from ...core.calendar.google_client import GoogleCalendarClient
                                calendar_tool._parser.google_client = GoogleCalendarClient(
                                    config=calendar_tool.config,
                                    credentials=calendar_tool.credentials
                                )
                                calendar_client = calendar_tool._parser.google_client
                                logger.info("[SCHEDULE] Created google_client from credentials")
                            except Exception as e:
                                logger.warning(f"[SCHEDULE] Failed to create google_client: {e}")
                        else:
                            logger.warning(f"[SCHEDULE] Parser exists but google_client not set and no credentials available. Has credentials attr: {hasattr(calendar_tool, 'credentials')}, Credentials value: {getattr(calendar_tool, 'credentials', None)}")
                else:
                    logger.warning(f"[SCHEDULE] Parser not initialized. Has _initialize_parser: {hasattr(calendar_tool, '_initialize_parser')}")
            
            if calendar_client and hasattr(calendar_client, 'list_events'):
                logger.info(f"[SCHEDULE] Fetching events: days_back={days_back}, days_ahead={days_ahead} (query: '{query}')")
                try:
                    events = calendar_client.list_events(
                        days_ahead=days_ahead,
                        days_back=days_back,
                        max_results=self.MAX_EVENTS_TO_FETCH  # CRITICAL: Pass max_results to ensure we get all events
                    )
                    logger.info(f"[SCHEDULE] Retrieved {len(events)} events from calendar client")
                    return events[:self.MAX_EVENTS_TO_FETCH]  # Use configurable limit
                except Exception as e:
                    logger.error(f"[SCHEDULE] Error calling list_events: {e}", exc_info=True)
                    return []
            else:
                logger.warning(f"[SCHEDULE] Calendar client not available. Has calendar_service: {hasattr(calendar_tool, 'calendar_service')}, Has _parser: {hasattr(calendar_tool, '_parser')}, Parser initialized: {hasattr(calendar_tool, '_parser') and calendar_tool._parser is not None}, Has google_client: {hasattr(calendar_tool, '_parser') and calendar_tool._parser and hasattr(calendar_tool._parser, 'google_client')}, Has credentials: {hasattr(calendar_tool, 'credentials') and calendar_tool.credentials is not None}")
            
            return []
        except Exception as e:
            logger.warning(f"[SCHEDULE] Error fetching events: {e}")
            return []
    
    async def _fetch_tasks(self, task_tool: Any, query: str, now_user: datetime) -> List[Dict[str, Any]]:
        """
        Fetch relevant tasks
        
        CRITICAL: Only fetch tasks if the query explicitly mentions tasks or asks about both calendar and tasks.
        Do NOT fetch tasks for calendar-only queries.
        """
        # CRITICAL: Check if query explicitly mentions tasks
        query_lower = query.lower()
        has_task_keywords = any(keyword in query_lower for keyword in TASK_KEYWORDS)
        
        # If query is calendar-only (mentions calendar/events/meetings but NOT tasks), don't fetch tasks
        has_calendar_keywords = any(keyword in query_lower for keyword in CALENDAR_KEYWORDS)
        
        if has_calendar_keywords and not has_task_keywords:
            # Calendar-only query - don't fetch tasks
            logger.info(f"[SCHEDULE] Calendar-only query detected, skipping task fetch: '{query}'")
            return []
        
        try:
            # Extract time range from query
            end_time = self._extract_end_time(query, now_user)
            
            # Get raw tasks from service directly
            if hasattr(task_tool, 'task_service'):
                tasks = task_tool.task_service.list_tasks(status="pending", limit=self.MAX_TASKS_TO_FETCH)
                return tasks
            
            return []
        except Exception as e:
            logger.warning(f"[SCHEDULE] Error fetching tasks: {e}")
            return []
    
    async def _fetch_notion(self, notion_tool: Any, query: str, now_user: datetime) -> List[Dict[str, Any]]:
        """
        Fetch relevant Notion pages with date properties
        
        CRITICAL: Only fetch Notion pages if the query explicitly mentions Notion or asks about schedule across platforms.
        Do NOT fetch Notion for calendar/task-only queries.
        """
        if not notion_tool:
            return []
        
        # CRITICAL: Check if query explicitly mentions Notion
        query_lower = query.lower()
        has_notion_keywords = any(keyword in query_lower for keyword in CrossDomainConfig.NOTION_KEYWORDS)
        
        # If query is calendar/task-only (mentions calendar/events/meetings/tasks but NOT Notion), don't fetch Notion
        has_calendar_keywords = any(keyword in query_lower for keyword in CALENDAR_KEYWORDS)
        has_task_keywords = any(keyword in query_lower for keyword in TASK_KEYWORDS)
        
        if (has_calendar_keywords or has_task_keywords) and not has_notion_keywords:
            # Calendar/task-only query - don't fetch Notion
            logger.info(f"[SCHEDULE] Calendar/task-only query detected, skipping Notion fetch: '{query}'")
            return []
        
        try:
            # Extract time range from query (dynamic, no hardcoded fallback)
            end_time = self._extract_end_time(query, now_user)
            if not end_time:
                # Only use default if query doesn't specify a time range
                end_time = now_user + timedelta(days=self.DEFAULT_NOTION_LOOKAHEAD_DAYS)
            
            # Search Notion for pages with date properties in the time range
            # Use NotionTool's search action which handles graph-grounded search
            if hasattr(notion_tool, '_run_async'):
                search_query = f"{query} date:{now_user.strftime('%Y-%m-%d')}"
                try:
                    search_result = await notion_tool._run_async(
                        action='search',
                        query=search_query
                    )
                    
                    # Parse search result - could be a string or dict
                    if isinstance(search_result, dict) and 'results' in search_result:
                        results = search_result['results']
                    elif isinstance(search_result, list):
                        results = search_result
                    else:
                        results = []
                    
                    # Filter results by date if they have date properties
                    notion_pages = []
                    for page in results[:self.MAX_NOTION_PAGES_TO_FETCH]:
                        if isinstance(page, dict):
                            # Check if page has date properties in the time range
                            if self._notion_page_in_time_range(page, now_user, end_time):
                                notion_pages.append(page)
                    return notion_pages
                except Exception as e:
                    logger.debug(f"[SCHEDULE] Notion search failed: {e}")
                    return []
            
            return []
        except Exception as e:
            logger.warning(f"[SCHEDULE] Error fetching Notion pages: {e}")
            return []
    
    def _notion_page_in_time_range(
        self,
        page: Dict[str, Any],
        start_time: datetime,
        end_time: datetime
    ) -> bool:
        """Check if a Notion page has a date property within the time range"""
        try:
            if 'properties' not in page:
                return False
            
            # Check all date properties in the page
            for prop_name, prop_data in page.get('properties', {}).items():
                if isinstance(prop_data, dict):
                    prop_type = prop_data.get('type')
                    if prop_type == 'date':
                        date_value = prop_data.get('date')
                        if date_value:
                            # Handle both single date and date range
                            if isinstance(date_value, dict):
                                page_date_str = date_value.get('start')
                            elif isinstance(date_value, str):
                                page_date_str = date_value
                            else:
                                continue
                            
                            if page_date_str:
                                try:
                                    page_date = datetime.fromisoformat(page_date_str.replace('Z', '+00:00'))
                                    if page_date.tzinfo:
                                        page_date = page_date.astimezone(self.user_tz)
                                    else:
                                        page_date = self.user_tz.localize(page_date)
                                    
                                    # Check if date is in range
                                    if start_time <= page_date <= end_time:
                                        return True
                                except (ValueError, AttributeError):
                                    continue
            
            return False
        except Exception as e:
            logger.debug(f"[SCHEDULE] Error checking Notion page date: {e}")
            return False
    
    def _extract_end_time(self, query: str, now_user: datetime) -> Optional[datetime]:
        """Extract end time from query (e.g., '8 pm', 'tomorrow', 'end of day')"""
        query_lower = query.lower()
        
        # Extract "8 pm", "8pm", "20:00", etc.
        time_match = re.search(r'(\d{1,2})\s*(pm|am|:00|:30)', query_lower)
        if time_match:
            hour = int(time_match.group(1))
            period = time_match.group(2) if len(time_match.groups()) > 1 else None
            
            if period and 'pm' in period and hour < 12:
                hour += 12
            elif period and 'am' in period and hour == 12:
                hour = 0
            
            end_time = now_user.replace(hour=hour, minute=0, second=0, microsecond=0)
            if end_time < now_user:
                end_time += timedelta(days=1)
            return end_time
        
        # Extract "tomorrow", "next week", etc.
        if "tomorrow" in query_lower:
            return (now_user + timedelta(days=1)).replace(
                hour=self.END_OF_DAY_HOUR,
                minute=self.END_OF_DAY_MINUTE,
                second=self.END_OF_DAY_SECOND
            )
        if "end of day" in query_lower or "end of today" in query_lower:
            return now_user.replace(
                hour=self.END_OF_DAY_HOUR,
                minute=self.END_OF_DAY_MINUTE,
                second=self.END_OF_DAY_SECOND
            )
        
        return None
    
    def _handle_time_until(
        self,
        query: str,
        events: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        notion_pages: List[Dict[str, Any]],
        now_user: datetime
    ) -> str:
        """Handle 'how much time until...' queries"""
        query_lower = query.lower()
        
        # Find next event
        next_event = self._find_next_event(events, now_user, query)
        
        if not next_event:
            return "You don't have any upcoming events scheduled."
        
        event_start = self._parse_event_time(next_event.get('start', {}))
        if not event_start:
            return f"I found **{next_event.get('title', 'an event')}** but couldn't determine its time."
        
        # Convert to user timezone
        event_start_user = self._convert_to_user_timezone(event_start)
        
        time_diff = event_start_user - now_user
        
        if time_diff.total_seconds() < 0:
            return f"**{next_event.get('title', 'That event')}** has already passed."
        
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)
        
        event_title = next_event.get('title', next_event.get('summary', 'your next event'))
        time_str = self._format_time_difference(hours, minutes)
        
        event_time_str = event_start_user.strftime('%I:%M %p')
        
        return f"You have {time_str} until **{event_title}** at {event_time_str}."
    
    def _categorize_event(self, event_title: str) -> str:
        """Categorize event type for contextual advice"""
        title_lower = event_title.lower()
        
        if any(word in title_lower for word in ['reading', 'read', 'book']):
            return 'reading'
        elif any(word in title_lower for word in ['workout', 'exercise', 'gym', 'run', 'fitness']):
            return 'fitness'
        elif any(word in title_lower for word in ['meeting', 'call', 'standup', 'sync']):
            return 'meeting'
        elif any(word in title_lower for word in ['sleep', 'bed', 'rest']):
            return 'rest'
        elif any(word in title_lower for word in ['meal', 'lunch', 'dinner', 'breakfast', 'eat']):
            return 'meal'
        elif any(word in title_lower for word in ['study', 'learn', 'course']):
            return 'learning'
        else:
            return 'general'
    
    def _generate_contextual_event_response(
        self,
        event_title: str,
        time_str: str,
        event_start_user: datetime,
        now_user: datetime,
        all_events: List[Dict[str, Any]],
        query: str
    ) -> str:
        """Generate contextual, conversational response with encouraging advice"""
        # Gather context for LLM
        event_hour = event_start_user.hour
        is_today = event_start_user.date() == now_user.date()
        is_late_night = event_hour >= self.LATE_NIGHT_HOUR_THRESHOLD
        is_early_morning = event_hour < self.EARLY_MORNING_HOUR_THRESHOLD
        
        # Count events today
        events_today = [
            e for e in all_events
            if self._parse_event_time(e.get('start', {})) and
            self._parse_event_time(e.get('start', {})).astimezone(self.user_tz).date() == now_user.date()
        ]
        event_count_today = len(events_today)
        
        # Determine event type/category from title
        event_type = self._categorize_event(event_title)
        
        # ALWAYS use LLM for conversational response - don't fall back to simple response
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            
            if self.config:
                llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE, max_tokens=self.LLM_MAX_TOKENS)
            else:
                llm = None
            
            if llm:
                prompt = f"""You are Clavr, a friendly and encouraging personal assistant. Generate a natural, conversational response about an event.

Event: "{event_title}"
Time: {time_str}
Event hour: {event_hour}:00
Is today: {is_today}
Is late night (10 PM+): {is_late_night}
Is early morning (before 7 AM): {is_early_morning}
Events today: {event_count_today}
Event type: {event_type}

User asked: "{query}"

CRITICAL: Generate a friendly, conversational response that:
1. Answers the question directly (what time the event is)
2. Provides contextual, encouraging advice based on:
   - Event type (e.g., "Reading" → encourage reading habits, "Workout" → encourage fitness)
   - Time of day (late night → suggest sleep, early morning → encourage)
   - Schedule density (many events → suggest rest/balance)
3. Be natural and warm, NOT robotic or formal
4. Keep it concise (1-2 sentences max)
5. ALWAYS include encouraging/helpful context - never just state the time
6. Format event titles in BOLD markdown: **Event Title** (NOT quotes)

CRITICAL FORMATTING RULE:
- Event titles MUST be formatted in bold markdown: **Event Title**
- Do NOT use quotes around titles: "Event Title" (WRONG)
- Do NOT use single quotes: 'Event Title' (WRONG)
- DO use bold markdown: **Event Title** (CORRECT)

Examples:
- Reading at 10:30 PM → "Your **Reading** event is at 10:30 PM today. Great to see you prioritizing reading! Just remember to get enough sleep afterward."
- Many events + late night → "Your event is at {time_str}. You've had a busy day with {event_count_today} events - make sure to rest well tonight!"
- Early morning workout → "Your event is at {time_str}. Starting early - that's dedication! Have a great session!"
- Reading event → "Your **Reading** event is at {time_str}. Love that you're making time for reading!"

IMPORTANT: Do NOT just say "'{event_title}' is at {time_str}." - always add encouraging context and format title in bold!

Response:"""

                response = llm.invoke([HumanMessage(content=prompt)])
                response_text = None
                was_truncated = False
                
                if hasattr(response, 'content') and response.content:
                    response_text = response.content
                    # Check for truncation indicators
                    if hasattr(response, 'response_metadata') and response.response_metadata:
                        metadata = response.response_metadata
                        if 'finish_reason' in metadata:
                            finish_reason = metadata['finish_reason']
                            if finish_reason == 'length':
                                was_truncated = True
                                logger.warning(f"[SCHEDULE] LLM response was TRUNCATED (finish_reason: {finish_reason})")
                                # Retry with higher max_tokens
                                try:
                                    logger.info("[SCHEDULE] Attempting to regenerate with higher max_tokens...")
                                    retry_llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE, max_tokens=self.LLM_MAX_TOKENS_RETRY)
                                    retry_response = retry_llm.invoke([HumanMessage(content=prompt)])
                                    if hasattr(retry_response, 'content') and retry_response.content:
                                        response_text = retry_response.content
                                        logger.info(f"[SCHEDULE] Retry successful - got {len(response_text)} chars")
                                        was_truncated = False
                                except Exception as retry_error:
                                    logger.warning(f"[SCHEDULE] Retry with higher max_tokens failed: {retry_error}")
                elif hasattr(response, 'content'):
                    response_text = response.content
                else:
                    response_text = str(response) if response else None
                
                if response_text and len(response_text.strip()) > 5:
                    logger.info(f"[SCHEDULE] Generated contextual response for event: {event_title}")
                    return response_text.strip()
                else:
                    logger.warning(f"[SCHEDULE] LLM returned empty or too short response: '{response_text}'")
        except Exception as e:
            logger.error(f"[SCHEDULE] Contextual response generation failed: {e}", exc_info=True)
        
        # Fallback: Generate a basic conversational response even without LLM
        # This ensures we never return the robotic "'Reading' is at 10:30 PM today."
        if event_type == 'reading':
            if is_late_night:
                return f"Your **Reading** event is at {time_str}. Great to see you prioritizing reading! Just remember to get enough sleep afterward."
            else:
                return f"Your **Reading** event is at {time_str}. Love that you're making time for reading!"
        elif event_type == 'fitness':
            if is_early_morning:
                return f"Your event is at {time_str}. Starting early - that's dedication! Have a great session!"
            else:
                return f"Your event is at {time_str}. Keep up the great work with your fitness routine!"
        elif event_count_today > 3 and is_late_night:
            return f"Your event is at {time_str}. You've had a busy day with {event_count_today} events - make sure to rest well tonight!"
        else:
            # Generic conversational fallback
            if event_start_user < now_user:
                return f"Your **{event_title}** event was at {time_str}."
            else:
                return f"Your **{event_title}** event is at {time_str}. Have a great time!"
    
    def _handle_event_time(
        self,
        query: str,
        events: List[Dict[str, Any]],
        now_user: datetime
    ) -> str:
        """Handle 'what time was...' queries with contextual, conversational responses"""
        query_lower = query.lower()
        
        # Extract event name from query (using LLM understanding)
        event_name = self._extract_event_name(query)
        
        # If query is asking for "next event" generically, find the next upcoming event
        if not event_name or any(phrase in query_lower for phrase in ['next event', 'next meeting', 'my next', 'the next', 'upcoming']):
            # Find the next upcoming event
            next_event = self._find_next_event(events, now_user, query)
            if next_event:
                matching_event = next_event
            else:
                matching_event = None
        else:
            # Find matching event using all criteria (title, date, time, description)
            matching_event = self._find_matching_event(events, event_name, query_lower, query)
        
        if not matching_event:
            if not event_name:
                return "You don't have any upcoming events scheduled."
            else:
                return f"I couldn't find an event matching **{event_name}**."
        
        event_start = self._parse_event_time(matching_event.get('start', {}))
        if not event_start:
            return f"I found **{matching_event.get('title', 'an event')}** but couldn't determine its time."
        
        # Convert to user timezone
        event_start_user = self._convert_to_user_timezone(event_start)
        
        event_title = matching_event.get('title', matching_event.get('summary', 'event'))
        
        # Format time based on whether it's today, tomorrow, or another day
        if event_start_user.date() == now_user.date():
            time_str = event_start_user.strftime('%I:%M %p today')
        elif event_start_user.date() == (now_user + timedelta(days=1)).date():
            time_str = event_start_user.strftime('%I:%M %p tomorrow')
        else:
            time_str = event_start_user.strftime('%I:%M %p on %B %d, %Y')
        
        # Generate contextual, conversational response using LLM
        return self._generate_contextual_event_response(
            event_title, time_str, event_start_user, now_user, events, query
        )
    
    def _handle_time_range(
        self,
        query: str,
        events: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        notion_pages: List[Dict[str, Any]],
        now_user: datetime
    ) -> str:
        """Handle 'what do I have between...' queries"""
        query_lower = query.lower()
        
        # CRITICAL: Initialize variables that will be used later
        has_task_keywords = any(keyword in query_lower for keyword in TASK_KEYWORDS)
        has_calendar_keywords = any(keyword in query_lower for keyword in CALENDAR_KEYWORDS)
        has_notion_keywords = any(keyword in query_lower for keyword in CrossDomainConfig.NOTION_KEYWORDS)
        end_time = None  # Will be set in each branch
        
        # CRITICAL: Extract date from query to check for specific date queries (past or future)
        criteria = self._extract_search_criteria(query)
        date_str = criteria.get('date')
        target_date = None
        
        # Parse the date if specified
        if date_str:
            target_date = self._parse_date_from_query(date_str, now_user)
        
        # CRITICAL: Check if query is asking about a specific date (past or future)
        # This handles queries like "next week Monday", "next Monday", "last week Friday", etc.
        if target_date:
            # Calculate date boundaries for the target date
            day_start = self._get_day_start(target_date)
            day_end = day_start + timedelta(days=1)
            end_time = day_end  # Set end_time for prompt building
            
            # Filter events to only include events from that specific date
            events_in_range = self._filter_by_time_range(events, day_start, day_end)
            
            logger.info(f"[SCHEDULE] Specific date query detected: '{date_str}', filtering {len(events)} events to {len(events_in_range)} events for date {target_date.date()}")
            
            # Filter tasks and Notion pages for that date if needed
            tasks_in_range = self._filter_tasks_by_time(tasks, day_start, day_end) if has_task_keywords else []
            notion_pages_in_range = [
                page for page in notion_pages 
                if self._notion_page_in_time_range(page, day_start, day_end)
            ] if has_notion_keywords or notion_pages else []
            
            # If no events found for that date, return appropriate message
            if not events_in_range and not tasks_in_range and not notion_pages_in_range:
                is_past = target_date.date() < now_user.date()
                date_display, _ = self._format_date_display(target_date, query_lower)
                return self._generate_empty_schedule_response(
                    date_display, is_past, has_calendar_keywords, has_task_keywords, has_notion_keywords
                )
            
            # Continue with LLM generation below (will use events_in_range which is already filtered)
        # CRITICAL: Check if query is asking about "yesterday" - if so, filter events from yesterday
        elif "yesterday" in query_lower:
            # Calculate yesterday's boundaries
            yesterday_start = self._get_day_start(now_user - timedelta(days=1))
            yesterday_end = yesterday_start + timedelta(days=1)
            
            # Set end_time for use in prompt building later
            end_time = yesterday_end
            
            # Filter events to only include events from yesterday
            events_in_range = self._filter_by_time_range(events, yesterday_start, yesterday_end)
            
            logger.info(f"[SCHEDULE] Time range query with 'yesterday' detected, filtering {len(events)} events to {len(events_in_range)} events for yesterday")
            
            # Filter tasks and Notion pages for yesterday if needed (keywords already initialized above)
            tasks_in_range = self._filter_tasks_by_time(tasks, yesterday_start, yesterday_end) if has_task_keywords else []
            notion_pages_in_range = [
                page for page in notion_pages 
                if self._notion_page_in_time_range(page, yesterday_start, yesterday_end)
            ] if has_notion_keywords or notion_pages else []
            
            # If no events found for yesterday, return appropriate message
            if not events_in_range and not tasks_in_range and not notion_pages_in_range:
                return self._generate_empty_schedule_response(
                    "yesterday", True, has_calendar_keywords, has_task_keywords, has_notion_keywords
                )
            
            # Continue with LLM generation below (will use events_in_range which is already filtered)
        elif "today" in query_lower:
            # CRITICAL: For "today" queries, filter events from START of today (00:00:00) to END of today (23:59:59)
            # This ensures we include ALL events from today, including past events like 5am
            today_start = self._get_day_start(now_user)
            today_end = today_start + timedelta(days=1)
            
            # Set end_time for use in prompt building later
            end_time = today_end
            
            # Filter events to only include events from today (full day)
            events_in_range = self._filter_by_time_range(events, today_start, today_end)
            
            logger.info(f"[SCHEDULE] Time range query with 'today' detected, filtering {len(events)} events to {len(events_in_range)} events for today (from {today_start} to {today_end})")
            
            # Filter tasks and Notion pages for today if needed (keywords already initialized above)
            tasks_in_range = self._filter_tasks_by_time(tasks, today_start, today_end) if has_task_keywords else []
            notion_pages_in_range = [
                page for page in notion_pages 
                if self._notion_page_in_time_range(page, today_start, today_end)
            ] if has_notion_keywords or notion_pages else []
            
            # If no events found for today, return appropriate message
            if not events_in_range and not tasks_in_range and not notion_pages_in_range:
                return self._generate_empty_schedule_response(
                    "today", False, has_calendar_keywords, has_task_keywords, has_notion_keywords
                )
            
            # Continue with LLM generation below (will use events_in_range which is already filtered)
        else:
            # Extract end time from query (dynamic, no hardcoded fallback)
            end_time = self._extract_end_time(query, now_user)
            if not end_time:
                # Only use default if query doesn't specify a time range
                # This is a fallback for queries like "what do I have" without a specific time
                end_time = now_user + timedelta(hours=self.DEFAULT_TIME_RANGE_HOURS)
            
            # Filter events, tasks, and Notion pages in range (keywords already initialized above)
            events_in_range = self._filter_by_time_range(events, now_user, end_time)
            tasks_in_range = self._filter_tasks_by_time(tasks, now_user, end_time) if has_task_keywords else []
            notion_pages_in_range = [
                page for page in notion_pages 
                if self._notion_page_in_time_range(page, now_user, end_time)
            ] if has_notion_keywords or notion_pages else []
        
        # CRITICAL: Check if user explicitly asked for a time range
        # Only mention time ranges if the query explicitly includes them
        user_explicitly_asked_for_time_range = any(phrase in query_lower for phrase in [
            'between', 'from', 'until', 'to', 'until', 'before', 'after'
        ]) and any(phrase in query_lower for phrase in [
            'now', 'today', 'pm', 'am', ':', 'hour', 'minute'
        ])
        
        # CRITICAL: Ensure tasks_in_range and notion_pages_in_range are initialized
        # For "today" and "yesterday" queries, they're already filtered above
        # For other queries, they're filtered in the else block above
        # But we need to ensure they exist for the code below
        if "today" not in query_lower and "yesterday" not in query_lower:
            # These should already be set in the else block above, but ensure they exist
            if 'tasks_in_range' not in locals():
                tasks_in_range = []
            if 'notion_pages_in_range' not in locals():
                notion_pages_in_range = []
        
        # If calendar-only query and no events, generate LLM response (don't hardcode time ranges)
        if has_calendar_keywords and not has_task_keywords and not has_notion_keywords:
            if not events_in_range:
                # Generate conversational response using LLM instead of hardcoded time range
                pass  # Fall through to LLM generation below
        elif not events_in_range and not tasks_in_range and not notion_pages_in_range:
            # Generate conversational response using LLM instead of hardcoded time range
            pass  # Fall through to LLM generation below
        
        # Generate conversational response using LLM instead of robotic format
        try:
            from ....ai.llm_factory import LLMFactory
            from ....ai.prompts import get_agent_system_prompt
            from langchain_core.messages import SystemMessage, HumanMessage
            import json
            
            # Prepare event and task data with time awareness
            event_data = self._prepare_event_data_for_llm(events_in_range, now_user)
            
            task_data = []
            # CRITICAL: Only include tasks if query explicitly mentions them
            if has_task_keywords:
                for task in tasks_in_range[:self.MAX_EVENTS_TO_DISPLAY]:
                    task_title = task.get('title', task.get('description', 'Untitled'))
                    due_date = task.get('due_date', task.get('due'))
                    time_str = None
                    if due_date:
                        try:
                            if isinstance(due_date, str):
                                due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                            else:
                                due_dt = due_date
                            if due_dt.tzinfo:
                                due_dt_user = due_dt.astimezone(self.user_tz)
                            else:
                                due_dt_user = self.user_tz.localize(due_dt)
                            time_str = due_dt_user.strftime('%I:%M %p').lstrip('0')
                        except:
                            pass
                    task_data.append({
                        'title': task_title,
                        'time': time_str
                    })
            
            notion_data = []
            # CRITICAL: Only include Notion pages if query explicitly mentions them
            if has_notion_keywords:
                for page in notion_pages_in_range[:self.MAX_EVENTS_TO_DISPLAY]:
                    page_title = page.get('title') or page.get('properties', {}).get('title', {}).get('title', [{}])[0].get('plain_text', 'Untitled')
                    # Extract date from page properties
                    page_date_str = None
                    for prop_name, prop_data in page.get('properties', {}).items():
                        if isinstance(prop_data, dict) and prop_data.get('type') == 'date':
                            date_value = prop_data.get('date')
                            if date_value:
                                page_date_str = date_value.get('start') if isinstance(date_value, dict) else date_value
                                break
                    time_str = None
                    if page_date_str:
                        try:
                            page_date = datetime.fromisoformat(page_date_str.replace('Z', '+00:00'))
                            if page_date.tzinfo:
                                page_date_user = page_date.astimezone(self.user_tz)
                            else:
                                page_date_user = self.user_tz.localize(page_date)
                            time_str = page_date_user.strftime('%I:%M %p').lstrip('0')
                        except:
                            pass
                    notion_data.append({
                        'title': page_title,
                        'time': time_str
                    })
            
            # Generate conversational response
            if self.config:
                llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE, max_tokens=self.LLM_MAX_TOKENS)
                if llm:
                    # CRITICAL: Only mention tasks/Notion in prompt if query explicitly asks for them
                    task_section = ""
                    if has_task_keywords:
                        task_section = f"\n\nTasks ({len(task_data)}):\n{json.dumps(task_data, indent=2) if task_data else 'None'}"
                    
                    notion_section = ""
                    if has_notion_keywords:
                        notion_section = f"\n\nNotion Pages ({len(notion_data)}):\n{json.dumps(notion_data, indent=2) if notion_data else 'None'}"
                    
                    # CRITICAL: Only include time range in prompt if user explicitly asked for it
                    # Ensure end_time is defined (it should be set in all code paths above)
                    time_range_section = ""
                    if user_explicitly_asked_for_time_range and end_time is not None:
                        time_range_section = f"\nTime range: {now_user.strftime('%I:%M %p')} to {end_time.strftime('%I:%M %p')}\n"
                    
                    prompt = f"""The user asked: "{query}"{time_range_section}
Current Time: {now_user.strftime('%I:%M %p').lstrip('0')}
Events ({len(event_data)}) - each event has 'is_past' field indicating if it already happened:
{json.dumps(event_data, indent=2) if event_data else 'None'}{task_section}{notion_section}

CRITICAL CONTENT RULES:
- ONLY mention calendar events if Events data is provided above
- ONLY mention tasks if Tasks data is provided above AND the query explicitly mentions tasks
- ONLY mention Notion pages if Notion Pages data is provided above AND the query explicitly mentions Notion
- DO NOT mention tasks if the query is ONLY about calendar events
- DO NOT mention Notion if the query is ONLY about calendar events or tasks
- DO NOT say "you don't have any tasks/Notion pages" unless the query explicitly asks about them
- DO NOT hallucinate or add information that wasn't requested

CRITICAL TIME AWARENESS RULE:
- Check the current time ({now_user.strftime('%I:%M %p').lstrip('0')}) against each event's time
- For events with 'is_past': true (event time < current time), use PAST TENSE:
  * "You HAD **a learning reminder** at 5:00 AM" (NOT "you have")
  * "You STARTED with **reading** at 5:00 AM" (NOT "you start")
- For events with 'is_past': false (event time > current time), use FUTURE/PRESENT TENSE:
  * "You WILL BE **reading later tonight** at 10:30 PM" (NOT "you have Reading")
  * "You HAVE **a reading session** coming up at 10:30 PM"
- Group past and future events naturally: "You started with **X** at 5 AM, and later tonight you'll be **doing Y** at 10:30 PM"

CRITICAL FORMATTING RULE - ABSOLUTELY NO QUOTES:
- Event titles MUST be formatted in bold markdown: **paraphrased reference**
- NEVER use quotes around titles: "Event Title" (WRONG - ABSOLUTELY FORBIDDEN)
- NEVER use single quotes: 'Event Title' (WRONG - ABSOLUTELY FORBIDDEN)
- Do NOT use commas to separate titles: Event Title, (WRONG)
- DO use bold markdown: **paraphrased reference** (CORRECT)
- PARAPHRASE naturally instead of repeating verbatim: "Reading" → "**reading**" or "**you'll be reading**" (NOT "**Reading**" or "'Reading'")

Generate a natural, conversational response that:
- Answers the query directly
- Mentions events{' and tasks' if has_task_keywords else ''}{' and Notion pages' if has_notion_keywords else ''} naturally in flowing sentences
- Formats ALL event, task, and Notion page titles in bold markdown: **Title**
- Uses contractions ("you've", "I've", "don't")
- Avoids robotic formats like "You have X event(s):" or bullet points
- Is warm and friendly

CRITICAL: Do NOT use formats like:
- "You have X event(s):"
- Bullet points (•, *, -)
- Numbered lists
- Quotes around titles: "Event Title" (use **Event Title** instead)

ABSOLUTE PROHIBITION - NEVER MENTION TIME RANGES:
- NEVER mention specific times or time ranges (e.g., "between now and 3:50 PM", "until 4:00 PM", "from now until...") UNLESS the user explicitly asked for a specific time range in their query
- NEVER calculate or infer an end time based on the current time - only use time references that the user explicitly mentioned
- For "today" queries, ONLY say "today" or "for today" - NEVER mention specific times like "until 3:50 PM" or "between now and..."
- For "tomorrow" queries, ONLY say "tomorrow" - NEVER mention specific times
- Match the user's level of specificity EXACTLY - if they didn't mention times, don't add times
- If no events found, say "You don't have anything scheduled for [time reference from query]" - NEVER add time ranges

Generate ONLY the conversational response:"""
                    
                    messages = [
                        SystemMessage(content=get_agent_system_prompt()),
                        HumanMessage(content=prompt)
                    ]
                    
                    response = llm.invoke(messages)
                    response_text = None
                    was_truncated = False
                    
                    if hasattr(response, 'content') and response.content:
                        response_text = response.content
                        # Check for truncation indicators
                        if hasattr(response, 'response_metadata') and response.response_metadata:
                            metadata = response.response_metadata
                            if 'finish_reason' in metadata:
                                finish_reason = metadata['finish_reason']
                                if finish_reason == 'length':
                                    was_truncated = True
                                    logger.warning(f"[SCHEDULE] LLM response was TRUNCATED (finish_reason: {finish_reason})")
                                    # Retry with higher max_tokens
                                    try:
                                        logger.info("[SCHEDULE] Attempting to regenerate with higher max_tokens...")
                                        retry_llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE, max_tokens=self.LLM_MAX_TOKENS_RETRY)
                                        retry_response = retry_llm.invoke(messages)
                                        if hasattr(retry_response, 'content') and retry_response.content:
                                            response_text = retry_response.content
                                            logger.info(f"[SCHEDULE] Retry successful - got {len(response_text)} chars")
                                            was_truncated = False
                                    except Exception as retry_error:
                                        logger.warning(f"[SCHEDULE] Retry with higher max_tokens failed: {retry_error}")
                    
                    if response_text:
                        return response_text.strip()
        except Exception as e:
            logger.warning(f"[SCHEDULE] Failed to generate conversational response: {e}")
        
        # Fallback to natural sentence format (NOT robotic)
        response_parts = []
        
        if events_in_range:
            event_descriptions = []
            for event in events_in_range[:self.MAX_EVENTS_TO_DISPLAY_FALLBACK]:
                event_start = self._parse_event_time(event.get('start', {}))
                if event_start:
                    event_start_user = self._convert_to_user_timezone(event_start)
                    time_str = event_start_user.strftime('%I:%M %p').lstrip('0')
                    event_descriptions.append(f"**{event.get('title', 'Untitled')}** at {time_str}")
            
            if event_descriptions:
                if len(event_descriptions) == 1:
                    response_parts.append(f"You've got {event_descriptions[0]}.")
                elif len(event_descriptions) == 2:
                    response_parts.append(f"You've got {event_descriptions[0]} and {event_descriptions[1]}.")
                else:
                    first_few = ", ".join(event_descriptions[:-1])
                    last_one = event_descriptions[-1]
                    response_parts.append(f"You've got {first_few}, and {last_one}.")
        
        if tasks_in_range:
            task_descriptions = []
            for task in tasks_in_range[:self.MAX_EVENTS_TO_DISPLAY_FALLBACK]:
                task_title = task.get('title', task.get('description', 'Untitled'))
                due_date = task.get('due_date', task.get('due'))
                if due_date:
                    try:
                        if isinstance(due_date, str):
                            due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                        else:
                            due_dt = due_date
                        due_dt_user = self._convert_to_user_timezone(due_dt)
                        time_str = due_dt_user.strftime('%I:%M %p').lstrip('0')
                        task_descriptions.append(f"{task_title} (due {time_str})")
                    except:
                        task_descriptions.append(task_title)
                else:
                    task_descriptions.append(task_title)
            
            if task_descriptions:
                if len(task_descriptions) == 1:
                    response_parts.append(f"You've got {task_descriptions[0]} on your task list.")
                elif len(task_descriptions) == 2:
                    response_parts.append(f"You've got {task_descriptions[0]} and {task_descriptions[1]} on your task list.")
                else:
                    first_few = ", ".join(task_descriptions[:-1])
                    last_one = task_descriptions[-1]
                    response_parts.append(f"You've got {first_few}, and {last_one} on your task list.")
        
        # CRITICAL: Fallback should not mention time ranges unless user explicitly asked
        if response_parts:
            return " ".join(response_parts)
        else:
            # Use natural language based on query, not hardcoded time ranges
            query_lower = query.lower()
            if "today" in query_lower:
                return self._generate_empty_schedule_response("today", False, True, False, False)
            elif "tomorrow" in query_lower:
                return self._generate_empty_schedule_response("tomorrow", False, True, False, False)
            elif "yesterday" in query_lower:
                return self._generate_empty_schedule_response("yesterday", True, True, False, False)
            else:
                return "You don't have anything scheduled."
    
    def _handle_generic_schedule(
        self,
        query: str,
        events: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        notion_pages: List[Dict[str, Any]],
        now_user: datetime
    ) -> str:
        """Handle generic schedule queries"""
        query_lower = query.lower()
        
        # CRITICAL: Check if query is asking about a specific date (past or future)
        # Extract date from query to determine the target date
        criteria = self._extract_search_criteria(query)
        date_str = criteria.get('date')
        
        # Parse the date if specified
        target_date = None
        if date_str:
            target_date = self._parse_date_from_query(date_str, now_user)
        elif "yesterday" in query_lower:
            target_date = self._get_day_start(now_user - timedelta(days=1))
        
        # If a specific date is mentioned, filter events to that specific date (past or future)
        if target_date:
            # Calculate date boundaries for the target date
            day_start = self._get_day_start(target_date)
            day_end = day_start + timedelta(days=1)
            
            # Filter events to only include events from that specific date
            filtered_events = self._filter_by_time_range(events, day_start, day_end)
            
            is_past = target_date.date() < now_user.date()
            is_future = target_date.date() > now_user.date()
            is_today = target_date.date() == now_user.date()
            
            logger.info(f"[SCHEDULE] Specific date query detected: '{date_str or 'yesterday'}', filtering {len(events)} events to {len(filtered_events)} events for date {target_date.date()} (past={is_past}, future={is_future}, today={is_today})")
            
            # If no events found for that date, return appropriate message
            if not filtered_events:
                date_display, _ = self._format_date_display(target_date, query_lower)
                return self._generate_empty_schedule_response(
                    date_display, is_past, True, False, False  # Calendar-only query
                )
            
            # Generate response with events from that date
            # Use the same LLM-based response generation as _handle_time_range
            try:
                from ....ai.llm_factory import LLMFactory
                from ....ai.prompts import get_agent_system_prompt
                from langchain_core.messages import SystemMessage, HumanMessage
                import json
                
                # Prepare event data
                event_data = self._prepare_event_data_for_llm(filtered_events, now_user)
                
                if self.config:
                    llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE, max_tokens=self.LLM_MAX_TOKENS)
                    if llm:
                        date_str_formatted = target_date.strftime('%B %d, %Y')
                        prompt = f"""The user asked: "{query}"

Events on {date_str_formatted} ({len(event_data)}):
{json.dumps(event_data, indent=2) if event_data else 'None'}

CRITICAL CONTENT RULES:
- Generate a natural, conversational response
- Use contractions ("you've", "I've", "don't", "can't")
- Write like you're talking to a friend, not writing a report
- Format event titles in BOLD using markdown: **Event Title** (NOT quotes)
- NEVER mention time ranges unless the user explicitly asked for them
- For "yesterday" queries, just say "yesterday" - don't mention specific times

CRITICAL: Do NOT use formats like:
- "You have X event(s):"
- Bullet points (•, *, -)
- Numbered lists
- Quotes around titles: "Event Title" (use **Event Title** instead)

Generate ONLY the conversational response:"""

                        system_prompt = get_agent_system_prompt()
                        if not system_prompt or not isinstance(system_prompt, str):
                            system_prompt = "You are Clavr, an intelligent personal assistant. Provide helpful, natural, conversational responses."
                        
                        messages = [
                            SystemMessage(content=system_prompt),
                            HumanMessage(content=prompt)
                        ]
                        
                        response = llm.invoke(messages)
                        response_text = None
                        was_truncated = False
                        
                        if hasattr(response, 'content') and response.content:
                            response_text = response.content
                            # Check for truncation indicators
                            if hasattr(response, 'response_metadata') and response.response_metadata:
                                metadata = response.response_metadata
                                if 'finish_reason' in metadata:
                                    finish_reason = metadata['finish_reason']
                                    if finish_reason == 'length':
                                        was_truncated = True
                                        logger.warning(f"[SCHEDULE] LLM response was TRUNCATED (finish_reason: {finish_reason})")
                                        # Retry with higher max_tokens
                                        try:
                                            logger.info("[SCHEDULE] Attempting to regenerate with higher max_tokens...")
                                            retry_llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE, max_tokens=self.LLM_MAX_TOKENS_RETRY)
                                            retry_response = retry_llm.invoke(messages)
                                            if hasattr(retry_response, 'content') and retry_response.content:
                                                response_text = retry_response.content
                                                logger.info(f"[SCHEDULE] Retry successful - got {len(response_text)} chars")
                                                was_truncated = False
                                        except Exception as retry_error:
                                            logger.warning(f"[SCHEDULE] Retry with higher max_tokens failed: {retry_error}")
                        elif hasattr(response, 'content'):
                            response_text = response.content
                        else:
                            response_text = str(response) if response else None
                        
                        if response_text and len(response_text.strip()) > 5:
                            logger.info(f"[SCHEDULE] Generated response for specific date query: '{date_str or 'yesterday'}' (date: {target_date.date()})")
                            return response_text.strip()
            except Exception as e:
                logger.warning(f"[SCHEDULE] LLM response generation failed for past date query: {e}")
            
            # Fallback: Simple formatted response
            event_titles = [f"**{e.get('title', 'Untitled')}**" for e in filtered_events[:self.MAX_EVENTS_TO_DISPLAY_FALLBACK]]
            date_display, verb = self._format_date_display(target_date, query_lower)
            
            if len(filtered_events) == 1:
                return f"You {verb} {event_titles[0]} {date_display}."
            elif len(filtered_events) <= self.MAX_EVENTS_TO_DISPLAY_FALLBACK:
                return f"You {verb} {', '.join(event_titles[:-1])}, and {event_titles[-1]} {date_display}."
            else:
                remaining = len(filtered_events) - self.MAX_EVENTS_TO_DISPLAY_FALLBACK
                return f"You {verb} {', '.join(event_titles)}, and {remaining} more event{'s' if remaining != 1 else ''} {date_display}."
        
        # Default: show what's coming up (for future/current queries)
        next_event = self._find_next_event(events, now_user, query)
        
        if next_event:
            event_start = self._parse_event_time(next_event.get('start', {}))
            if event_start:
                event_start_user = self._convert_to_user_timezone(event_start)
                
                time_diff = event_start_user - now_user
                hours = int(time_diff.total_seconds() // 3600)
                minutes = int((time_diff.total_seconds() % 3600) // 60)
                time_str = self._format_time_difference(hours, minutes)
                
                return f"Your next event is **{next_event.get('title', 'Untitled')}** in {time_str}."
        
        return "I couldn't find any upcoming events to answer your question."
    
    def _find_next_event(
        self,
        events: List[Dict[str, Any]],
        now_user: datetime,
        query: str
    ) -> Optional[Dict[str, Any]]:
        """Find the next upcoming event"""
        upcoming_events = []
        
        for event in events:
            event_start = self._parse_event_time(event.get('start', {}))
            if event_start:
                event_start_user = self._convert_to_user_timezone(event_start)
                
                if event_start_user > now_user:
                    upcoming_events.append((event_start_user, event))
        
        if not upcoming_events:
            return None
        
        # Sort by start time and return the earliest
        upcoming_events.sort(key=lambda x: x[0])
        
        # If query mentions specific event name, try to match
        event_name = self._extract_event_name(query)
        if event_name:
            for _, event in upcoming_events:
                if event_name.lower() in event.get('title', '').lower():
                    return event
        
        return upcoming_events[0][1]
    
    def _find_matching_event(
        self,
        events: List[Dict[str, Any]],
        event_name: Optional[str],
        query_lower: str,
        query: str
    ) -> Optional[Dict[str, Any]]:
        """Find event matching query using LLM-based semantic understanding with all criteria"""
        # Extract all criteria from query using LLM
        criteria = self._extract_search_criteria(query)
        
        # If no specific criteria, return the next upcoming event
        if not criteria.get('title') and not criteria.get('date') and not criteria.get('time') and not criteria.get('description'):
            # Check if query is asking for "next event" generically
            if any(phrase in query_lower for phrase in ['next event', 'next meeting', 'my next', 'the next', 'upcoming']):
                # Return the first/earliest event (already sorted by _find_next_event)
                if events:
                    return events[0] if isinstance(events[0], dict) else None
                return None
        
        # Use LLM-based semantic matching that considers all criteria
        best_match = None
        best_confidence = 0.0
        
        for event in events:
            match_result = self._semantic_match_event(event, criteria, query)
            if match_result and match_result.get('confidence', 0) > best_confidence:
                best_confidence = match_result.get('confidence', 0)
                best_match = event
        
        if best_match and best_confidence >= self.SEMANTIC_MATCH_CONFIDENCE_THRESHOLD:
            logger.info(f"[SCHEDULE] Found best match: '{best_match.get('title', '')}' (confidence: {best_confidence:.2f})")
            return best_match
        
        # Fallback: exact title match if no LLM match
        if criteria.get('title'):
            for event in events:
                title = event.get('title', event.get('summary', '')).lower()
                if criteria['title'].lower() in title:
                    logger.info(f"[SCHEDULE] Fallback exact title match: '{event.get('title', '')}'")
                    return event
        
        return None
    
    def _extract_search_criteria(self, query: str) -> Dict[str, Any]:
        """Extract search criteria (title, date, time, description) from query using LLM"""
        criteria = {
            'title': None,
            'date': None,
            'time': None,
            'description': None
        }
        
        if not self.config:
            return criteria
        
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            import json
            
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE)
            if not llm:
                return criteria
            
            prompt = f"""Extract search criteria from this query. The user wants to find a calendar event.

Query: "{query}"

Extract:
1. title: Event/meeting title (e.g., "Clavr AI meeting", "team standup")
2. date: Specific date mentioned (e.g., "November 20th", "November 20", "20th", "tomorrow", "today", "yesterday", "next week Monday", "next Monday", "Monday", "next week", "last week Friday")
3. time: Specific time mentioned (e.g., "2 pm", "2:00 PM", "at 8 am")
4. description: Any description or context mentioned

Examples:
- "What time do I have my Clavr AI meeting on November 20th?" → {{"title": "Clavr AI meeting", "date": "November 20th"}}
- "When is my meeting tomorrow at 2pm?" → {{"date": "tomorrow", "time": "2pm"}}
- "What time is the team standup?" → {{"title": "team standup"}}
- "What did I have on my calendar yesterday?" → {{"date": "yesterday"}}
- "What was on my calendar yesterday?" → {{"date": "yesterday"}}
- "What is on my calendar next week Monday?" → {{"date": "next week Monday"}}
- "What do I have next Monday?" → {{"date": "next Monday"}}
- "What's on my calendar Monday?" → {{"date": "Monday"}}
- "What did I have last week Friday?" → {{"date": "last week Friday"}}
- "What's on my schedule next week?" → {{"date": "next week"}}

CRITICAL: If a date is specified (like "November 20th", "next week Monday", "next Monday"), extract the FULL date phrase including modifiers like "next week", "next", "last week", "last". Preserve the exact wording so it can be parsed correctly.

Respond with ONLY valid JSON:
{{
    "title": "title or null",
    "date": "date or null",
    "time": "time or null",
    "description": "description or null"
}}"""

            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            if not isinstance(response_text, str):
                response_text = str(response_text) if response_text else ""
            
            if response_text:
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    criteria['title'] = result.get('title') or None
                    criteria['date'] = result.get('date') or None
                    criteria['time'] = result.get('time') or None
                    criteria['description'] = result.get('description') or None
                    
                    logger.info(f"[SCHEDULE] Extracted criteria: {criteria}")
        except Exception as e:
            logger.debug(f"[SCHEDULE] LLM criteria extraction failed: {e}")
        
        return criteria
    
    def _semantic_match_event(
        self,
        event: Dict[str, Any],
        criteria: Dict[str, Any],
        original_query: str
    ) -> Optional[Dict[str, Any]]:
        """Use LLM to semantically match an event against search criteria"""
        if not self.config:
            return None
        
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            import json
            
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE)
            if not llm:
                return None
            
            # Get event details
            event_title = event.get('title', event.get('summary', ''))
            event_start = self._parse_event_time(event.get('start', {}))
            event_date_str = None
            event_date_short = None
            event_time_str = None
            
            if event_start:
                event_start_user = self._convert_to_user_timezone(event_start)
                
                event_date_str = event_start_user.strftime('%B %d, %Y')  # "November 20, 2025"
                event_date_short = event_start_user.strftime('%B %d')  # "November 20"
                event_time_str = event_start_user.strftime('%I:%M %p')  # "02:00 PM"
            
            event_description = event.get('description', '')
            event_description_truncated = (
                event_description[:self.MAX_DESCRIPTION_LENGTH_FOR_PROMPT] 
                if event_description else 'none'
            )
            
            # Parse criteria date to compare
            criteria_date_str = None
            if criteria.get('date'):
                criteria_date_parsed = self._parse_date_from_query(criteria.get('date'), datetime.now(self.user_tz))
                if criteria_date_parsed:
                    criteria_date_str = criteria_date_parsed.strftime('%B %d, %Y')
            
            prompt = f"""Does this calendar event match the user's search criteria?

User's query: "{original_query}"
Search criteria:
- Title: {criteria.get('title') or 'not specified'}
- Date: {criteria.get('date') or 'not specified'} {f'({criteria_date_str})' if criteria_date_str else ''}
- Time: {criteria.get('time') or 'not specified'}
- Description: {criteria.get('description') or 'not specified'}

Event details:
- Title: "{event_title}"
- Date: {event_date_str or 'unknown'} (also: {event_date_short or 'unknown'})
- Time: {event_time_str or 'unknown'}
- Description: "{event_description_truncated}"

CRITICAL PRIORITY RULES:
1. If DATE is specified in criteria → Event MUST match that date (highest priority)
   - "November 20th" matches "November 20, 2025" or "November 20"
   - "tomorrow" matches the day after today
   - Date matching is EXACT - if date doesn't match, confidence should be 0.0
2. If TITLE is specified → Event should match that title (high priority)
   - "Clavr AI meeting" matches "Clavr AI meeting" or "1:1 Clavr meeting"
   - Use semantic understanding, not just exact match
3. If TIME is specified → Event should match that time (medium priority)
   - "2 pm" matches "2:00 PM" or "14:00"
4. If DESCRIPTION is specified → Event should match that description (low priority)

Examples:
- Query: "Clavr AI meeting on November 20th" → Must match date "November 20th" AND title "Clavr AI meeting"
- Query: "meeting tomorrow at 2pm" → Must match date "tomorrow" AND time "2pm"
- Query: "Clavr AI meeting" → Should match title "Clavr AI meeting" (any date)

IMPORTANT: If date is specified and doesn't match, return {{"matches": false, "confidence": 0.0}}

Respond with ONLY valid JSON:
{{
    "matches": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            if not isinstance(response_text, str):
                response_text = str(response_text) if response_text else ""
            
            if response_text:
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    if result.get('matches', False):
                        logger.info(f"[SCHEDULE] Semantic match: '{event_title}' → confidence: {result.get('confidence', 0):.2f}, reasoning: {result.get('reasoning', '')}")
                        return result
        except Exception as e:
            logger.debug(f"[SCHEDULE] Semantic matching failed: {e}")
        
        return None
    
    def _parse_date_from_query(self, date_str: str, now_user: datetime) -> Optional[datetime]:
        """Parse date string to datetime, handling relative dates like 'tomorrow', 'next week Monday', 'November 20th'"""
        if not date_str:
            return None
        
        date_str_lower = date_str.lower().strip()
        
        # Handle simple relative dates first
        if date_str_lower == 'tomorrow':
            return self._get_day_start(now_user + timedelta(days=1))
        elif date_str_lower == 'today':
            return self._get_day_start(now_user)
        elif date_str_lower == 'yesterday':
            return self._get_day_start(now_user - timedelta(days=1))
        
        # Handle weekday names (Monday, Tuesday, etc.) and relative weekdays (next Monday, next week Monday, etc.)
        weekday_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        
        # Check for weekday patterns
        for weekday_name, weekday_num in weekday_map.items():
            if weekday_name in date_str_lower:
                # Calculate days until next occurrence of this weekday
                current_weekday = now_user.weekday()
                days_until_weekday = (weekday_num - current_weekday) % 7
                if days_until_weekday == 0:
                    days_until_weekday = 7  # If today is that weekday, get next week's occurrence
                
                # Check for "next week" or "next" modifier
                if 'next week' in date_str_lower or ('next' in date_str_lower and 'week' in date_str_lower):
                    # "next week Monday" - get Monday of next week
                    days_until_weekday = 7 + (weekday_num - current_weekday) % 7
                    if (weekday_num - current_weekday) % 7 == 0:
                        days_until_weekday = 7  # If today is Monday, "next week Monday" is 7 days away
                elif 'next' in date_str_lower and weekday_name in date_str_lower:
                    # "next Monday" - get the next occurrence (could be this week or next week)
                    days_until_weekday = (weekday_num - current_weekday) % 7
                    if days_until_weekday == 0:
                        days_until_weekday = 7
                elif 'last week' in date_str_lower or ('last' in date_str_lower and 'week' in date_str_lower):
                    # "last week Monday" - get Monday of last week
                    days_until_weekday = -7 + (weekday_num - current_weekday) % 7
                    if (weekday_num - current_weekday) % 7 == 0:
                        days_until_weekday = -7  # If today is Monday, "last week Monday" is 7 days ago
                elif 'last' in date_str_lower and weekday_name in date_str_lower:
                    # "last Monday" - get the most recent past occurrence
                    days_until_weekday = (weekday_num - current_weekday) % 7 - 7
                    if days_until_weekday == 0:
                        days_until_weekday = -7
                
                target_date = now_user + timedelta(days=days_until_weekday)
                return self._get_day_start(target_date)
        
        # Handle "next week" without a specific weekday (assume Monday of next week)
        if 'next week' in date_str_lower and not any(day in date_str_lower for day in weekday_map.keys()):
            current_weekday = now_user.weekday()
            days_until_next_monday = (7 - current_weekday) % 7
            if days_until_next_monday == 0:
                days_until_next_monday = 7
            target_date = now_user + timedelta(days=days_until_next_monday)
            return self._get_day_start(target_date)
        
        # Handle "last week" without a specific weekday (assume Monday of last week)
        if 'last week' in date_str_lower and not any(day in date_str_lower for day in weekday_map.keys()):
            current_weekday = now_user.weekday()
            days_since_last_monday = current_weekday + 7
            target_date = now_user - timedelta(days=days_since_last_monday)
            return self._get_day_start(target_date)
        
        # Try to parse absolute dates like "November 20th", "November 20", "20th"
        try:
            from dateutil import parser as date_parser
            # Try parsing with dateutil
            parsed_date = date_parser.parse(date_str, default=now_user)
            return self._get_day_start(parsed_date)
        except:
            # Try manual parsing for "November 20th" format
            month_names = {
                'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
                'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
            }
            
            for month_name, month_num in month_names.items():
                if month_name in date_str_lower:
                    # Extract day number
                    day_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)?', date_str_lower)
                    if day_match:
                        day = int(day_match.group(1))
                        year = now_user.year
                        # If the date is in the past, assume next year
                        try:
                            parsed = datetime(year, month_num, day)
                            if parsed < now_user:
                                parsed = datetime(year + 1, month_num, day)
                            return self._get_day_start(parsed)
                        except:
                            pass
        
        return None
    
    def _extract_event_name(self, query: str) -> Optional[str]:
        """Extract event name from query using LLM understanding"""
        # Use LLM to extract event name semantically
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            
            if self.config:
                llm = LLMFactory.get_llm_for_provider(self.config, temperature=self.LLM_TEMPERATURE, max_tokens=self.LLM_MAX_TOKENS)
            else:
                llm = None
            
            if llm:
                prompt = f"""Extract the specific event/meeting name from this query. If the query refers to "next event", "next meeting", "my next event", etc. without a specific name, return null.

Query: "{query}"

Examples:
- "What time is my Clavr standup?" → "Clavr standup"
- "What time was my team meeting yesterday?" → "team meeting"
- "What time is my next event?" → null (no specific name)
- "When is my afternoon meeting?" → "afternoon meeting" (if it's a specific named meeting)

Respond with ONLY valid JSON:
{{
    "event_name": "specific name or null",
    "reasoning": "brief explanation"
}}"""

                response = llm.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Ensure response_text is a string
                if not isinstance(response_text, str):
                    response_text = str(response_text) if response_text else ""
                
                import json
                if response_text:
                    json_match = re.search(r'\{[\s\S]*\}', response_text)
                    if json_match:
                        result = json.loads(json_match.group(0))
                        event_name = result.get('event_name')
                        if event_name and event_name.lower() != 'null':
                            logger.info(f"[SCHEDULE] LLM extracted event name: '{event_name}'")
                            return event_name
        except Exception as e:
            logger.debug(f"[SCHEDULE] LLM event name extraction failed, using patterns: {e}")
        
        # Fallback to pattern matching
        query_lower = query.lower()
        
        # Skip if it's a generic "next event" query
        if any(phrase in query_lower for phrase in ['next event', 'next meeting', 'my next', 'the next']):
            # Only extract if there's a specific name mentioned
            if 'clavr' in query_lower or 'standup' in query_lower or 'team' in query_lower:
                # Try to extract specific name
                pass
            else:
                return None  # Generic "next event" - don't extract name
        
        # Try to extract between "my" and "meeting/event/standup"
        match = re.search(r'my\s+([^meeting|event|standup|call]+?)\s+(meeting|event|standup|call)', query_lower)
        if match:
            name = match.group(1).strip()
            if name and len(name) > 1 and name not in ['next', 'upcoming', 'first', 'last']:
                return name
        
        # Try to extract after "the"
        match = re.search(r'the\s+([^meeting|event|standup|call]+?)\s+(meeting|event|standup|call)', query_lower)
        if match:
            name = match.group(1).strip()
            if name and len(name) > 1 and name not in ['next', 'upcoming', 'first', 'last']:
                return name
        
        # Try to extract before "meeting/event" (e.g., "clavr standup meeting")
        match = re.search(r'([a-z]+(?:\s+[a-z]+)?)\s+(meeting|event|standup|call)', query_lower)
        if match:
            name = match.group(1).strip()
            # Filter out common words
            if name and len(name) > 1 and name not in ['my', 'the', 'a', 'an', 'next', 'upcoming', 'first', 'last']:
                return name
        
        return None
    
    def _parse_event_time(self, start_obj: Any) -> Optional[datetime]:
        """Parse event start time from various formats"""
        if isinstance(start_obj, dict):
            # Google Calendar format: {'dateTime': '...'} or {'date': '...'}
            if 'dateTime' in start_obj:
                try:
                    return datetime.fromisoformat(start_obj['dateTime'].replace('Z', '+00:00'))
                except:
                    pass
            if 'date' in start_obj:
                try:
                    return datetime.fromisoformat(start_obj['date'])
                except:
                    pass
        elif isinstance(start_obj, str):
            try:
                return datetime.fromisoformat(start_obj.replace('Z', '+00:00'))
            except:
                pass
        elif isinstance(start_obj, datetime):
            return start_obj
        
        return None
    
    def _filter_by_time_range(
        self,
        events: List[Dict[str, Any]],
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Filter events within time range"""
        filtered = []
        
        for event in events:
            event_start = self._parse_event_time(event.get('start', {}))
            if event_start:
                event_start_user = self._convert_to_user_timezone(event_start)
                
                if start_time <= event_start_user <= end_time:
                    filtered.append(event)
        
        return filtered
    
    def _filter_tasks_by_time(
        self,
        tasks: List[Dict[str, Any]],
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Filter tasks within time range"""
        filtered = []
        
        for task in tasks:
            due_date = task.get('due_date', task.get('due'))
            if due_date:
                try:
                    if isinstance(due_date, str):
                        due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                    else:
                        due_dt = due_date
                    
                    due_dt_user = self._convert_to_user_timezone(due_dt)
                    
                    if start_time <= due_dt_user <= end_time:
                        filtered.append(task)
                except:
                    pass
        
        return filtered
    
    def _format_time_difference(self, hours: int, minutes: int) -> str:
        """Format time difference in natural language"""
        if hours == 0:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif minutes == 0:
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            return f"{hours} hour{'s' if hours != 1 else ''} and {minutes} minute{'s' if minutes != 1 else ''}"
    
    def _format_date_display(self, target_date: datetime, query_lower: str) -> Tuple[str, str]:
        """
        Format date for display in responses and determine appropriate verb.
        
        Args:
            target_date: The target date to format
            query_lower: Lowercase query string for context
            
        Returns:
            Tuple of (date_display, verb) where verb is "have" or "had"
        """
        if "yesterday" in query_lower:
            return "yesterday", "had"
        elif "tomorrow" in query_lower:
            return "tomorrow", "have"
        elif "today" in query_lower:
            return "today", "have"
        elif "next week" in query_lower or "next" in query_lower:
            weekday_name = target_date.strftime('%A')
            date_display = f"next {weekday_name}" if "next" in query_lower else f"{weekday_name}, {target_date.strftime('%B %d')}"
            return date_display, "have"
        elif "last week" in query_lower or "last" in query_lower:
            weekday_name = target_date.strftime('%A')
            date_display = f"last {weekday_name}" if "last" in query_lower else f"{weekday_name}, {target_date.strftime('%B %d')}"
            return date_display, "had"
        else:
            date_display = target_date.strftime('%A, %B %d, %Y')
            verb = "have" if target_date.date() >= datetime.now(self.user_tz).date() else "had"
            return date_display, verb
    
    def _generate_empty_schedule_response(
        self,
        date_display: str,
        is_past: bool,
        has_calendar_keywords: bool,
        has_task_keywords: bool,
        has_notion_keywords: bool
    ) -> str:
        """
        Generate response when no events/tasks/notion pages are found for a date.
        
        Args:
            date_display: Formatted date string for display
            is_past: Whether the date is in the past
            has_calendar_keywords: Whether query mentions calendar
            has_task_keywords: Whether query mentions tasks
            has_notion_keywords: Whether query mentions Notion
            
        Returns:
            Natural language response string
        """
        if has_calendar_keywords and not has_task_keywords and not has_notion_keywords:
            # Calendar-only query
            if is_past:
                return f"You didn't have anything scheduled for {date_display}."
            else:
                return f"You don't have anything scheduled for {date_display}."
        else:
            # Multi-domain or generic query
            if is_past:
                return f"You didn't have anything scheduled for {date_display}."
            else:
                return f"You don't have anything scheduled for {date_display}."
    
    def _prepare_event_data_for_llm(
        self,
        events: List[Dict[str, Any]],
        now_user: datetime,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Prepare event data for LLM prompt generation.
        
        Args:
            events: List of event dictionaries
            now_user: Current time in user timezone
            limit: Optional limit on number of events (defaults to MAX_EVENTS_TO_DISPLAY)
            
        Returns:
            List of event data dictionaries with title, time, and is_past flag
        """
        if limit is None:
            limit = self.MAX_EVENTS_TO_DISPLAY
        
        event_data = []
        for event in events[:limit]:
            event_start = self._parse_event_time(event.get('start', {}))
            if event_start:
                event_start_user = self._convert_to_user_timezone(event_start)
                time_str = event_start_user.strftime('%I:%M %p').lstrip('0')
                is_past = event_start_user < now_user
                event_data.append({
                    'title': event.get('title', 'Untitled'),
                    'time': time_str,
                    'is_past': is_past
                })
        return event_data
    
    def _convert_to_user_timezone(self, dt: datetime) -> datetime:
        """
        Convert datetime to user timezone.
        
        Args:
            dt: Datetime object (may be naive or timezone-aware)
            
        Returns:
            Datetime in user timezone
        """
        if dt.tzinfo:
            return dt.astimezone(self.user_tz)
        else:
            return self.user_tz.localize(dt)
    
    def _get_day_start(self, dt: datetime) -> datetime:
        """
        Get the start of a day (00:00:00) for a given datetime.
        
        Args:
            dt: Datetime object
            
        Returns:
            Datetime at the start of the day (00:00:00)
        """
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    
    def _get_day_end(self, dt: datetime) -> datetime:
        """
        Get the end of a day (23:59:59) for a given datetime.
        
        Args:
            dt: Datetime object
            
        Returns:
            Datetime at the end of the day (23:59:59)
        """
        return dt.replace(
            hour=self.END_OF_DAY_HOUR,
            minute=self.END_OF_DAY_MINUTE,
            second=self.END_OF_DAY_SECOND
        )

