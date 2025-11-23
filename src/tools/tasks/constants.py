"""
Constants and Configuration for Task Tool

This module contains all configuration constants, default values,
and reusable configurations for the task management system.
"""

# Default task values
DEFAULT_PRIORITY = "medium"
DEFAULT_STATUS = "pending"
DEFAULT_ANALYTICS_DAYS = 30
DEFAULT_REMINDER_DAYS = 7  # Default days for reminder lookups
DEFAULT_DAYS_AHEAD = 7  # Default days ahead for task summaries
DEFAULT_DURATION_MINUTES = 60  # Default duration for scheduled task time
DEFAULT_ESTIMATED_HOURS = 1.0  # Default estimated hours for tasks

# Priority levels (ordered by urgency)
PRIORITY_LEVELS = ["low", "medium", "high", "critical"]

# Valid task statuses
VALID_STATUSES = ["pending", "in_progress", "completed", "cancelled"]

# Priority markers for display
PRIORITY_MARKERS = {
    'critical': '[!!!]',
    'high': '[!!]',
    'medium': '[!]',
    'low': '[-]',
}

# Status markers for display
STATUS_MARKERS = {
    'completed': '[X]',
    'in_progress': '[~]',
    'pending': '[ ]',
    'cancelled': '[/]',
}

# Task categories
DEFAULT_CATEGORIES = [
    'work',
    'personal',
    'health',
    'finance',
    'education',
    'meeting',
    'errands',
    'home',
]

# AI prompt templates
AI_TASK_EXTRACTION_PROMPT = """You are an expert task manager. Extract actionable tasks from emails.
For each task, identify:
1. Clear task description
2. Priority level (low/medium/high/critical)
3. Due date if mentioned
4. Any relevant tags or categories

Return tasks in this format:
TASK: [description]
PRIORITY: [priority]
DUE: [date if mentioned]
TAGS: [comma-separated tags]
---
"""

AI_TEXT_EXTRACTION_PROMPT = """You are an expert at identifying actionable tasks in text.
Extract clear, specific action items with these details:
- Task description (clear and actionable)
- Priority (low/medium/high/critical) based on urgency indicators
- Due date if mentioned (relative dates like "by Friday" or "next week")
- Any tags or categories

Format each task as:
TASK: [clear description]
PRIORITY: [low/medium/high/critical]
DUE: [date/deadline if mentioned, or "none"]
CATEGORY: [category if apparent]
---
"""

AI_ENHANCEMENT_PROMPT = """You are a task management expert. Analyze task descriptions and suggest:
1. Appropriate category (work, personal, health, finance, etc.)
2. Priority level (low/medium/high/critical)
3. Relevant tags (3-5 keywords)
4. Estimated hours to complete
5. Suggested subtasks if the task is complex
6. Helpful notes or tips

Format response as:
CATEGORY: [category]
PRIORITY: [priority]
TAGS: [tag1, tag2, tag3]
ESTIMATED_HOURS: [number]
SUBTASKS: [subtask1 | subtask2 | subtask3]
NOTES: [helpful tips or context]"""

# Urgency keywords for auto-prioritization
URGENCY_KEYWORDS = {
    'critical': ['urgent', 'asap', 'critical', 'emergency', 'immediately'],
    'high': ['important', 'high priority', 'soon', 'deadline'],
    'low': ['fyi', 'low priority', 'whenever', 'optional'],
}

# Period mappings for accomplishment summaries
PERIOD_DAYS = {
    'day': 1,
    'week': 7,
    'month': 30,
    'quarter': 90,
    'year': 365,
}

# Email integration constants
EMAIL_BODY_PREVIEW_LENGTH = 100  # Length for email body preview snippets
EMAIL_BODY_MAX_LENGTH_FOR_PROMPT = 1000  # Max body length for AI prompts

# LLM configuration constants
LLM_TEMPERATURE = 0.7  # Default temperature for LLM calls
LLM_TEMPERATURE_LOW = 0.1  # Low temperature for classification tasks
LLM_TIMEOUT_SECONDS = 30  # Timeout for LLM calls in seconds

# Task display limits
MAX_TASKS_FOR_LLM_CONTEXT = 10  # Maximum tasks to include in LLM prompt
MAX_TASKS_FOR_DISPLAY = 20  # Maximum tasks to display in fallback response
MAX_COMPLETED_TASKS_FOR_CONTEXT = 1000  # Maximum completed tasks to fetch for context

# Task data limits
MAX_BODY_LENGTH_FOR_PROMPT = 4000  # Maximum body length for LLM prompts
MIN_BODY_LENGTH_THRESHOLD = 200  # Minimum body length to consider fetching full content
PREVIEW_LENGTH_FOR_EMAIL = 500  # Preview length for email content in task context
