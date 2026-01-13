"""
Calendar operations

Main exports:
- GoogleCalendarClient: Full-featured Google Calendar API client
- RecurrenceParser: Parse natural language recurrence patterns
- TemplateStorage: Manage meeting presets (PostgreSQL-backed)
- Utility functions: See utils.py for timezone, parsing, and formatting helpers
"""

from .google_client import GoogleCalendarClient
from .recurrence_parser import RecurrenceParser
from .presets import TemplateStorage

__all__ = [
    'GoogleCalendarClient',
    'RecurrenceParser',
    'TemplateStorage',  # PostgreSQL-backed
]

