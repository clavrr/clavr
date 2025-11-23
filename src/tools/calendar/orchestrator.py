"""
Calendar Orchestrator

Handles complex multi-step calendar operations with user confirmations.
Examples:
- "Move my standup to 2pm" -> Check conflicts -> Ask confirmation -> Execute
- "Reschedule 3pm meeting to tomorrow" -> Find event -> Check conflicts -> Confirm -> Move
"""
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from ..constants import ToolLimits
from ...core.calendar.utils import DEFAULT_DAYS_AHEAD
from .smart_parser import SmartCalendarParser
from .actions import CalendarActions
from .search import CalendarSearch
from .availability import CalendarAvailability

logger = setup_logger(__name__)


class CalendarOrchestrator:
    """Orchestrate complex calendar operations with intelligent workflows"""
    
    def __init__(
        self,
        actions: CalendarActions,
        search: CalendarSearch,
        availability: CalendarAvailability,
        confirmation_callback: Optional[Callable] = None
    ):
        """
        Initialize orchestrator
        
        Args:
            actions: Calendar actions module
            search: Calendar search module
            availability: Calendar availability module
            confirmation_callback: Optional callback for user confirmations
        """
        self.actions = actions
        self.search = search
        self.availability = availability
        self.parser = SmartCalendarParser()
        self.confirmation_callback = confirmation_callback
    
    def execute_query(self, query: str) -> str:
        """
        Execute a natural language calendar query
        
        Args:
            query: Natural language query
            
        Returns:
            Result message
        """
        # Parse the query
        parsed = self.parser.parse_query(query)
        
        if not parsed.get('action'):
            return f"[ERROR] Could not understand the query: '{query}'"
        
        action = parsed['action']
        
        # Route to appropriate handler
        if action == 'reschedule':
            return self._handle_reschedule(parsed)
        elif action == 'cancel':
            return self._handle_cancel(parsed)
        elif action == 'create':
            return self._handle_create(parsed)
        elif action == 'find_free_time':
            return self._handle_find_free_time(parsed)
        elif action in ['list', 'list_with_actions']:
            return self._handle_list(parsed)
        else:
            return f"[ERROR] Unknown action: {action}"
    
    def _handle_reschedule(self, parsed: Dict[str, Any]) -> str:
        """
        Handle reschedule operation with conflict detection
        
        Workflow:
        1. Find the event to reschedule
        2. Check for conflicts at new time
        3. Suggest alternatives if conflicts found
        4. Confirm with user (if callback provided)
        5. Execute the move
        """
        entities = parsed.get('entities', {})
        
        # Step 1: Find the event
        event_time = entities.get('event_time')
        event_name = entities.get('event_name', '')
        new_time = entities.get('new_time')
        
        if not new_time:
            return "[ERROR] Please specify the new time for the meeting"
        
        # Search for the event using raw search to get event objects
        search_query = event_name if event_name else ""
        events = self.search.search_events_raw(
            query=search_query,
            days_ahead=DEFAULT_DAYS_AHEAD,
            start_time=event_time
        )
        
        if not events:
            return f"[ERROR] No events found matching: '{search_query}'"
        
        # Extract the best matching event
        matched_event = self._find_best_matching_event(events, event_name, event_time)
        
        if not matched_event:
            # Multiple matches - return list for user to choose
            if len(events) > 1:
                message = f"[INFO] Found {len(events)} matching events. Please specify which one:\n\n"
                for i, event in enumerate(events[:ToolLimits.MAX_EVENTS_DISPLAY], 1):
                    event_details = self._extract_event_info(event)
                    message += f"{i}. {event_details['title']} - {event_details['time']} (ID: {event_details['id']})\n"
                if len(events) > ToolLimits.MAX_EVENTS_DISPLAY:
                    message += f"\n... and {len(events) - ToolLimits.MAX_EVENTS_DISPLAY} more events\n"
                message += f"\nUse: `calendar move_event <event_id> {new_time}`"
                return message
            else:
                return f"[ERROR] Could not match event from search results"
        
        event_id = matched_event.get('id')
        # Extract title using extract_event_details for consistency
        event_info = self._extract_event_info(matched_event)
        event_title = event_info['title']
        
        # Step 2: Check for conflicts at new time
        try:
            # Parse new time and check conflicts
            from ...core.calendar.utils import parse_datetime_with_timezone
            
            new_time_dt = parse_datetime_with_timezone(new_time, None)
            if not new_time_dt:
                return f"[ERROR] Could not parse new time: {new_time}"
            
            # Check conflicts (assuming 60-minute duration)
            conflict_result = self.actions._check_scheduling_conflicts(new_time_dt, 60)
            
            if conflict_result['has_conflict']:
                # Step 3: Present conflicts and suggestions
                message = f"WARNING: **Cannot reschedule - Conflict Detected**\n\n"
                message += f"You have {len(conflict_result['conflicts'])} conflicting event(s) at {new_time}:\n\n"
                
                for i, conflict in enumerate(conflict_result['conflicts'][:ToolLimits.MAX_CONFLICTS_DISPLAY], 1):
                    conflict_title = conflict.get('summary', 'Untitled')
                    message += f"{i}. {conflict_title}\n"
                
                suggestions = conflict_result.get('suggestions', [])
                if suggestions:
                    message += f"\n**Suggested alternative times:**\n"
                    for i, suggestion in enumerate(suggestions, 1):
                        message += f"{i}. {suggestion['display']}\n"
                    
                    message += f"\n**To reschedule to a suggested time, try:**\n"
                    message += f"   'Reschedule {event_name} to {suggestions[0]['display']}'\n"
                
                return message
            
            # Step 4: No conflicts - proceed with rescheduling
            # Use the calendar service to update the event
            try:
                from ...core.calendar.utils import parse_datetime_with_timezone, format_datetime_for_calendar
                
                # Parse and format new time
                new_time_dt = parse_datetime_with_timezone(new_time, self.actions.config)
                if not new_time_dt:
                    return f"[ERROR] Could not parse new time: {new_time}"
                
                # Get event duration
                event_start_str = matched_event['start'].get('dateTime', matched_event['start'].get('date'))
                event_end_str = matched_event['end'].get('dateTime', matched_event['end'].get('date'))
                
                try:
                    event_start_dt = datetime.fromisoformat(event_start_str.replace('Z', '+00:00'))
                    event_end_dt = datetime.fromisoformat(event_end_str.replace('Z', '+00:00'))
                    duration_minutes = int((event_end_dt - event_start_dt).total_seconds() / 60)
                except:
                    duration_minutes = 60  # Default duration
                
                # Calculate new end time
                new_end_dt = new_time_dt + timedelta(minutes=duration_minutes)
                
                # Format times for API
                new_start_iso = format_datetime_for_calendar(new_time_dt)
                new_end_iso = format_datetime_for_calendar(new_end_dt)
                
                # Update the event
                updated_event = self.actions.calendar_service.update_event(
                    event_id=event_id,
                    start_time=new_start_iso,
                    end_time=new_end_iso
                )
                
                if updated_event:
                    message = f"SUCCESS: **Event rescheduled**\n\n"
                    message += f"Event: {event_title}\n"
                    message += f"New time: {new_time}\n"
                    message += f"Event ID: {event_id}\n"
                    return message
                else:
                    return f"[ERROR] Failed to reschedule event {event_id}"
                    
            except Exception as e:
                logger.error(f"Failed to reschedule event: {e}", exc_info=True)
                return f"[ERROR] Failed to reschedule event: {str(e)}"
            
        except Exception as e:
            logger.error(f"Error in reschedule workflow: {e}")
            return f"[ERROR] Failed to process reschedule: {str(e)}"
    
    def _handle_cancel(self, parsed: Dict[str, Any]) -> str:
        """Handle cancel operation with search and confirmation"""
        entities = parsed.get('entities', {})
        
        event_time = entities.get('event_time')
        event_name = entities.get('event_name', '')
        attendees = entities.get('attendees', [])
        
        # Build search query
        search_query = event_name
        if attendees:
            search_query += f" with {', '.join(attendees)}"
        
        # Search for the event using raw search
        events = self.search.search_events_raw(
            query=search_query,
            days_ahead=DEFAULT_DAYS_AHEAD,
            start_time=event_time
        )
        
        if not events:
            return f"[ERROR] No events found matching: '{search_query}'"
        
        # Extract the best matching event
        matched_event = self._find_best_matching_event(events, event_name, event_time)
        
        if not matched_event:
            # Multiple matches - return list for user to choose
            if len(events) > 1:
                message = f"[INFO] Found {len(events)} matching events. Please specify which one to cancel:\n\n"
                for i, event in enumerate(events[:ToolLimits.MAX_EVENTS_DISPLAY], 1):
                    event_info = self._extract_event_info(event)
                    message += f"{i}. {event_info['title']} - {event_info['time']} (ID: {event_info['id']})\n"
                if len(events) > ToolLimits.MAX_EVENTS_DISPLAY:
                    message += f"\n... and {len(events) - ToolLimits.MAX_EVENTS_DISPLAY} more events\n"
                message += f"\nUse: `calendar delete <event_id>`"
                return message
            else:
                return f"[ERROR] Could not match event from search results"
        
        # Found a match - show details and ask for confirmation
        event_info = self._extract_event_info(matched_event)
        event_id = event_info['id']
        
        message = f"FOUND: **Event to Cancel:**\n\n"
        message += f"Title: {event_info['title']}\n"
        message += f"Time: {event_info['time']}\n"
        if event_info['location']:
            message += f"Location: {event_info['location']}\n"
        if event_info['attendees']:
            message += f"Attendees: {', '.join(event_info['attendees'][:ToolLimits.MAX_ATTENDEES_DISPLAY])}\n"
        message += f"\nEvent ID: {event_id}\n"
        message += f"\nNOTE: **To confirm cancellation, use:**\n"
        message += f"`calendar delete {event_id}`"
        
        return message
    
    def _handle_create(self, parsed: Dict[str, Any]) -> str:
        """Handle create operation with conflict detection"""
        entities = parsed.get('entities', {})
        
        # Build parameters
        title = entities.get('title', 'New Event')
        start_time = entities.get('time') or entities.get('date', 'tomorrow at 9am')
        duration = entities.get('duration_minutes', 60)
        attendees = entities.get('attendees')
        recurrence = entities.get('recurrence_pattern') if entities.get('is_recurring') else None
        
        # Create the event (conflict detection is built-in)
        result = self.actions.create_event(
            title=title,
            start_time=start_time,
            duration_minutes=duration,
            attendees=attendees,
            recurrence=recurrence
        )
        
        return result
    
    def _handle_find_free_time(self, parsed: Dict[str, Any]) -> str:
        """Handle find free time operation"""
        entities = parsed.get('entities', {})
        
        duration = entities.get('duration_minutes', 60)
        start_date = entities.get('date')
        
        result = self.availability.find_free_time(
            duration_minutes=duration,
            start_date=start_date
        )
        
        return result
    
    def _handle_list(self, parsed: Dict[str, Any]) -> str:
        """Handle list operation with optional action items"""
        entities = parsed.get('entities', {})
        context = parsed.get('context', {})
        
        from ...core.calendar.utils import DEFAULT_DAYS_AHEAD
        days_ahead = DEFAULT_DAYS_AHEAD  # Default
        time_range = entities.get('time_range', 'week')
        
        if time_range == 'today':
            days_ahead = 1
        elif time_range == 'tomorrow':
            days_ahead = 2
        elif time_range == 'month':
            days_ahead = 30
        
        # List events
        result = self.search.list_events(days_ahead=days_ahead)
        
        # If action items requested, add note
        if context.get('include_action_items'):
            result += "\n\nNOTE: **Action Items:**\n"
            result += "To extract action items from events, use the `prepare_meeting` action for specific events."
        
        return result
    
    def handle_smart_reschedule(
        self,
        event_identifier: str,
        new_time: str,
        auto_find_alternatives: bool = True
    ) -> Dict[str, Any]:
        """
        Smart reschedule with automatic conflict resolution
        
        Args:
            event_identifier: Event name, time, or ID
            new_time: Proposed new time
            auto_find_alternatives: Auto-suggest alternatives if conflicts
            
        Returns:
            Dictionary with status, conflicts, and suggestions
        """
        try:
            # Parse new time
            from ...core.calendar.utils import parse_datetime_with_timezone
            
            new_time_dt = parse_datetime_with_timezone(new_time, None)
            if not new_time_dt:
                return {
                    'success': False,
                    'error': f'Invalid new time: {new_time}'
                }
            
            # Check for conflicts (default 60 min duration)
            conflict_result = self.actions._check_scheduling_conflicts(new_time_dt, 60)
            
            if conflict_result['has_conflict']:
                response = {
                    'success': False,
                    'has_conflict': True,
                    'conflicts': conflict_result['conflicts'],
                    'suggestions': conflict_result.get('suggestions', []),
                    'message': self._format_conflict_message(
                        event_identifier,
                        new_time,
                        conflict_result
                    )
                }
                
                return response
            
            # No conflicts - ready to reschedule
            return {
                'success': True,
                'has_conflict': False,
                'message': f'SUCCESS: No conflicts at {new_time}. Ready to reschedule {event_identifier}.',
                'next_step': 'confirm_and_execute'
            }
            
        except Exception as e:
            logger.error(f"Smart reschedule error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _format_conflict_message(
        self,
        event_name: str,
        new_time: str,
        conflict_result: Dict[str, Any]
    ) -> str:
        """Format a user-friendly conflict message"""
        message = f"WARNING: **Cannot reschedule '{event_name}' to {new_time}**\n\n"
        message += f"**Conflicting Events ({len(conflict_result['conflicts'])}):**\n"
        
        for i, conflict in enumerate(conflict_result['conflicts'][:ToolLimits.MAX_CONFLICTS_DISPLAY], 1):
            title = conflict.get('summary', 'Untitled')
            message += f"{i}. {title}\n"
        
        suggestions = conflict_result.get('suggestions', [])
        if suggestions:
            message += f"\n**Alternative times available:**\n"
            for i, suggestion in enumerate(suggestions, 1):
                message += f"{i}. {suggestion['display']}\n"
        
        return message
    
    def _find_best_matching_event(
        self,
        events: List[Dict[str, Any]],
        event_name: Optional[str] = None,
        event_time: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find the best matching event from a list of events
        
        Args:
            events: List of event dictionaries
            event_name: Optional event name to match
            event_time: Optional event time to match
            
        Returns:
            Best matching event or None if ambiguous
        """
        if not events:
            return None
        
        if len(events) == 1:
            return events[0]
        
        # If we have both name and time, try to find exact match
        if event_name and event_time:
            try:
                from ...core.calendar.utils import parse_datetime_with_timezone
                target_time_dt = parse_datetime_with_timezone(event_time, self.actions.config)
                
                if target_time_dt:
                    # Find events matching both name and time (within 1 hour window)
                    event_name_lower = event_name.lower()
                    for event in events:
                        # Extract title from event (can be 'summary' or 'title')
                        event_title = (event.get('summary') or event.get('title') or '').lower()
                        event_start_str = event['start'].get('dateTime', event['start'].get('date'))
                        
                        try:
                            event_start_dt = datetime.fromisoformat(event_start_str.replace('Z', '+00:00'))
                            time_diff = abs((event_start_dt - target_time_dt).total_seconds())
                            
                            # Match if name contains query or query contains name, and time is within 1 hour
                            name_match = (event_name_lower in event_title or event_title in event_name_lower)
                            time_match = time_diff < 3600  # Within 1 hour
                            
                            if name_match and time_match:
                                return event
                        except:
                            continue
            except:
                pass
        
        # If we have name, find best name match
        if event_name:
            event_name_lower = event_name.lower()
            best_match = None
            best_score = 0
            
            for event in events:
                # Extract title from event (can be 'summary' or 'title')
                event_title = (event.get('summary') or event.get('title') or '').lower()
                
                # Calculate match score
                score = 0
                if event_name_lower == event_title:
                    score = 100  # Exact match
                elif event_name_lower in event_title:
                    score = 50 + len(event_name_lower) / len(event_title) * 30  # Partial match
                elif event_title in event_name_lower:
                    score = 30 + len(event_title) / len(event_name_lower) * 20
                
                if score > best_score:
                    best_score = score
                    best_match = event
            
            if best_match and best_score > 30:
                return best_match
        
        # If we have time, find closest time match
        if event_time:
            try:
                from ...core.calendar.utils import parse_datetime_with_timezone
                target_time_dt = parse_datetime_with_timezone(event_time, self.actions.config)
                
                if target_time_dt:
                    best_match = None
                    min_time_diff = float('inf')
                    
                    for event in events:
                        event_start_str = event['start'].get('dateTime', event['start'].get('date'))
                        try:
                            event_start_dt = datetime.fromisoformat(event_start_str.replace('Z', '+00:00'))
                            time_diff = abs((event_start_dt - target_time_dt).total_seconds())
                            
                            if time_diff < min_time_diff:
                                min_time_diff = time_diff
                                best_match = event
                        except:
                            continue
                    
                    if best_match and min_time_diff < 86400:  # Within 24 hours
                        return best_match
            except:
                pass
        
        # If no clear match, return None (ambiguous)
        return None
    
    def _extract_event_info(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract key information from an event dictionary
        
        Args:
            event: Event dictionary
            
        Returns:
            Dictionary with extracted event info
        """
        from ...core.calendar.utils import extract_event_details, format_event_time_display
        
        event_details = extract_event_details(event)
        start_dt = event_details.get('start')
        
        time_str = "Time TBD"
        if start_dt:
            try:
                time_str = format_event_time_display(start_dt, include_date=True)
            except:
                time_str = str(start_dt)
        
        return {
            'id': event.get('id', ''),
            'title': event_details.get('title', 'Untitled'),
            'time': time_str,
            'location': event_details.get('location', ''),
            'attendees': event_details.get('attendees', [])
        }
