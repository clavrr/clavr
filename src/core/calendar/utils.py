"""
Calendar Utilities - Shared helper functions for calendar operations

This module provides reusable utilities for:
- Timezone handling and conversions
- Date/time parsing and formatting
- Event data transformation
- Conflict detection helpers
"""
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
import pytz
import re

from ...utils.config import get_timezone
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_DURATION_MINUTES = 60
DEFAULT_DAYS_AHEAD = 7


# ============================================================================
# TIMEZONE HELPERS
# ============================================================================

def get_user_timezone(config: Optional[Any] = None) -> str:
    """
    Get the user's configured timezone, with a sensible default.
    
    Args:
        config: Optional configuration object
        
    Returns:
        Timezone string (e.g., "America/Los_Angeles")
    """
    if config:
        tz = get_timezone(config)
        if tz:
            return tz
    return DEFAULT_TIMEZONE


def get_utc_now() -> datetime:
    """
    Get current UTC time with timezone info.
    
    Returns:
        Current UTC datetime with timezone
    """
    return datetime.utcnow().replace(tzinfo=pytz.UTC)


def convert_to_user_timezone(dt: datetime, config: Optional[Any] = None) -> datetime:
    """
    Convert datetime to user's configured timezone.
    
    Args:
        dt: Datetime to convert
        config: Optional configuration object
        
    Returns:
        Datetime in user's timezone
    """
    tz_name = get_user_timezone(config)
    user_tz = pytz.timezone(tz_name)
    
    if dt.tzinfo is None:
        dt = user_tz.localize(dt)
    else:
        dt = dt.astimezone(user_tz)
    
    return dt


