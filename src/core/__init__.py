"""
Core business logic modules

Clean architecture with Google API clients and credential management.

Exports:
- Google API Clients: Calendar, Gmail, Tasks, Keep, Drive
- Credential Management: CredentialProvider, CredentialFactory
- Base Class: BaseGoogleAPIClient
"""

# Google API Clients
from .calendar.google_client import GoogleCalendarClient
from .email.google_client import GoogleGmailClient
from .tasks.google_client import GoogleTasksClient
from .keep.google_client import GoogleKeepClient
from .drive.google_client import GoogleDriveClient

# Base class for extending
from .base.google_api_client import BaseGoogleAPIClient

# Credential management
from .credential_provider import CredentialProvider, CredentialFactory

__all__ = [
    # API Clients
    'GoogleCalendarClient',
    'GoogleGmailClient',
    'GoogleTasksClient',
    'GoogleKeepClient',
    'GoogleDriveClient',
    # Base
    'BaseGoogleAPIClient',
    # Credentials
    'CredentialProvider',
    'CredentialFactory',
]



