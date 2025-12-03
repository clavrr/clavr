"""
Gmail Integration Module

Provides Gmail API integration for email operations.
Integrates with Google Gmail API through the EmailService business logic layer.

Architecture:
    EmailTool → EmailService → Gmail API
    
The service layer provides:
- Clean business logic interfaces
- Centralized error handling
- Shared code between tools and workers
- Better testability
"""

# Lazy imports to avoid circular dependencies
def __getattr__(name):
    if name == 'EmailService':
        from .service import EmailService
        return EmailService
    elif name == 'GmailWatchService':
        from .watch_service import GmailWatchService
        return GmailWatchService
    elif name == 'GmailWatchHelper':
        from .watch_helper import GmailWatchHelper
        return GmailWatchHelper
    elif name == 'EmailServiceException':
        from .exceptions import EmailServiceException
        return EmailServiceException
    elif name == 'EmailNotFoundException':
        from .exceptions import EmailNotFoundException
        return EmailNotFoundException
    elif name == 'EmailSendException':
        from .exceptions import EmailSendException
        return EmailSendException
    elif name == 'EmailSearchException':
        from .exceptions import EmailSearchException
        return EmailSearchException
    elif name == 'EmailIntegrationException':
        from .exceptions import EmailIntegrationException
        return EmailIntegrationException
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'EmailService',
    'GmailWatchService',
    'GmailWatchHelper',
    'EmailServiceException',
    'EmailNotFoundException',
    'EmailSendException',
    'EmailSearchException',
    'EmailIntegrationException',
]
