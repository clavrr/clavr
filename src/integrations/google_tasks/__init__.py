"""
Google Tasks Integration Module

Provides Google Tasks API integration for task operations.
Integrates with Google Tasks API through the TaskService business logic layer.

Architecture:
    TaskTool → TaskService → Tasks API
    
The service layer provides:
- Clean business logic interfaces
- Centralized error handling
- Shared code between tools and workers
- Better testability
"""

# Lazy imports to avoid circular dependencies
def __getattr__(name):
    if name == 'TaskService':
        from .service import TaskService
        return TaskService
    elif name == 'TaskServiceException':
        from .exceptions import TaskServiceException
        return TaskServiceException
    elif name == 'TaskNotFoundException':
        from .exceptions import TaskNotFoundException
        return TaskNotFoundException
    elif name == 'TaskValidationException':
        from .exceptions import TaskValidationException
        return TaskValidationException
    elif name == 'TaskIntegrationException':
        from .exceptions import TaskIntegrationException
        return TaskIntegrationException
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'TaskService',
    'TaskServiceException',
    'TaskNotFoundException',
    'TaskValidationException',
    'TaskIntegrationException',
]
