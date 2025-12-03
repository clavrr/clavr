"""
Core business logic modules

Clean architecture with Google API clients and credential management.
All deprecated classes have been removed (v3.0.0).
"""

from .calendar.google_client import GoogleCalendarClient
from .email.google_client import GoogleGmailClient

__all__ = [
    'GoogleCalendarClient',
    'GoogleGmailClient',
]

