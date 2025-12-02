"""
Calendar Utility Handlers

Handles utility and advanced calendar functions:
- Conflict analysis
- Free time detection
- Calendar search
- Calendar listing
- Duplicate detection
- Missing details detection

This module contains utility functions for advanced calendar operations.
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from langchain.tools import BaseTool
import pytz

from ....utils.logger import setup_logger
from ....core.calendar.utils import (
    DEFAULT_DURATION_MINUTES,
    find_conflicts,
    parse_event_time,
    events_overlap,
    calculate_duration_minutes
)

logger = setup_logger(__name__)

# Constants for utility operations
MAX_RESULTS_CONFLICT_ANALYSIS = 100
MAX_RESULTS_FREE_TIME = 50
MAX_RESULTS_SEARCH = 20
MAX_RESULTS_DUPLICATES = 100
MAX_RESULTS_MISSING_DETAILS = 50
DEFAULT_MIN_DURATION_MINUTES = DEFAULT_DURATION_MINUTES
MAX_FREE_SLOTS_DISPLAY = 5
MAX_INCOMPLETE_EVENTS_DISPLAY = 10


class CalendarUtilityHandlers:
    """
    Handles utility and advanced calendar operations.
    
    This includes:
    - Conflict analysis (handle_conflict_analysis_action)
    - Free time finding (handle_find_free_time_action)
    - Calendar search (handle_search_action)
    - Calendar listing (handle_list_calendars_action)
    - Duplicate detection (handle_find_duplicates_action)
    - Missing details detection (handle_find_missing_details_action)
    """
    
    def __init__(self, calendar_parser):
        """
        Initialize utility handlers.
        
        Args:
            calendar_parser: Parent CalendarParser instance for accessing tools, config, etc.
        """
        self.calendar_parser = calendar_parser
    
    def handle_conflict_analysis_action(self, tool: BaseTool, query: str) -> str:
        """
        Analyze calendar for conflicts and overlapping events.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting conflict analysis
            
        Returns:
            Conflict analysis results
        """
        try:
            logger.info(f"[UTILITY] Analyzing calendar conflicts for query: '{query}'")
            
            # Get all events for analysis
            result = tool._run(action="list", time_min=None, max_results=MAX_RESULTS_CONFLICT_ANALYSIS)
            
            if self._check_result_error(result):
                return "I couldn't analyze your calendar for conflicts right now. Please try again."
            
            # Parse events from result
            events = self._parse_events_from_list_result(result)
            
            if not events:
                return "You don't have any events scheduled, so there are no conflicts!"
            
            # Find overlapping events
            conflicts = self._find_overlapping_events(events)
            
            if not conflicts:
                return f"Good news! I checked {len(events)} events and found no scheduling conflicts."
            
            # Format conflict report
            conflict_msg = f"I found {len(conflicts)} potential conflict(s) in your calendar:\n\n"
            for i, conflict in enumerate(conflicts, 1):
                conflict_msg += f"{i}. **{conflict['event1']['summary']}** and **{conflict['event2']['summary']}** overlap\n"
                conflict_msg += f"   Both scheduled around {conflict['time']}\n\n"
            
            return conflict_msg
            
        except Exception as e:
            logger.error(f"Conflict analysis failed: {e}", exc_info=True)
            return f"I encountered an error while analyzing conflicts: {str(e)}"
    
    def handle_find_free_time_action(self, tool: BaseTool, query: str) -> str:
        """
        Find free time slots in the calendar.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting free time
            
        Returns:
            Free time slot suggestions
        """
        try:
            logger.info(f"[UTILITY] Finding free time for query: '{query}'")
            
            # Extract duration preference from query
            duration = self._extract_duration_preference(query)
            
            # Get events to find gaps
            result = tool._run(action="list", time_min=None, max_results=MAX_RESULTS_FREE_TIME)
            
            if self._check_result_error(result):
                return "I couldn't check your calendar for free time right now. Please try again."
            
            # Parse events
            events = self._parse_events_from_list_result(result)
            
            # Find gaps between events
            free_slots = self._find_free_slots(events, duration or DEFAULT_MIN_DURATION_MINUTES)
            
            if not free_slots:
                return "I couldn't find any significant free time slots in your calendar. You might want to check a different time period."
            
            # Format response
            msg = f"I found {len(free_slots)} free time slot(s):\n\n"
            for i, slot in enumerate(free_slots[:MAX_FREE_SLOTS_DISPLAY], 1):
                msg += f"{i}. {slot['start']} - {slot['end']} ({slot['duration']} min)\n"
            
            return msg
            
        except Exception as e:
            logger.error(f"Find free time failed: {e}", exc_info=True)
            return f"I encountered an error while finding free time: {str(e)}"
    
    def handle_search_action(self, tool: BaseTool, query: str) -> str:
        """
        Search calendar events (non-classified version).
        
        Args:
            tool: Calendar tool to execute with
            query: User query with search terms
            
        Returns:
            Search results
        """
        try:
            logger.info(f"[UTILITY] Searching calendar for query: '{query}'")
            
            # Extract search terms from query
            search_terms = self._extract_search_terms(query)
            
            if not search_terms:
                return "I couldn't understand what you want to search for. Could you be more specific?"
            
            # Search using the tool
            result = tool._run(action="search", query=" ".join(search_terms), max_results=MAX_RESULTS_SEARCH)
            
            if not result:
                return f"I couldn't find any events matching '{' '.join(search_terms)}'."
            
            return result
            
        except Exception as e:
            logger.error(f"Calendar search failed: {e}", exc_info=True)
            return f"I encountered an error while searching: {str(e)}"
    
    def handle_list_calendars_action(self, tool: BaseTool, query: str) -> str:
        """
        List available calendars.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting calendar list
            
        Returns:
            List of available calendars
        """
        try:
            logger.info(f"[UTILITY] Listing calendars for query: '{query}'")
            
            # Try to get calendar list
            result = tool._run(action="list_calendars")
            
            if not result:
                return "I couldn't retrieve your calendar list right now. You might only have your primary calendar."
            
            return result
            
        except Exception as e:
            logger.error(f"List calendars failed: {e}", exc_info=True)
            return "I can access your primary calendar. Additional calendars can be added through Google Calendar settings."
    
    def handle_find_duplicates_action(self, tool: BaseTool, query: str) -> str:
        """
        Find duplicate events in the calendar.
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting duplicate detection
            
        Returns:
            Duplicate event report
        """
        try:
            logger.info(f"[UTILITY] Finding duplicate events for query: '{query}'")
            
            # Get all events
            result = tool._run(action="list", time_min=None, max_results=MAX_RESULTS_DUPLICATES)
            
            if self._check_result_error(result):
                return "I couldn't check for duplicates right now. Please try again."
            
            # Parse events
            events = self._parse_events_from_list_result(result)
            
            if not events:
                return "You don't have any events to check for duplicates."
            
            # Find duplicates
            duplicates = self._find_duplicate_events(events)
            
            if not duplicates:
                return f"Good news! I checked {len(events)} events and found no duplicates."
            
            # Format response
            msg = f"I found {len(duplicates)} potential duplicate(s):\n\n"
            for i, dup in enumerate(duplicates, 1):
                msg += f"{i}. **{dup['title']}** appears {dup['count']} times\n"
            
            return msg
            
        except Exception as e:
            logger.error(f"Find duplicates failed: {e}", exc_info=True)
            return f"I encountered an error while checking for duplicates: {str(e)}"
    
    def handle_find_missing_details_action(self, tool: BaseTool, query: str) -> str:
        """
        Find events missing important details (description, location, etc.).
        
        Args:
            tool: Calendar tool to execute with
            query: User query requesting missing details check
            
        Returns:
            Report of events with missing details
        """
        try:
            logger.info(f"[UTILITY] Finding events with missing details for query: '{query}'")
            
            # Get upcoming events
            result = tool._run(action="list", time_min=None, max_results=MAX_RESULTS_MISSING_DETAILS)
            
            if self._check_result_error(result):
                return "I couldn't check for missing details right now. Please try again."
            
            # Parse events
            events = self._parse_events_from_list_result(result)
            
            if not events:
                return "You don't have any events to check."
            
            # Find events with missing details
            incomplete_events = self._find_incomplete_events(events)
            
            if not incomplete_events:
                return f"Great! All {len(events)} events have complete details."
            
            # Format response
            msg = f"I found {len(incomplete_events)} event(s) with missing details:\n\n"
            for i, event in enumerate(incomplete_events[:MAX_INCOMPLETE_EVENTS_DISPLAY], 1):
                msg += f"{i}. **{event['summary']}**\n"
                msg += f"   Missing: {', '.join(event['missing'])}\n\n"
            
            return msg
            
        except Exception as e:
            logger.error(f"Find missing details failed: {e}", exc_info=True)
            return f"I encountered an error while checking for missing details: {str(e)}"
    
    # ==================== Helper Methods ====================
    
    def _check_result_error(self, result: str) -> bool:
        """
        Check if result indicates an error.
        
        Args:
            result: Result string to check
            
        Returns:
            True if error detected, False otherwise
        """
        if not result:
            return True
        result_lower = result.lower()
        return "error" in result_lower or "failed" in result_lower or "not available" in result_lower
    
    def _parse_events_from_list_result(self, result: str) -> List[Dict[str, Any]]:
        """
        Parse events from list result.
        
        Args:
            result: Raw result from calendar tool
            
        Returns:
            List of parsed events
        """
        events = []
        
        try:
            # Simple parsing - look for numbered events
            lines = result.split('\n')
            current_event = {}
            
            for line in lines:
                # Match numbered event lines like "1. Event Title"
                if re.match(r'^\d+\.', line):
                    if current_event:
                        events.append(current_event)
                    current_event = {'summary': line.split('.', 1)[1].strip() if '.' in line else line}
                elif 'Time:' in line or 'When:' in line:
                    current_event['time'] = line.split(':', 1)[1].strip() if ':' in line else ''
                elif 'Location:' in line:
                    current_event['location'] = line.split(':', 1)[1].strip() if ':' in line else ''
                elif 'Description:' in line:
                    current_event['description'] = line.split(':', 1)[1].strip() if ':' in line else ''
            
            if current_event:
                events.append(current_event)
                
        except Exception as e:
            logger.warning(f"Failed to parse events from result: {e}")
        
        return events
    
    def _find_overlapping_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Find events that overlap in time.
        
        Uses proper datetime parsing and conflict detection from core utilities.
        
        Args:
            events: List of parsed events
            
        Returns:
            List of conflict dictionaries with event details
        """
        conflicts = []
        
        # Parse events with proper datetime objects
        parsed_events = []
        for event in events:
            # Try to parse start and end times from event
            start_time = None
            end_time = None
            
            # Check if event has structured time data
            if 'start' in event:
                start_time = parse_event_time(event.get('start', {}))
            elif 'time' in event:
                # Try to parse from time string
                time_str = event.get('time', '')
                if time_str:
                    try:
                        # Attempt to parse time string (format may vary)
                        start_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        pass
            
            # Estimate end time if we have start time
            if start_time:
                duration_minutes = event.get('duration_minutes', DEFAULT_DURATION_MINUTES)
                end_time = start_time + timedelta(minutes=duration_minutes)
            
            if start_time and end_time:
                parsed_events.append({
                    'event': event,
                    'start': start_time,
                    'end': end_time
                })
        
        # Check for overlaps using proper conflict detection
        for i, event1_data in enumerate(parsed_events):
            for event2_data in parsed_events[i+1:]:
                if events_overlap(
                    event1_data['start'],
                    event1_data['end'],
                    event2_data['start'],
                    event2_data['end']
                ):
                    conflicts.append({
                        'event1': event1_data['event'],
                        'event2': event2_data['event'],
                        'time': event1_data['start'].strftime('%Y-%m-%d %H:%M')
                    })
        
        return conflicts
    
    def _find_free_slots(self, events: List[Dict[str, Any]], min_duration: int = DEFAULT_MIN_DURATION_MINUTES) -> List[Dict[str, Any]]:
        """
        Find free time slots between events.
        
        Args:
            events: List of parsed events
            min_duration: Minimum duration in minutes for a free slot
            
        Returns:
            List of free time slot dictionaries with start, end, and duration
        """
        free_slots = []
        
        # Parse events with proper datetime objects
        parsed_events = []
        for event in events:
            start_time = None
            end_time = None
            
            if 'start' in event:
                start_time = parse_event_time(event.get('start', {}))
            elif 'time' in event:
                time_str = event.get('time', '')
                if time_str:
                    try:
                        start_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        continue
            
            if start_time:
                duration_minutes = event.get('duration_minutes', DEFAULT_DURATION_MINUTES)
                end_time = start_time + timedelta(minutes=duration_minutes)
                parsed_events.append({
                    'start': start_time,
                    'end': end_time
                })
        
        # Sort events by start time
        parsed_events.sort(key=lambda x: x['start'])
        
        # Find gaps between events
        # Get timezone from first event or use UTC
        if parsed_events and parsed_events[0]['start'].tzinfo:
            tz = parsed_events[0]['start'].tzinfo
            now = datetime.now(tz)
        else:
            now = datetime.now(pytz.UTC)
        
        # Check gap before first event
        if parsed_events:
            first_start = parsed_events[0]['start']
            if first_start > now:
                gap_duration = calculate_duration_minutes(now, first_start)
                if gap_duration >= min_duration:
                    free_slots.append({
                        'start': now.strftime('%Y-%m-%d %H:%M'),
                        'end': first_start.strftime('%Y-%m-%d %H:%M'),
                        'duration': gap_duration
                    })
        
        # Check gaps between events
        for i in range(len(parsed_events) - 1):
            event1_end = parsed_events[i]['end']
            event2_start = parsed_events[i + 1]['start']
            
            if event2_start > event1_end:
                gap_duration = calculate_duration_minutes(event1_end, event2_start)
                if gap_duration >= min_duration:
                    free_slots.append({
                        'start': event1_end.strftime('%Y-%m-%d %H:%M'),
                        'end': event2_start.strftime('%Y-%m-%d %H:%M'),
                        'duration': gap_duration
                    })
        
        return free_slots
    
    def _extract_duration_preference(self, query: str) -> Optional[int]:
        """
        Extract desired duration from query in minutes.
        
        Args:
            query: User query containing duration preference
            
        Returns:
            Duration in minutes or None if not found
        """
        match = re.search(r'(\d+)\s*(hour|hr|h|minute|min|m)s?', query, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            unit = match.group(2).lower()
            return value * 60 if unit.startswith('h') else value
        return None
    
    def _extract_search_terms(self, query: str) -> List[str]:
        """Extract search terms from query."""
        # Remove common words
        stop_words = {'search', 'find', 'look', 'for', 'my', 'the', 'a', 'an', 'in', 'on', 'at', 'calendar', 'events', 'event'}
        words = query.lower().split()
        return [w for w in words if w not in stop_words]
    
    def _find_duplicate_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find duplicate events by title."""
        title_counts = {}
        
        for event in events:
            title = event.get('summary', '').lower()
            if title:
                title_counts[title] = title_counts.get(title, 0) + 1
        
        duplicates = []
        for title, count in title_counts.items():
            if count > 1:
                duplicates.append({'title': title, 'count': count})
        
        return duplicates
    
    def _find_incomplete_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find events with missing details."""
        incomplete = []
        
        for event in events:
            missing = []
            if not event.get('description'):
                missing.append('description')
            if not event.get('location'):
                missing.append('location')
            
            if missing:
                incomplete.append({
                    'summary': event.get('summary', 'Untitled'),
                    'missing': missing
                })
        
        return incomplete
