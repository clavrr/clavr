"""
Task Recurrence Handler - Handle recurring tasks
"""
import re
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from .utils import parse_task_datetime

logger = setup_logger(__name__)


class TaskRecurrenceHandler:
    """
    Handle recurring task creation and management
    
    Supports patterns like:
    - "daily", "every day"
    - "weekly", "every Monday"
    - "monthly", "every month"
    - "every 3 days"
    """
    
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
    
    # Day name mappings
    DAY_NAMES = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6,
        'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3,
        'fri': 4, 'sat': 5, 'sun': 6
    }
    
    def parse_recurrence(self, query: str, start_date: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """
        Parse recurrence pattern from natural language
        
        Args:
            query: Natural language query (e.g., "every Monday", "daily")
            start_date: Start date for calculating next occurrence
            
        Returns:
            Dictionary with recurrence pattern or None
        """
        if not query:
            return None
        
        query_lower = query.lower().strip()
        
        # Check for recurrence keywords
        has_recurrence = any(keyword in query_lower for keyword in [
            'every', 'daily', 'weekly', 'monthly', 'yearly', 'recurring',
            'repeat', 'repeating', 'each', 'recur'
        ])
        
        if not has_recurrence:
            return None
        
        if start_date is None:
            start_date = datetime.now()
        
        # Parse frequency
        frequency = self._parse_frequency(query_lower)
        if not frequency:
            return None
        
        # Parse interval (e.g., "every 3 days")
        interval = self._parse_interval(query_lower)
        
        # Parse day of week (e.g., "every Monday")
        day_of_week = self._parse_day_of_week(query_lower)
        
        # Parse count (e.g., "for 10 times")
        count = self._parse_count(query_lower)
        
        # Parse until date (e.g., "until December 31")
        until_date = self._parse_until_date(query_lower, start_date)
        
        return {
            'frequency': frequency,
            'interval': interval or 1,
            'day_of_week': day_of_week,
            'count': count,
            'until_date': until_date.isoformat() if until_date else None
        }
    
    def _parse_frequency(self, query: str) -> Optional[str]:
        """Extract frequency (DAILY, WEEKLY, MONTHLY, YEARLY)"""
        for pattern, freq in self.FREQUENCY_PATTERNS.items():
            if pattern in query:
                return freq
        return None
    
    def _parse_interval(self, query: str) -> Optional[int]:
        """Extract interval (e.g., "every 3 days" -> 3)"""
        match = re.search(r'every\s+(\d+)\s+(?:day|week|month|year)s?', query)
        if match:
            return int(match.group(1))
        return None
    
    def _parse_day_of_week(self, query: str) -> Optional[int]:
        """Extract day of week (0=Monday, 6=Sunday)"""
        for day_name, day_num in self.DAY_NAMES.items():
            if f"every {day_name}" in query or f"on {day_name}" in query:
                return day_num
        return None
    
    def _parse_count(self, query: str) -> Optional[int]:
        """Extract count (e.g., "for 10 times")"""
        match = re.search(r'for\s+(\d+)\s+times?', query)
        if match:
            return int(match.group(1))
        return None
    
    def _parse_until_date(self, query: str, start_date: datetime) -> Optional[datetime]:
        """Parse until date from query"""
        # Simple patterns: "until December 31", "until 2024-12-31"
        until_patterns = [
            r'until\s+(\d{4}-\d{2}-\d{2})',
            r'until\s+([A-Za-z]+\s+\d{1,2})',
            r'through\s+(\d{4}-\d{2}-\d{2})',
        ]
        
        for pattern in until_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip()
                try:
                    # Try ISO format first
                    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                        return datetime.fromisoformat(date_str)
                    # Try dateutil if available
                    try:
                        from dateutil import parser as dateutil_parser
                        return dateutil_parser.parse(date_str, default=start_date)
                    except ImportError:
                        pass
                except Exception as e:
                    logger.debug(f"Failed to parse until date '{date_str}': {e}")
        
        return None
    
    def calculate_next_occurrence(
        self,
        recurrence: Dict[str, Any],
        last_occurrence: datetime
    ) -> Optional[datetime]:
        """
        Calculate next occurrence based on recurrence pattern
        
        Args:
            recurrence: Recurrence dictionary from parse_recurrence
            last_occurrence: Last occurrence date
            
        Returns:
            Next occurrence datetime or None
        """
        frequency = recurrence.get('frequency')
        interval = recurrence.get('interval', 1)
        day_of_week = recurrence.get('day_of_week')
        until_date = recurrence.get('until_date')
        
        if until_date:
            until_dt = parse_task_datetime(until_date)
            if until_dt and last_occurrence >= until_dt:
                return None
        
        next_date = last_occurrence
        
        if frequency == 'DAILY':
            next_date = last_occurrence + timedelta(days=interval)
        elif frequency == 'WEEKLY':
            if day_of_week is not None:
                # Find next occurrence of specific day
                days_ahead = day_of_week - last_occurrence.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                next_date = last_occurrence + timedelta(days=days_ahead)
            else:
                next_date = last_occurrence + timedelta(weeks=interval)
        elif frequency == 'MONTHLY':
            # Simple monthly: add 1 month
            try:
                if last_occurrence.month == 12:
                    next_date = last_occurrence.replace(year=last_occurrence.year + 1, month=1)
                else:
                    next_date = last_occurrence.replace(month=last_occurrence.month + 1)
            except ValueError:
                # Handle edge cases (e.g., Jan 31 -> Feb 28)
                next_date = last_occurrence + timedelta(days=30)
        elif frequency == 'YEARLY':
            try:
                next_date = last_occurrence.replace(year=last_occurrence.year + 1)
            except ValueError:
                next_date = last_occurrence + timedelta(days=365)
        
        # Check count limit
        count = recurrence.get('count')
        if count:
            # This would need to track occurrences, simplified here
            pass
        
        return next_date







