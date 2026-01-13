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

from ...utils import get_timezone, FlexibleDateParser
from ...utils.logger import setup_logger
from ...utils.config import ConfigDefaults

logger = setup_logger(__name__)


# CONSTANTS

DEFAULT_DURATION_MINUTES = ConfigDefaults.CALENDAR_DEFAULT_DURATION
DEFAULT_DAYS_AHEAD = ConfigDefaults.CALENDAR_SEARCH_DAYS_AHEAD


# TIMEZONE HELPERS

def get_user_timezone(config: Optional[Any] = None) -> str:
    """
    Get the user's configured timezone, with a sensible default.
    """
    return get_timezone(config)


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
    
    Uses FlexibleDateParser for robust natural language and ISO parsing.
    """
    if not time_str:
        return None
    
    try:
        parser = FlexibleDateParser(config)
        result = parser.parse_date_expression(time_str, prefer_future=prefer_future)
        
        if result:
            dt = result['start']
            logger.info(f"Parsed datetime '{time_str}' using FlexibleDateParser -> {dt.isoformat()}")
            return dt
            
    except Exception as e:
        logger.warning(f"FlexibleDateParser failed for '{time_str}': {e}")
    
    # Fallback to basic ISO parsing if FlexibleDateParser fails
    try:
        # Handle UTC timezone (Z suffix)
        if time_str.endswith('Z'):
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            tz_name = get_user_timezone(config)
            local_tz = pytz.timezone(tz_name)
            return dt.astimezone(local_tz)
        
        # Handle ISO format
        if 'T' in time_str or re.match(r'^\d{4}-\d{2}-\d{2}$', time_str):
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                tz_name = get_user_timezone(config)
                local_tz = pytz.timezone(tz_name)
                # If date only, set to 9 AM
                if 'T' not in time_str:
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
    days_ahead: int = ConfigDefaults.CALENDAR_SEARCH_DAYS_AHEAD,
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
        
        # SMART EXPANSION: If start and end are identical and at midnight (common for date-only queries),
        # expand end_user to the end of the day so we don't return an empty 0-second range.
        if end_user == start_user and end_user.hour == 0 and end_user.minute == 0:
            end_user = end_user.replace(hour=23, minute=59, second=59, microsecond=999999)
            logger.debug(f"[CAL] Expanded identical start/end range to end of day: {end_user}")
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
        
    # If already a datetime object, return it directly
    if isinstance(event_time_obj, datetime):
        return event_time_obj

    
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
            # All-day events are UTC-based by convention in our system to avoid naive comparisons
            return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC)
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
        - transparency: Event transparency (opaque/transparent)
        - event_type: Event type (default, outOfOffice, workingLocation)
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
        'html_link': event.get('htmlLink', ''),
        'transparency': event.get('transparency', 'opaque'),
        'event_type': event.get('eventType', 'default')
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
    Resolve a person's name to their email address using ArangoDB graph (Contact Resolver role).
    
    This implements the architecture pattern:
    (p:Person {name: 'Maniko'})-[:HAS_EMAIL]->(e:Email)
    
    Args:
        name: Person's name (e.g., "Maniko", "John Smith")
        graph_manager: KnowledgeGraphManager instance for ArangoDB queries
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
        # Build graph query according to architecture:
        # Find person by alias and return their email address
        
        # Use case-insensitive matching for better results
        # First try exact match, then try partial/fuzzy match
        graph_query = """
        MATCH (a:Alias)
        WHERE toLower(a.value) = toLower($name)
        MATCH (a)<-[:HAS_ALIAS]-(p:Person)
        MATCH (p)-[:HAS_EMAIL]->(e:EmailAddress)
        RETURN e.address AS email
        LIMIT 1
        """
        
        # Add user_id filter if provided (for multi-user support)
        if user_id:
            graph_query = """
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
        
        # Helper function to execute graph query
        def execute_graph_query(query: str, params: dict) -> Optional[List[Dict[str, Any]]]:
            """Execute a graph query and return results"""
            try:
                import asyncio
                try:
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            import concurrent.futures
                            def run_in_new_loop():
                                new_loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(new_loop)
                                try:
                                    return new_loop.run_until_complete(
                                        graph_manager.query(query, params=params)
                                    )
                                finally:
                                    new_loop.close()
                            
                            with concurrent.futures.ThreadPoolExecutor() as executor:
                                future = executor.submit(run_in_new_loop)
                                return future.result(timeout=5.0)
                        else:
                            return loop.run_until_complete(graph_manager.query(query, params=params))
                    except RuntimeError:
                        return asyncio.run(graph_manager.query(query, params=params))
                except Exception as e:
                    logger.warning(f"[CAL] Graph query execution failed: {e}")
                    return None
            except Exception as e:
                logger.debug(f"[CAL] Graph query failed: {e}")
                return None
        
        # Try exact match first
        results = execute_graph_query(graph_query, params)
        if results and len(results) > 0:
            result = results[0]
            if isinstance(result, dict):
                email = result.get('email') or result.get('e.address')
            else:
                email = str(result)
            
            if email:
                email_address = email.lower().strip()
                logger.info(f"[CAL] Resolved name '{name}' to email '{email_address}' via ArangoDB graph (exact match)")
                return email_address
        
        # If exact match failed, try partial/fuzzy match (contains)
        # This helps find "Nick" when stored as "Nicholas" or "Nicky"
        fuzzy_query = """
        MATCH (a:Alias)
        WHERE toLower(a.value) CONTAINS toLower($name) OR toLower($name) CONTAINS toLower(a.value)
        MATCH (a)<-[:HAS_ALIAS]-(p:Person)
        MATCH (p)-[:HAS_EMAIL]->(e:EmailAddress)
        RETURN e.address AS email, a.value AS alias
        ORDER BY 
            CASE 
                WHEN toLower(a.value) = toLower($name) THEN 1
                WHEN toLower(a.value) STARTS WITH toLower($name) THEN 2
                WHEN toLower($name) STARTS WITH toLower(a.value) THEN 3
                ELSE 4
            END
        LIMIT 1
        """
        
        if user_id:
            fuzzy_query = """
            MATCH (a:Alias)
            WHERE toLower(a.value) CONTAINS toLower($name) OR toLower($name) CONTAINS toLower(a.value)
            MATCH (a)<-[:HAS_ALIAS]-(p:Person)
            WHERE p.user_id = $user_id OR p.user_id IS NULL
            MATCH (p)-[:HAS_EMAIL]->(e:EmailAddress)
            RETURN e.address AS email, a.value AS alias
            ORDER BY 
                CASE 
                    WHEN toLower(a.value) = toLower($name) THEN 1
                    WHEN toLower(a.value) STARTS WITH toLower($name) THEN 2
                    WHEN toLower($name) STARTS WITH toLower(a.value) THEN 3
                    ELSE 4
                END
            LIMIT 1
            """
        
        results = execute_graph_query(fuzzy_query, params)
        if results and len(results) > 0:
            result = results[0]
            if isinstance(result, dict):
                email = result.get('email') or result.get('e.address')
            else:
                email = str(result)
            
            if email:
                email_address = email.lower().strip()
                logger.info(f"[CAL] Resolved name '{name}' to email '{email_address}' via ArangoDB graph (fuzzy match)")
                return email_address
        
        logger.debug(f"[CAL] Could not resolve name '{name}' to email via graph")
        return None
        
    except Exception as e:
        logger.debug(f"[CAL] Graph lookup failed for '{name}': {e}. Will try RAG and email search fallbacks.")
        return None