def parse_datetime_with_timezone(
    time_str: str,
    config: Optional[Any] = None,
    prefer_future: bool = True
) -> Optional[datetime]:
    """
    Parse a datetime string, handling various formats and timezones.
    
    Handles:
    - ISO format with timezone (2025-01-15T14:00:00-08:00)
    - ISO format UTC (2025-01-15T14:00:00Z)
    - ISO format naive (2025-01-15T14:00:00) - assumes configured timezone
    - Date only (2025-01-15) - assumes 9:00 AM in configured timezone
    - Natural language with timezone: "3 pm PST", "10am PST", "2:30 PM EST"
    
    Args:
        time_str: Datetime string to parse
        config: Optional configuration object for timezone
        prefer_future: If True, prefer future dates when ambiguous
        
    Returns:
        Parsed datetime with timezone info, or None if parsing fails
    """
    if not time_str:
        return None
    
    tz_name = get_user_timezone(config)
    local_tz = pytz.timezone(tz_name)
    
    try:
        # Handle UTC timezone (Z suffix)
        if time_str.endswith('Z'):
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.astimezone(local_tz)
        
        # Handle explicit timezone offset (+08:00, -05:00)
        # IMPORTANT: Preserve the original timezone - don't convert!
        # This is critical for PST/PDT and other explicit timezones
        if re.search(r'[+-]\d{2}:\d{2}$', time_str):
            dt = datetime.fromisoformat(time_str)
            # Preserve the original timezone - don't convert to configured timezone
            # The caller can convert if needed, but we preserve the user's intent
            return dt
        
        # Handle ISO format without timezone (assume configured timezone)
        if 'T' in time_str:
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                dt = local_tz.localize(dt)
            return dt
        
        # Handle date-only format (assume 9:00 AM in configured timezone)
        if re.match(r'^\d{4}-\d{2}-\d{2}$', time_str):
            dt = datetime.fromisoformat(time_str)
            dt = dt.replace(hour=9, minute=0, second=0, microsecond=0)
            dt = local_tz.localize(dt)
            return dt
        
        # NEW: Handle natural language time formats with timezone abbreviations
        # Examples: "3 pm PST", "10am PST", "2:30 PM EST", "tomorrow at 3 pm PST"
        time_str_lower = time_str.lower().strip()
        
        # Map timezone abbreviations to pytz timezones
        tz_abbrev_map = {
            'pst': 'America/Los_Angeles',  # Pacific Standard Time
            'pdt': 'America/Los_Angeles',   # Pacific Daylight Time
            'est': 'America/New_York',      # Eastern Standard Time
            'edt': 'America/New_York',     # Eastern Daylight Time
            'cst': 'America/Chicago',       # Central Standard Time
            'cdt': 'America/Chicago',       # Central Daylight Time
            'mst': 'America/Denver',        # Mountain Standard Time
            'mdt': 'America/Denver',        # Mountain Daylight Time
            'utc': 'UTC',
            'gmt': 'GMT',
        }
        
        # Extract timezone abbreviation if present
        specified_tz = None
        tz_abbrev = None
        for abbrev, tz_name in tz_abbrev_map.items():
            if abbrev in time_str_lower:
                specified_tz = pytz.timezone(tz_name)
                tz_abbrev = abbrev
                logger.info(f"Found timezone abbreviation '{abbrev}' -> {tz_name}")
                break
        
        # Extract time patterns - handle formats like "3 pm", "10am", "2:30 PM"
        # Order matters: more specific patterns first
        time_patterns = [
            r'(\d{1,2}):(\d{2})\s*(am|pm)',  # "2:30 pm" or "2:30pm"
            r'(\d{1,2})(am|pm)',              # "10am" or "3pm" (no space)
            r'(\d{1,2})\s+(am|pm)',           # "3 pm" or "10 am" (with space)
            r'(\d{1,2}):(\d{2})',             # "14:30" (24-hour format)
        ]
        
        hour = None
        minute = 0
        for pattern in time_patterns:
            match = re.search(pattern, time_str_lower)
            if match:
                try:
                    hour = int(match.group(1))
                    minute = 0
                    am_pm = None
                    
                    # Determine which groups contain what based on pattern
                    num_groups = len(match.groups())
                    
                    if num_groups >= 3:
                        # Pattern has hour:minute:am/pm format (e.g., "2:30 pm")
                        try:
                            minute = int(match.group(2))
                        except (ValueError, IndexError):
                            minute = 0
                        am_pm = match.group(3).lower() if match.group(3) else None
                    elif num_groups >= 2:
                        # Could be hour:minute OR hour:am/pm
                        group2 = match.group(2)
                        # Check if group 2 is a number (minutes) or am/pm
                        if group2.isdigit():
                            minute = int(group2)
                            # Check for am/pm in group 3 if it exists
                            if num_groups >= 3 and match.group(3):
                                am_pm = match.group(3).lower()
                        else:
                            # Group 2 is am/pm (e.g., "10am" pattern)
                            am_pm = group2.lower()
                    
                    # Convert to 24-hour format
                    if am_pm == 'pm' and hour < 12:
                        hour += 12
                    elif am_pm == 'am' and hour == 12:
                        hour = 0
                    
                    logger.debug(f"Parsed time: hour={hour}, minute={minute}, am_pm={am_pm} from pattern '{pattern}'")
                    break
                except (ValueError, IndexError, AttributeError) as e:
                    logger.debug(f"Error parsing time pattern '{pattern}': {e}")
                    continue
        
        # Extract date - try to parse relative dates first
        now = datetime.now(local_tz)
        target_date = now
        
        # Handle relative dates
        if 'tomorrow' in time_str_lower:
            target_date = now + timedelta(days=1)
        elif 'today' in time_str_lower:
            target_date = now
        elif 'next week' in time_str_lower:
            target_date = now + timedelta(days=7)
        else:
            # Try to extract specific date
            # For now, default to today if no date specified
            target_date = now
        
        if hour is not None:
            # Create datetime with extracted time
            dt = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            # No time specified - use business hours default (10 AM) instead of midnight
            dt = target_date.replace(hour=10, minute=0, second=0, microsecond=0)
        
        # Apply timezone if specified
        if specified_tz:
            # If the datetime is naive, localize it to the specified timezone
            if dt.tzinfo is None:
                dt = specified_tz.localize(dt)
            else:
                # Convert to specified timezone
                dt = dt.astimezone(specified_tz)
        else:
            # No timezone specified, use configured timezone
            if dt.tzinfo is None:
                dt = local_tz.localize(dt)
        
        logger.info(f"Parsed natural language time '{time_str}' -> {dt.isoformat()}")
        return dt
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse datetime '{time_str}': {e}")
        return None
    
    # If we get here, try to parse as ISO date (fallback)
    try:
        dt = datetime.fromisoformat(time_str)
        dt = dt.replace(hour=9, minute=0, second=0, microsecond=0)
        dt = local_tz.localize(dt)
        return dt
    except (ValueError, TypeError):
        pass
    
    return None


