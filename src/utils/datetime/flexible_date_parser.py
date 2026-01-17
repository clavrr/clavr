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
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

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
        self.timezone_name = None
        
        # Try to get timezone from config
        from src.utils.config import get_timezone
        self.timezone_name = get_timezone(config)
        
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
        
        # Timezone abbreviations to IANA names
        self.tz_abbrev_map = {
            'pst': 'America/Los_Angeles',
            'pdt': 'America/Los_Angeles',
            'est': 'America/New_York',
            'edt': 'America/New_York',
            'cst': 'America/Chicago',
            'cdt': 'America/Chicago',
            'mst': 'America/Denver',
            'mdt': 'America/Denver',
            'utc': 'UTC',
            'gmt': 'GMT',
        }
        
        # Special time words
        self.special_time_words = {
            'noon': (12, 0),
            'midday': (12, 0),
            'midnight': (0, 0),
        }
    
    def parse(self, query: str, now: Optional[datetime] = None) -> Optional[Tuple[datetime, datetime]]:
        """
        Parse a date query and return start/end datetime range.
        
        Args:
            query: Natural language date expression
            now: Optional reference datetime (defaults to now)
            
        Returns:
            Tuple of (start_datetime, end_datetime) or None if not parseable
        """
        if not query:
            return None
            
        # 0. Check for ISO format first (fast path)
        if re.match(r'^\d{4}-\d{2}-\d{2}', query):
            if DATEUTIL_AVAILABLE:
                try:
                    parsed = dateutil.parser.parse(query)
                    return (self._localize(parsed), self._localize(parsed + timedelta(hours=1)))
                except Exception:
                    pass
                    
        # 1. Extract timezone if present
        query_remaining, tz_info = self._extract_timezone(query)
        query_lower = query_remaining.lower().strip()
        
        # 2. Extract specific time if present
        target_time = self._parse_time(query_lower)
        
        # 2b. Check for relative time offsets ("in 30 mins", "in half an hour")
        # This overrides target_time if found (as it calculates a specific target time)
        # We need 'now' for this, so we must initialize it eaerlier if needed
        # But 'now' is passed in later or defaulted. Let's default it here temporarily for calculation
        temp_now = now or datetime.now()
        # If now was passed, use it. If not, use local now.
        if temp_now.tzinfo is None and self.timezone_name and PYTZ_AVAILABLE:
            # We need to localize temp_now to interpret relative correctly if we want to be precise,
            # but usually relative minutes don't depend on TZ unless crossing borders.
            pass

        relative_offset_time = self._parse_relative_time_offset(query_lower, temp_now)
        if relative_offset_time:
             # This returns a datetime. We extract time from it?
             # Or we return it as a full result immediately?
             # parse() returns range (start, end).
             # So if we have relative offset, we return (target, target+1h).
             start = relative_offset_time
             # Localize if needed (if temp_now wasn't localized)
             # But let's integrate with the flow:
             # If we have relative offset, we can treat it as a result immediately.
             
             # Ensure consistency with how parse() expects 'now' logic later
             # But simpler to return here.
             
             # If config has timezone, localize it
             start = self._localize(start, tz_info)
             return (start, start + timedelta(hours=1))

        # Get base dates
        if now is None:
            now = datetime.now()
        
        # Ensure now is localized if config has timezone
        if now.tzinfo is None:
            now = self._localize(now, tz_info)
            
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 3. Try parsing date part
        result = None
        
        # Try relative date patterns first
        result = self._parse_relative(query_lower, now, today)
        
        # Try day of week if not found
        if not result:
            result = self._parse_day_of_week(query_lower, today)
        
        if not result:
            result = self._parse_month_date(query_lower, now)

        # Try time of day ("this afternoon", "morning")
        if not result:
            result = self.get_time_of_day_range(query_lower, today)
        
        if not result and target_time:
            result = (today, today + timedelta(days=1) - timedelta(seconds=1))
            
        if result:
            start, end = result
            
            # Apply target time if found
            if target_time:
                h, m = target_time
                start = start.replace(hour=h, minute=m, second=0, microsecond=0)
                # If it's a specific time, the range is small (e.g., 1 hour) or just that point
                # For most queries, 1 hour duration is a sensible default if not specified
                end = start + timedelta(hours=1)
            
            # Localize
            return (self._localize(start, tz_info), self._localize(end, tz_info))
        
        # Fallback to dateutil if available
        if DATEUTIL_AVAILABLE:
            try:
                parsed = dateutil.parser.parse(query_remaining, fuzzy=True)
                start = parsed
                if not target_time:
                    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
                    end = start + timedelta(days=1) - timedelta(seconds=1)
                else:
                    end = start + timedelta(hours=1)
                
                return (self._localize(start, tz_info), self._localize(end, tz_info))
            except Exception:
                pass
        
        return None
    
    def _extract_timezone(self, query: str) -> Tuple[str, Optional[Any]]:
        """
        Extract timezone abbreviation from query and return (remaining_query, tz_info).
        """
        query_lower = query.lower()
        for abbrev, tz_name in self.tz_abbrev_map.items():
            # Match abbreviation as a whole word
            if re.search(rf'\b{abbrev}\b', query_lower):
                remaining = re.sub(rf'\b{abbrev}\b', '', query_lower).strip()
                if PYTZ_AVAILABLE:
                    return remaining, pytz.timezone(tz_name)
                return remaining, None
        return query, None

    def _localize(self, dt: datetime, tz: Optional[Any] = None) -> datetime:
        """
        Localize a naive datetime or convert an aware one.
        """
        target_tz = tz
        if not target_tz and PYTZ_AVAILABLE and self.timezone_name:
            target_tz = pytz.timezone(self.timezone_name)
            
        if not target_tz:
            return dt
            
        if dt.tzinfo is None:
            if hasattr(target_tz, 'localize'): # pytz
                return target_tz.localize(dt)
            return dt.replace(tzinfo=target_tz)
        
        return dt.astimezone(target_tz)

    def _parse_time(self, query: str) -> Optional[Tuple[int, int]]:
        """
        Extract time (hour, minute) from query.
        """
        query_lower = query.lower().strip()
        
        # 1. Check special time words
        for word, (h, m) in self.special_time_words.items():
            if re.search(rf'\b{word}\b', query_lower):
                return h, m
        
        # 2. Check for time patterns
        time_patterns = [
            r'(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)',  # "2:30 pm", "2:30 p.m."
            r'(\d{1,2})\s*([ap]\.?m\.?)',          # "10am", "3 p.m."
            r'(\d{1,2}):(\d{2})',                  # "14:30"
            r'\b(\d{1,2})\s*o\'clock\b',           # "3 o'clock"
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, query_lower)
            if match:
                groups = match.groups()
                try:
                    hour = int(groups[0])
                    minute = 0
                    am_pm = None
                    
                    if len(groups) >= 2:
                        # Normalize am/pm (remove dots)
                        potential_am_pm = groups[1].replace('.', '').lower()
                        if potential_am_pm in ('am', 'pm'):
                            am_pm = potential_am_pm
                        else:
                            minute = int(groups[1])
                            if len(groups) >= 3:
                                am_pm = groups[2].replace('.', '').lower()
                    
                    # Convert to 24-hour format
                    if am_pm == 'pm' and hour < 12:
                        hour += 12
                    elif am_pm == 'am' and hour == 12:
                        hour = 0
                    
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        return hour, minute
                except (ValueError, TypeError):
                    continue
        
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

    def _parse_relative_time_offset(self, query: str, now: datetime) -> Optional[datetime]:
        """
        Parse relative time offsets like "in 10 minutes", "in half an hour".
        """
        query_lower = query.lower()
        
        # "in half an hour"
        if "in half an hour" in query_lower or "in half hour" in query_lower:
            return now + timedelta(minutes=30)
        
        # "in an hour"
        if "in an hour" in query_lower or "in 1 hour" in query_lower:
            return now + timedelta(hours=1)
            
        # "in X minutes/hours"
        match = re.search(r'in\s+(\d+)\s*(min|minute|hour|hr)s?', query_lower)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            
            if 'min' in unit:
                return now + timedelta(minutes=num)
            elif 'hour' in unit or 'hr' in unit:
                return now + timedelta(hours=num)
                
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
    
    def parse_date_expression(
        self, 
        query: str, 
        prefer_future: bool = True,
        now: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a date expression and return a dict with start and end datetimes.
        
        This is similar to parse() but returns a dict format that's more convenient
        for some use cases.
        
        Args:
            query: Natural language date expression
            prefer_future: If True, prefer future dates when ambiguous
            now: Optional reference datetime
            
        Returns:
            Dict with 'start' and 'end' datetime keys, or None if not parseable
        """
        result = self.parse(query, now=now)
        if not result:
            return None
        
        start, end = result
        
        # If prefer_future is True and the date is in the past, adjust it
        if now is None:
            now = datetime.now()
        if start.tzinfo:
            now = self._localize(now)
            
        if prefer_future and start < now:
            # For relative dates like "Monday", move to next occurrence
            if any(day in query.lower() for day in self.day_names.keys()):
                # Already handled in _parse_day_of_week, but double-check
                if start < datetime.now():
                    start = start + timedelta(weeks=1)
                    end = start + timedelta(days=1) - timedelta(seconds=1)
        
        return {
            'start': start,
            'end': end,
            'start_datetime': start,
            'end_datetime': end
        }
    
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

