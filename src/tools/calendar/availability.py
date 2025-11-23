"""
Calendar Availability Module

Handles free time finding, conflict detection, and availability checks.
"""
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from ..constants import ToolLimits
from ...integrations.google_calendar.service import CalendarService
from ...core.calendar.utils import (
    parse_datetime_with_timezone,
    parse_event_time,
    find_conflicts,
    format_event_time_display,
    get_day_boundaries,
    events_overlap,
    DEFAULT_DURATION_MINUTES
)

logger = setup_logger(__name__)


class CalendarAvailability:
    """Calendar availability and conflict detection operations"""
    
    def __init__(self, calendar_service: CalendarService, config: Optional[Any] = None):
        """
        Initialize calendar availability
        
        Args:
            calendar_service: Calendar service instance
            config: Configuration object
        """
        self.calendar_service = calendar_service
        # Keep backward compatibility
        self.google_client = calendar_service.calendar_client if hasattr(calendar_service, 'calendar_client') else None
        self.config = config
    
    def find_free_time(
        self,
        duration_minutes: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> str:
        """
        Find free time slots in calendar
        
        Args:
            duration_minutes: Required duration in minutes
            start_date: Optional start date (ISO format)
            end_date: Optional end date (ISO format)
            
        Returns:
            Formatted list of free time slots
        """
        try:
            free_slots = self.google_client.find_free_time_slots(
                duration_minutes=duration_minutes,
                start_date=start_date,
                end_date=end_date
            )
            
            if not free_slots:
                return "No free time slots found in the specified range."
            
            output = f"**📅 Available Time Slots ({len(free_slots)}):**\n\n"
            for i, slot in enumerate(free_slots[:ToolLimits.MAX_FREE_SLOTS_DISPLAY], 1):
                start_dt = datetime.fromisoformat(slot['start'].replace('Z', '+00:00'))
                formatted_time = format_event_time_display(start_dt, include_date=True)
                output += f"{i}. {formatted_time} ({duration_minutes} minutes)\n"
            
            if len(free_slots) > ToolLimits.MAX_FREE_SLOTS_DISPLAY:
                output += f"\n... and {len(free_slots) - ToolLimits.MAX_FREE_SLOTS_DISPLAY} more slots available"
            
            return output
            
        except Exception as e:
            return f"[ERROR] Failed to find free time: {str(e)}"
    
    def check_conflicts(
        self,
        start_time: str,
        duration_minutes: int = DEFAULT_DURATION_MINUTES
    ) -> Dict[str, Any]:
        """
        Check for calendar conflicts at the proposed time
        
        Args:
            start_time: Proposed start time (ISO format)
            duration_minutes: Event duration in minutes
            
        Returns:
            Dictionary with conflict information
        """
        try:
            # Parse start time
            start_dt = parse_datetime_with_timezone(start_time, self.config)
            if not start_dt:
                return {'has_conflict': False, 'error': 'Invalid start_time'}
            
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
            
            # Collect all events for suggestions
            day_events: List[Tuple[datetime, datetime]] = []
            for event in events:
                event_start = parse_event_time(event.get('start', {}))
                event_end = parse_event_time(event.get('end', {}))
                if event_start and event_end:
                    day_events.append((event_start, event_end))
            
            return {
                'has_conflict': len(conflicts) > 0,
                'conflicts': conflicts,
                'proposed_start': start_dt,
                'proposed_end': end_dt,
                'day_events': day_events
            }
            
        except Exception as e:
            logger.warning(f"Could not check for conflicts: {e}")
            return {'has_conflict': False, 'error': str(e)}
    
    def analyze_conflicts(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> str:
        """
        Analyze calendar for conflicts
        
        Args:
            start_time: Optional start time for analysis period
            end_time: Optional end time for analysis period
            
        Returns:
            Conflict analysis result
        """
        try:
            # Get events for analysis
            if start_time and end_time:
                events = self.google_client.get_events_in_range(start_time, end_time)
            else:
                # Default to next 7 days
                now = datetime.now()
                week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                week_end = week_start + timedelta(days=7)
                
                start_time = week_start.isoformat() + 'Z'
                end_time = week_end.isoformat() + 'Z'
                
                events = self.google_client.get_events_in_range(start_time, end_time)
            
            if not events:
                return "[CAL] **No events found** in the specified time period."
            
            # Find conflicts
            conflicts = self._find_calendar_conflicts(events)
            
            if not conflicts:
                return "[OK] **No scheduling conflicts detected!** Your calendar looks well-organized."
            
            # Format conflict analysis
            result = f"🚨 **Calendar Conflict Analysis:**\n\n"
            result += f"Found {len(conflicts)} potential conflicts:\n\n"
            
            for i, conflict in enumerate(conflicts, 1):
                result += f"{i}. **Conflict at {conflict['time']}:**\n"
                result += f"   • {conflict['event1']}\n"
                result += f"   • {conflict['event2']}\n"
                result += f"   📍 Overlap: {conflict['overlap_duration']} minutes\n\n"
            
            result += "💡 **Recommendations:**\n"
            result += "• Consider rescheduling overlapping events\n"
            result += "• Use shorter meeting durations when possible\n"
            result += "• Block buffer time between back-to-back meetings\n"
            
            return result
            
        except Exception as e:
            logger.error(f"Conflict analysis failed: {e}")
            return f"[ERROR] Error analyzing conflicts: {str(e)}"
    
    def check_attendee_availability(
        self,
        attendees: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        duration_minutes: int = DEFAULT_DURATION_MINUTES
    ) -> str:
        """
        Check when attendees are available
        
        Args:
            attendees: List of attendee emails
            start_date: Start date (ISO format)
            end_date: End date (ISO format)
            duration_minutes: Required meeting duration
            
        Returns:
            Availability analysis
        """
        try:
            if not attendees:
                return "[ERROR] No attendees specified"
            
            # Set default date range (next 7 days)
            if not start_date:
                start_date = datetime.now().isoformat() + 'Z'
            if not end_date:
                end_date = (datetime.now() + timedelta(days=7)).isoformat() + 'Z'
            
            # Check freebusy for all attendees
            freebusy_result = self.google_client.check_freebusy(
                time_min=start_date,
                time_max=end_date,
                items=[{'id': email} for email in attendees]
            )
            
            if not freebusy_result or 'calendars' not in freebusy_result:
                return "[ERROR] Failed to check availability"
            
            # Analyze availability
            output = f"**📊 Availability for {len(attendees)} attendees:**\n\n"
            
            calendars = freebusy_result.get('calendars', {})
            for email, calendar_data in calendars.items():
                busy_periods = calendar_data.get('busy', [])
                output += f"**{email}:**\n"
                
                if not busy_periods:
                    output += "  ✅ Available all day\n"
                else:
                    output += f"  🔴 {len(busy_periods)} busy periods\n"
                    for period in busy_periods[:3]:
                        start = datetime.fromisoformat(period['start'].replace('Z', '+00:00'))
                        end = datetime.fromisoformat(period['end'].replace('Z', '+00:00'))
                        output += f"    • {format_event_time_display(start)} - {format_event_time_display(end)}\n"
                output += "\n"
            
            return output
            
        except Exception as e:
            return f"[ERROR] Failed to check availability: {str(e)}"
    
    def _find_calendar_conflicts(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find conflicts in a list of calendar events"""
        conflicts = []
        
        # Sort events by start time
        sorted_events = sorted(events, key=lambda x: x['start'].get('dateTime', x['start'].get('date')))
        
        for i in range(len(sorted_events)):
            for j in range(i + 1, len(sorted_events)):
                event1 = sorted_events[i]
                event2 = sorted_events[j]
                
                # Check if events overlap
                if self._events_overlap(event1, event2):
                    conflict_info = self._create_conflict_info(event1, event2)
                    conflicts.append(conflict_info)
        
        return conflicts
    
    def _events_overlap(self, event1: Dict[str, Any], event2: Dict[str, Any]) -> bool:
        """Check if two events overlap"""
        try:
            start1 = parse_event_time(event1.get('start', {}))
            end1 = parse_event_time(event1.get('end', {}))
            start2 = parse_event_time(event2.get('start', {}))
            end2 = parse_event_time(event2.get('end', {}))
            
            if not all([start1, end1, start2, end2]):
                return False
            
            return events_overlap(start1, end1, start2, end2)
        except Exception as e:
            logger.warning(f"Error checking event overlap: {e}")
            return False
    
    def _create_conflict_info(self, event1: Dict[str, Any], event2: Dict[str, Any]) -> Dict[str, Any]:
        """Create conflict information between two events"""
        start1 = parse_event_time(event1.get('start', {}))
        end1 = parse_event_time(event1.get('end', {}))
        start2 = parse_event_time(event2.get('start', {}))
        end2 = parse_event_time(event2.get('end', {}))
        
        if not all([start1, end1, start2, end2]):
            return {}
        
        # Calculate overlap duration
        overlap_start = max(start1, start2)
        overlap_end = min(end1, end2)
        overlap_duration = int((overlap_end - overlap_start).total_seconds() / 60)
        
        conflict_time = format_event_time_display(overlap_start, include_date=False)
        
        return {
            'time': conflict_time,
            'event1': event1.get('summary', event1.get('title', 'Untitled Event')),
            'event2': event2.get('summary', event2.get('title', 'Untitled Event')),
            'overlap_duration': overlap_duration,
            'start1': start1,
            'end1': end1,
            'start2': start2,
            'end2': end2
        }