def format_datetime_for_calendar(
    dt: datetime,
    config: Optional[Any] = None
) -> str:
    """
    Format a datetime for Google Calendar API (RFC3339 format).
    
    Args:
        dt: Datetime to format
        config: Optional configuration object for timezone
        
    Returns:
        RFC3339 formatted string (e.g., "2025-01-15T14:00:00")
    """
    if dt.tzinfo is None:
        tz_name = get_user_timezone(config)
        local_tz = pytz.timezone(tz_name)
        dt = local_tz.localize(dt)
    
    # Convert to configured timezone
    tz_name = get_user_timezone(config)
    local_tz = pytz.timezone(tz_name)
    dt_local = dt.astimezone(local_tz)
    
    return dt_local.strftime('%Y-%m-%dT%H:%M:00')


def format_datetime_rfc3339(
    dt: datetime,
    preserve_timezone: bool = True
) -> str:
    """
    Format datetime to RFC3339 format, preserving timezone offset if present.
    
    Args:
        dt: Datetime to format
        preserve_timezone: If True, preserve timezone offset in output
        
    Returns:
        RFC3339 formatted string with timezone offset if present
    """
    if dt.tzinfo is None:
        return dt.strftime('%Y-%m-%dT%H:%M:00')
    
    if preserve_timezone:
        # Format with timezone offset
        tz_offset = dt.strftime('%z')
        if tz_offset:
            offset_formatted = f"{tz_offset[:3]}:{tz_offset[3:]}"
            return dt.strftime(f'%Y-%m-%dT%H:%M:00{offset_formatted}')
    
    return dt.strftime('%Y-%m-%dT%H:%M:00')


def get_timezone_from_offset(offset_hours: float) -> Optional[str]:
    """
    Get timezone name from UTC offset hours.
    
    Args:
        offset_hours: UTC offset in hours (e.g., -8 for PST, -7 for PDT)
        
    Returns:
        Timezone name or None if not recognized
    """
    # Common timezone mappings
    timezone_map = {
        -8: 'America/Los_Angeles',  # PST
        -7: 'America/Los_Angeles',  # PDT
        -6: 'America/Denver',       # MST/MDT
        -5: 'America/New_York',     # EST/EDT
        0: 'UTC',
        1: 'Europe/London',
        9: 'Asia/Tokyo',
    }
    
    return timezone_map.get(int(offset_hours))


def get_day_boundaries(
    dt: datetime,
    config: Optional[Any] = None
) -> Tuple[datetime, datetime]:
    """
    Get start and end of day for a given datetime in the configured timezone.
    
    Args:
        dt: Datetime to get day boundaries for
        config: Optional configuration object for timezone
        
    Returns:
        Tuple of (day_start, day_end) in configured timezone
    """
    tz_name = get_user_timezone(config)
    local_tz = pytz.timezone(tz_name)
    
    # Ensure dt is in configured timezone
    if dt.tzinfo is None:
        dt = local_tz.localize(dt)
    else:
        dt = dt.astimezone(local_tz)
    
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    
    return day_start, day_end


