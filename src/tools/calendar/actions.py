"""
Calendar Actions Module

Handles calendar event CRUD operations: create, update, delete events.
"""
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import re

from ...utils.logger import setup_logger
from ...integrations.google_calendar.service import CalendarService
from ...core.calendar.utils import (
    parse_datetime_with_timezone,
    format_datetime_for_calendar,
    format_event_time_display,
    get_user_timezone,
    validate_attendees,
    get_day_boundaries,
    find_conflicts,
    parse_event_time,
    events_overlap,
    DEFAULT_DURATION_MINUTES
)
import pytz

logger = setup_logger(__name__)


class CalendarActions:
    """Calendar event CRUD operations"""
    
    def __init__(self, calendar_service: CalendarService, config: Optional[Any] = None, date_parser: Optional[Any] = None):
        """
        Initialize calendar actions
        
        Args:
            calendar_service: Calendar service instance
            config: Configuration object
            date_parser: Optional date parser for flexible date handling
        """
        self.calendar_service = calendar_service
        # Keep backward compatibility - some code may access google_client directly
        self.google_client = calendar_service.calendar_client if hasattr(calendar_service, 'calendar_client') else None
        self.config = config
        self.date_parser = date_parser
    
    def create_event(
        self,
        title: str,
        start_time: str,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
        attendees: Optional[List[str]] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        recurrence: Optional[str] = None,
        skip_conflict_check: bool = False
    ) -> str:
        """
        Create a new calendar event with automatic conflict detection
        
        Args:
            title: Event title
            start_time: Start time (ISO format or natural language)
            duration_minutes: Event duration in minutes
            attendees: List of attendee emails
            description: Event description
            location: Event location
            recurrence: Recurrence pattern (RRULE format)
            skip_conflict_check: Skip conflict detection (default: False)
            
        Returns:
            Success message with event details or conflict warning
        """
        try:
            if not title or not start_time:
                return "[ERROR] Title and start_time are required to create an event"
            
            # Parse and normalize start_time
            start_dt = parse_datetime_with_timezone(start_time, self.config)
            if not start_dt:
                return f"Invalid start_time format: {start_time}"
            
            # === AUTOMATIC CONFLICT DETECTION ===
            if not skip_conflict_check:
                conflict_result = self._check_scheduling_conflicts(start_dt, duration_minutes)
                if conflict_result['has_conflict']:
                    return self._format_conflict_warning(
                        title, start_dt, duration_minutes, 
                        conflict_result['conflicts'],
                        conflict_result.get('suggestions', [])
                    )
            
            # Format for Google Calendar API
            if re.search(r'[+-]\d{2}:\d{2}$', start_time):
                # Has timezone offset - preserve it
                if start_dt.tzinfo:
                    tz_offset = start_dt.strftime('%z')
                    if tz_offset:
                        offset_formatted = f"{tz_offset[:3]}:{tz_offset[3:]}"
                        rfc3339_start = start_dt.strftime(f'%Y-%m-%dT%H:%M:00{offset_formatted}')
                    else:
                        rfc3339_start = start_dt.strftime('%Y-%m-%dT%H:%M:00')
                else:
                    rfc3339_start = start_time
            else:
                rfc3339_start = format_datetime_for_calendar(start_dt, self.config)
            
            # Validate duration
            final_duration = duration_minutes if duration_minutes and duration_minutes > 0 else DEFAULT_DURATION_MINUTES
            
            # Validate attendees
            attendees = validate_attendees(attendees)
            
            # Parse recurrence if provided
            recurrence_list = self._parse_recurrence(recurrence, start_dt) if recurrence else None
            
            logger.info(f"Creating event: {title} at {rfc3339_start} (duration: {final_duration} min)")
            
            # Create event via Google Calendar client
            created_event = self.google_client.create_event(
                title=title,
                start_time=rfc3339_start,
                duration_minutes=final_duration,
                description=description or "",
                location=location or "",
                attendees=attendees,
                recurrence=recurrence_list
            )
            
            if created_event:
                link = created_event.get('htmlLink', '')
                
                # Format display time
                display_dt = start_dt
                if start_dt.tzinfo:
                    utc_offset = start_dt.utcoffset()
                    tz_offset_hours = utc_offset.total_seconds() / 3600 if utc_offset else None
                    
                    if tz_offset_hours in [-8, -7]:  # PST/PDT
                        display_dt = start_dt
                    else:
                        tz_name = get_user_timezone(self.config)
                        configured_tz = pytz.timezone(tz_name)
                        display_dt = start_dt.astimezone(configured_tz)
                else:
                    tz_name = get_user_timezone(self.config)
                    configured_tz = pytz.timezone(tz_name)
                    display_dt = configured_tz.localize(start_dt) if start_dt.tzinfo is None else start_dt.astimezone(configured_tz)
                
                display_time = format_event_time_display(display_dt, include_date=True)
                
                return f"Created Google Calendar event: {title}\nDate: {display_time}\nLink: {link}"
            else:
                return f"Failed to create Google Calendar event: {title}"
            
        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            raise Exception(f"Failed to create event: {str(e)}")
    
    def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        attendees: Optional[List[str]] = None,
        description: Optional[str] = None,
        location: Optional[str] = None
    ) -> str:
        """Update an existing calendar event"""
        try:
            if not event_id:
                return "[ERROR] event_id is required to update an event"
            
            # Convert start_time to RFC 3339 format if provided
            rfc3339_start = None
            rfc3339_end = None
            if start_time:
                try:
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    rfc3339_start = start_dt.isoformat() + 'Z'
                    
                    if duration_minutes:
                        end_dt = start_dt + timedelta(minutes=duration_minutes)
                        rfc3339_end = end_dt.isoformat() + 'Z'
                except:
                    return f"[ERROR] Invalid start_time format: {start_time}"
            
            # Update event
            updated_event = self.google_client.update_event(
                event_id=event_id,
                title=title,
                start_time=rfc3339_start,
                end_time=rfc3339_end,
                description=description,
                location=location,
                attendees=attendees
            )
            
            if updated_event:
                return f"Updated Google Calendar event: {updated_event.get('summary', 'Untitled')}"
            else:
                return f"Failed to update Google Calendar event: {event_id}"
            
        except Exception as e:
            raise Exception(f"Failed to update event: {str(e)}")
    
    def delete_event(self, event_id: str) -> str:
        """Delete a calendar event"""
        try:
            if not event_id:
                return "[ERROR] event_id is required to delete an event"
            
            success = self.google_client.delete_event(event_id=event_id)
            
            if success:
                return f"Deleted Google Calendar event: {event_id}"
            else:
                return f"Failed to delete Google Calendar event: {event_id}"
            
        except Exception as e:
            raise Exception(f"Failed to delete event: {str(e)}")
    
    def move_event(self, event_id: str, new_start_time: str) -> str:
        """Move an event to a new time"""
        try:
            if not event_id or not new_start_time:
                return "[ERROR] event_id and new_start_time are required"
            
            # Get existing event to preserve duration
            event = self.google_client.get_event(event_id)
            if not event:
                return f"[ERROR] Event not found: {event_id}"
            
            # Calculate duration from existing event
            start_dt = datetime.fromisoformat(event['start'].get('dateTime', '').replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(event['end'].get('dateTime', '').replace('Z', '+00:00'))
            duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
            
            # Update with new time
            return self.update_event(event_id, start_time=new_start_time, duration_minutes=duration_minutes)
            
        except Exception as e:
            raise Exception(f"Failed to move event: {str(e)}")
    
    def _parse_recurrence(self, recurrence: Optional[str], start_dt: datetime) -> Optional[List[str]]:
        """Parse recurrence pattern into Google Calendar RRULE format"""
        if not recurrence:
            return None
        
        try:
            from ...core.calendar.recurrence_parser import RecurrenceParser
            recurrence_parser = RecurrenceParser()
            return recurrence_parser.parse(recurrence, start_dt)
        except Exception as e:
            logger.warning(f"Could not parse recurrence '{recurrence}': {e}")
            return None
    
    def _check_scheduling_conflicts(
        self,
        start_dt: datetime,
        duration_minutes: int
    ) -> Dict[str, Any]:
        """
        Check for scheduling conflicts at proposed time
        
        Args:
            start_dt: Proposed start datetime
            duration_minutes: Event duration in minutes
            
        Returns:
            Dictionary with conflict information and suggestions
        """
        try:
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            
            # Get day boundaries
            day_start, day_end = get_day_boundaries(start_dt, self.config)
            
            # Convert to UTC for API call
            from datetime import timezone
            day_start_utc = day_start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            day_end_utc = day_end.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            
            # Get events for the day
            events = self.google_client.get_events_in_range(day_start_utc, day_end_utc)
            
            # Find conflicts
            conflicts = find_conflicts(start_dt, end_dt, events)
            
            # If conflicts found, suggest alternative times
            suggestions = []
            if conflicts:
                suggestions = self._suggest_alternative_times(
                    start_dt, duration_minutes, events
                )
            
            return {
                'has_conflict': len(conflicts) > 0,
                'conflicts': conflicts,
                'suggestions': suggestions,
                'proposed_start': start_dt,
                'proposed_end': end_dt
            }
            
        except Exception as e:
            logger.warning(f"Could not check for conflicts: {e}")
            return {'has_conflict': False, 'error': str(e)}
    
    def _suggest_alternative_times(
        self,
        proposed_start: datetime,
        duration_minutes: int,
        existing_events: List[Dict[str, Any]],
        max_suggestions: int = 5
    ) -> List[Dict[str, str]]:
        """
        Intelligently suggest alternative time slots when conflicts are detected.
        Searches same day first, then next day, then entire week.
        
        Args:
            proposed_start: Original proposed start time
            duration_minutes: Required duration
            existing_events: List of existing events
            max_suggestions: Maximum number of suggestions to return
            
        Returns:
            List of suggested time slots with display strings
        """
        suggestions = []
        
        try:
            # Parse existing events into time slots
            busy_slots = []
            for event in existing_events:
                event_start = parse_event_time(event.get('start', {}))
                event_end = parse_event_time(event.get('end', {}))
                if event_start and event_end:
                    busy_slots.append((event_start, event_end))
            
            # Sort busy slots by start time
            busy_slots.sort(key=lambda x: x[0])
            
            # Get user timezone for day boundaries
            from ...core.calendar.utils import get_user_timezone
            tz_name = get_user_timezone(self.config)
            user_tz = pytz.timezone(tz_name)
            
            # Ensure proposed_start has timezone
            if proposed_start.tzinfo is None:
                proposed_start = user_tz.localize(proposed_start)
            
            # Strategy 1: Find free slots on the same day
            day_start, day_end = get_day_boundaries(proposed_start, self.config)
            same_day_suggestions = self._find_free_slots_in_range(
                day_start, day_end, duration_minutes, busy_slots, 
                preferred_start=proposed_start, max_count=max_suggestions
            )
            suggestions.extend(same_day_suggestions)
            
            # Strategy 2: If day is full or not enough suggestions, try next day
            if len(suggestions) < max_suggestions:
                next_day_start = day_start + timedelta(days=1)
                next_day_end = day_end + timedelta(days=1)
                next_day_suggestions = self._find_free_slots_in_range(
                    next_day_start, next_day_end, duration_minutes, busy_slots,
                    max_count=max_suggestions - len(suggestions)
                )
                suggestions.extend(next_day_suggestions)
            
            # Strategy 3: If still not enough, search entire week
            if len(suggestions) < max_suggestions:
                week_start = day_start
                week_end = day_start + timedelta(days=7)
                week_suggestions = self._find_free_slots_in_range(
                    week_start, week_end, duration_minutes, busy_slots,
                    max_count=max_suggestions - len(suggestions)
                )
                suggestions.extend(week_suggestions)
            
        except Exception as e:
            logger.warning(f"Could not suggest alternative times: {e}")
        
        return suggestions[:max_suggestions]
    
    def _find_free_slots_in_range(
        self,
        range_start: datetime,
        range_end: datetime,
        duration_minutes: int,
        busy_slots: List[Tuple[datetime, datetime]],
        preferred_start: Optional[datetime] = None,
        max_count: int = 5,
        working_hours_only: bool = True
    ) -> List[Dict[str, str]]:
        """
        Find free time slots within a date range.
        
        Args:
            range_start: Start of search range
            range_end: End of search range
            duration_minutes: Required duration
            busy_slots: List of (start, end) tuples for busy periods
            preferred_start: Preferred start time (prioritize slots near this)
            max_count: Maximum suggestions to return
            working_hours_only: Only suggest during working hours (9am-6pm)
            
        Returns:
            List of suggested time slots
        """
        suggestions = []
        
        # Filter busy slots to this range
        range_busy_slots = [
            (start, end) for start, end in busy_slots
            if start < range_end and end > range_start
        ]
        
        # Sort by start time
        range_busy_slots.sort(key=lambda x: x[0])
        
        # Define working hours
        work_start_hour = 9
        work_end_hour = 18
        
        # Start searching from preferred_start or range_start
        current_time = preferred_start if preferred_start and preferred_start >= range_start else range_start
        
        # Ensure current_time is at start of hour for cleaner suggestions
        current_time = current_time.replace(minute=0, second=0, microsecond=0)
        
        # Try 30-minute intervals
        interval_minutes = 30
        
        while current_time < range_end and len(suggestions) < max_count:
            # Check working hours
            if working_hours_only:
                if current_time.hour < work_start_hour:
                    current_time = current_time.replace(hour=work_start_hour, minute=0)
                    continue
                if current_time.hour >= work_end_hour:
                    # Move to next day
                    current_time = (current_time + timedelta(days=1)).replace(hour=work_start_hour, minute=0)
                    if current_time >= range_end:
                        break
                    continue
            
            # Calculate end time for this slot
            slot_end = current_time + timedelta(minutes=duration_minutes)
            
            # Check if slot extends beyond range
            if slot_end > range_end:
                break
            
            # Check if this slot conflicts with any busy slot
            is_free = True
            for busy_start, busy_end in range_busy_slots:
                if events_overlap(current_time, slot_end, busy_start, busy_end):
                    is_free = False
                    # Skip to after this busy slot
                    current_time = busy_end
                    # Round up to next interval
                    current_time = current_time.replace(minute=0, second=0, microsecond=0)
                    if current_time.minute % interval_minutes != 0:
                        current_time += timedelta(minutes=interval_minutes - (current_time.minute % interval_minutes))
                    break
            
            if is_free:
                suggestions.append({
                    'start': current_time.isoformat(),
                    'display': format_event_time_display(current_time, include_date=True)
                })
                current_time += timedelta(minutes=interval_minutes)
            else:
                # Already advanced current_time in the conflict check
                pass
        
        return suggestions
    
    def _format_conflict_warning(
        self,
        title: str,
        start_dt: datetime,
        duration_minutes: int,
        conflicts: List[Dict[str, Any]],
        suggestions: List[Dict[str, str]]
    ) -> str:
        """
        Format a user-friendly conflict warning with suggestions
        
        Args:
            title: Event title
            start_dt: Proposed start time
            duration_minutes: Event duration
            conflicts: List of conflicting events
            suggestions: List of suggested alternative times
            
        Returns:
            Formatted conflict warning message
        """
        proposed_time = format_event_time_display(start_dt, include_date=True)
        
        message = f"⚠️ **Scheduling Conflict Detected**\n\n"
        message += f"Cannot schedule '{title}' at {proposed_time}\n"
        message += f"Duration: {duration_minutes} minutes\n\n"
        
        message += f"**Conflicting Events ({len(conflicts)}):**\n"
        for i, conflict in enumerate(conflicts[:3], 1):  # Show max 3 conflicts
            conflict_title = conflict.get('summary', 'Untitled Event')
            conflict_start = conflict.get('start_time', 'Unknown time')
            message += f"{i}. {conflict_title} at {conflict_start}\n"
        
        if len(conflicts) > 3:
            message += f"   ... and {len(conflicts) - 3} more conflicts\n"
        
        if suggestions:
            message += f"\n💡 **Suggested Alternative Times:**\n"
            for i, suggestion in enumerate(suggestions, 1):
                message += f"{i}. {suggestion['display']}\n"
            
            message += f"\n📝 **To schedule at a suggested time, try:**\n"
            message += f"   'Schedule {title} at {suggestions[0]['display']}'\n"
        else:
            message += f"\n💡 **Tip:** Try using 'find free time' to see available slots\n"
        
        return message
