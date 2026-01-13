"""
Memory System Constants

Configuration constants for short-term and long-term memory management.
No hardcoded values - all configuration centralized here.

Version: 1.0.0
Last Updated: 2025-01-21
"""
from datetime import timedelta

# Short-Term Memory (Session Memory) Configuration
SESSION_TTL_HOURS = 24  # Time-to-live for Session nodes (auto-cleanup after 24 hours)
SESSION_MESSAGE_LIMIT = 5  # Number of recent messages to retrieve (last 3-5 turns)
SESSION_MESSAGE_MAX_LIMIT = 20  # Maximum messages to retrieve if needed

# Long-Term Memory (Personalization) Configuration
USER_PREFERENCE_KEYS = [
    'preferred_calendar',
    'time_zone',
    'preferred_scheduling_time',
    'notification_preferences',
    'default_tool_preferences'
]

# Goal Management Configuration
GOAL_STATUS_ACTIVE = 'active'
GOAL_STATUS_COMPLETED = 'completed'
GOAL_STATUS_ARCHIVED = 'archived'
GOAL_PRIORITY_HIGH = 'high'
GOAL_PRIORITY_MEDIUM = 'medium'
GOAL_PRIORITY_LOW = 'low'

# Memory Retrieval Configuration
MEMORY_RETRIEVAL_TIMEOUT_SECONDS = 5.0  # Timeout for memory retrieval operations
MEMORY_CACHE_TTL_SECONDS = 300  # Cache TTL for memory queries (5 minutes)

# Context Construction Configuration
CONTEXT_FORMAT_XML = 'xml'  # Format memory context as XML blocks
CONTEXT_FORMAT_JSON = 'json'  # Format memory context as JSON blocks
DEFAULT_CONTEXT_FORMAT = CONTEXT_FORMAT_XML

# Memory Integration Points
MEMORY_PRE_PROMPT_INJECTION = True  # Enable pre-prompt memory injection
MEMORY_POST_EXECUTION_STORAGE = True  # Enable post-execution memory storage

# Error Handling
MEMORY_FALLBACK_ON_ERROR = True  # Fallback gracefully if memory operations fail
MEMORY_LOG_ERRORS = True  # Log memory operation errors

# Intent Detection Patterns (Fallback)
INTENT_KEYWORDS = {
    "email": ["email", "mail", "inbox", "send", "reply"],
    "tasks": ["task", "todo", "action", "remind", "list"],
    "calendar": ["calendar", "meeting", "schedule", "event", "book"],
    "multi_step": [" and ", " then ", " after ", " also ", " plus "]
}

# Pattern Complexity Thresholds
COMPLEXITY_THRESHOLDS = {
    "high": 0.8,
    "medium": 0.5,
    "low": 0.2
}

# Similarity Thresholds
SIMILARITY_THRESHOLD_HIGH = 0.7
SIMILARITY_THRESHOLD_MEDIUM = 0.5
SIMILARITY_THRESHOLD_LOW = 0.3

