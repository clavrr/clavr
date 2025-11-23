"""
Calendar Analytics Module

Handles calendar analytics and insights.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from ...utils.logger import setup_logger
from ...integrations.google_calendar.service import CalendarService
from ...core.calendar.utils import parse_event_time, format_event_time_display

logger = setup_logger(__name__)


class CalendarAnalytics:
    """Calendar analytics and insights operations"""
    
    def __init__(self, calendar_service: CalendarService, config: Optional[Any] = None):
        """
        Initialize calendar analytics
        
        Args:
            calendar_service: Calendar service instance
            config: Configuration object
        """
        self.calendar_service = calendar_service
        # Keep backward compatibility
        self.google_client = calendar_service.calendar_client if hasattr(calendar_service, 'calendar_client') else None
        self.config = config
    
    def get_analytics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> str:
        """
        Get calendar analytics and insights
        
        Args:
            start_date: Optional start date (ISO format)
            end_date: Optional end date (ISO format)
            
        Returns:
            Analytics report
        """
        try:
            # Set default date range (last 30 days)
            if not start_date:
                start_date = (datetime.now() - timedelta(days=30)).isoformat() + 'Z'
            if not end_date:
                end_date = datetime.now().isoformat() + 'Z'
            
            # Get events
            events = self.google_client.get_events_in_range(start_date, end_date)
            
            if not events:
                return "No events found in the specified period."
            
            # Calculate analytics
            total_events = len(events)
            total_time_minutes = 0
            attendee_counts = defaultdict(int)
            day_counts = defaultdict(int)
            hour_counts = defaultdict(int)
            
            for event in events:
                # Calculate duration
                start = parse_event_time(event.get('start', {}))
                end = parse_event_time(event.get('end', {}))
                if start and end:
                    duration = (end - start).total_seconds() / 60
                    total_time_minutes += duration
                    
                    # Track by day and hour
                    day_counts[start.strftime('%A')] += 1
                    hour_counts[start.hour] += 1
                
                # Track attendees
                attendees = event.get('attendees', [])
                for attendee in attendees:
                    email = attendee.get('email', '')
                    if email:
                        attendee_counts[email] += 1
            
            # Format output
            output = f"**📊 Calendar Analytics**\n\n"
            output += f"**Period:** {start_date[:10]} to {end_date[:10]}\n\n"
            
            output += f"**Summary:**\n"
            output += f"• Total Events: {total_events}\n"
            output += f"• Total Time: {int(total_time_minutes / 60)} hours {int(total_time_minutes % 60)} minutes\n"
            output += f"• Average Duration: {int(total_time_minutes / total_events)} minutes per event\n\n"
            
            # Busiest days
            if day_counts:
                sorted_days = sorted(day_counts.items(), key=lambda x: x[1], reverse=True)
                output += f"**Busiest Days:**\n"
                for day, count in sorted_days[:3]:
                    output += f"• {day}: {count} events\n"
                output += "\n"
            
            # Peak hours
            if hour_counts:
                sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
                output += f"**Peak Hours:**\n"
                for hour, count in sorted_hours[:3]:
                    time_str = f"{hour:02d}:00"
                    output += f"• {time_str}: {count} events\n"
                output += "\n"
            
            # Top attendees
            if attendee_counts:
                sorted_attendees = sorted(attendee_counts.items(), key=lambda x: x[1], reverse=True)
                output += f"**Top Attendees:**\n"
                for email, count in sorted_attendees[:5]:
                    output += f"• {email}: {count} events\n"
            
            return output
            
        except Exception as e:
            return f"[ERROR] Failed to generate analytics: {str(e)}"
    
    def find_missing_details(self, days_ahead: int = 30) -> str:
        """
        Find events missing important details
        
        Args:
            days_ahead: Days to look ahead
            
        Returns:
            List of events with missing details
        """
        try:
            events = self.google_client.list_events(days_ahead=days_ahead)
            
            if not events:
                return "No events found to check."
            
            missing_details = []
            
            for event in events:
                issues = []
                
                # Check for missing description
                if not event.get('description'):
                    issues.append('missing description')
                
                # Check for missing location
                if not event.get('location'):
                    issues.append('missing location')
                
                # Check for missing attendees
                if not event.get('attendees'):
                    issues.append('no attendees')
                
                if issues:
                    missing_details.append({
                        'event': event,
                        'issues': issues
                    })
            
            if not missing_details:
                return "[OK] **All events have complete details!**"
            
            output = f"**⚠️ Events Missing Details ({len(missing_details)}):**\n\n"
            
            for item in missing_details[:10]:
                event = item['event']
                issues = item['issues']
                
                start = event['start'].get('dateTime', event['start'].get('date'))
                try:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    formatted_time = format_event_time_display(start_dt, include_date=True)
                except:
                    formatted_time = start
                
                output += f"**{event.get('summary', 'Untitled')}**\n"
                output += f"  Time: {formatted_time}\n"
                output += f"  Issues: {', '.join(issues)}\n\n"
            
            if len(missing_details) > 10:
                output += f"... and {len(missing_details) - 10} more events with missing details\n"
            
            return output
            
        except Exception as e:
            return f"[ERROR] Failed to find missing details: {str(e)}"
    
    def prepare_meeting(self, event_id: str) -> str:
        """
        Prepare for a meeting by gathering context
        
        Args:
            event_id: Event ID
            
        Returns:
            Meeting preparation summary
        """
        try:
            event = self.google_client.get_event(event_id)
            
            if not event:
                return f"[ERROR] Event not found: {event_id}"
            
            # Extract event details
            summary = event.get('summary', 'Untitled')
            start = event['start'].get('dateTime', event['start'].get('date'))
            location = event.get('location', 'Not specified')
            description = event.get('description', 'No description')
            attendees = event.get('attendees', [])
            
            # Format output
            output = f"**📋 Meeting Preparation: {summary}**\n\n"
            output += f"**Time:** {start}\n"
            output += f"**Location:** {location}\n\n"
            
            if attendees:
                output += f"**Attendees ({len(attendees)}):**\n"
                for attendee in attendees[:10]:
                    email = attendee.get('email', '')
                    status = attendee.get('responseStatus', 'needsAction')
                    output += f"  • {email} ({status})\n"
                output += "\n"
            
            output += f"**Description:**\n{description}\n\n"
            
            output += "**Preparation Checklist:**\n"
            output += "  ☐ Review agenda\n"
            output += "  ☐ Prepare materials\n"
            output += "  ☐ Test tech setup\n"
            output += "  ☐ Send reminders to attendees\n"
            
            return output
            
        except Exception as e:
            return f"[ERROR] Failed to prepare meeting: {str(e)}"
