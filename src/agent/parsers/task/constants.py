"""
Task Parser Constants - Centralized configuration for task parsing

This module defines all constants used across the task parser module
to ensure consistency and enable easy configuration changes.

Usage:
    from .constants import TaskParserConfig
    
    limit = TaskParserConfig.DEFAULT_TASK_LIMIT
    confidence_threshold = TaskParserConfig.DEFAULT_CONFIDENCE_THRESHOLD
"""


class TaskParserConfig:
    """Configuration constants for task parser"""
    
    # Confidence thresholds
    DEFAULT_CONFIDENCE_THRESHOLD = 0.6
    LOW_CONFIDENCE_THRESHOLD = 0.5
    HIGH_CONFIDENCE_THRESHOLD = 0.85
    
    # LLM configuration
    LLM_TEMPERATURE = 0.1
    LLM_MAX_TOKENS = 2000
    LLM_MAX_TOKENS_BRIEF = 1500
    LLM_MAX_TOKENS_SUMMARY = 2000
    
    # Task limits
    DEFAULT_TASK_LIMIT = 10
    MAX_TASK_LIMIT = 100
    MIN_TASK_LIMIT = 1
    
    # Learning system configuration
    MAX_CORRECTIONS_STORED = 100
    MAX_SUCCESSFUL_QUERIES_STORED = 50
    SIMILARITY_THRESHOLD_LOW = 0.3
    SIMILARITY_THRESHOLD_HIGH = 0.6
    DEFAULT_SIMILAR_EXAMPLES_LIMIT = 3
    
    # Semantic matching configuration
    DEFAULT_SEMANTIC_THRESHOLD = 0.7
    GEMINI_THRESHOLD_MULTIPLIER = 0.95
    
    # Task validation
    MIN_DESCRIPTION_LENGTH = 2
    MIN_DESCRIPTION_LENGTH_STRICT = 3
    MAX_DESCRIPTION_LENGTH = 500
    
    # Date/time defaults
    DEFAULT_REMINDER_DAYS = 1
    DEFAULT_UPCOMING_DAYS = 7
    DEFAULT_FREQUENCY = "weekly"
    
    # Display limits
    MAX_TASKS_DISPLAY = 10
    MAX_TASKS_PREVIEW = 5
    MAX_TASKS_ANALYSIS = 5
    
    # Organization score calculation
    POINTS_PER_TASK = 3
    MAX_ORGANIZATION_SCORE = 100


class TaskActionTypes:
    """All supported task actions"""
    CREATE = "create"
    LIST = "list"
    COMPLETE = "complete"
    DELETE = "delete"
    SEARCH = "search"
    ANALYZE = "analyze"
    UPDATE = "update"
    PRIORITIZE = "prioritize"
    TEMPLATE = "template"
    RECURRING = "recurring"
    REMINDERS = "reminders"
    OVERDUE = "overdue"
    SUBTASKS = "subtasks"
    BULK = "bulk"
    
    @classmethod
    def all(cls):
        """Get all action types"""
        return [
            cls.CREATE, cls.LIST, cls.COMPLETE, cls.DELETE, cls.SEARCH,
            cls.ANALYZE, cls.UPDATE, cls.PRIORITIZE, cls.TEMPLATE,
            cls.RECURRING, cls.REMINDERS, cls.OVERDUE, cls.SUBTASKS, cls.BULK
        ]


class TaskEntityTypes:
    """Entity types extracted from task queries"""
    DESCRIPTION = "description"
    DUE_DATE = "due_date"
    PRIORITY = "priority"
    CATEGORY = "category"
    PROJECT = "project"
    TAGS = "tags"
    NOTES = "notes"
    REMINDER_DAYS = "reminder_days"
    ESTIMATED_HOURS = "estimated_hours"
    ASSIGNEE = "assignee"
    STATUS = "status"


class TaskPriorities:
    """Task priority levels"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    
    @classmethod
    def all(cls):
        """Get all priority levels"""
        return [cls.HIGH, cls.MEDIUM, cls.LOW]


class TaskStatuses:
    """Task status values"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    
    @classmethod
    def all(cls):
        """Get all status values"""
        return [cls.PENDING, cls.IN_PROGRESS, cls.COMPLETED, cls.CANCELLED]


class TaskFrequencies:
    """Recurring task frequencies"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    WEEKDAYS = "weekdays"
    WEEKENDS = "weekends"
    
    @classmethod
    def all(cls):
        """Get all frequency types"""
        return [
            cls.DAILY, cls.WEEKLY, cls.MONTHLY, cls.YEARLY,
            cls.WEEKDAYS, cls.WEEKENDS
        ]


def get_action_validation_rules(action: str) -> dict:
    """
    Get validation rules for a task action
    
    Args:
        action: Task action type
        
    Returns:
        Dictionary of required and optional parameters
    """
    rules = {
        TaskActionTypes.CREATE: {
            "required": ["description"],
            "optional": ["due_date", "priority", "category", "tags", "notes"]
        },
        TaskActionTypes.COMPLETE: {
            "required": ["task_description"],
            "optional": []
        },
        TaskActionTypes.DELETE: {
            "required": ["task_description"],
            "optional": []
        },
        TaskActionTypes.SEARCH: {
            "required": ["search_terms"],
            "optional": ["limit"]
        },
        TaskActionTypes.LIST: {
            "required": [],
            "optional": ["filter", "limit"]
        },
    }
    
    return rules.get(action, {"required": [], "optional": []})

