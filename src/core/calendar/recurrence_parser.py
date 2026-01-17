"""
Recurrence Parser - Converts natural language recurrence patterns to RRULE format

Parses natural language expressions like "every Monday" or "daily for 30 days"
into Google Calendar RRULE format (e.g., "FREQ=WEEKLY;BYDAY=MO").
"""
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

# Try to import dateutil.parser for robust date parsing
DATEUTIL_AVAILABLE = False
FLEXIBLE_PARSER_AVAILABLE = False
_flexible_date_parser = None
dateutil_parser = None
logger = None

try:
    from dateutil import parser as dateutil_parser
    DATEUTIL_AVAILABLE = True
except ImportError:
    DATEUTIL_AVAILABLE = False

# Fallback: try FlexibleDateParser if available
if not DATEUTIL_AVAILABLE:
    try:
        from ...utils import FlexibleDateParser
        _flexible_date_parser = FlexibleDateParser()
        FLEXIBLE_PARSER_AVAILABLE = True
    except ImportError:
        # FlexibleDateParser not available - will use manual parsing
        FLEXIBLE_PARSER_AVAILABLE = False

# Always import logger
try:
    from ...utils.logger import setup_logger
    logger = setup_logger(__name__)
except ImportError:
    # Logger not available - will use None checks before logging
    logger = None


