"""
Time Query Handler - Handles time-based queries across calendar, tasks, and Notion

This module provides intelligent handling of time-based queries that require:
- Calendar event information
- Task information
- Notion page information (with date properties)
- Timezone awareness
- Time calculations (time until, time between, etc.)

Examples:
- "How much time do I have before my afternoon meeting?"
- "What time was my clavr standup meeting yesterday?"
- "What do I have between now and 8 pm?"
- "How much time is left before my next event?"
- "What Notion pages do I have scheduled today?"

Architecture:
    Orchestrator → TimeQueryHandler → [CalendarTool, TaskTool, NotionTool] → Response Formatter
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


class TimeQueryHandler:
    """
    Handles time-based queries that require calendar, task, and Notion information
    
    Features:
    - Detects time-based query patterns
    - Fetches calendar events, tasks, and Notion pages
    - Calculates time differences with timezone awareness
    - Formats natural language responses
    """
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize time query handler
        
        Args:
            config: Optional configuration object for timezone
        """
        self.config = config
        self.user_tz = pytz.timezone(get_user_timezone(config))
        
        # Time query patterns
        self.time_patterns = [
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
                'pattern': r'\b(what do i have|what have i got|what\'s on|what is on)\s+(between|from|until|before|till)',
                'type': 'time_range',
                'confidence': 0.9
            },
            {
                'pattern': r'\b(how much|how many)\s+(time|hours?|minutes?)\s+(is left|until|before)',
                'type': 'time_until',
                'confidence': 0.85
            },
        ]
    
    def is_time_query(self, query: str) -> Tuple[bool, Optional[str], float]:
        """
        Detect if query is a time-based query using LLM-based understanding
        
        Args:
            query: User query
            
        Returns:
            Tuple of (is_time_query, query_type, confidence)
        """
        # Use LLM to understand semantic meaning, not just pattern matching
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            
            llm = LLMFactory.get_llm()
            if llm:
                prompt = f"""Analyze this query and determine if it's asking about TIME, SCHEDULING, or EVENT TIMES.

Query: "{query}"

Is this query asking about:
- Time until something? (e.g., "how much time before", "how long until")
- What time something is/was? (e.g., "what time is my meeting", "when was my standup")
- What events/tasks are in a time range? (e.g., "what do I have between now and 8pm")
- Time calculations or scheduling awareness?

Respond with ONLY valid JSON:
{{
    "is_time_query": true/false,
    "query_type": "time_until" | "event_time" | "time_range" | null,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

                response = llm.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Parse JSON response
                import json
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    if result.get('is_time_query', False):
                        query_type = result.get('query_type')
                        confidence = result.get('confidence', 0.7)
                        logger.info(f"[TIME] LLM detected time query: '{query}' → {query_type} (confidence: {confidence})")
                        return True, query_type, confidence
        except Exception as e:
            logger.debug(f"[TIME] LLM detection failed, falling back to patterns: {e}")
        
        # Fallback to pattern matching if LLM unavailable
        query_lower = query.lower()
        
        for pattern_info in self.time_patterns:
            if re.search(pattern_info['pattern'], query_lower):
                logger.info(f"[TIME] Pattern detected time query: '{query}' → {pattern_info['type']}")
                return True, pattern_info['type'], pattern_info['confidence']
        
        return False, None, 0.0
    
    async def handle_time_query(
        self,
        query: str,
        calendar_tool: Any,
        task_tool: Any,
        notion_tool: Optional[Any] = None
    ) -> str:
        """
        Handle time-based query by fetching calendar, tasks, and Notion pages, then calculating times
        
        Args:
            query: User query
            calendar_tool: Calendar tool instance
            task_tool: Task tool instance
            notion_tool: Optional Notion tool instance
            
        Returns:
            Natural language response
        """
        is_time_query, query_type, confidence = self.is_time_query(query)
        
        if not is_time_query:
            return None  # Not a time query
        
        logger.info(f"[TIME] Handling time query: '{query}' (type: {query_type})")
        
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
                return self._handle_generic_time(query, events, tasks, notion_pages, now_user)
                
        except Exception as e:
            logger.error(f"[TIME] Error handling time query: {e}", exc_info=True)
            return f"I encountered an error while processing your time-based query. Could you try rephrasing it?"
    
    async def _fetch_events(self, calendar_tool: Any, query: str, now_user: datetime) -> List[Dict[str, Any]]:
        """Fetch relevant calendar events"""
        try:
            # Extract time range from query
            end_time = self._extract_end_time(query, now_user)
            
            # Fetch events up to end time (or default 7 days ahead)
            if end_time:
                days_ahead = max(1, (end_time - now_user).days + 1)
            else:
                days_ahead = 7
            
            # Also look back a bit for "yesterday" queries
            days_back = 1 if "yesterday" in query.lower() else 0
            
            # Get raw events from service directly
            if hasattr(calendar_tool, 'calendar_service'):
                events = calendar_tool.calendar_service.list_events(
                    days_ahead=days_ahead,
                    days_back=days_back
                )
                return events[:20]  # Limit to 20 events
            
            return []
        except Exception as e:
            logger.warning(f"[TIME] Error fetching events: {e}")
            return []
    
    async def _fetch_tasks(self, task_tool: Any, query: str, now_user: datetime) -> List[Dict[str, Any]]:
        """Fetch relevant tasks"""
        try:
            # Extract time range from query
            end_time = self._extract_end_time(query, now_user)
            
            # Get raw tasks from service directly
            if hasattr(task_tool, 'task_service'):
                tasks = task_tool.task_service.list_tasks(status="pending", limit=50)
                return tasks
            
            return []
        except Exception as e:
            logger.warning(f"[TIME] Error fetching tasks: {e}")
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
            logger.info(f"[TIME] Calendar/task-only query detected, skipping Notion fetch: '{query}'")
            return []
        
        try:
            # Extract time range from query
            end_time = self._extract_end_time(query, now_user) or (now_user + timedelta(days=7))
            
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
                    for page in results[:20]:
                        if isinstance(page, dict):
                            # Check if page has date properties in the time range
                            if self._notion_page_in_time_range(page, now_user, end_time):
                                notion_pages.append(page)
                    return notion_pages
                except Exception as e:
                    logger.debug(f"[TIME] Notion search failed: {e}")
                    return []
            
            return []
        except Exception as e:
            logger.warning(f"[TIME] Error fetching Notion pages: {e}")
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
            logger.debug(f"[TIME] Error checking Notion page date: {e}")
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
            return (now_user + timedelta(days=1)).replace(hour=23, minute=59, second=59)
        if "end of day" in query_lower or "end of today" in query_lower:
            return now_user.replace(hour=23, minute=59, second=59)
        
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
            return f"I found '{next_event.get('title', 'an event')}' but couldn't determine its time."
        
        # Convert to user timezone
        if event_start.tzinfo:
            event_start_user = event_start.astimezone(self.user_tz)
        else:
            event_start_user = self.user_tz.localize(event_start)
        
        time_diff = event_start_user - now_user
        
        if time_diff.total_seconds() < 0:
            return f"'{next_event.get('title', 'That event')}' has already passed."
        
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)
        
        event_title = next_event.get('title', next_event.get('summary', 'your next event'))
        time_str = self._format_time_difference(hours, minutes)
        
        event_time_str = event_start_user.strftime('%I:%M %p')
        
        return f"You have {time_str} until '{event_title}' at {event_time_str}."
    
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
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            
            llm = LLMFactory.get_llm()
            if not llm:
                # Fallback to simple response
                if event_start_user < now_user:
                    return f"'{event_title}' was at {time_str}."
                else:
                    return f"'{event_title}' is at {time_str}."
            
            # Gather context for LLM
            event_hour = event_start_user.hour
            is_today = event_start_user.date() == now_user.date()
            is_late_night = event_hour >= 22  # 10 PM or later
            is_early_morning = event_hour < 7  # Before 7 AM
            
            # Count events today
            events_today = [
                e for e in all_events
                if self._parse_event_time(e.get('start', {})) and
                self._parse_event_time(e.get('start', {})).astimezone(self.user_tz).date() == now_user.date()
            ]
            event_count_today = len(events_today)
            
            # Determine event type/category from title
            event_type = self._categorize_event(event_title)
            
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

Generate a friendly, conversational response that:
1. Answers the question directly (what time the event is)
2. Provides contextual, encouraging advice based on:
   - Event type (e.g., "Reading" → encourage reading habits)
   - Time of day (late night → suggest sleep, early morning → encourage)
   - Schedule density (many events → suggest rest/balance)
3. Be natural and warm, not robotic
4. Keep it concise (1-2 sentences max)
5. Only provide advice if it's genuinely helpful and relevant

Examples:
- Reading at 10:30 PM → "Your 'Reading' event is at 10:30 PM today. Great to see you prioritizing reading! Just remember to get enough sleep afterward."
- Many events + late night → "Your event is at {time_str}. You've had a busy day with {event_count_today} events - make sure to rest well tonight!"
- Early morning workout → "Your event is at {time_str}. Starting early - that's dedication! Have a great session!"

Response:"""

            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            if response_text and len(response_text.strip()) > 10:
                logger.info(f"[TIME] Generated contextual response for event: {event_title}")
                return response_text.strip()
        except Exception as e:
            logger.debug(f"[TIME] Contextual response generation failed: {e}")
        
        # Fallback to simple response
        if event_start_user < now_user:
            return f"'{event_title}' was at {time_str}."
        else:
            return f"'{event_title}' is at {time_str}."
    
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
            # Find matching event by name
            matching_event = self._find_matching_event(events, event_name, query_lower)
        
        if not matching_event:
            if not event_name:
                return "You don't have any upcoming events scheduled."
            else:
                return f"I couldn't find an event matching '{event_name}'."
        
        event_start = self._parse_event_time(matching_event.get('start', {}))
        if not event_start:
            return f"I found '{matching_event.get('title', 'an event')}' but couldn't determine its time."
        
        # Convert to user timezone
        if event_start.tzinfo:
            event_start_user = event_start.astimezone(self.user_tz)
        else:
            event_start_user = self.user_tz.localize(event_start)
        
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
        end_time = self._extract_end_time(query, now_user) or (now_user + timedelta(hours=8))
        
        # CRITICAL: Check if query explicitly mentions tasks or Notion
        query_lower = query.lower()
        has_task_keywords = any(keyword in query_lower for keyword in TASK_KEYWORDS)
        has_calendar_keywords = any(keyword in query_lower for keyword in CALENDAR_KEYWORDS)
        has_notion_keywords = any(keyword in query_lower for keyword in CrossDomainConfig.NOTION_KEYWORDS)
        
        # CRITICAL: Check if query is asking about "yesterday" - if so, adjust time range
        query_lower = query.lower()
        is_yesterday_query = "yesterday" in query_lower
        
        # Calculate actual time range for filtering
        if is_yesterday_query:
            # For "yesterday" queries, filter events from yesterday's start to yesterday's end
            yesterday_start = (now_user - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_end = yesterday_start + timedelta(days=1)
            filter_start = yesterday_start
            filter_end = yesterday_end
            logger.info(f"[TIME] Yesterday query detected, filtering events from {filter_start.date()} to {filter_end.date()}")
        else:
            # For other queries, use the normal time range
            filter_start = now_user
            filter_end = end_time
        
        # Filter events, tasks, and Notion pages in range
        events_in_range = self._filter_by_time_range(events, filter_start, filter_end)
        tasks_in_range = self._filter_tasks_by_time(tasks, filter_start, filter_end) if has_task_keywords else []
        notion_pages_in_range = [
            page for page in notion_pages 
            if self._notion_page_in_time_range(page, filter_start, filter_end)
        ] if has_notion_keywords or notion_pages else []
        
        if not events_in_range and not tasks_in_range and not notion_pages_in_range:
            # CRITICAL: Don't hardcode time ranges - use natural language based on query
            if "today" in query_lower:
                return "You don't have anything scheduled for today."
            elif "tomorrow" in query_lower:
                return "You don't have anything scheduled for tomorrow."
            elif "yesterday" in query_lower:
                return "You didn't have anything scheduled yesterday."
            else:
                return "You don't have anything scheduled."
        
        response_parts = []
        
        if events_in_range:
            response_parts.append(f"You have {len(events_in_range)} event(s):")
            for event in events_in_range[:5]:  # Limit to 5
                event_start = self._parse_event_time(event.get('start', {}))
                if event_start:
                    if event_start.tzinfo:
                        event_start_user = event_start.astimezone(self.user_tz)
                    else:
                        event_start_user = self.user_tz.localize(event_start)
                    time_str = event_start_user.strftime('%I:%M %p')
                    response_parts.append(f"  • {event.get('title', 'Untitled')} at {time_str}")
        
        if tasks_in_range:
            response_parts.append(f"\nYou have {len(tasks_in_range)} task(s):")
            for task in tasks_in_range[:5]:  # Limit to 5
                task_title = task.get('title', task.get('description', 'Untitled'))
                due_date = task.get('due_date', task.get('due'))
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
                        time_str = due_dt_user.strftime('%I:%M %p')
                        response_parts.append(f"  • {task_title} (due {time_str})")
                    except:
                        response_parts.append(f"  • {task_title}")
                else:
                    response_parts.append(f"  • {task_title}")
        
        if notion_pages_in_range:
            response_parts.append(f"\nYou have {len(notion_pages_in_range)} Notion page(s):")
            for page in notion_pages_in_range[:5]:  # Limit to 5
                page_title = page.get('title') or page.get('properties', {}).get('title', {}).get('title', [{}])[0].get('plain_text', 'Untitled')
                # Extract date from page properties
                page_date_str = None
                for prop_name, prop_data in page.get('properties', {}).items():
                    if isinstance(prop_data, dict) and prop_data.get('type') == 'date':
                        date_value = prop_data.get('date')
                        if date_value:
                            page_date_str = date_value.get('start') if isinstance(date_value, dict) else date_value
                            break
                if page_date_str:
                    try:
                        page_date = datetime.fromisoformat(page_date_str.replace('Z', '+00:00'))
                        if page_date.tzinfo:
                            page_date_user = page_date.astimezone(self.user_tz)
                        else:
                            page_date_user = self.user_tz.localize(page_date)
                        time_str = page_date_user.strftime('%I:%M %p')
                        response_parts.append(f"  • {page_title} (scheduled {time_str})")
                    except:
                        response_parts.append(f"  • {page_title}")
                else:
                    response_parts.append(f"  • {page_title}")
        
        return "\n".join(response_parts)
    
    def _handle_generic_time(
        self,
        query: str,
        events: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        notion_pages: List[Dict[str, Any]],
        now_user: datetime
    ) -> str:
        """Handle generic time queries"""
        query_lower = query.lower()
        
        # CRITICAL: Check if query is asking about "yesterday" - if so, filter events from yesterday
        if "yesterday" in query_lower:
            # Calculate yesterday's boundaries
            yesterday_start = (now_user - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_end = yesterday_start + timedelta(days=1)
            
            # Filter events to only include events from yesterday
            yesterday_events = self._filter_by_time_range(events, yesterday_start, yesterday_end)
            
            logger.info(f"[TIME] Generic time query with 'yesterday' detected, filtering {len(events)} events to {len(yesterday_events)} events for yesterday")
            
            if not yesterday_events:
                return "You didn't have anything scheduled yesterday."
            
            # Generate response with yesterday's events
            event_titles = [f"**{e.get('title', 'Untitled')}**" for e in yesterday_events[:5]]
            if len(yesterday_events) == 1:
                return f"You had {event_titles[0]} yesterday."
            elif len(yesterday_events) <= 5:
                return f"You had {', '.join(event_titles[:-1])}, and {event_titles[-1]} yesterday."
            else:
                return f"You had {', '.join(event_titles)}, and {len(yesterday_events) - 5} more event{'s' if len(yesterday_events) - 5 != 1 else ''} yesterday."
        
        # Default: show what's coming up (for future/current queries)
        next_event = self._find_next_event(events, now_user, query)
        
        if next_event:
            event_start = self._parse_event_time(next_event.get('start', {}))
            if event_start:
                if event_start.tzinfo:
                    event_start_user = event_start.astimezone(self.user_tz)
                else:
                    event_start_user = self.user_tz.localize(event_start)
                
                time_diff = event_start_user - now_user
                hours = int(time_diff.total_seconds() // 3600)
                minutes = int((time_diff.total_seconds() % 3600) // 60)
                time_str = self._format_time_difference(hours, minutes)
                
                return f"Your next event is '{next_event.get('title', 'Untitled')}' in {time_str}."
        
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
                if event_start.tzinfo:
                    event_start_user = event_start.astimezone(self.user_tz)
                else:
                    event_start_user = self.user_tz.localize(event_start)
                
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
        query_lower: str
    ) -> Optional[Dict[str, Any]]:
        """Find event matching query using semantic understanding"""
        # If no specific event name, return the next upcoming event
        if not event_name:
            # Check if query is asking for "next event" generically
            if any(phrase in query_lower for phrase in ['next event', 'next meeting', 'my next', 'the next', 'upcoming']):
                # Return the first/earliest event (already sorted by _find_next_event)
                if events:
                    return events[0] if isinstance(events[0], dict) else None
                return None
        
        # Use semantic matching for event names
        for event in events:
            title = event.get('title', event.get('summary', '')).lower()
            
            # Exact match
            if event_name and event_name.lower() in title:
                return event
            
            # Semantic match using LLM if available
            try:
                from ....ai.llm_factory import LLMFactory
                from langchain_core.messages import HumanMessage
                
                llm = LLMFactory.get_llm()
                if llm and event_name:
                    prompt = f"""Does this event title match the query intent?

Event title: "{event.get('title', event.get('summary', ''))}"
Query looking for: "{event_name}"
Original query: "{query_lower}"

Respond with ONLY valid JSON:
{{
    "matches": true/false,
    "confidence": 0.0-1.0
}}"""

                    response = llm.invoke([HumanMessage(content=prompt)])
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    import json
                    json_match = re.search(r'\{[\s\S]*\}', response_text)
                    if json_match:
                        result = json.loads(json_match.group(0))
                        if result.get('matches', False) and result.get('confidence', 0) > 0.7:
                            logger.info(f"[TIME] Semantic match found: '{event.get('title', '')}' matches '{event_name}'")
                            return event
            except Exception:
                pass
        
        return None
    
    def _extract_event_name(self, query: str) -> Optional[str]:
        """Extract event name from query using LLM understanding"""
        # Use LLM to extract event name semantically
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            
            llm = LLMFactory.get_llm()
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
                
                import json
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    event_name = result.get('event_name')
                    if event_name and event_name.lower() != 'null':
                        logger.info(f"[TIME] LLM extracted event name: '{event_name}'")
                        return event_name
        except Exception as e:
            logger.debug(f"[TIME] LLM event name extraction failed, using patterns: {e}")
        
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
                if event_start.tzinfo:
                    event_start_user = event_start.astimezone(self.user_tz)
                else:
                    event_start_user = self.user_tz.localize(event_start)
                
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
                    
                    if due_dt.tzinfo:
                        due_dt_user = due_dt.astimezone(self.user_tz)
                    else:
                        due_dt_user = self.user_tz.localize(due_dt)
                    
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

