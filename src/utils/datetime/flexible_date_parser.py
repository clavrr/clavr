"""
FlexibleDateParser - Intelligent date/time parsing from natural language

Handles queries like:
- "today", "tomorrow", "yesterday"
- "this week", "next week", "last week"
- "this month", "next month"
- "in 3 days", "2 weeks ago"
- "Monday", "next Tuesday"
- "morning", "afternoon", "evening"
- "January 15", "Jan 15, 2024"
"""
import re
from datetime import datetime, timedelta, date, time
from typing import Optional, Tuple, Dict, Any, Union
import calendar

try:
    import dateutil.parser
    from dateutil.relativedelta import relativedelta
    DATEUTIL_AVAILABLE = True
except ImportError:
    DATEUTIL_AVAILABLE = False


class FlexibleDateParser:
    """
    Flexible date parser that handles natural language date expressions.
    
    Works with or without dateutil library (graceful degradation).
    """
    
    def __init__(self, config: Optional[Any] = None):
        """
        Initialize the parser.
        
        Args:
            config: Optional config object with timezone settings
        """
        self.config = config
        self.timezone = None
        
        # Try to get timezone from config
        if config:
            try:
                if hasattr(config, 'agent') and hasattr(config.agent, 'timezone'):
                    self.timezone = config.agent.timezone
                elif hasattr(config, 'timezone'):
                    self.timezone = config.timezone
            except Exception:
                pass
        
        # Day name mappings
        self.day_names = {
            'monday': 0, 'mon': 0,
            'tuesday': 1, 'tue': 1, 'tues': 1,
            'wednesday': 2, 'wed': 2,
            'thursday': 3, 'thu': 3, 'thur': 3, 'thurs': 3,
            'friday': 4, 'fri': 4,
            'saturday': 5, 'sat': 5,
            'sunday': 6, 'sun': 6
        }
        
        # Month name mappings
        self.month_names = {
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
        
        # Time of day ranges (start_hour, end_hour)
        self.time_of_day = {
            'morning': (6, 12),
            'afternoon': (12, 17),
            'evening': (17, 21),
            'night': (21, 6),
        }
    
    def parse(self, query: str) -> Optional[Tuple[datetime, datetime]]:
        """
        Parse a date query and return start/end datetime range.
        
        Args:
            query: Natural language date expression
            
        Returns:
            Tuple of (start_datetime, end_datetime) or None if not parseable
        """
        if not query:
            return None
            
        query_lower = query.lower().strip()
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Try relative date patterns first
        result = self._parse_relative(query_lower, now, today)
        if result:
            return result
        
        # Try day of week
        result = self._parse_day_of_week(query_lower, today)
        if result:
            return result
        
        # Try month/date patterns
        result = self._parse_month_date(query_lower, now)
        if result:
            return result
        
        # Try duration patterns (last X days, past X weeks)
        result = self._parse_duration(query_lower, now, today)
        if result:
            return result
        
        # Fallback to dateutil if available
        if DATEUTIL_AVAILABLE:
            try:
                parsed = dateutil.parser.parse(query, fuzzy=True)
                start = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1) - timedelta(seconds=1)
                return (start, end)
            except Exception:
                pass
        
        return None
    
    def _parse_relative(
        self, 
        query: str, 
        now: datetime, 
        today: datetime
    ) -> Optional[Tuple[datetime, datetime]]:
        """Parse relative date expressions like today, tomorrow, yesterday"""
        
        if 'today' in query:
            return (today, today + timedelta(days=1) - timedelta(seconds=1))
        
        if 'tomorrow' in query:
            start = today + timedelta(days=1)
            return (start, start + timedelta(days=1) - timedelta(seconds=1))
        
        if 'yesterday' in query:
            start = today - timedelta(days=1)
            return (start, start + timedelta(days=1) - timedelta(seconds=1))
        
        # This week (Mon-Sun of current week)
        if 'this week' in query:
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=7) - timedelta(seconds=1)
            return (start, end)
        
        # Next week
        if 'next week' in query:
            start = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
            end = start + timedelta(days=7) - timedelta(seconds=1)
            return (start, end)
        
        # Last week
        if 'last week' in query:
            start = today - timedelta(days=today.weekday()) - timedelta(weeks=1)
            end = start + timedelta(days=7) - timedelta(seconds=1)
            return (start, end)
        
        # This month
        if 'this month' in query:
            start = today.replace(day=1)
            _, last_day = calendar.monthrange(today.year, today.month)
            end = today.replace(day=last_day, hour=23, minute=59, second=59)
            return (start, end)
        
        # Next month
        if 'next month' in query:
            if today.month == 12:
                start = today.replace(year=today.year + 1, month=1, day=1)
            else:
                start = today.replace(month=today.month + 1, day=1)
            _, last_day = calendar.monthrange(start.year, start.month)
            end = start.replace(day=last_day, hour=23, minute=59, second=59)
            return (start, end)
        
        # Last month
        if 'last month' in query:
            if today.month == 1:
                start = today.replace(year=today.year - 1, month=12, day=1)
            else:
                start = today.replace(month=today.month - 1, day=1)
            _, last_day = calendar.monthrange(start.year, start.month)
            end = start.replace(day=last_day, hour=23, minute=59, second=59)
            return (start, end)
        
        return None
    
    def _parse_day_of_week(
        self, 
        query: str, 
        today: datetime
    ) -> Optional[Tuple[datetime, datetime]]:
        """Parse day of week references like Monday, next Tuesday"""
        
        is_next = 'next' in query
        
        for day_name, day_num in self.day_names.items():
            if day_name in query:
                days_ahead = day_num - today.weekday()
                
                if is_next:
                    # "next Monday" means the Monday of next week
                    if days_ahead <= 0:
                        days_ahead += 7
                    days_ahead += 7  # Add another week
                else:
                    # Default: find the next occurrence
                    if days_ahead <= 0:
                        days_ahead += 7
                
                start = today + timedelta(days=days_ahead)
                end = start + timedelta(days=1) - timedelta(seconds=1)
                return (start, end)
        
        return None
    
    def _parse_month_date(
        self, 
        query: str, 
        now: datetime
    ) -> Optional[Tuple[datetime, datetime]]:
        """Parse month/date patterns like January 15, Jan 15 2024"""
        
        for month_name, month_num in self.month_names.items():
            if month_name in query:
                # Try to extract day number
                day_match = re.search(r'\b(\d{1,2})\b', query)
                if day_match:
                    day = int(day_match.group(1))
                    if 1 <= day <= 31:
                        # Try to extract year
                        year_match = re.search(r'\b(20\d{2})\b', query)
                        year = int(year_match.group(1)) if year_match else now.year
                        
                        try:
                            start = datetime(year, month_num, day)
                            end = start + timedelta(days=1) - timedelta(seconds=1)
                            return (start, end)
                        except ValueError:
                            pass
                else:
                    # Just month name - return the whole month
                    year = now.year
                    start = datetime(year, month_num, 1)
                    _, last_day = calendar.monthrange(year, month_num)
                    end = datetime(year, month_num, last_day, 23, 59, 59)
                    return (start, end)
        
        return None
    
    def _parse_duration(
        self, 
        query: str, 
        now: datetime, 
        today: datetime
    ) -> Optional[Tuple[datetime, datetime]]:
        """Parse duration patterns like 'last 7 days', 'past 2 weeks', 'in 3 days'"""
        
        # "in X days/weeks/months" (future)
        future_match = re.search(r'in\s+(\d+)\s+(day|week|month)s?', query)
        if future_match:
            num = int(future_match.group(1))
            unit = future_match.group(2)
            
            if unit == 'day':
                start = today + timedelta(days=num)
            elif unit == 'week':
                start = today + timedelta(weeks=num)
            elif unit == 'month':
                if DATEUTIL_AVAILABLE:
                    start = today + relativedelta(months=num)
                else:
                    start = today + timedelta(days=num * 30)
            
            end = start + timedelta(days=1) - timedelta(seconds=1)
            return (start, end)
        
        # "X days/weeks/months ago" or "last X days/weeks"
        past_match = re.search(r'(?:last|past)\s+(\d+)\s+(day|week|month)s?|(\d+)\s+(day|week|month)s?\s+ago', query)
        if past_match:
            if past_match.group(1):
                num = int(past_match.group(1))
                unit = past_match.group(2)
            else:
                num = int(past_match.group(3))
                unit = past_match.group(4)
            
            if unit == 'day':
                start = today - timedelta(days=num)
            elif unit == 'week':
                start = today - timedelta(weeks=num)
            elif unit == 'month':
                if DATEUTIL_AVAILABLE:
                    start = today - relativedelta(months=num)
                else:
                    start = today - timedelta(days=num * 30)
            
            end = now  # Up to now
            return (start, end)
        
        return None
    
    def get_time_of_day_range(
        self, 
        query: str, 
        base_date: Optional[datetime] = None
    ) -> Optional[Tuple[datetime, datetime]]:
        """
        Get time range for time-of-day expressions.
        
        Args:
            query: Query containing time of day reference
            base_date: Base date to apply time range to
            
        Returns:
            Tuple of (start_datetime, end_datetime) or None
        """
        query_lower = query.lower()
        base = base_date or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for tod_name, (start_hour, end_hour) in self.time_of_day.items():
            if tod_name in query_lower:
                if end_hour > start_hour:
                    start = base.replace(hour=start_hour)
                    end = base.replace(hour=end_hour) - timedelta(seconds=1)
                else:
                    # Night wraps around midnight
                    start = base.replace(hour=start_hour)
                    end = (base + timedelta(days=1)).replace(hour=end_hour) - timedelta(seconds=1)
                return (start, end)
        
        return None
    
    def extract_date_filter(
        self, 
        query: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract date filter parameters from query.
        
        Returns dict with 'after', 'before', or 'newer_than' keys.
        """
        result = self.parse(query)
        if not result:
            return None
        
        start, end = result
        
        return {
            'after': start.strftime('%Y/%m/%d'),
            'before': end.strftime('%Y/%m/%d'),
            'start_datetime': start,
            'end_datetime': end
        }