class RecurrenceParser:
    """
    Parse natural language recurrence patterns into Google Calendar RRULE format
    
    Examples:
        "every Monday" -> FREQ=WEEKLY;BYDAY=MO
        "daily for the next month" -> FREQ=DAILY;COUNT=30
        "monthly on the first Friday" -> FREQ=MONTHLY;BYDAY=1FR
        "weekly until December 31" -> FREQ=WEEKLY;UNTIL=20231231T000000Z
    """
    
    # Day name mappings
    DAY_NAMES = {
        'monday': 'MO', 'tuesday': 'TU', 'wednesday': 'WE', 'thursday': 'TH',
        'friday': 'FR', 'saturday': 'SA', 'sunday': 'SU',
        'mon': 'MO', 'tue': 'TU', 'wed': 'WE', 'thu': 'TH',
        'fri': 'FR', 'sat': 'SA', 'sun': 'SU'
    }
    
    # Frequency patterns
    FREQUENCY_PATTERNS = {
        'daily': 'DAILY',
        'day': 'DAILY',
        'every day': 'DAILY',
        'each day': 'DAILY',
        'weekly': 'WEEKLY',
        'week': 'WEEKLY',
        'every week': 'WEEKLY',
        'each week': 'WEEKLY',
        'monthly': 'MONTHLY',
        'month': 'MONTHLY',
        'every month': 'MONTHLY',
        'each month': 'MONTHLY',
        'yearly': 'YEARLY',
        'year': 'YEARLY',
        'annually': 'YEARLY',
        'every year': 'YEARLY',
        'each year': 'YEARLY'
    }
    
    # Ordinal patterns (first, second, third, etc.)
    ORDINAL_PATTERNS = {
        'first': 1, '1st': 1, 'second': 2, '2nd': 2,
        'third': 3, '3rd': 3, 'fourth': 4, '4th': 4,
        'fifth': 5, '5th': 5, 'last': -1
    }
    
    def parse(self, query: str, start_date: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """
        Parse natural language recurrence pattern
        
        Args:
            query: Natural language query (e.g., "every Monday", "daily for 30 days")
            start_date: Start date for calculating UNTIL/COUNT
            
        Returns:
            Dictionary with 'recurrence' (RRULE string) and 'until' (optional end date)
            or None if no recurrence pattern found
        """
        if not query:
            return None
        
        query_lower = query.lower().strip()
        
        # Check if query contains recurrence keywords
        has_recurrence = any(keyword in query_lower for keyword in [
            'every', 'daily', 'weekly', 'monthly', 'yearly', 'recurring',
            'repeat', 'repeating', 'each', 'recur'
        ])
        
        if not has_recurrence:
            return None
        
        try:
            # Parse ordinal position first (needed for frequency detection)
            bysetpos = self._parse_ordinal(query_lower)
            byday = self._parse_day_of_week(query_lower)
            
            # CRITICAL: For ordinal patterns like "first Friday of each month",
            # default to MONTHLY frequency (semantically correct)
            # But if user specifies a count like "for next 6 months", use that count
            has_ordinal_pattern = bysetpos is not None and byday is not None
            
            # Parse frequency first (needed for count parsing context)
            freq = self._parse_frequency(query_lower)
            
            # For ordinal patterns with "of every month" or "of each month", use MONTHLY frequency
            # This is semantically correct: "first Friday of each month" = MONTHLY
            if has_ordinal_pattern:
                if 'of every month' in query_lower or 'of each month' in query_lower or 'every month' in query_lower or 'each month' in query_lower:
                    freq = 'MONTHLY'
                elif freq is None:
                    # Default to MONTHLY for ordinal patterns (semantically correct)
                    freq = 'MONTHLY'
            
            # Handle "every <day>" patterns for WEEKLY frequency
            # E.g., "every Wednesday" should be WEEKLY, not DAILY
            if freq is None or freq == 'DAILY':
                # Check if it's "every <day of week>" pattern
                every_day_pattern = r'every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)'
                if re.search(every_day_pattern, query_lower) and byday and not has_ordinal_pattern:
                    freq = 'WEEKLY'
            
            if not freq:
                return None
            
            # Parse day of week (for weekly/monthly/yearly)
            if freq in ['WEEKLY', 'MONTHLY', 'YEARLY']:
                if not byday:
                    byday = self._parse_day_of_week(query_lower)
            
            # Parse day of month (for monthly)
            bymonthday = None
            if freq == 'MONTHLY':
                bymonthday = self._parse_day_of_month(query_lower)
            
            # Parse ordinal position (first Monday, last Friday, etc.)
            # For YEARLY frequency with ordinal patterns, we still need bysetpos
            if bysetpos is None and (freq == 'MONTHLY' or freq == 'YEARLY') and byday:
                bysetpos = self._parse_ordinal(query_lower)
            
            # Parse count (number of occurrences) - pass frequency for context
            count = self._parse_count(query_lower, freq)
            has_count_specification = count is not None
            
            # Parse until date
            until_date = self._parse_until_date(query_lower, start_date)
            
            # Build RRULE
            rrule_parts = [f"FREQ={freq}"]
            
            # Handle ordinal day patterns (first Friday, last Monday, etc.)
            # Format: BYDAY=1FR (first Friday), BYDAY=-1FR (last Friday)
            # For YEARLY frequency with ordinal patterns, use BYDAY with ordinal
            if byday and bysetpos:
                # Combine ordinal with day: 1FR = first Friday, -1FR = last Friday
                ordinal_day = []
                for day_code in byday:
                    if bysetpos == -1:
                        # Last occurrence
                        ordinal_day.append(f"-1{day_code}")
                    else:
                        # First, second, third, etc.
                        ordinal_day.append(f"{bysetpos}{day_code}")
                rrule_parts.append(f"BYDAY={','.join(ordinal_day)}")
            elif byday:
                rrule_parts.append(f"BYDAY={','.join(byday)}")
            
            # For YEARLY frequency with ordinal patterns, add BYMONTH if not already specified
            # This ensures "first Friday of each month" recurs yearly on the first Friday of each month
            if freq == 'YEARLY' and byday and bysetpos:
                # YEARLY with BYDAY=1FR means "first Friday of each month, every year"
                # This is correct - no need to add BYMONTH
                pass
            
            if bymonthday:
                rrule_parts.append(f"BYMONTHDAY={bymonthday}")
            
            # Only add BYSETPOS if we didn't combine it with BYDAY
            if bysetpos and not byday:
                rrule_parts.append(f"BYSETPOS={bysetpos}")
            
            if count:
                rrule_parts.append(f"COUNT={count}")
            elif until_date:
                # Format until date as YYYYMMDDTHHMMSSZ
                until_str = until_date.strftime('%Y%m%dT%H%M%SZ')
                rrule_parts.append(f"UNTIL={until_str}")
            
            rrule = ';'.join(rrule_parts)
            
            result = {
                'recurrence': [rrule],
                'until': until_date.isoformat() if until_date else None
            }
            
            if logger:
                logger.info(f"Parsed recurrence: '{query}' -> {rrule}")
            
            return result
            
        except Exception as e:
            if logger:
                logger.warning(f"Failed to parse recurrence from '{query}': {e}")
            return None
    
    def _parse_frequency(self, query: str) -> Optional[str]:
        """Parse frequency from query"""
        for pattern, freq in self.FREQUENCY_PATTERNS.items():
            if pattern in query:
                return freq
        return None
    
    def _parse_day_of_week(self, query: str) -> Optional[list]:
        """Parse day of week from query using word boundaries to avoid false matches"""
        days = []
        
        # Use word boundaries to avoid matching 'mon' in 'month'
        # Sort by length (longest first) to match 'wednesday' before 'wed'
        sorted_days = sorted(self.DAY_NAMES.items(), key=lambda x: len(x[0]), reverse=True)
        
        for day_name, day_code in sorted_days:
            # Use regex with word boundaries to ensure exact matches
            # This prevents 'mon' from matching in 'month'
            pattern = r'\b' + re.escape(day_name) + r'\b'
            if re.search(pattern, query, re.IGNORECASE):
                if day_code not in days:
                    days.append(day_code)
        
        return days if days else None
    
    def _parse_day_of_month(self, query: str) -> Optional[int]:
        """Parse day of month from query (e.g., "on the 15th")"""
        # Look for patterns like "on the 15th", "on day 15"
        patterns = [
            r'on\s+the\s+(\d+)(?:st|nd|rd|th)?',
            r'on\s+day\s+(\d+)',
            r'day\s+(\d+)',
            r'the\s+(\d+)(?:st|nd|rd|th)?'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                day = int(match.group(1))
                if 1 <= day <= 31:
                    return day
        return None
    
    def _parse_ordinal(self, query: str) -> Optional[int]:
        """Parse ordinal position (first, second, last, etc.)"""
        for ordinal_text, ordinal_num in self.ORDINAL_PATTERNS.items():
            if ordinal_text in query:
                return ordinal_num
        return None
    
    def _parse_count(self, query: str, freq: Optional[str] = None) -> Optional[int]:
        """
        Parse count (number of occurrences).
        
        Handles:
        - "for 30 days" with DAILY frequency -> COUNT=30
        - "for 5 weeks" with WEEKLY frequency -> COUNT=5
        - "for 6 months" with MONTHLY frequency -> COUNT=6
        - "5 times" -> COUNT=5 (regardless of frequency)
        - "repeat 3 times" -> COUNT=3
        
        Args:
            query: Query string
            freq: Frequency (DAILY, WEEKLY, MONTHLY, YEARLY) - used for context
            
        Returns:
            Count value or None if not found
        """
        query_lower = query.lower()
        
        # Patterns: "for 30 days", "for the next 10 weeks", "for next 6 months", "5 times"
        patterns = [
            r'for\s+(?:the\s+)?(?:next\s+)?(\d+)\s+(?:day|days|week|weeks|month|months|year|years|time|times)',
            r'(\d+)\s+(?:time|times)(?!\s+(?:day|week|month|year))',  # "5 times" but not "5 times a day"
            r'repeat\s+(\d+)\s+(?:time|times)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                count = int(match.group(1))
                matched_text = match.group(0)  # The matched portion: "for 6 months", "for 10 days", etc.
                
                # If "times" is specified, return the count directly (number of occurrences)
                if 'time' in matched_text:
                    # Check if it's "X times" (occurrences) vs "X times a day/week" (frequency)
                    if not re.search(r'\d+\s+times?\s+(?:a|per|each)\s+(?:day|week|month|year)', query_lower):
                        return count
                
                # For duration-based counts, check the MATCHED TEXT, not the whole query
                # This prevents "wednesday" from matching "day"
                if 'days' in matched_text or ('day' in matched_text and 'days' not in matched_text):
                    if freq == 'DAILY':
                        return count  # For DAILY: "for 10 days" = 10 occurrences
                    else:
                        # Different frequency, keep the duration count
                        return count
                        
                elif 'weeks' in matched_text or 'week' in matched_text:
                    if freq == 'WEEKLY':
                        return count  # For WEEKLY: "for 5 weeks" = 5 occurrences
                    elif freq == 'DAILY':
                        return count * 7  # For DAILY over weeks: "for 2 weeks" = 14 days
                    else:
                        return count
                        
                elif 'months' in matched_text or 'month' in matched_text:
                    if freq == 'MONTHLY':
                        return count  # For MONTHLY: "for 6 months" = 6 occurrences
                    elif freq == 'WEEKLY':
                        # For WEEKLY over months: "every Wed for 6 months" = ~26 weeks
                        return count * 4  # Approximate: 4 weeks per month
                    elif freq == 'DAILY':
                        return count * 30  # For DAILY over months: ~30 days per month
                    else:
                        return count
                        
                elif 'years' in matched_text or 'year' in matched_text:
                    if freq == 'YEARLY':
                        return count  # For YEARLY: "for 2 years" = 2 occurrences
                    elif freq == 'MONTHLY':
                        return count * 12  # For MONTHLY over years: 12 months per year
                    elif freq == 'WEEKLY':
                        return count * 52  # For WEEKLY over years: 52 weeks per year
                    elif freq == 'DAILY':
                        return count * 365  # For DAILY over years: 365 days per year
                    else:
                        return count
                else:
                    # Default: assume it's a count of occurrences
                    return count
        return None
    
    def _parse_until_date(self, query: str, start_date: Optional[datetime] = None) -> Optional[datetime]:
        """Parse until date from query"""
        # Patterns: "until December 31", "until 2024-12-31", "for the next month"
        if not start_date:
            start_date = datetime.now()
        
        # Check for "until" date
        until_patterns = [
            r'until\s+(\d{4}-\d{2}-\d{2})',
            r'until\s+([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?)',
            r'through\s+(\d{4}-\d{2}-\d{2})',
            r'through\s+([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?)'
        ]
        
        for pattern in until_patterns:
            match = re.search(pattern, query)
            if match:
                date_str = match.group(1).strip()
                try:
                    # Try ISO format first
                    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                        return datetime.fromisoformat(date_str)
                    
                    # Use proper date parser for natural language dates
                    parsed_date = self._parse_date_string(date_str, start_date)
                    if parsed_date:
                        return parsed_date
                except Exception as e:
                    if logger:
                        logger.debug(f"Failed to parse date '{date_str}': {e}")
                    pass
        
        # Check for "for the next X" patterns
        next_patterns = [
            r'for\s+the\s+next\s+(\d+)\s+months?',
            r'for\s+the\s+next\s+(\d+)\s+weeks?',
            r'for\s+the\s+next\s+(\d+)\s+days?'
        ]
        
        for pattern in next_patterns:
            match = re.search(pattern, query)
            if match:
                num = int(match.group(1))
                if 'month' in query:
                    return start_date + timedelta(days=num * 30)
                elif 'week' in query:
                    return start_date + timedelta(weeks=num)
                elif 'day' in query:
                    return start_date + timedelta(days=num)
        
        return None
    
    def _parse_date_string(self, date_str: str, reference_date: Optional[datetime] = None) -> Optional[datetime]:
        """
        Parse a date string using available date parsers
        
        Args:
            date_str: Date string to parse (e.g., "December 31", "Dec 31 2024", "2024-12-31")
            reference_date: Reference date for relative parsing (defaults to now)
            
        Returns:
            Parsed datetime or None if parsing fails
        """
        if not date_str:
            return None
        
        if reference_date is None:
            reference_date = datetime.now()
        
        # Try dateutil.parser first (most robust)
        if DATEUTIL_AVAILABLE:
            try:
                # dateutil.parser can handle many formats including:
                # "December 31", "Dec 31 2024", "31 Dec 2024", etc.
                parsed = dateutil_parser.parse(date_str, default=reference_date, fuzzy=True)
                if logger:
                    logger.debug(f"Parsed '{date_str}' using dateutil: {parsed}")
                return parsed
            except (ValueError, TypeError) as e:
                if logger:
                    logger.debug(f"dateutil failed to parse '{date_str}': {e}")
        
        # Fallback to FlexibleDateParser if available
        if FLEXIBLE_PARSER_AVAILABLE:
            try:
                result = _flexible_date_parser.parse_date_expression(date_str, prefer_future=True)
                if result and 'start' in result:
                    return result['start']
            except Exception as e:
                if logger:
                    logger.debug(f"FlexibleDateParser failed to parse '{date_str}': {e}")
        
        # Fallback: Manual parsing for common patterns
        try:
            # Try patterns like "December 31" or "Dec 31"
            month_patterns = [
                r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:\s+(\d{4}))?',
                r'(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)(?:\s+(\d{4}))?',
            ]
            
            month_names = {
                'january': 1, 'jan': 1, 'february': 2, 'feb': 2,
                'march': 3, 'mar': 3, 'april': 4, 'apr': 4,
                'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7,
                'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'sept': 9,
                'october': 10, 'oct': 10, 'november': 11, 'nov': 11,
                'december': 12, 'dec': 12
            }
            
            for pattern in month_patterns:
                match = re.search(pattern, date_str.lower())
                if match:
                    groups = match.groups()
                    if len(groups) >= 2:
                        # Extract month and day
                        if groups[0].isdigit():
                            day = int(groups[0])
                            month_name = groups[1]
                            year = int(groups[2]) if len(groups) > 2 and groups[2] else reference_date.year
                        else:
                            month_name = groups[0]
                            day = int(groups[1])
                            year = int(groups[2]) if len(groups) > 2 and groups[2] else reference_date.year
                        
                        month = month_names.get(month_name.lower())
                        if month and 1 <= day <= 31:
                            parsed = datetime(year, month, day)
                            # If the date is in the past relative to reference_date, assume next year
                            if parsed < reference_date:
                                parsed = datetime(year + 1, month, day)
                            if logger:
                                logger.debug(f"Manually parsed '{date_str}': {parsed}")
                            return parsed
        except Exception as e:
            if logger:
                logger.debug(f"Manual parsing failed for '{date_str}': {e}")
        
        return None

