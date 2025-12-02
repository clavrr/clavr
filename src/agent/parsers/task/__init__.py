"""
Task Parser Modular Handlers

This package contains the modular handler components for the TaskParser:
- semantic_matcher: TaskSemanticPatternMatcher for semantic intent matching
- learning_system: TaskLearningSystem for learning from corrections
- classification_handlers: TaskClassificationHandlers for intent detection
- action_handlers: TaskActionHandlers for specific task actions  
- analytics_handlers: TaskAnalyticsHandlers for task analysis and insights
- creation_handlers: TaskCreationHandlers for task creation and parsing
- management_handlers: TaskManagementHandlers for task operations
- query_processing_handlers: TaskQueryProcessingHandlers for query execution
- utility_handlers: TaskUtilityHandlers for common utilities

These modules reduce the size of task_parser.py from 3,285 lines to a manageable 
delegating interface, improving maintainability and code organization.

Note: Imports are lazy to avoid loading heavy dependencies at module import time.
Import the classes directly from their modules:

    from src.agent.parsers.task.classification_handlers import TaskClassificationHandlers
    from src.agent.parsers.task.creation_handlers import TaskCreationHandlers
    etc.
"""

# No imports at module level to keep imports fast
# Classes can be imported directly from their respective modules

# Export constants for easy access
from .constants import (
    TaskParserConfig,
    TaskActionTypes,
    TaskEntityTypes,
    TaskPriorities,
    TaskStatuses,
    TaskFrequencies,
    get_action_validation_rules
)

__all__ = [
    'semantic_matcher', 
    'learning_system',
    'classification_handlers',
    'action_handlers', 
    'analytics_handlers',
    'creation_handlers',
    'management_handlers',
    'query_processing_handlers',
    'utility_handlers',
    # Constants
    'TaskParserConfig',
    'TaskActionTypes',
    'TaskEntityTypes',
    'TaskPriorities',
    'TaskStatuses',
    'TaskFrequencies',
    'get_action_validation_rules'
]