def resolve_name_to_email_via_rag(
    name: str,
    rag_engine: Optional[Any] = None,
    user_id: Optional[int] = None
) -> Optional[str]:
    """
    Resolve a person's name to their email address using Qdrant/RAG semantic search.
    
    This uses semantic similarity to find person names even with variations
    (e.g., "Nick" will match "Nicholas", "Nicky", etc. in the email index).
    
    Args:
        name: Person's name (e.g., "Nick", "John Smith")
        rag_engine: RAGEngine instance for Qdrant semantic search
        user_id: Optional user ID for multi-user support
        
    Returns:
        Email address if found, None otherwise
    """
    if not name or not name.strip():
        return None
    
    if not rag_engine:
        logger.debug(f"[CAL] Cannot resolve name '{name}' via RAG - no rag_engine provided")
        return None
    
    try:
        # Search for emails FROM this person specifically (not just mentioning them)
        # Use multiple query variations to find emails where the person is the sender
        # Priority: emails FROM the person, then emails where person's email appears in content
        queries = [
            f"email from {name} sent by {name}",
            f"{name} email address contact",
            f"email sender {name}"
        ]
        
        all_results = []
        seen_ids = set()
        
        # Try multiple queries and combine results
        for query in queries:
            results = rag_engine.search(
                query=query,
                k=10,  # Get fewer results per query to avoid duplicates
                filters={'user_id': str(user_id)} if user_id else None,
                rerank=True,
                min_confidence=0.3
            )
            
            # Deduplicate results by content hash or metadata
            for result in results:
                result_id = result.get('id') or hash(str(result.get('content', ''))[:100])
                if result_id not in seen_ids:
                    seen_ids.add(result_id)
                    all_results.append(result)
        
        # Limit to top 20 unique results
        results = all_results[:20]
        
        if results and len(results) > 0:
            # Extract email addresses from search results
            email_pattern = re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')
            found_emails = []
            name_lower = name.lower().strip()
            name_parts = name_lower.split()  # Split name into parts for better matching
            
            # Helper function to check if email matches the person's name
            def email_matches_name(email: str, name: str, name_parts: list) -> float:
                """Check if email address matches the person's name. Returns confidence score (0-1)."""
                email_lower = email.lower()
                email_username = email_lower.split('@')[0] if '@' in email_lower else email_lower
                name_lower = name.lower()
                
                # Exact name match in username (highest confidence)
                # e.g., "anthony" in "manikoanthony" or "anthony" in "anthony.smith"
                if name_lower in email_username:
                    return 1.0
                
                # All name parts appear in username
                if all(part in email_username for part in name_parts if len(part) > 2):
                    return 0.9
                
                # First name or last name in username
                if len(name_parts) > 0:
                    first_name = name_parts[0]
                    if first_name in email_username and len(first_name) > 2:
                        return 0.8  # Increased from 0.7
                    if len(name_parts) > 1:
                        last_name = name_parts[-1]
                        if last_name in email_username and len(last_name) > 2:
                            return 0.8  # Increased from 0.7
                
                # Partial match (e.g., "anthony" -> "anthony" or "maniko" -> "maniko")
                for part in name_parts:
                    if len(part) > 3 and part in email_username:
                        return 0.6  # Increased from 0.5
                
                # More lenient: check if any significant part of name appears
                for part in name_parts:
                    if len(part) > 2 and part in email_username:
                        return 0.4  # Lower confidence but still acceptable
                
                return 0.0  # No match
            
            # Filter out obviously wrong emails (generic, no-reply, etc.)
            def is_valid_person_email(email: str) -> bool:
                """Check if email looks like a real person's email (not generic)."""
                email_lower = email.lower()
                invalid_patterns = [
                    'noreply', 'no-reply', 'donotreply', 'do-not-reply',
                    'email@', 'mail@', 'info@', 'contact@', 'support@',
                    'booking@', 'reservation@', 'automated@', 'system@',
                    'notification@', 'alerts@', 'newsletter@', 'marketing@'
                ]
                return not any(pattern in email_lower for pattern in invalid_patterns)
            
            logger.info(f"[CAL] Processing {len(results)} RAG results for name '{name}'")
            for idx, result in enumerate(results):
                # Check metadata for sender/recipient email
                metadata = result.get('metadata', {})
                content = result.get('content', '') or ''
                score = result.get('score', 0) or result.get('distance', 1.0)
                
                # Log first few results for debugging
                if idx < 3:
                    logger.debug(
                        f"[CAL] RAG result {idx+1}/{len(results)}: score={score:.3f}, "
                        f"metadata_keys={list(metadata.keys())}, "
                        f"sender={metadata.get('sender', 'N/A')[:50]}, "
                        f"content_preview={str(content)[:150]}"
                    )
                
                # Try to extract from metadata first (most reliable)
                sender = metadata.get('sender', '') or metadata.get('from', '') or metadata.get('sender_email', '') or ''
                recipient = metadata.get('recipient', '') or metadata.get('to', '') or metadata.get('recipient_email', '') or ''
                
                # Also extract emails from content (lower priority but still useful)
                content_str = str(content)
                
                # Prioritize sender emails over recipient emails, then content
                # When searching for "Anthony", we want emails FROM Anthony, not TO Anthony
                priority_order = [
                    ('sender', sender, 3.0),  # Sender emails get 3x priority boost
                    ('recipient', recipient, 1.0),  # Recipient emails get normal priority
                    ('content', content_str, 0.5)  # Content emails get lower priority
                ]
                
                for source_type, field, priority_multiplier in priority_order:
                    if field:
                        matches = email_pattern.findall(str(field))
                        for match in matches:
                            email_lower = match.lower().strip()
                            
                            # Skip obviously invalid emails
                            if not is_valid_person_email(email_lower):
                                if idx < 3:  # Only log first few for debugging
                                    logger.debug(f"[CAL] Skipping invalid email pattern: {email_lower}")
                                continue
                            
                            # Only add if it's not already in the list
                            if email_lower not in [e['email'] for e in found_emails]:
                                # Check if email matches the person's name
                                name_match_score = email_matches_name(email_lower, name_lower, name_parts)
                                
                                # More lenient validation:
                                # 1. Name matches email (high confidence)
                                # 2. Name appears in sender field (medium confidence)
                                # 3. Name appears in content near email (lower confidence)
                                name_in_field = name_lower in str(field).lower()
                                name_in_content = name_lower in content_str.lower() if source_type == 'content' else False
                                
                                # Accept if: name matches email OR name in sender field OR (name in content AND email looks valid)
                                should_include = (
                                    name_match_score > 0 or
                                    (source_type == 'sender' and name_in_field) or
                                    (source_type == 'content' and name_in_content and name_match_score >= 0.4)
                                )
                                
                                if should_include:
                                    # If no name match but from sender field, give it some confidence
                                    if name_match_score == 0:
                                        if source_type == 'sender' and name_in_field:
                                            name_match_score = 0.5  # Medium confidence for sender field
                                        elif source_type == 'content' and name_in_content:
                                            name_match_score = 0.4  # Lower confidence for content
                                        else:
                                            name_match_score = 0.3  # Minimal confidence
                                    
                                    # Calculate priority: sender emails get higher priority
                                    adjusted_score = score * priority_multiplier * (1.0 + name_match_score)
                                    
                                    # Extra bonus if name appears in field text
                                    if name_in_field or name_in_content:
                                        adjusted_score *= 1.3
                                    
                                    found_emails.append({
                                        'email': email_lower,
                                        'score': adjusted_score,
                                        'source': source_type,
                                        'original_score': score,
                                        'name_match': name_match_score
                                    })
                                    logger.debug(
                                        f"[CAL] Found candidate email: {email_lower} "
                                        f"(source: {source_type}, name_match: {name_match_score:.2f}, "
                                        f"score: {adjusted_score:.2f})"
                                    )
                                elif idx < 3:  # Only log first few rejections
                                    logger.debug(
                                        f"[CAL] Rejected email (no match): {email_lower} "
                                        f"(name_match: {name_match_score:.2f}, source: {source_type})"
                                    )
            
            if found_emails:
                # Sort by adjusted score (higher is better), prioritizing sender emails and name matches
                found_emails.sort(
                    key=lambda x: (x['score'], x['name_match'], x['source'] == 'sender'),
                    reverse=True
                )
                best_email = found_emails[0]['email']
                best_source = found_emails[0]['source']
                name_match = found_emails[0].get('name_match', 0)
                logger.info(
                    f"[CAL] Resolved name '{name}' to email '{best_email}' via RAG semantic search "
                    f"(source: {best_source}, name_match: {name_match:.2f}, score: {found_emails[0]['score']:.2f})"
                )
                return best_email
            else:
                # Only log detailed info at debug level to reduce noise
                # The system will fall back to email search which works reliably
                logger.debug(
                    f"[CAL] RAG search found {len(results)} results for '{name}' but none contained valid person emails. "
                    f"Falling back to email search (Tier 3)."
                )
        
        logger.debug(f"[CAL] RAG search did not find valid email for '{name}', will try email search fallback")
        return None
        
    except Exception as e:
        logger.debug(f"[CAL] RAG search failed for '{name}': {e}. Will try email search fallback.")
        return None


