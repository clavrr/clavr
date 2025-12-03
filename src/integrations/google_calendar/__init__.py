"""
Google Calendar Integration Module

Provides Google Calendar API integration for calendar operations.
Integrates with Google Calendar API through the CalendarService business logic layer.

Architecture:
    CalendarTool → CalendarService → Calendar API
    
The service layer provides:
- Clean business logic interfaces
- Centralized error handling
- Shared code between tools and workers
- Better testability
"""

# Lazy imports to avoid circular dependencies
def __getattr__(name):
    if name == 'CalendarService':
        from .service import CalendarService
        return CalendarService
    elif name == 'CalendarServiceException':
        from .exceptions import CalendarServiceException
        return CalendarServiceException
    elif name == 'EventNotFoundException':
        from .exceptions import EventNotFoundException
        return EventNotFoundException
    elif name == 'SchedulingConflictException':
        from .exceptions import SchedulingConflictException
        return SchedulingConflictException
    elif name == 'InvalidTimeRangeException':
        from .exceptions import InvalidTimeRangeException
        return InvalidTimeRangeException
    elif name == 'CalendarIntegrationException':
        from .exceptions import CalendarIntegrationException
        return CalendarIntegrationException
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'CalendarService',
    'CalendarServiceException',
    'EventNotFoundException',
    'SchedulingConflictException',
    'InvalidTimeRangeException',
    'CalendarIntegrationException',
]
