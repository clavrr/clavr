"""
Flexible Date Parser for Calendar Queries
Handles both past and future date expressions
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import re
import pytz

from ..logger import setup_logger
from ..config import get_timezone
from .datetime_helpers import (
    normalize_datetime_start,
    normalize_datetime_end,
    get_time_of_day_range
)

logger = setup_logger(__name__)


class FlexibleDateParser:
    """
    Parse natural language date expressions into date ranges
    
    Supports:
    - Past: "yesterday", "2 days ago", "last week", "last month", "3 months ago"
    - Future: "tomorrow", "3 days from now", "next week", "next month", "3 months from now"
    - Specific dates: "November 20", "2025-11-20", "on December 15"
    - Ranges: "this week", "next week", "last week"
    """
    
    def __init__(self, config: Optional[Any] = None):
        self.config = config
        self.tz_name = get_timezone(config) if config else 'UTC'
        self.user_tz = pytz.timezone(self.tz_name)
    
    def parse_date_expression(self, query: str, prefer_future: bool = True) -> Optional[Dict[str, datetime]]:
        """
        Parse a date expression and return a date range.
        
        Args:
            query: Natural language date expression
            prefer_future: If True, ambiguous dates default to future
            
        Returns:
            Dict with 'start' and 'end' datetime objects, or None if parsing fails.
            May also include 'time_of_day' key with values: 'morning', 'afternoon', 'evening', 'night'
        """
        if not query:
            return None
        
        query_lower = query.lower().strip()
        now = datetime.now(self.user_tz)
        today = now.date()
        
        # Extract specific time first (e.g., "at 1 pm", "around 10ish am")
        specific_time = self._extract_specific_time(query_lower)
        
        # Extract time-of-day expression (morning, afternoon, etc.)
        time_of_day = None
        if 'morning' in query_lower:
            time_of_day = 'morning'
        elif 'afternoon' in query_lower:
            time_of_day = 'afternoon'
        elif 'evening' in query_lower:
            time_of_day = 'evening'
        elif 'night' in query_lower or 'tonight' in query_lower:
            time_of_day = 'night'
        
        # Single date expressions
        single_date = self._parse_single_date(query_lower, now, today, prefer_future)
        if single_date:
            # Apply specific time if found (e.g., "today at 1 pm")
            if specific_time:
                hour, minute = specific_time
                single_date = single_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                # For specific times, create a narrow range (1 hour window)
                start = single_date
                end = single_date + timedelta(hours=1)
            elif time_of_day:
                # Apply time-of-day constraints using helper function
                start, end = get_time_of_day_range(single_date, time_of_day)
            else:
                # Full day range using helper functions
                start = normalize_datetime_start(single_date)
                end = normalize_datetime_end(single_date)
            
            result = {'start': start, 'end': end}
            if time_of_day:
                result['time_of_day'] = time_of_day
            if specific_time:
                result['specific_time'] = specific_time
            return result
        
        # Range expressions
        range_result = self._parse_date_range(query_lower, now, today, prefer_future)
        if range_result:
            if specific_time:
                # Apply specific time to range start
                hour, minute = specific_time
                range_result['start'] = range_result['start'].replace(hour=hour, minute=minute, second=0, microsecond=0)
                range_result['end'] = range_result['start'] + timedelta(hours=1)
            elif time_of_day:
                # Apply time-of-day to range start/end
                range_result['time_of_day'] = time_of_day
        return range_result
    
    def _get_time_of_day_range(self, date: datetime, time_of_day: str) -> Tuple[datetime, datetime]:
        """
        Get start and end times for a time-of-day period (deprecated - use datetime_helpers.get_time_of_day_range).
        
        This method is kept for backward compatibility but delegates to the centralized helper.
        
        Args:
            date: Base date (should have timezone info)
            time_of_day: 'morning', 'afternoon', 'evening', or 'night'
            
        Returns:
            Tuple of (start_datetime, end_datetime) with same timezone as input date
        """
        return get_time_of_day_range(date, time_of_day)
    
    def _parse_single_date(self, query: str, now: datetime, today, prefer_future: bool) -> Optional[datetime]:
        """Parse a single date expression"""
        # Today
        if any(phrase in query for phrase in ['today', 'tonight', 'this evening', 'this afternoon', 'this morning']):
            return normalize_datetime_start(now)
        
        # Tomorrow
        if 'tomorrow' in query:
            tomorrow_dt = now + timedelta(days=1)
            return normalize_datetime_start(tomorrow_dt)
        
        # Yesterday
        if 'yesterday' in query:
            return normalize_datetime_start(now - timedelta(days=1))
        
        # N days ago
        match = re.search(r'(\d+)\s+days?\s+ago', query)
        if match:
            days = int(match.group(1))
            return normalize_datetime_start(now - timedelta(days=days))
        
        # N days from now / in N days
        match = re.search(r'(\d+)\s+days?\s+(?:from\s+now|ahead)', query) or re.search(r'in\s+(\d+)\s+days?', query)
        if match:
            days = int(match.group(1))
            return normalize_datetime_start(now + timedelta(days=days))
        
        # Last week (same day last week)
        if 'last week' in query:
            return normalize_datetime_start(now - timedelta(days=7))
        
        # Next week (same day next week)
        if 'next week' in query:
            return normalize_datetime_start(now + timedelta(days=7))
        
        # Last month (approximately 30 days ago)
        if 'last month' in query:
            return normalize_datetime_start(now - timedelta(days=30))
        
        # Next month (approximately 30 days from now)
        if 'next month' in query:
            return normalize_datetime_start(now + timedelta(days=30))
        
        # N months ago
        match = re.search(r'(\d+)\s+months?\s+ago', query)
        if match:
            months = int(match.group(1))
            return normalize_datetime_start(now - timedelta(days=months * 30))
        
        # N months from now
        match = re.search(r'(\d+)\s+months?\s+(?:from\s+now|ahead)', query)
        if match:
            months = int(match.group(1))
            return normalize_datetime_start(now + timedelta(days=months * 30))
        
        # Specific date formats
        # ISO format: 2025-11-20
        iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', query)
        if iso_match:
            try:
                date_str = iso_match.group(1)
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                normalized = normalize_datetime_start(parsed_date)
                return self.user_tz.localize(normalized.replace(tzinfo=None)) if not normalized.tzinfo else normalized
            except ValueError:
                pass
        
        # Month day year format: "November 20, 2027", "Nov 20 2027", "on December 15, 2025"
        month_day_year_match = re.search(r'(?:on\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:,\s*|\s+)(\d{4})', query, re.IGNORECASE)
        if month_day_year_match:
            month_name = month_day_year_match.group(1).lower()
            day = int(month_day_year_match.group(2))
            year = int(month_day_year_match.group(3))
            month_num = self._month_name_to_num(month_name)
            if month_num:
                parsed_date = datetime(year, month_num, day)
                normalized = normalize_datetime_start(parsed_date)
                return self.user_tz.localize(normalized.replace(tzinfo=None)) if not normalized.tzinfo else normalized
        
        # Month day format: "November 20", "Nov 20", "October 25th", "on December 15" (without year)
        # Also handles ordinal: "25th", "1st", "2nd", "3rd"
        month_day_match = re.search(r'(?:on\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?!\s*\d{4})', query, re.IGNORECASE)
        if month_day_match:
            month_name = month_day_match.group(1).lower()
            day = int(month_day_match.group(2))
            month_num = self._month_name_to_num(month_name)
            if month_num:
                year = now.year
                # If date has passed and prefer_future, use next year
                if prefer_future:
                    test_date = datetime(year, month_num, day)
                    if test_date.date() < today:
                        year += 1
                parsed_date = datetime(year, month_num, day)
                normalized = normalize_datetime_start(parsed_date)
                return self.user_tz.localize(normalized.replace(tzinfo=None)) if not normalized.tzinfo else normalized
        
        # Day names with week context: "last week Monday", "this Monday", "next Monday"
        weekday_names = {
            'monday': 0, 'mon': 0, 'tuesday': 1, 'tue': 1, 'tues': 1,
            'wednesday': 2, 'wed': 2, 'thursday': 3, 'thu': 3, 'thur': 3, 'thurs': 3,
            'friday': 4, 'fri': 4, 'saturday': 5, 'sat': 5, 'sunday': 6, 'sun': 6
        }
        
        # Pattern: "last week Monday", "this Monday", "next Monday", "Monday last week"
        weekday_match = None
        week_context = None
        
        # Check for "last week [weekday]" or "[weekday] last week"
        if 'last week' in query:
            week_context = 'last'
            # Try to find weekday after "last week"
            after_match = re.search(r'last\s+week\s+(' + '|'.join(weekday_names.keys()) + ')', query, re.IGNORECASE)
            if after_match:
                weekday_match = after_match.group(1).lower()
            # Try to find weekday before "last week"
            before_match = re.search(r'(' + '|'.join(weekday_names.keys()) + r')\s+last\s+week', query, re.IGNORECASE)
            if before_match:
                weekday_match = before_match.group(1).lower()
        elif 'this week' in query or 'this' in query:
            week_context = 'this'
            # Try to find weekday after "this"
            after_match = re.search(r'this\s+(' + '|'.join(weekday_names.keys()) + ')', query, re.IGNORECASE)
            if after_match:
                weekday_match = after_match.group(1).lower()
        elif 'next week' in query or 'next' in query:
            week_context = 'next'
            # Try to find weekday after "next"
            after_match = re.search(r'next\s+(' + '|'.join(weekday_names.keys()) + ')', query, re.IGNORECASE)
            if after_match:
                weekday_match = after_match.group(1).lower()
        
        if weekday_match and weekday_match in weekday_names:
            target_weekday = weekday_names[weekday_match]
            current_weekday = now.weekday()
            
            if week_context == 'last':
                # Find last week's Monday (or other weekday)
                days_back = (current_weekday - target_weekday + 7) % 7
                if days_back == 0:
                    days_back = 7  # Same day, go back a week
                target_date = now - timedelta(days=days_back + 7)
            elif week_context == 'this':
                # Find this week's Monday (or other weekday)
                days_ahead = (target_weekday - current_weekday) % 7
                if days_ahead == 0:
                    target_date = now  # Today
                else:
                    target_date = now + timedelta(days=days_ahead)
            else:  # next
                # Find next week's Monday (or other weekday)
                days_ahead = (target_weekday - current_weekday) % 7
                if days_ahead == 0:
                    days_ahead = 7  # Same day, go to next week
                else:
                    days_ahead += 7  # Next week
                target_date = now + timedelta(days=days_ahead)
            
            normalized = normalize_datetime_start(target_date)
            return self.user_tz.localize(normalized.replace(tzinfo=None)) if not normalized.tzinfo else normalized
        
        # Year-only format: "in 2027", "2027", "during 2025"
        year_match = re.search(r'(?:in|during|year\s+)?(\d{4})', query)
        if year_match:
            year = int(year_match.group(1))
            # Return start of year
            parsed_date = datetime(year, 1, 1)
            normalized = normalize_datetime_start(parsed_date)
            return self.user_tz.localize(normalized.replace(tzinfo=None)) if not normalized.tzinfo else normalized
        
        return None
    
    def _extract_specific_time(self, query: str) -> Optional[Tuple[int, int]]:
        """
        Extract specific time from query (e.g., "at 1 pm", "around 10ish am", "at 2:30 PM").
        
        Returns:
            Tuple of (hour, minute) in 24-hour format, or None if no time found
        """
        # Patterns for time extraction
        # "at 1 pm", "at 1pm", "at 1:30 pm", "around 10ish am", "at 2:30 PM", "yesterday around 10ish am"
        time_patterns = [
            # Pattern 1: "at/around/about [number]ish [am/pm]" or "at/around/about [number]:[minutes] [am/pm]"
            r'(?:at|around|about)\s+(\d{1,2})(?:ish)?(?::(\d{2}))?\s*(am|pm)',
            # Pattern 2: "[number] [am/pm]" (standalone time)
            r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2)) if match.group(2) else 0
                am_pm = match.group(3) if len(match.groups()) >= 3 and match.group(3) else None
                
                # Handle "ish" in the query (approximate time - use hour with 0 minutes)
                if 'ish' in query.lower() and minute == 0:
                    # Already handled by making minute 0
                    pass
                
                # Convert to 24-hour format
                if am_pm:
                    am_pm_lower = am_pm.lower()
                    if 'pm' in am_pm_lower and hour != 12:
                        hour += 12
                    elif 'am' in am_pm_lower and hour == 12:
                        hour = 0
                
                # Validate hour and minute
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return (hour, minute)
        
        return None
    
    def _parse_date_range(self, query: str, now: datetime, _today, prefer_future: bool) -> Optional[Dict[str, datetime]]:
        """
        Parse a date range expression
        
        Args:
            query: Query string to parse
            now: Current datetime
            _today: Current date (unused, kept for API consistency with _parse_single_date)
            prefer_future: Whether to prefer future dates for ambiguous expressions
        """
        # Time-based queries: "past hour", "last hour", "past 2 hours", "last 3 hours"
        # Pattern: (past|last|in the past|within the past) [number] hour(s)
        hour_match = re.search(r'(?:past|last|in\s+the\s+past|within\s+the\s+past)\s+(\d+)?\s*hours?', query, re.IGNORECASE)
        if hour_match:
            hours = int(hour_match.group(1)) if hour_match.group(1) else 1
            start = now - timedelta(hours=hours)
            end = now
            return {'start': start, 'end': end}
        
        # "past X minutes", "last X minutes"
        minute_match = re.search(r'(?:past|last|in\s+the\s+past|within\s+the\s+past)\s+(\d+)?\s*minutes?', query, re.IGNORECASE)
        if minute_match:
            minutes = int(minute_match.group(1)) if minute_match.group(1) else 1
            start = now - timedelta(minutes=minutes)
            end = now
            return {'start': start, 'end': end}
        
        # This week (today to end of week)
        if 'this week' in query:
            days_until_sunday = (6 - now.weekday()) % 7
            if days_until_sunday == 0:
                days_until_sunday = 7
            start = normalize_datetime_start(now)
            end = normalize_datetime_end(now + timedelta(days=days_until_sunday))
            return {'start': start, 'end': end}
        
        # Next week (7-13 days from today)
        if 'next week' in query:
            start = normalize_datetime_start(now + timedelta(days=7))
            end = normalize_datetime_end(now + timedelta(days=13))
            return {'start': start, 'end': end}
        
        # Last week (7-13 days ago)
        if 'last week' in query:
            start = normalize_datetime_start(now - timedelta(days=13))
            end = normalize_datetime_end(now - timedelta(days=7))
            return {'start': start, 'end': end}
        
        # This month
        if 'this month' in query:
            start = normalize_datetime_start(now.replace(day=1))
            # Last day of current month
            if now.month == 12:
                end = now.replace(year=now.year + 1, month=1, day=1) - timedelta(microseconds=1)
            else:
                end = now.replace(month=now.month + 1, day=1) - timedelta(microseconds=1)
            end = normalize_datetime_end(end)
            return {'start': start, 'end': end}
        
        # Next month
        if 'next month' in query:
            if now.month == 12:
                start = normalize_datetime_start(now.replace(year=now.year + 1, month=1, day=1))
                end = now.replace(year=now.year + 1, month=2, day=1) - timedelta(microseconds=1)
            else:
                start = normalize_datetime_start(now.replace(month=now.month + 1, day=1))
                if now.month == 11:
                    end = now.replace(year=now.year + 1, month=1, day=1) - timedelta(microseconds=1)
                else:
                    end = now.replace(month=now.month + 2, day=1) - timedelta(microseconds=1)
            end = normalize_datetime_end(end)
            return {'start': start, 'end': end}
        
        # Last month
        if 'last month' in query:
            if now.month == 1:
                start = normalize_datetime_start(now.replace(year=now.year - 1, month=12, day=1))
                end = now.replace(month=1, day=1) - timedelta(microseconds=1)
            else:
                start = normalize_datetime_start(now.replace(month=now.month - 1, day=1))
                end = now.replace(month=now.month, day=1) - timedelta(microseconds=1)
            end = normalize_datetime_end(end)
            return {'start': start, 'end': end}
        
        return None
    
    def _month_name_to_num(self, month_name: str) -> Optional[int]:
        """Convert month name to number"""
        months = {
            'january': 1, 'jan': 1,
            'february': 2, 'feb': 2,
            'march': 3, 'mar': 3,
            'april': 4, 'apr': 4,
            'may': 5,
            'june': 6, 'jun': 6,
            'july': 7, 'jul': 7,
            'august': 8, 'aug': 8,
            'september': 9, 'sep': 9, 'sept': 9,
            'october': 10, 'oct': 10,
            'november': 11, 'nov': 11,
            'december': 12, 'dec': 12
        }
        return months.get(month_name.lower())