def resolve_name_to_email(
    name: str,
    email_service: Optional[Any] = None,
    config: Optional[Any] = None,
    graph_manager: Optional[Any] = None,
    user_id: Optional[int] = None,
    rag_engine: Optional[Any] = None
) -> Optional[str]:
    """
    Resolve a person's name to their email address.
    
    This function implements the Contact Resolver role with a three-tier approach:
    1. First, try ArangoDB graph lookup (fast, accurate, uses Person/Alias/EmailAddress nodes)
    2. Then, try Qdrant/RAG semantic search (finds names even with variations like "Nick" vs "Nicholas")
    3. Finally, fallback to email search if graph and RAG don't have the contact
    
    Args:
        name: Person's name (e.g., "Maniko", "John Smith", "Nick")
        email_service: Optional EmailService instance for fallback email search
        config: Optional config (currently unused)
        graph_manager: Optional KnowledgeGraphManager instance for ArangoDB graph lookup
        user_id: Optional user ID for multi-user support
        rag_engine: Optional RAGEngine instance for Qdrant semantic search
        
    Returns:
        Email address if found, None otherwise
    """
    # Suppress unused parameter warning
    _ = config
    if not name or not name.strip():
        return None
    
    # Check if it's already an email address
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if email_pattern.match(name.strip()):
        return name.strip().lower()
    
    # Log what services are available
    logger.info(
        f"[CAL] Resolving name '{name}' to email - "
        f"graph_manager: {graph_manager is not None}, "
        f"rag_engine: {rag_engine is not None}, "
        f"email_service: {email_service is not None}, "
        f"user_id: {user_id}"
    )
    
    # TIER 1: Try ArangoDB graph lookup first (Contact Resolver role)
    if graph_manager:
        logger.debug(f"[CAL] Attempting ArangoDB graph lookup for '{name}'")
        email = resolve_name_to_email_via_graph(name, graph_manager, user_id)
        if email:
            logger.info(f"[CAL] Resolved name '{name}' to email '{email}' via ArangoDB graph")
            return email
        else:
            logger.debug(f"[CAL] ArangoDB graph lookup failed for '{name}'")
    else:
        logger.debug(f"[CAL] No graph_manager available, skipping ArangoDB lookup")
    
    # TIER 2: Try Qdrant/RAG semantic search for name variations
    if rag_engine:
        logger.debug(f"[CAL] Attempting RAG semantic search for '{name}'")
        email = resolve_name_to_email_via_rag(name, rag_engine, user_id)
        if email:
            logger.info(f"[CAL] Resolved name '{name}' to email '{email}' via RAG semantic search")
            return email
        else:
            logger.debug(f"[CAL] RAG search did not find email for '{name}', trying email search fallback")
    else:
        logger.debug(f"[CAL] No rag_engine available, skipping RAG search (will use email search)")
    
    # TIER 3: Fallback to email search if graph and RAG don't have the contact
    if not email_service:
        logger.debug(f"[CAL] Cannot resolve name '{name}' to email - no email_service provided (graph and RAG also failed). This is expected if email service is not available.")
        return None
    
    logger.debug(f"[CAL] Attempting email search fallback for '{name}'")
    
    try:
        # Search for emails FROM this person first (most reliable)
        # When searching for "Anthony", we want emails FROM Anthony, not TO Anthony
        emails_from = email_service.search_emails(
            from_email=name,
            limit=20  # Get more results to find the best match
        )
        
        found_emails = []
        name_lower = name.lower().strip()
        name_parts = name_lower.split()
        email_pattern = re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')
        
        # Helper function to check if email matches the person's name (same as RAG function)
        def email_matches_name(email: str, name: str, name_parts: list) -> float:
            """Check if email address matches the person's name. Returns confidence score (0-1)."""
            email_lower = email.lower()
            email_username = email_lower.split('@')[0] if '@' in email_lower else email_lower
            name_lower = name.lower()
            
            # Exact name match in username (highest confidence)
            # e.g., "anthony" in "manikoanthony" or "anthony" in "anthony.smith"
            if name_lower in email_username:
                return 1.0
            
            # All name parts appear in username
            if all(part in email_username for part in name_parts if len(part) > 2):
                return 0.9
            
            # First name or last name in username
            if len(name_parts) > 0:
                first_name = name_parts[0]
                if first_name in email_username and len(first_name) > 2:
                    return 0.8  # Increased from 0.7
                if len(name_parts) > 1:
                    last_name = name_parts[-1]
                    if last_name in email_username and len(last_name) > 2:
                        return 0.8  # Increased from 0.7
            
            # Partial match (e.g., "anthony" -> "anthony" or "maniko" -> "maniko")
            for part in name_parts:
                if len(part) > 3 and part in email_username:
                    return 0.6  # Increased from 0.5
            
            # More lenient: check if any significant part of name appears
            for part in name_parts:
                if len(part) > 2 and part in email_username:
                    return 0.4  # Lower confidence but still acceptable
            
            return 0.0  # No match
        
        # Filter out obviously wrong emails
        def is_valid_person_email(email: str) -> bool:
            """Check if email looks like a real person's email (not generic)."""
            email_lower = email.lower()
            invalid_patterns = [
                'noreply', 'no-reply', 'donotreply', 'do-not-reply',
                'email@', 'mail@', 'info@', 'contact@', 'support@',
                'booking@', 'reservation@', 'automated@', 'system@',
                'notification@', 'alerts@', 'newsletter@', 'marketing@'
            ]
            return not any(pattern in email_lower for pattern in invalid_patterns)
        
        # Process emails FROM this person (highest priority)
        if emails_from and len(emails_from) > 0:
            for email in emails_from:
                sender = email.get('from') or email.get('sender', '')
                if sender:
                    matches = email_pattern.findall(str(sender))
                    for match in matches:
                        email_lower = match.lower().strip()
                        
                        # Skip invalid emails
                        if not is_valid_person_email(email_lower):
                            logger.debug(f"[CAL] Skipping invalid email pattern: {email_lower}")
                            continue
                        
                        if email_lower not in [e['email'] for e in found_emails]:
                            # Check if name appears in sender field and email matches name
                            sender_lower = str(sender).lower()
                            name_match_score = email_matches_name(email_lower, name_lower, name_parts)
                            
                            # Include emails with name match OR if name appears in sender field (more lenient)
                            if name_match_score > 0 or (name_lower in sender_lower):
                                # If no name match but name in sender field, give it some confidence
                                if name_match_score == 0:
                                    name_match_score = 0.3  # Give it some confidence if from sender field
                                priority = 3.0 if name_lower in sender_lower else 2.0
                                priority *= (1.0 + name_match_score)  # Boost based on name match
                                
                                found_emails.append({
                                    'email': email_lower,
                                    'priority': priority,
                                    'source': 'from',
                                    'sender_field': sender,
                                    'name_match': name_match_score
                                })
                                logger.debug(
                                    f"[CAL] Found candidate email: {email_lower} "
                                    f"(name_match: {name_match_score:.2f}, priority: {priority:.2f})"
                                )
                            else:
                                logger.debug(f"[CAL] Rejected email (no name match): {email_lower}")
        
        # Only search emails TO this person if we didn't find any FROM emails
        # This prevents picking the wrong email (e.g., picking recipient email instead of sender)
        if not found_emails:
            emails_to = email_service.search_emails(
                to_email=name,
                limit=20
            )
            
            if emails_to and len(emails_to) > 0:
                for email in emails_to:
                    to_field = email.get('to', '')
                    if to_field:
                        matches = email_pattern.findall(str(to_field))
                        for match in matches:
                            email_lower = match.lower().strip()
                            
                            # Skip invalid emails
                            if not is_valid_person_email(email_lower):
                                continue
                            
                            if email_lower not in [e['email'] for e in found_emails]:
                                name_match_score = email_matches_name(email_lower, name_lower, name_parts)
                                
                                # Only include if name matches OR if name appears in recipient field
                                if name_match_score > 0 or name_lower in str(to_field).lower():
                                    if name_match_score == 0:
                                        name_match_score = 0.2  # Give some confidence if name in field
                                    found_emails.append({
                                        'email': email_lower,
                                        'priority': 1.0 * (1.0 + name_match_score),  # Lower priority for recipient emails
                                        'source': 'to',
                                        'to_field': to_field,
                                        'name_match': name_match_score
                                    })
                                    logger.debug(
                                        f"[CAL] Found candidate email from recipient: {email_lower} "
                                        f"(name_match: {name_match_score:.2f})"
                                    )
        
        if found_emails:
            # Sort by priority (higher is better), prioritizing sender emails and name matches
            found_emails.sort(
                key=lambda x: (x['priority'], x.get('name_match', 0), x['source'] == 'from'),
                reverse=True
            )
            best_email = found_emails[0]['email']
            best_source = found_emails[0]['source']
            name_match = found_emails[0].get('name_match', 0)
            logger.info(
                f"[CAL] Resolved name '{name}' to email '{best_email}' from email search "
                f"(source: {best_source}, name_match: {name_match:.2f}, priority: {found_emails[0]['priority']:.2f}, "
                f"total candidates: {len(found_emails)})"
            )
            return best_email
        else:
            logger.debug(
                f"[CAL] Email search found {len(emails_from) if emails_from else 0} emails FROM '{name}' "
                f"but none passed validation (this is expected if no matching emails exist)"
            )
        
        logger.debug(f"[CAL] Could not resolve name '{name}' to email address")
        return None
        
    except Exception as e:
        logger.debug(f"[CAL] Email search failed for '{name}': {e}. This is expected if email service is unavailable.")
        return None


