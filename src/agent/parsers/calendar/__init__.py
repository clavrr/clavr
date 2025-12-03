"""
Calendar Parser Submodule - Modular calendar query parsing

This module provides lazy loading for calendar parser components:
- Semantic pattern matching
- Learning system
- Action handlers
- Event management
- Conversational responses
"""

# Lazy loading - modules imported when needed
__all__ = [
    'CalendarSemanticPatternMatcher',
    'CalendarLearningSystem',
    'CalendarEventHandlers',
    'CalendarListSearchHandlers',
    'CalendarActionClassifiers',
    'CalendarUtilityHandlers',
    'CalendarAdvancedHandlers',
]

def __getattr__(name):
    """Lazy load calendar modules on demand"""
    if name == "CalendarSemanticPatternMatcher":
        from .semantic_matcher import CalendarSemanticPatternMatcher
        return CalendarSemanticPatternMatcher
    elif name == "CalendarLearningSystem":
        from .learning_system import CalendarLearningSystem
        return CalendarLearningSystem
    elif name == "CalendarEventHandlers":
        from .event_handlers import CalendarEventHandlers
        return CalendarEventHandlers
    elif name == "CalendarListSearchHandlers":
        from .list_search_handlers import CalendarListSearchHandlers
        return CalendarListSearchHandlers
    elif name == "CalendarActionClassifiers":
        from .action_classifiers import CalendarActionClassifiers
        return CalendarActionClassifiers
    elif name == "CalendarUtilityHandlers":
        from .utility_handlers import CalendarUtilityHandlers
        return CalendarUtilityHandlers
    elif name == "CalendarAdvancedHandlers":
        from .advanced_handlers import CalendarAdvancedHandlers
        return CalendarAdvancedHandlers
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
