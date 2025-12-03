"""
Calendar List & Search Handlers Module

This module contains methods for listing and searching calendar events:
- Event listing with date/time filtering
- Event searching with various criteria
- Event counting
- Time-of-day filtering (morning, afternoon, evening)
- Conversational response generation for lists and searches

Extracted from calendar_parser.py as part of Phase 3D modularization.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from langchain.tools import BaseTool

from ....core.calendar.utils import DEFAULT_DAYS_AHEAD

logger = logging.getLogger(__name__)

# Constants for time period parsing
DAYS_TODAY = 1
DAYS_TOMORROW = 2
DAYS_THIS_WEEK = 7
DAYS_NEXT_WEEK = 14
DAYS_THIS_MONTH = 30
DAYS_DEFAULT = DEFAULT_DAYS_AHEAD  # Use constant from utils

# Constants for event counting
EVENT_MARKER = '**'  # Marker used in formatted event strings
MIN_DAYS_AHEAD = 1  # Minimum days to look ahead

# Constants for date range queries
DAYS_BUFFER_FOR_TODAY = 2  # Get 2 days to ensure we get all of today
DAYS_BUFFER_FOR_TOMORROW = 3  # Get 3 days to ensure we get tomorrow
DAYS_BUFFER_FOR_NEXT_WEEK = 14  # Get 14 days to ensure we get next week


class CalendarListSearchHandlers:
    """Handles calendar listing and search operations"""
    
    def __init__(self, parser):
        """
        Initialize list/search handlers
        
        Args:
            parser: Parent CalendarParser instance
        """
        self.parser = parser
    
    def parse_time_period_from_query(self, query: str) -> int:
        """
        Parse time period from query to determine days_ahead for listing events
        
        Args:
            query: User query
            
        Returns:
            Number of days to look ahead (default: 1 for "today", 7 for general queries)
        """
        query_lower = query.lower()
        
        # Today-specific patterns
        if any(phrase in query_lower for phrase in [
            "today", "tonight", "this afternoon", "this evening", 
            "this morning", "right now", "now"
        ]):
            return DAYS_TODAY
        
        # Tomorrow
        if any(phrase in query_lower for phrase in [
            "tomorrow", "tomorrow's"
        ]):
            return DAYS_TOMORROW
        
        # This week
        if any(phrase in query_lower for phrase in [
            "this week", "the week", "weekly"
        ]):
            return DAYS_THIS_WEEK
        
        # Next week
        if any(phrase in query_lower for phrase in [
            "next week"
        ]):
            return DAYS_NEXT_WEEK
        
        # This month
        if any(phrase in query_lower for phrase in [
            "this month", "the month"
        ]):
            return DAYS_THIS_MONTH
        
        # Specific day mentions - check for today/tomorrow/week context
        # If no specific time period mentioned, default to 1 day (today) for "what do i have" queries
        # but 7 days for general "show my calendar" queries
        
        if any(phrase in query_lower for phrase in [
            "what do i have", "do i have", "what do i have on"
        ]):
            # These typically refer to "today" by default
            return DAYS_TODAY
        
        # Default to DEFAULT_DAYS_AHEAD for general calendar queries
        return DAYS_DEFAULT
    
    def handle_count_action(self, tool: 'BaseTool', query: str) -> str:
        """Handle calendar event count action - returns conversational count response"""
        # Parse date/time from query
        days_ahead = self.parse_time_period_from_query(query)
        logger.info(f"Calendar count action - days_ahead: {days_ahead}")
        
        # Get events and return just the count
        events_result = tool._run(action="list", days_ahead=days_ahead)
        
        # Count the events from the result
        # Events are returned as a formatted string, count the event markers
        event_count = events_result.count(EVENT_MARKER) if EVENT_MARKER in events_result else 0
        
        # Generate conversational response
        return self._generate_count_response(query, days_ahead, event_count)
    
    def handle_count_action_with_classification(self, tool: 'BaseTool', query: str, classification: Dict[str, Any]) -> str:
        """Handle calendar count with LLM classification"""
        entities = classification.get('entities', {})
        date_range = entities.get('date_range')
        
        # Use date_parser if available
        if date_range and self.parser.date_parser:
            try:
                parsed = self.parser.date_parser.parse_date_expression(date_range, prefer_future=True)
                if parsed:
                    days_ahead = (parsed['end'] - datetime.now()).days
                    days_ahead = max(MIN_DAYS_AHEAD, days_ahead)
                    events_result = tool._run(action="list", days_ahead=days_ahead)
                    event_count = events_result.count(EVENT_MARKER) if EVENT_MARKER in events_result else 0
                    return self._generate_count_response(query, days_ahead, event_count)
            except Exception as e:
                logger.warning(f"Date parser failed for count: {e}")
        
        # Fallback to pattern-based parsing
        days_ahead = self.parse_time_period_from_query(query)
        events_result = tool._run(action="list", days_ahead=days_ahead)
        event_count = events_result.count(EVENT_MARKER) if EVENT_MARKER in events_result else 0
        return self._generate_count_response(query, days_ahead, event_count)
    
    def handle_search_action_with_classification(self, tool: 'BaseTool', query: str, classification: Dict[str, Any]) -> str:
        """Handle calendar search with LLM classification and conversational response"""
        entities = classification.get('entities', {})
        title = entities.get('title')
        
        if title:
            search_result = tool._run(action="search", title=title)
        else:
            # Fallback to pattern-based extraction
            search_query = self._extract_search_query(query, ["search", "find", "look for"])
            search_result = tool._run(action="search", title=search_query)
        
        # Generate conversational response
        return self._generate_list_response(search_result, query)
    
    def handle_list_action_with_classification(self, tool: 'BaseTool', query: str, classification: Dict[str, Any]) -> str:
        """Handle calendar listing with LLM classification"""
        query_lower = query.lower()
        entities = classification.get('entities', {})
        date_range = entities.get('date_range')
        
        # Check if query is for "today" or "tomorrow"
        is_today_query = any(phrase in query_lower for phrase in [
            "today", "tonight", "this afternoon", "this evening", 
            "this morning", "right now", "now"
        ])
        
        is_tomorrow_query = any(phrase in query_lower for phrase in [
            "tomorrow", "tomorrow's", "tomorrows"
        ])
        
        is_next_week_query = any(phrase in query_lower for phrase in [
            "next week", "next week's"
        ])
        
        # Use date_parser if available
        if date_range and self.parser.date_parser:
            try:
                parsed = self.parser.date_parser.parse_date_expression(date_range, prefer_future=True)
                if parsed:
                    # Calculate days_ahead based on parsed range
                    days_ahead = (parsed['end'] - datetime.now()).days
                    days_ahead = max(MIN_DAYS_AHEAD, days_ahead)
                    
                    # If this is a "today" or "tomorrow" query, filter the results
                    if is_today_query:
                        result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_TODAY)
                        filtered_result = self._filter_events_to_today(result)
                    elif is_tomorrow_query:
                        result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_TOMORROW)
                        filtered_result = self._filter_events_to_tomorrow(result)
                    elif is_next_week_query:
                        result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_NEXT_WEEK)
                        filtered_result = self._filter_events_to_next_week(result)
                    else:
                        filtered_result = tool._run(action="list", days_ahead=days_ahead)
                    
                    # Generate conversational response
                    return self._generate_list_response(filtered_result, query)
            except Exception as e:
                logger.warning(f"Date parser failed for list: {e}")
        
        # Fallback to pattern-based parsing
        days_ahead = self.parse_time_period_from_query(query)
        
        if is_today_query:
            # Get events for today and tomorrow, then filter to only today
            result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_TODAY)
            filtered_result = self._filter_events_to_today(result)
        elif is_tomorrow_query:
            # Get events for tomorrow and day after, then filter to only tomorrow
            result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_TOMORROW)
            filtered_result = self._filter_events_to_tomorrow(result)
        elif is_next_week_query:
            # Get events for next 14 days, then filter to only next week (days 7-13)
            result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_NEXT_WEEK)
            filtered_result = self._filter_events_to_next_week(result)
        else:
            filtered_result = tool._run(action="list", days_ahead=days_ahead)
        
        # Generate conversational response
        return self._generate_list_response(filtered_result, query)
    
    def handle_list_action(self, tool: 'BaseTool', query: str) -> str:
        """
        Handle calendar listing action with date parsing.
        
        This is the main method for listing calendar events with comprehensive
        date/time filtering including time-of-day support (morning, afternoon, evening).
        """
        # Verify date parser is available
        if not self.parser.date_parser:
            logger.warning("[CAL] Date parser not available - time-of-day filtering may be limited")
        
        # Parse date/time from query
        query_lower = query.lower()
        days_ahead = self.parse_time_period_from_query(query)
        
        # Extract event title/name if mentioned (e.g., "What time is my Clavr AI meeting next week?")
        # CRITICAL: Use LLM to understand semantic meaning, not literal matching
        event_title = None
        query_lower = query.lower()
        
        # Skip extraction if query is asking for "next event" generically
        is_generic_next = any(phrase in query_lower for phrase in [
            'next event', 'next meeting', 'my next', 'the next', 'upcoming event', 
            'upcoming meeting', 'next one', 'first event', 'first meeting'
        ])
        
        if not is_generic_next and self.parser.classifier:
            try:
                classification = self.parser.classifier.classify_query(query)
                entities = classification.get('entities', {})
                event_title = entities.get('title')
                # Validate that extracted title is not a generic phrase
                if event_title:
                    event_title_lower = event_title.lower()
                    if any(phrase in event_title_lower for phrase in ['next', 'upcoming', 'first', 'my next', 'the next']):
                        event_title = None  # Don't use generic phrases as titles
                    else:
                        logger.info(f"[CAL] Extracted event title from query: {event_title}")
            except Exception as e:
                logger.debug(f"[CAL] Failed to extract event title via classifier: {e}")
        
        # If no title from classifier, try pattern-based extraction (but skip if generic)
        if not event_title and not is_generic_next:
            event_title = self._extract_event_title_from_query(query)
            # Validate extracted title
            if event_title:
                event_title_lower = event_title.lower()
                if any(phrase in event_title_lower for phrase in ['next', 'upcoming', 'first', 'my next', 'the next']):
                    event_title = None  # Don't use generic phrases as titles
        
        # Try to use flexible date parser first (handles past, future, and specific dates)
        date_range_parsed = None
        if self.parser.date_parser:
            try:
                # Try to parse the entire query as a date expression
                logger.info(f"[CAL] Attempting to parse date range from query: '{query}'")
                date_range_parsed = self.parser.date_parser.parse_date_expression(query, prefer_future=True)
                if date_range_parsed:
                    logger.info(f"[CAL] ✓ SUCCESS: Parsed date range from query: {date_range_parsed['start']} to {date_range_parsed['end']}")
                    logger.info(f"[CAL] Time of day detected: {date_range_parsed.get('time_of_day', 'none')}")
                else:
                    logger.warning(f"[CAL] ✗ FAILED: FlexibleDateParser returned None for query: '{query}'")
            except Exception as e:
                logger.error(f"[CAL] ✗ ERROR: FlexibleDateParser failed to parse query '{query}': {e}", exc_info=True)
        
        # If event title is specified, use search instead of list
        if event_title:
            logger.info(f"[CAL] Event title specified: '{event_title}', using search functionality")
            # Calculate days_ahead based on date range if available
            if date_range_parsed:
                days_diff = (date_range_parsed['end'].date() - date_range_parsed['start'].date()).days
                days_ahead = max(DAYS_THIS_MONTH, days_diff + DAYS_THIS_WEEK)  # Search wider range
            
            # Use search to find events matching the title
            search_result = tool._run(action="search", title=event_title, days_ahead=days_ahead)
            
            # If search didn't find results or returned error, try listing and filtering by title
            if not search_result or "[ERROR]" in search_result or "No events found" in search_result:
                logger.info(f"[CAL] Search didn't find results, trying list + title filter")
                # Get events for the date range
                if date_range_parsed:
                    import pytz as pytz_module
                    days_diff = (date_range_parsed['end'].date() - date_range_parsed['start'].date()).days
                    days_back = 0
                    days_ahead_query = max(DAYS_THIS_WEEK, days_diff + DAYS_TOMORROW)
                    now = datetime.now(date_range_parsed['start'].tzinfo if date_range_parsed['start'].tzinfo else pytz_module.UTC)
                    if date_range_parsed['start'].date() < now.date():
                        days_back = (now.date() - date_range_parsed['start'].date()).days + 1
                    
                    list_result = tool._run(
                        action="list",
                        days_ahead=days_ahead_query,
                        days_back=days_back,
                        start_date=date_range_parsed['start'].isoformat() if date_range_parsed['start'] else None,
                        end_date=date_range_parsed['end'].isoformat() if date_range_parsed['end'] else None
                    )
                else:
                    list_result = tool._run(action="list", days_ahead=days_ahead)
                
                # Filter by title
                search_result = self._filter_events_by_title(list_result, event_title)
                
                # If we have a date range, also filter by date
                if date_range_parsed and search_result:
                    search_result = self._filter_events_by_date_range(
                        search_result,
                        date_range_parsed['start'],
                        date_range_parsed['end']
                    )
            
            # Generate conversational response
            return self._generate_list_response(search_result, query, event_title=event_title)
        
        # If date range was parsed, use generic filter with time-of-day support
        if date_range_parsed:
            start_date = date_range_parsed['start']
            end_date = date_range_parsed['end']
            time_of_day = date_range_parsed.get('time_of_day')
            
            logger.info(f"[CAL] ===== DATE RANGE PARSED =====")
            logger.info(f"[CAL] Parsed start_date: {start_date} (hour={start_date.hour}, minute={start_date.minute})")
            logger.info(f"[CAL] Parsed end_date: {end_date} (hour={end_date.hour}, minute={end_date.minute})")
            logger.info(f"[CAL] Time of day: {time_of_day}")
            
            # Query calendar and filter results
            import pytz as pytz_module
            days_diff = (end_date.date() - start_date.date()).days
            days_back = 0
            days_ahead_query = max(DAYS_THIS_WEEK, days_diff + DAYS_TOMORROW)
            
            # If querying past dates, calculate days_back
            now = datetime.now(start_date.tzinfo if start_date.tzinfo else pytz_module.UTC)
            if start_date.date() < now.date():
                days_back = (now.date() - start_date.date()).days + 1
            
            # Query full day range
            if start_date.tzinfo:
                query_start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                query_start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            
            if end_date.tzinfo:
                query_end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                query_end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            result = tool._run(
                action="list", 
                days_ahead=days_ahead_query,
                days_back=days_back,
                start_date=query_start_date.isoformat() if query_start_date else None,
                end_date=query_end_date.isoformat() if query_end_date else None
            )
            
            # Filter by date range (includes time filtering)
            filtered_result = self._filter_events_by_date_range(result, start_date, end_date)
            
            if not filtered_result or not filtered_result.strip():
                return self._generate_empty_list_response(query, query_lower, time_of_day)
            
            result_to_use = filtered_result
        else:
            # Fallback to pattern-based filtering
            is_today_query = any(phrase in query_lower for phrase in [
                "today", "tonight", "this afternoon", "this evening", "this morning", "right now", "now"
            ])
            
            is_tomorrow_query = any(phrase in query_lower for phrase in [
                "tomorrow", "tomorrow's", "tomorrows"
            ])
            
            is_yesterday_query = any(phrase in query_lower for phrase in [
                "yesterday", "yesterday's"
            ])
            
            is_next_week_query = any(phrase in query_lower for phrase in [
                "next week", "next week's"
            ])
            
            # Get events and filter
            if is_today_query:
                result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_TODAY)
                result_to_use = self._filter_events_to_today(result)
            elif is_tomorrow_query:
                result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_TOMORROW)
                result_to_use = self._filter_events_to_tomorrow(result)
            elif is_yesterday_query:
                # CRITICAL: For "yesterday" queries, fetch events with days_back=1
                # and filter to only show yesterday's events
                result = tool._run(action="list", days_back=1, days_ahead=0)
                result_to_use = self._filter_events_to_yesterday(result)
            elif is_next_week_query:
                result = tool._run(action="list", days_ahead=DAYS_BUFFER_FOR_NEXT_WEEK)
                result_to_use = self._filter_events_to_next_week(result)
            else:
                result_to_use = tool._run(action="list", days_ahead=days_ahead)
        
        # Generate conversational response
        return self._generate_list_response(result_to_use, query)
    
    # ==================== Helper Methods ====================
    
    def _generate_count_response(self, query: str, days_ahead: int, event_count: int) -> str:
        """
        Generate conversational count response.
        
        Args:
            query: User query
            days_ahead: Number of days ahead
            event_count: Number of events found
            
        Returns:
            Conversational count response
        """
        # Extract time period description
        time_period = "today" if days_ahead == DAYS_TODAY else f"the next {days_ahead} days"
        
        # Generate conversational response using LLM if available
        if self.parser.llm_client:
            try:
                conversational_response = self._generate_conversational_response("", query, event_count=event_count)
                if conversational_response:
                    return conversational_response
            except Exception as e:
                logger.debug(f"[CAL] Failed to generate conversational count response: {e}")
        
        # Fallback: simple conversational response
        if event_count == 0:
            return f"You don't have any calendar events {time_period}."
        elif event_count == 1:
            return f"You have 1 calendar event {time_period}."
        else:
            return f"You have {event_count} calendar events {time_period}."
    
    def _generate_list_response(self, result: str, query: str, event_title: Optional[str] = None) -> str:
        """
        Generate conversational list response.
        
        Args:
            result: Formatted event list result
            query: User query
            event_title: Optional event title if searching for specific event
            
        Returns:
            Conversational list response
        """
        # Handle empty results
        if not result or not result.strip():
            return self._generate_empty_list_response(query, query.lower(), None)
        
        # Generate conversational response using LLM if available
        if self.parser.llm_client:
            try:
                conversational_response = self._generate_conversational_response(result, query)
                if conversational_response:
                    return conversational_response
            except Exception as e:
                logger.debug(f"[CAL] Failed to generate conversational list response: {e}")
        
        # Fallback: return formatted result
        if event_title and "couldn't find" in result.lower():
            return f"I couldn't find any events matching '{event_title}'."
        
        return result
    
    def _generate_empty_list_response(self, query: str, query_lower: str, time_of_day: Optional[str]) -> str:
        """
        Generate response for empty event lists.
        
        Args:
            query: User query
            query_lower: Lowercase query
            time_of_day: Optional time of day (morning, afternoon, evening)
            
        Returns:
            Empty list response
        """
        # Try LLM first if available
        if self.parser.llm_client:
            try:
                conversational_response = self._generate_conversational_response("", query, event_count=0)
                if conversational_response:
                    return conversational_response
            except Exception as e:
                logger.debug(f"[CAL] Failed to generate empty list response: {e}")
        
        # Fallback: simple responses based on query
        if "yesterday" in query_lower:
            return "You didn't have anything on your calendar yesterday."
        elif "tomorrow" in query_lower:
            return "You don't have anything on your calendar tomorrow."
        elif "today" in query_lower:
            return "You don't have anything on your calendar today."
        elif time_of_day:
            return f"You don't have any meetings {time_of_day}."
        else:
            return "You don't have any upcoming calendar events."
    
    def _generate_conversational_response(self, result: str, query: str, event_count: Optional[int] = None) -> Optional[str]:
        """
        Generate conversational response using LLM if available.
        
        Args:
            result: Raw result string
            query: User query
            event_count: Optional event count for count queries
            
        Returns:
            Conversational response or None if generation fails
        """
        if not self.parser.llm_client:
            return None
        
        try:
            return self.parser._generate_conversational_calendar_response(result, query, event_count=event_count)
        except Exception as e:
            logger.debug(f"[CAL] Failed to generate conversational response: {e}")
            return None
    
    def _extract_event_title_from_query(self, query: str) -> Optional[str]:
        """
        Extract event title from query using pattern matching.
        
        Args:
            query: User query
            
        Returns:
            Extracted event title or None
        """
        query_lower = query.lower()
        
        # Look for patterns like "my X meeting", "the X meeting", "X meeting", "meeting X"
        patterns = [
            r'what.*?(?:time|when).*?(?:is|are).*?(?:my|the)?\s+([^?]+?)\s+meeting',
            r'what.*?(?:time|when).*?(?:is|are).*?(?:my|the)?\s+([^?]+?)(?:\s+next|\s+tomorrow|\s+on|$)',
            r'my\s+([^?]+?)\s+meeting',
            r'the\s+([^?]+?)\s+meeting',
            r'([^?]+?)\s+meeting',
            r'meeting\s+(?:called|named|about)\s+([^?]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                potential_title = match.group(1).strip()
                # Remove common words that aren't part of the title
                potential_title = re.sub(
                    r'\b(my|the|a|an|on|at|for|with|about|next|this|last|is|are|do|does|did|will|would|can|could)\b',
                    '', potential_title, flags=re.IGNORECASE
                ).strip()
                # Remove date/time words
                potential_title = re.sub(
                    r'\b(today|tomorrow|yesterday|next week|this week|last week|morning|afternoon|evening|night|time|when|what)\b',
                    '', potential_title, flags=re.IGNORECASE
                ).strip()
                # Remove question words and common verbs
                potential_title = re.sub(
                    r'^\s*(what|when|where|who|which|how)\s+', '', potential_title, flags=re.IGNORECASE
                ).strip()
                
                if potential_title and len(potential_title) > 2:
                    # Capitalize properly (e.g., "clavr ai" -> "Clavr AI")
                    event_title = ' '.join(
                        word.capitalize() if word.lower() not in ['ai', 'api', 'ui', 'ux'] else word.upper()
                        for word in potential_title.split()
                    )
                    logger.info(f"[CAL] Extracted event title via pattern: {event_title}")
                    return event_title
        
        return None
    
    def _extract_search_query(self, query: str, keywords: list) -> Optional[str]:
        """
        Extract search query from user input.
        
        Args:
            query: User query
            keywords: List of keywords that indicate search intent
            
        Returns:
            Search query string or None
        """
        query_lower = query.lower()
        
        for keyword in keywords:
            pattern = rf'{keyword}\s+(?:for\s+)?["\']?([^"\']+?)["\']?(?:\s|$)'
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # Fallback: try to extract quoted text
        match = re.search(r'["\']([^"\']+)["\']', query)
        if match:
            return match.group(1).strip()
        
        return None
    
    def _filter_events_to_today(self, result: str) -> str:
        """
        Filter events to only show today's events.
        
        Args:
            result: Formatted event list result
            
        Returns:
            Filtered result with only today's events
        """
        if not result:
            return result
        
        return self.parser._filter_events_to_today(result)
    
    def _filter_events_to_tomorrow(self, result: str) -> str:
        """
        Filter events to only show tomorrow's events.
        
        Args:
            result: Formatted event list result
            
        Returns:
            Filtered result with only tomorrow's events
        """
        if not result:
            return result
        
        return self.parser._filter_events_to_tomorrow(result)
    
    def _filter_events_to_yesterday(self, result: str) -> str:
        """
        Filter events to only show yesterday's events.
        
        Args:
            result: Formatted event list result
            
        Returns:
            Filtered result with only yesterday's events
        """
        if not result:
            return result
        
        return self.parser._filter_events_to_yesterday(result)
    
    def _filter_events_to_next_week(self, result: str) -> str:
        """
        Filter events to only show next week's events.
        
        Args:
            result: Formatted event list result
            
        Returns:
            Filtered result with only next week's events
        """
        if not result:
            return result
        
        return self.parser._filter_events_to_next_week(result)
    
    def _filter_events_by_title(self, result: str, title: str) -> str:
        """
        Filter events by title.
        
        Args:
            result: Formatted event list result
            title: Title to filter by
            
        Returns:
            Filtered result with matching events
        """
        if not result or not title:
            return result
        
        return self.parser._filter_events_by_title(result, title)
    
    def _filter_events_by_date_range(self, result: str, start_date: datetime, end_date: datetime) -> str:
        """
        Filter events by date range.
        
        Args:
            result: Formatted event list result
            start_date: Start date for filtering
            end_date: End date for filtering
            
        Returns:
            Filtered result with events in date range
        """
        if not result:
            return result
        
        return self.parser._filter_events_by_date_range(result, start_date, end_date)
