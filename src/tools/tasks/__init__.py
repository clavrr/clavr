"""
Tasks Package

Modular task management system with email integration, calendar integration,
AI features, and comprehensive CRUD operations.
"""
from .constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    DEFAULT_ANALYTICS_DAYS,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_ESTIMATED_HOURS,
    PRIORITY_MARKERS,
    STATUS_MARKERS,
    AI_TASK_EXTRACTION_PROMPT,
    AI_TEXT_EXTRACTION_PROMPT,
    AI_ENHANCEMENT_PROMPT,
    EMAIL_BODY_PREVIEW_LENGTH,
    EMAIL_BODY_MAX_LENGTH_FOR_PROMPT,
    URGENCY_KEYWORDS,
    PERIOD_DAYS
)

from .core_operations import CoreOperations
from .email_integration import EmailIntegration
from .calendar_integration import CalendarIntegration
from .ai_features import AIFeatures
from .summarize_integration import SummarizeIntegration
from .utils import TaskUtils

__all__ = [
    # Constants
    'DEFAULT_PRIORITY',
    'DEFAULT_STATUS',
    'DEFAULT_ANALYTICS_DAYS',
    'DEFAULT_REMINDER_DAYS',
    'DEFAULT_DAYS_AHEAD',
    'DEFAULT_DURATION_MINUTES',
    'DEFAULT_ESTIMATED_HOURS',
    'PRIORITY_MARKERS',
    'STATUS_MARKERS',
    'AI_TASK_EXTRACTION_PROMPT',
    'AI_TEXT_EXTRACTION_PROMPT',
    'AI_ENHANCEMENT_PROMPT',
    'EMAIL_BODY_PREVIEW_LENGTH',
    'EMAIL_BODY_MAX_LENGTH_FOR_PROMPT',
    'URGENCY_KEYWORDS',
    'PERIOD_DAYS',
    
    # Classes
    'CoreOperations',
    'EmailIntegration',
    'CalendarIntegration',
    'AIFeatures',
    'SummarizeIntegration',
    'TaskUtils',
]
