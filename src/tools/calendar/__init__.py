"""
Calendar tool package - modular calendar operations with smart NLP

This package provides a refactored, maintainable structure for calendar operations:
- actions.py: Event CRUD operations (create, update, delete)
- search.py: Event search and listing
- availability.py: Free time finding, conflict detection, availability checks
- analytics.py: Calendar analytics and insights
- smart_parser.py: Natural language query parsing
- orchestrator.py: Complex multi-step operation handling
"""

from .actions import CalendarActions
from .search import CalendarSearch
from .availability import CalendarAvailability
from .analytics import CalendarAnalytics
from .smart_parser import SmartCalendarParser
from .orchestrator import CalendarOrchestrator
from .formatting_handlers import CalendarFormattingHandlers

__all__ = [
    'CalendarActions',
    'CalendarSearch',
    'CalendarAvailability',
    'CalendarAnalytics',
    'SmartCalendarParser',
    'CalendarOrchestrator',
    'CalendarFormattingHandlers',
]
