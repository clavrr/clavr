"""
Simplified Date/Time Parser
Replaces 100+ lines of repetitive if/elif logic with clean, maintainable code
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple
import re

from ..logger import setup_logger
from .datetime_helpers import days_until_weekday

logger = setup_logger(__name__)


WEEKDAYS = {
    'monday': 0, 'mon': 0,
    'tuesday': 1, 'tue': 1, 'tues': 1,
    'wednesday': 2, 'wed': 2,
    'thursday': 3, 'thu': 3, 'thur': 3, 'thurs': 3,
    'friday': 4, 'fri': 4,
    'saturday': 5, 'sat': 5,
    'sunday': 6, 'sun': 6
}


def parse_natural_time(time_str: str) -> Optional[datetime]:
    """
    Parse natural language time expressions into datetime objects.
    
    Supports:
    - "tomorrow at 2pm"
    - "next Monday at 10am"
    - "today at 3:30pm"
    - "Friday at 4pm"
    - ISO format: "2025-10-24T14:00:00"
    
    Args:
        time_str: Natural language time expression
        
    Returns:
        datetime object or None if parsing fails
        
    Examples:
        >>> parse_natural_time("tomorrow at 2pm")
        datetime(2025, 10, 25, 14, 0)
        >>> parse_natural_time("next Monday at 10am")
        datetime(2025, 10, 27, 10, 0)
    """
    try:
        # Try ISO format first
        if 'T' in time_str or re.match(r'^\d{4}-\d{2}-\d{2}', time_str):
            try:
                return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            except ValueError:
                pass  # Not ISO format, continue to natural language parsing
        
        now = datetime.now()
        time_str_lower = time_str.lower()
        
        # Extract hour and minute
        hour, minute = _extract_time(time_str_lower)
        if hour is None:
            logger.warning(f"Could not extract time from: '{time_str}'")
            return None
        
        # Determine target date
        target_date = _extract_date(time_str_lower, now)
        
        return target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
    except Exception as e:
        logger.error(f"Error parsing time '{time_str}': {e}", exc_info=True)
        return None


def _extract_time(time_str: str) -> Tuple[Optional[int], int]:
    """
    Extract hour and minute from time string.
    
    Returns:
        (hour, minute) tuple, or (None, 0) if parsing fails
    """
    # Match patterns like "2pm", "14:00", "3:30pm"
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str)
    if not time_match:
        return None, 0
    
    hour = int(time_match.group(1))
    minute = int(time_match.group(2)) if time_match.group(2) else 0
    am_pm = time_match.group(3)
    
    # Convert to 24-hour format
    if am_pm == 'pm' and hour < 12:
        hour += 12
    elif am_pm == 'am' and hour == 12:
        hour = 0
    
    return hour, minute


def _extract_date(time_str: str, now: datetime) -> datetime:
    """
    Extract target date from time string.
    
    Args:
        time_str: Lowercase time string
        now: Current datetime
        
    Returns:
        Target date as datetime object
    """
    # Handle relative dates
    if 'tomorrow' in time_str:
        return now + timedelta(days=1)
    
    if 'today' in time_str:
        return now
    
    # Handle "next week" style
    if 'next week' in time_str:
        return now + timedelta(days=7)
    
    # Handle weekdays
    for day_name, day_num in WEEKDAYS.items():
        if day_name in time_str:
            # Check if it's "next Monday" or just "Monday"
            is_next = 'next' in time_str
            days_ahead = _days_until_weekday(now.weekday(), day_num, skip_to_next_week=is_next)
            return now + timedelta(days=days_ahead)
    
    # Default to today
    return now


# Use centralized helper function
_days_until_weekday = days_until_weekday

