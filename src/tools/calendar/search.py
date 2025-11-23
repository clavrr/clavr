"""
Calendar Search Module

Handles calendar event search and listing operations.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from ..constants import ToolLimits
from ...integrations.google_calendar.service import CalendarService
from ...core.calendar.utils import (
    extract_event_details,
    format_event_time_display,
    get_user_timezone,
    DEFAULT_DAYS_AHEAD
)
import pytz

logger = setup_logger(__name__)


class CalendarSearch:
    """Calendar event search and listing operations"""
    
    def __init__(self, calendar_service: CalendarService, config: Optional[Any] = None):
        """
        Initialize calendar search
        
        Args:
            calendar_service: Calendar service instance
            config: Configuration object
        """
        self.calendar_service = calendar_service
        # Keep backward compatibility
        self.google_client = calendar_service.calendar_client if hasattr(calendar_service, 'calendar_client') else None
        self.config = config
    
    def list_events(
        self,
        days_ahead: int = DEFAULT_DAYS_AHEAD,
        days_back: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> str:
        """
        List calendar events
        
        Args:
            days_ahead: Number of days to look ahead
            days_back: Number of days to look back
            start_date: Optional ISO format start date
            end_date: Optional ISO format end date
            
        Returns:
            Formatted string with event details
        """
        try:
            # Parse ISO date strings to datetime objects if provided
            start_dt = None
            end_dt = None
            if start_date:
                try:
                    start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                except Exception as e:
                    logger.warning(f"Failed to parse start_date '{start_date}': {e}")
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                except Exception as e:
                    logger.warning(f"Failed to parse end_date '{end_date}': {e}")
            
            events = self.google_client.list_events(
                days_ahead=days_ahead,
                days_back=days_back,
                start_date=start_dt,
                end_date=end_dt
            )
            
            logger.info(f"Retrieved {len(events)} events from Google Calendar")
            
            if not events:
                return f"No upcoming events in the next {days_ahead} days."
            
            output = f"**[CAL] Google Calendar Events ({len(events)}):**\n\n"
            
            for event in events:
                event_details = extract_event_details(event)
                summary = event_details['title']
                start_dt = event_details['start']
                location = event_details['location']
                attendees = event_details['attendees']
                description = event_details['description']
                
                # Format start time
                if start_dt:
                    tz_name = get_user_timezone(self.config)
                    user_tz = pytz.timezone(tz_name)
                    
                    if start_dt.tzinfo:
                        start_dt_local = start_dt.astimezone(user_tz)
                    else:
                        start_dt_local = pytz.utc.localize(start_dt).astimezone(user_tz)
                    
                    formatted_time_display = format_event_time_display(start_dt_local, include_date=True)
                    formatted_time_parseable = start_dt_local.strftime('%Y-%m-%d %H:%M')
                else:
                    formatted_time_display = "Time TBD"
                    formatted_time_parseable = ""
                
                output += f"[CAL] **{summary}**\n"
                if formatted_time_parseable:
                    output += f"   [TIME] Time: {formatted_time_parseable}\n"
                else:
                    output += f"   [TIME] Time: {formatted_time_display}\n"
                
                if location:
                    output += f"   [LOC] Location: {location}\n"
                
                if attendees:
                    attendee_display = ', '.join(attendees[:ToolLimits.MAX_ATTENDEES_DISPLAY])
                    if len(attendees) > ToolLimits.MAX_ATTENDEES_DISPLAY:
                        attendee_display += f" and {len(attendees) - ToolLimits.MAX_ATTENDEES_DISPLAY} more"
                    output += f"   Attendees: {attendee_display}\n"
                
                if description:
                    output += f"   Description: {description}\n"
                
                output += "\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Failed to list events: {e}", exc_info=True)
            raise Exception(f"Failed to list events: {str(e)}")
    
    def search_events_raw(
        self,
        query: str,
        days_ahead: int = 30,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search events in Google Calendar and return raw event data
        
        Args:
            query: Search query
            days_ahead: Days to look ahead
            start_time: Optional start time for time range search
            end_time: Optional end time for time range search
            
        Returns:
            List of raw event dictionaries
        """
        try:
            # If specific time range is provided, use it
            if start_time and end_time:
                events = self.google_client.get_events_in_range(start_time, end_time)
            else:
                events = self.google_client.search_events(query=query, days_ahead=days_ahead)
            
            return events if events else []
            
        except Exception as e:
            logger.error(f"Failed to search events (raw): {e}", exc_info=True)
            return []
    
    def search_events(self, query: str, days_ahead: int = 30, start_time: Optional[str] = None, end_time: Optional[str] = None) -> str:
        """
        Search events in Google Calendar
        
        Args:
            query: Search query
            days_ahead: Days to look ahead
            start_time: Optional start time for time range search
            end_time: Optional end time for time range search
            
        Returns:
            Formatted search results
        """
        try:
            events = self.search_events_raw(query, days_ahead, start_time, end_time)
            
            if not events:
                return f"No events found matching: {query}"
            
            output = f"**SEARCH: Google Calendar Search Results ({len(events)}):**\n\n"
            
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                summary = event.get('title', 'No Title')
                location = event.get('location', '')
                
                # Format start time
                try:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    formatted_time = format_event_time_display(start_dt, include_date=True)
                except:
                    formatted_time = start
                
                output += f"[CAL] **{summary}**\n"
                output += f"   [TIME] Time: {formatted_time}\n"
                if location:
                    output += f"   [LOC] Location: {location}\n"
                output += "\n"
            
            return output
            
        except Exception as e:
            raise Exception(f"Failed to search events: {str(e)}")
    
    def find_duplicates(self, days_ahead: int = 30) -> str:
        """Find duplicate events in calendar"""
        try:
            events = self.google_client.list_events(days_ahead=days_ahead)
            
            if not events:
                return "No events found to check for duplicates."
            
            # Group events by title and time
            event_groups = {}
            for event in events:
                key = (
                    event.get('summary', '').lower(),
                    event['start'].get('dateTime', event['start'].get('date'))
                )
                if key not in event_groups:
                    event_groups[key] = []
                event_groups[key].append(event)
            
            # Find duplicates
            duplicates = {k: v for k, v in event_groups.items() if len(v) > 1}
            
            if not duplicates:
                return "[OK] No duplicate events found!"
            
            output = f"**DUPLICATES: Found {len(duplicates)} potential duplicate events:**\n\n"
            for (title, time), events in duplicates.items():
                output += f"**{title.title()}** at {time}:\n"
                for event in events:
                    output += f"  - ID: {event['id']}\n"
                output += "\n"
            
            return output
            
        except Exception as e:
            return f"[ERROR] Failed to find duplicates: {str(e)}"