def calculate_time_range(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    days_back: int = 0,
    days_ahead: int = 7,
    config: Optional[Any] = None
) -> Tuple[datetime, datetime]:
    """
    Calculate time range for calendar queries.
    
    Args:
        start_date: Optional specific start date (datetime or ISO string)
        end_date: Optional specific end date (datetime or ISO string)
        days_back: Days to look back (if start_date not provided)
        days_ahead: Days to look ahead (if end_date not provided)
        config: Optional configuration object
        
    Returns:
        Tuple of (start_datetime, end_datetime) in UTC
    """
    tz_name = get_user_timezone(config)
    user_tz = pytz.timezone(tz_name)
    utc_tz = pytz.UTC
    
    # Get current time in user's timezone
    now_utc = get_utc_now()
    now_user = now_utc.astimezone(user_tz)
    
    # Handle start_date - support both datetime and ISO string
    if start_date:
        if isinstance(start_date, str):
            # Parse ISO string
            try:
                start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                # Try without timezone
                start_date = datetime.fromisoformat(start_date)
        
        # Ensure timezone is set
        if start_date.tzinfo is None:
            start_date = user_tz.localize(start_date)
        else:
            # Convert to user timezone
            start_date = start_date.astimezone(user_tz)
        
        start_user = start_date
    elif days_back > 0:
        start_user = (now_user - timedelta(days=days_back)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        start_user = now_user.replace(hour=0, minute=0, second=0, microsecond=0)
    
    start_utc = start_user.astimezone(utc_tz)
    
    # Handle end_date - support both datetime and ISO string
    if end_date:
        if isinstance(end_date, str):
            # Parse ISO string
            try:
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                # Try without timezone
                end_date = datetime.fromisoformat(end_date)
        
        # Ensure timezone is set
        if end_date.tzinfo is None:
            end_date = user_tz.localize(end_date)
        else:
            # Convert to user timezone
            end_date = end_date.astimezone(user_tz)
        
        end_user = end_date
    else:
        # CRITICAL: Handle special cases for date range calculation
        if days_ahead == 0 and days_back > 0:
            # Looking back only (e.g., "yesterday") - set end_user to end of start_user's day
            end_user = start_user.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif days_back == 0 and days_ahead == 1:
            # Looking ahead 1 day (e.g., "today") - set end_user to end of today (23:59:59)
            # This ensures we get ALL events from today, including past events
            end_user = start_user.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            end_user = start_user + timedelta(days=days_ahead)
    
    end_utc = end_user.astimezone(utc_tz)
    
    return start_utc, end_utc


# ============================================================================
# EVENT TIME PARSING
# ============================================================================

def parse_event_time(event_time_obj: Dict[str, Any]) -> Optional[datetime]:
    """
    Parse event time from Google Calendar API format.
    
    Handles both dateTime (with time) and date (all-day) formats.
    
    Args:
        event_time_obj: Event time object from Google Calendar API
            Format: {'dateTime': '2025-01-15T14:00:00-08:00'} or {'date': '2025-01-15'}
        
    Returns:
        Parsed datetime or None if parsing fails
    """
    if not event_time_obj:
        return None
    
    date_time = event_time_obj.get('dateTime')
    if date_time:
        try:
            return datetime.fromisoformat(date_time.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    date = event_time_obj.get('date')
    if date:
        try:
            dt = datetime.fromisoformat(date)
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        except (ValueError, AttributeError):
            return None
    
    return None


def format_event_time_display(dt: datetime, include_date: bool = True) -> str:
    """
    Format a datetime for display to users.
    
    Args:
        dt: Datetime to format
        include_date: Whether to include the date
        
    Returns:
        Formatted string (e.g., "January 15 at 2:00 PM" or "2:00 PM")
    """
    if include_date:
        return dt.strftime('%B %d at %I:%M %p')
    return dt.strftime('%I:%M %p')


# ============================================================================
# EVENT DATA TRANSFORMATION
# ============================================================================

def extract_event_details(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract standardized event details from Google Calendar API event.
    
    Args:
        event: Event dictionary from Google Calendar API
        
    Returns:
        Dictionary with standardized fields:
        - id: Event ID
        - title: Event title
        - start: Start datetime
        - end: End datetime
        - location: Event location
        - attendees: List of attendee emails
        - description: Event description
        - html_link: Link to event in Google Calendar
    """
    start_dt = parse_event_time(event.get('start', {}))
    end_dt = parse_event_time(event.get('end', {}))
    
    attendees = []
    for attendee in event.get('attendees', []):
        email = attendee.get('email', '')
        if email:
            attendees.append(email)
    
    # Handle both Google Calendar API format (with 'summary') and our internal format (with 'title')
    title = event.get('title') or event.get('summary') or 'No Title'
    
    return {
        'id': event.get('id'),
        'title': title,
        'start': start_dt,
        'end': end_dt,
        'location': event.get('location', ''),
        'attendees': attendees,
        'description': event.get('description', ''),
        'html_link': event.get('htmlLink', '')
    }


def format_event_for_api(
    title: str,
    start_time: str,
    end_time: str,
    timezone: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    recurrence: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Build event body for Google Calendar API.
    
    Args:
        title: Event title
        start_time: Start time in RFC3339 format
        end_time: End time in RFC3339 format
        timezone: Timezone name (e.g., "America/Los_Angeles")
        description: Optional description
        location: Optional location
        attendees: Optional list of attendee emails
        recurrence: Optional recurrence rules
        
    Returns:
        Event body dictionary for API
    """
    event_body = {
        'summary': title,
        'start': {
            'dateTime': start_time,
            'timeZone': timezone,
        },
        'end': {
            'dateTime': end_time,
            'timeZone': timezone,
        },
    }
    
    if location:
        event_body['location'] = location
    
    if attendees:
        event_body['attendees'] = [{'email': email} for email in attendees]
    
    if description:
        event_body['description'] = description
    
    if recurrence:
        event_body['recurrence'] = recurrence
    
    return event_body


# ============================================================================
# CONFLICT DETECTION
# ============================================================================

def events_overlap(
    start1: datetime,
    end1: datetime,
    start2: datetime,
    end2: datetime
) -> bool:
    """
    Check if two time ranges overlap.
    
    Args:
        start1: Start of first range
        end1: End of first range
        start2: Start of second range
        end2: End of second range
        
    Returns:
        True if ranges overlap, False otherwise
    """
    return start1 < end2 and start2 < end1


def find_conflicts(
    proposed_start: datetime,
    proposed_end: datetime,
    existing_events: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Find conflicts between a proposed time range and existing events.
    
    Args:
        proposed_start: Proposed event start time
        proposed_end: Proposed event end time
        existing_events: List of existing events (from Google Calendar API format)
        
    Returns:
        List of conflicting events with details:
        - title: Event title
        - start_time: Start datetime
        - end_time: End datetime
    """
    conflicts = []
    
    for event in existing_events:
        event_start = parse_event_time(event.get('start', {}))
        event_end = parse_event_time(event.get('end', {}))
        
        if not event_start or not event_end:
            continue
        
        # Check for overlap
        if events_overlap(proposed_start, proposed_end, event_start, event_end):
            conflicts.append({
                'title': event.get('summary', 'Untitled Event'),
                'start_time': event_start,
                'end_time': event_end
            })
    
    return conflicts


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def calculate_ordinal_day_date(
    ordinal: int,
    day_name: str,
    reference_date: Optional[datetime] = None,
    config: Optional[Any] = None
) -> Optional[datetime]:
    """
    Calculate the date for an ordinal day pattern (e.g., first Friday of the month).
    
    Smart logic:
    - If we're past the ordinal day of the current month → use next month
    - If we haven't passed it yet → use current month
    
    Args:
        ordinal: Ordinal position (1=first, 2=second, -1=last, etc.)
        day_name: Day name ('monday', 'tuesday', etc.) or day code ('MO', 'TU', etc.)
        reference_date: Reference date (defaults to now)
        config: Optional configuration for timezone
        
    Returns:
        Datetime for the next occurrence of the ordinal day, or None if invalid
    """
    if reference_date is None:
        reference_date = datetime.now()
        tz_name = get_user_timezone(config)
        user_tz = pytz.timezone(tz_name)
        if reference_date.tzinfo is None:
            reference_date = user_tz.localize(reference_date)
        else:
            reference_date = reference_date.astimezone(user_tz)
    
    # Map day names to weekday numbers (0=Monday, 6=Sunday)
    day_mapping = {
        'monday': 0, 'mon': 0, 'mo': 0,
        'tuesday': 1, 'tue': 1, 'tu': 1,
        'wednesday': 2, 'wed': 2, 'we': 2,
        'thursday': 3, 'thu': 3, 'th': 3,
        'friday': 4, 'fri': 4, 'fr': 4,
        'saturday': 5, 'sat': 5, 'sa': 5,
        'sunday': 6, 'sun': 6, 'su': 6,
    }
    
    day_name_lower = day_name.lower()
    target_weekday = day_mapping.get(day_name_lower)
    if target_weekday is None:
        logger.warning(f"Invalid day name: {day_name}")
        return None
    
    # Get current month/year
    current_year = reference_date.year
    current_month = reference_date.month
    
    # Calculate the ordinal day of the current month
    first_day = datetime(current_year, current_month, 1, 
                       hour=reference_date.hour, minute=reference_date.minute,
                       tzinfo=reference_date.tzinfo)
    
    # Find first occurrence of the target weekday in the month
    days_until_first = (target_weekday - first_day.weekday()) % 7
    first_occurrence = first_day + timedelta(days=days_until_first)
    
    if ordinal == -1:
        # Last occurrence: find last occurrence of the weekday in the month
        # Start from the last day of the month and work backwards
        if current_month == 12:
            next_month = datetime(current_year + 1, 1, 1, tzinfo=reference_date.tzinfo)
        else:
            next_month = datetime(current_year, current_month + 1, 1, tzinfo=reference_date.tzinfo)
        last_day = next_month - timedelta(days=1)
        
        # Find last occurrence
        days_back = (last_day.weekday() - target_weekday) % 7
        last_occurrence = last_day - timedelta(days=days_back)
        last_occurrence = last_occurrence.replace(hour=reference_date.hour, minute=reference_date.minute)
        
        # Check if we've passed the last occurrence
        if reference_date.date() > last_occurrence.date():
            # Move to next month
            if current_month == 12:
                current_year += 1
                current_month = 1
            else:
                current_month += 1
            
            # Recalculate for next month
            first_day = datetime(current_year, current_month, 1, 
                               hour=reference_date.hour, minute=reference_date.minute,
                               tzinfo=reference_date.tzinfo)
            days_until_first = (target_weekday - first_day.weekday()) % 7
            first_occurrence = first_day + timedelta(days=days_until_first)
            
            if current_month == 12:
                next_month = datetime(current_year + 1, 1, 1, tzinfo=reference_date.tzinfo)
            else:
                next_month = datetime(current_year, current_month + 1, 1, tzinfo=reference_date.tzinfo)
            last_day = next_month - timedelta(days=1)
            days_back = (last_day.weekday() - target_weekday) % 7
            last_occurrence = last_day - timedelta(days=days_back)
            last_occurrence = last_occurrence.replace(hour=reference_date.hour, minute=reference_date.minute)
            
            return last_occurrence
        else:
            return last_occurrence
    else:
        # First, second, third, etc. occurrence
        # Calculate the nth occurrence
        nth_occurrence = first_occurrence + timedelta(weeks=ordinal - 1)
        
        # Check if nth occurrence is still in the current month
        if nth_occurrence.month != current_month:
            # The nth occurrence doesn't exist in this month (e.g., 5th Friday)
            # Move to next month
            if current_month == 12:
                current_year += 1
                current_month = 1
            else:
                current_month += 1
            
            # Recalculate for next month
            first_day = datetime(current_year, current_month, 1,
                               hour=reference_date.hour, minute=reference_date.minute,
                               tzinfo=reference_date.tzinfo)
            days_until_first = (target_weekday - first_day.weekday()) % 7
            first_occurrence = first_day + timedelta(days=days_until_first)
            nth_occurrence = first_occurrence + timedelta(weeks=ordinal - 1)
        
        # Check if we've passed this occurrence
        if reference_date.date() > nth_occurrence.date():
            # Move to next month
            if current_month == 12:
                current_year += 1
                current_month = 1
            else:
                current_month += 1
            
            # Recalculate for next month
            first_day = datetime(current_year, current_month, 1,
                               hour=reference_date.hour, minute=reference_date.minute,
                               tzinfo=reference_date.tzinfo)
            days_until_first = (target_weekday - first_day.weekday()) % 7
            first_occurrence = first_day + timedelta(days=days_until_first)
            nth_occurrence = first_occurrence + timedelta(weeks=ordinal - 1)
        
        return nth_occurrence


def calculate_duration_minutes(start: datetime, end: datetime) -> int:
    """
    Calculate duration in minutes between two datetimes.
    
    Args:
        start: Start datetime
        end: End datetime
        
    Returns:
        Duration in minutes
    """
    if not start or not end:
        return DEFAULT_DURATION_MINUTES
    
    delta = end - start
    return int(delta.total_seconds() / 60)


def resolve_name_to_email_via_graph(
    name: str,
    graph_manager: Optional[Any] = None,
    user_id: Optional[int] = None
) -> Optional[str]:
    """
    Resolve a person's name to their email address using Neo4j graph (Contact Resolver role).
    
    This implements the architecture pattern:
    MATCH (a:Alias {value: 'Maniko'})-[:HAS_ALIAS]-(p:Person)-[:HAS_EMAIL]->(e:EmailAddress)
    RETURN e.address
    
    Args:
        name: Person's name (e.g., "Maniko", "John Smith")
        graph_manager: KnowledgeGraphManager instance for Neo4j queries
        user_id: Optional user ID for multi-user support
        
    Returns:
        Email address if found in graph, None otherwise
    """
    if not name or not name.strip():
        return None
    
    # Check if it's already an email address
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if email_pattern.match(name.strip()):
        return name.strip().lower()
    
    if not graph_manager:
        logger.debug(f"[CAL] Cannot resolve name '{name}' via graph - no graph_manager provided")
        return None
    
    try:
        # Build Cypher query according to architecture:
        # MATCH (a:Alias {value: 'Maniko'})-[:HAS_ALIAS]-(p:Person)-[:HAS_EMAIL]->(e:EmailAddress)
        # RETURN e.address
        
        # Use case-insensitive matching for better results
        cypher_query = """
        MATCH (a:Alias)
        WHERE toLower(a.value) = toLower($name)
        MATCH (a)<-[:HAS_ALIAS]-(p:Person)
        MATCH (p)-[:HAS_EMAIL]->(e:EmailAddress)
        RETURN e.address AS email
        LIMIT 1
        """
        
        # Add user_id filter if provided (for multi-user support)
        if user_id:
            cypher_query = """
            MATCH (a:Alias)
            WHERE toLower(a.value) = toLower($name)
            MATCH (a)<-[:HAS_ALIAS]-(p:Person)
            WHERE p.user_id = $user_id OR p.user_id IS NULL
            MATCH (p)-[:HAS_EMAIL]->(e:EmailAddress)
            RETURN e.address AS email
            LIMIT 1
            """
        
        params = {"name": name.strip()}
        if user_id:
            params["user_id"] = user_id
        
        # Execute query (graph_manager.query is async, so we need to handle it)
        import asyncio
        try:
            # Try to get the current event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in an async context - create new event loop in thread
                    import concurrent.futures
                    def run_in_new_loop():
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            return new_loop.run_until_complete(
                                graph_manager.query(cypher_query, params=params)
                            )
                        finally:
                            new_loop.close()
                    
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(run_in_new_loop)
                        results = future.result(timeout=5.0)
                else:
                    # Event loop exists but not running - use it
                    results = loop.run_until_complete(graph_manager.query(cypher_query, params=params))
            except RuntimeError:
                # No event loop - create one
                results = asyncio.run(graph_manager.query(cypher_query, params=params))
        except Exception as e:
            logger.warning(f"[CAL] Graph query execution failed: {e}")
            return None
        
        if results and len(results) > 0:
            # Extract email from result
            result = results[0]
            if isinstance(result, dict):
                email = result.get('email') or result.get('e.address')
            else:
                email = str(result)
            
            if email:
                email_address = email.lower().strip()
                logger.info(f"[CAL] Resolved name '{name}' to email '{email_address}' via Neo4j graph")
                return email_address
        
        logger.debug(f"[CAL] Could not resolve name '{name}' to email via graph")
        return None
        
    except Exception as e:
        logger.warning(f"[CAL] Failed to resolve name '{name}' via graph: {e}")
        return None


def resolve_name_to_email(
    name: str,
    email_service: Optional[Any] = None,
    config: Optional[Any] = None,
    graph_manager: Optional[Any] = None,
    user_id: Optional[int] = None
) -> Optional[str]:
    """
    Resolve a person's name to their email address.
    
    This function implements the Contact Resolver role with a two-tier approach:
    1. First, try Neo4j graph lookup (fast, accurate, uses Person/Alias/EmailAddress nodes)
    2. Fallback to email search if graph doesn't have the contact
    
    Args:
        name: Person's name (e.g., "Maniko", "John Smith")
        email_service: Optional EmailService instance for fallback email search
        config: Optional config for creating EmailService if needed
        graph_manager: Optional KnowledgeGraphManager instance for Neo4j graph lookup
        user_id: Optional user ID for multi-user support
        
    Returns:
        Email address if found, None otherwise
    """
    if not name or not name.strip():
        return None
    
    # Check if it's already an email address
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if email_pattern.match(name.strip()):
        return name.strip().lower()
    
    # TIER 1: Try Neo4j graph lookup first (Contact Resolver role)
    if graph_manager:
        email = resolve_name_to_email_via_graph(name, graph_manager, user_id)
        if email:
            return email
    
    # TIER 2: Fallback to email search if graph doesn't have the contact
    if not email_service:
        logger.debug(f"[CAL] Cannot resolve name '{name}' to email - no email_service or graph_manager provided")
        return None
    
    try:
        # Search for emails from this person (most recent first)
        # Use intelligent sender matching
        emails = email_service.search_emails(
            from_email=name,
            limit=5  # Get a few results to find the email address
        )
        
        if emails and len(emails) > 0:
            # Extract email address from the first result (most recent)
            first_email = emails[0]
            sender = first_email.get('from') or first_email.get('sender', '')
            
            if sender:
                # Extract email from formats like "Name <email@domain.com>" or just "email@domain.com"
                email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', sender)
                if email_match:
                    email_address = email_match.group(1).lower().strip()
                    logger.info(f"[CAL] Resolved name '{name}' to email '{email_address}' from email search")
                    return email_address
        
        # Also try searching emails TO this person (in case they're a recipient)
        emails_to = email_service.search_emails(
            to_email=name,
            limit=5
        )
        
        if emails_to and len(emails_to) > 0:
            # Extract email from 'to' field
            first_email = emails_to[0]
            to_field = first_email.get('to', '')
            
            if to_field:
                # Extract email from formats like "Name <email@domain.com>" or just "email@domain.com"
                email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', to_field)
                if email_match:
                    email_address = email_match.group(1).lower().strip()
                    logger.info(f"[CAL] Resolved name '{name}' to email '{email_address}' from recipient search")
                    return email_address
        
        logger.debug(f"[CAL] Could not resolve name '{name}' to email address")
        return None
        
    except Exception as e:
        logger.warning(f"[CAL] Failed to resolve name '{name}' to email: {e}")
        return None


def resolve_attendees_to_emails(
    attendees: Optional[List[str]],
    email_service: Optional[Any] = None,
    config: Optional[Any] = None,
    graph_manager: Optional[Any] = None,
    user_id: Optional[int] = None
) -> Tuple[List[str], List[str]]:
    """
    Resolve attendee names to email addresses.
    
    Args:
        attendees: List of attendee names or email addresses
        email_service: Optional EmailService instance for searching emails
        config: Optional config for creating EmailService if needed
        
    Returns:
        Tuple of (resolved_emails, unresolved_names)
        - resolved_emails: List of valid email addresses
        - unresolved_names: List of names that couldn't be resolved
    """
    if not attendees:
        return ([], [])
    
    resolved_emails = []
    unresolved_names = []
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    
    for attendee in attendees:
        if not attendee or not attendee.strip():
            continue
        
        attendee = attendee.strip()
        
        # If it's already an email, use it directly
        if email_pattern.match(attendee):
            resolved_emails.append(attendee.lower())
        else:
            # Try to resolve name to email (uses graph first, then email search)
            email = resolve_name_to_email(attendee, email_service, config, graph_manager, user_id)
            if email:
                resolved_emails.append(email)
            else:
                unresolved_names.append(attendee)
    
    return (resolved_emails, unresolved_names)


def validate_attendees(attendees: Optional[List[str]]) -> Optional[List[str]]:
    """
    Validate and clean attendee email list.
    
    Args:
        attendees: List of attendee emails (may contain None or empty strings)
        
    Returns:
        Cleaned list of valid email addresses, or None if empty/invalid
    """
    if not attendees:
        return None
    
    # Filter out None, empty strings, and invalid emails
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    valid_attendees = [
        email.strip() for email in attendees
        if email and email.strip() and email_pattern.match(email.strip())
    ]
    
    return valid_attendees if valid_attendees else None