def resolve_attendees_to_emails(
    attendees: Optional[List[str]],
    email_service: Optional[Any] = None,
    config: Optional[Any] = None,
    graph_manager: Optional[Any] = None,
    user_id: Optional[int] = None,
    rag_engine: Optional[Any] = None
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
    logger.debug(
        f"[CAL] resolve_attendees_to_emails called with {len(attendees) if attendees else 0} attendees, "
        f"services: email_service={email_service is not None}, "
        f"graph_manager={graph_manager is not None}, rag_engine={rag_engine is not None}, user_id={user_id}"
    )
    
    if not attendees:
        logger.debug("[CAL] resolve_attendees_to_emails called with empty attendees list (this is normal if no attendees specified)")
        return ([], [])
    
    resolved_emails = []
    unresolved_names = []
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    
    for attendee in attendees:
        if not attendee or not attendee.strip():
            continue
        
        attendee = attendee.strip()
        logger.debug(f"[CAL] Resolving attendee: '{attendee}'")
        
        # If it's already an email, use it directly
        if email_pattern.match(attendee):
            logger.debug(f"[CAL] Attendee '{attendee}' is already an email address")
            resolved_emails.append(attendee.lower())
        else:
            # Try to resolve name to email (uses graph first, then RAG, then email search)
            logger.debug(f"[CAL] Attempting to resolve name '{attendee}' to email...")
            email = resolve_name_to_email(attendee, email_service, config, graph_manager, user_id, rag_engine)
            if email:
                logger.info(f"[CAL] Successfully resolved '{attendee}' to '{email}'")
                resolved_emails.append(email)
            else:
                logger.debug(f"[CAL] Could not resolve '{attendee}' to email (will be added to unresolved list)")
                unresolved_names.append(attendee)
    
    if resolved_emails or unresolved_names:
        logger.info(
            f"[CAL] Resolution complete: {len(resolved_emails)} resolved, {len(unresolved_names)} unresolved"
        )
        if unresolved_names:
            logger.info(f"[CAL] Unresolved names: {unresolved_names}")
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
