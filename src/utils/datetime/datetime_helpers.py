"""
DateTime Helper Utilities

Centralized datetime manipulation functions 
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple


def normalize_datetime_start(dt: datetime) -> datetime:
    """
    Normalize datetime to start of day (00:00:00.000000).
    
    Preserves timezone information.
    
    Args:
        dt: Datetime to normalize
        
    Returns:
        Datetime normalized to start of day
    """
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def normalize_datetime_end(dt: datetime) -> datetime:
    """
    Normalize datetime to end of day (23:59:59.999999).
    
    Preserves timezone information.
    
    Args:
        dt: Datetime to normalize
        
    Returns:
        Datetime normalized to end of day
    """
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def get_time_of_day_range(
    date: datetime, 
    time_of_day: str
) -> Tuple[datetime, datetime]:
    """
    Get start and end times for a time-of-day period.
    
    Args:
        date: Base date (should have timezone info)
        time_of_day: 'morning', 'afternoon', 'evening', or 'night'
        
    Returns:
        Tuple of (start_datetime, end_datetime) with same timezone as input date
    """
    time_ranges = {
        'morning': (6, 12),
        'afternoon': (12, 17),
        'evening': (17, 21),
        'night': (21, 23)
    }
    
    start_hour, end_hour = time_ranges.get(time_of_day, (0, 23))
    
    start = date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    
    if time_of_day == 'night':
        end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        end = date.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    
    # Ensure timezone is preserved
    if date.tzinfo:
        if not start.tzinfo:
            start = date.tzinfo.localize(start.replace(tzinfo=None)) if hasattr(date.tzinfo, 'localize') else start.replace(tzinfo=date.tzinfo)
        if not end.tzinfo:
            end = date.tzinfo.localize(end.replace(tzinfo=None)) if hasattr(date.tzinfo, 'localize') else end.replace(tzinfo=date.tzinfo)
    
    return start, end


def days_until_weekday(
    current_weekday: int, 
    target_weekday: int, 
    skip_to_next_week: bool = False
) -> int:
    """
    Calculate days until target weekday.
    
    Args:
        current_weekday: Current day (0=Monday, 6=Sunday)
        target_weekday: Target day (0=Monday, 6=Sunday)
        skip_to_next_week: If True, always go to next week even if target is today
        
    Returns:
        Number of days until target weekday
    """
    days_ahead = (target_weekday - current_weekday) % 7
    
    if days_ahead == 0:
        # Target is today, go to next week
        days_ahead = 7
    elif skip_to_next_week and days_ahead < 7:
        # "next Monday" means next week's Monday, not this week
        days_ahead += 7
    
    return days_ahead

