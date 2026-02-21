"""
Constants for Agents
"""

# Model Names
DEFAULT_FAST_MODEL = "gemini-3-flash-preview"
DEFAULT_REASONING_MODEL = "gemini-2.0-flash-thinking-exp-1219"

# Agent Names
AGENT_NAME_EMAIL = "EmailAgent"
AGENT_NAME_CALENDAR = "CalendarAgent"
AGENT_NAME_TASKS = "TaskAgent"
AGENT_NAME_NOTION = "NotionAgent"
AGENT_NAME_RESEARCH = "ResearchAgent"
AGENT_NAME_KEEP = "KeepAgent"
AGENT_NAME_FINANCE = "FinanceAgent"
AGENT_NAME_SUPERVISOR = "SupervisorAgent"
AGENT_NAME_CLASSIFIER = "ClassifierAgent"

# Memory Categories
MEMORY_CATEGORIES = ['preference', 'contact', 'work', 'general']

# Tool Aliases
TOOL_ALIASES_EMAIL = ["email", "gmail", "mail"]
TOOL_ALIASES_CALENDAR = ["calendar", "google_calendar", "gcal"]
TOOL_ALIASES_TASKS = ["task", "tasks", "google_tasks", "todo"]
TOOL_ALIASES_NOTION = ["notion"]
TOOL_ALIASES_KEEP = ["keep", "google_keep", "notes"]
TOOL_ALIASES_DRIVE = ["drive", "google_drive", "gdrive", "files"]
TOOL_ALIASES_FINANCE = ["finance", "spending", "receipts", "expenses", "money", "purchase"]
TOOL_ALIASES_ASANA = ["asana", "asana_tool"]


# Common Errors
ERROR_TOOL_NOT_AVAILABLE = "I'm sorry, that tool is currently unavailable."
ERROR_MISSING_PARAMS = "I didn't capture all the details needed. Could you please provide {missing}?"

# Intent Keywords (Centralized)
# Used by Supervisor, Classifier, and Agents for consistent routing
INTENT_KEYWORDS = {
    'email': {
        'send': ['send', 'compose', 'write', 'draft', 'reply', 'forward'],
        'manage': ['delete', 'archive', 'mark', 'trash', 'spam', 'label'],
        'search': ['search', 'find', 'show', 'list', 'check', 'get', 'read', 'inbox']
    },
    'calendar': {
        'schedule': ['book', 'set up', 'new meeting', 'new event', 'create event', 'schedule', 'create', 'add'],
        'update': ['reschedule', 'move', 'change', 'update', 'cancel', 'edit'],
        'list': ['agenda', 'calendar', 'show', 'list', 'what do i have', 'meetings', 'events', 'meeting', 'event', 'summarize', 'my schedule', 'upcoming', 'today', 'tomorrow', 'this week'],
        'availability': ['free', 'busy', 'available', 'gap', 'open', 'different time', 'another time', 'find time', 'find a slot', 'when can']
    },
    'tasks': {
        'create': ['create', 'add', 'make', 'set', 'remind me', 'new task', 'new todo', 'buy'],
        'complete': ['complete', 'finish', 'check off', 'done', 'mark complete'],
        'list': ['list', 'show', 'tasks', 'todos', 'outstanding', 'pending', 'summarize', 'get', 'what are']
    },
    'notion': {
        'search': ['search notion', 'find page', 'lookup'],
        'create': ['create page', 'new page', 'write note']
    },
    'research': {
        'deep': ['research', 'analyze', 'investigate', 'deep dive', 'comprehensive', 'study']
    },
    'notes': {
        'quick': ['note', 'jot', 'remember', 'write down', 'grocery', 'shopping']
    },
    'drive': {
        'search': ['drive', 'google drive', 'search drive', 'find file', 'google doc', 'spreadsheet', 'presentation', 'slide', 'pdf'],
        'list': ['recent files', 'my files', 'show drive']
    },
    'finance': {
        'aggregate': ['how much', 'total', 'spend', 'spending', 'expense', 'cost'],
        'lookup': ['last purchase', 'recent transaction', 'last receipt', 'latest purchase']
    },
    'asana': {
        'create': ['create', 'add', 'new', 'make', 'schedule'],
        'complete': ['complete', 'done', 'finish', 'mark'],
        'list': ['list', 'show', 'get', 'what', 'display'],
        'search': ['search', 'find', 'look for'],
        'delete': ['delete', 'remove', 'trash'],
        'projects': ['project', 'projects', 'boards']
    }
}
ERROR_LLM_NOT_AVAILABLE = "Error: Language model not available."

# Response Formatting Keywords (moved from SynthesisConfig)
URGENT_KEYWORDS = ["urgent", "asap", "emergency", "immediate", "critical"]
TIME_SENSITIVE_KEYWORDS = ["today", "tonight", "morning", "afternoon", "evening", "now", "soon"]
HIGH_PRIORITY_KEYWORDS = ["high", "important", "top", "priority"]

# Schema Validation Constants (moved from schemas.py)
VALID_DOMAINS = ["email", "calendar", "task", "tasks", "asana", "notion", "notes", "research", "drive", "general"]
VALID_ACTIONS = ["search", "list", "create", "update", "delete", "send", "schedule", "complete", "summarize", "manage"]

# Formatting Limits
MAX_URGENT_ITEMS = 3
MAX_TIME_SENSITIVE_ITEMS = 5
MAX_HIGH_PRIORITY_ITEMS = 5
MAX_STANDARD_ITEMS = 10
EXTRA_ITEMS_THRESHOLD = 12

# Centralized Error Messages for Agents
ERROR_NO_TITLE = "I couldn't identify the title. Please rephrase."
ERROR_NO_EVENT_TITLE = "I couldn't identify the event title. Please rephrase."
ERROR_NO_RECIPIENT = "I need a recipient to send the email to."
ERROR_NO_PAGE_TITLE = "I need a title to create a new page."
ERROR_AMBIGUOUS_UPDATE = "I'm not sure which {item_type} you want to update."
ERROR_AMBIGUOUS_COMPLETE = "I'm not sure which task you want to complete."
ERROR_AMBIGUOUS_DELETE = "I'm not sure which note you want to delete."
ERROR_RESEARCH_TIMEOUT = (
    "The research request is taking longer than expected. "
    "Please try a more specific query or break it into smaller parts."
)
ERROR_RESEARCH_UNAVAILABLE = "I'm unable to perform research at this time. Please try again later."

# Domain-to-Tool Routing (centralized - was duplicated in classifier.py and supervisor.py)
DOMAIN_TOOL_ROUTING = {
    "email": "email_tool",
    "calendar": "calendar_tool",
    "task": "task_tool",
    "tasks": "task_tool",
    "asana": "asana_tool",
    "notes": "keep_tool",
    'notion': "notion_tool",
    'research': "research_tool",
    'drive': "drive_agent",
    'finance': "finance_tool",
    'general': "supervisor"
}

# Research Agent Configuration
RESEARCH_DEFAULT_TIMEOUT = 300
RESEARCH_POLL_INTERVAL = 10

# LLM Configuration Defaults
DEFAULT_LLM_MAX_TOKENS = 2000
DEFAULT_LLM_TEMPERATURE = 0.0
SUPERVISOR_LLM_MAX_TOKENS = 8192  # Supervisor needs more tokens for planning and massive summarization
SUPERVISOR_LLM_TEMPERATURE = 0.0
INTENT_ANALYZER_TEMPERATURE = 0.1  # Low temperature for consistent JSON output
MIN_QUERY_LENGTH = 3  # Minimum query length before using LLM analysis
SAFETY_LLM_TEMPERATURE = 0.0 # Deterministic for security checks

# Caching Configuration
CACHE_CLEANUP_THRESHOLD = 100  # Trigger cache cleanup when size exceeds this
MAX_INTERACTION_HISTORY = 100  # Maximum interaction history per user
MAX_CACHED_ITEMS_DISPLAY = 3   # Max items to show in summary views

# Keyword Configuration
MAX_KEYWORDS_PER_DOMAIN = 15   # Maximum keywords extracted per domain

# Error Messages (continued)
ERROR_GENERAL_UNAVAILABLE = "I am a domain specialist agent. I can help you with Email, Tasks, Calendar, Notion, and Research."
ERROR_GENERAL_FAILURE = "I'm sorry, I encountered an error responding to that."


# Sentiment Analysis Keywords (from nlp_processor.py - now centralized)

CONFUSION_KEYWORDS = [
    "confused", "unsure", "don't understand", "help", "what do you mean", "???"
]
POSITIVE_KEYWORDS = [
    "please", "thanks", "thank you", "great", "good", "love", "liked"
]
NEGATIVE_KEYWORDS = [
    "bad", "wrong", "fail", "broken", "hate", "annoying", "slow", "stupid"
]

# Technical Terms (for complexity analysis)
TECHNICAL_TERMS = [
    'api', 'sync', 'cache', 'database', 'query', 'filter', 'parse', 'json', 'schema'
]

# ============================================================================
# Calendar Recurrence Patterns (from common.py - now centralized)
# ============================================================================
RECURRENCE_PATTERNS = [
    'monthly', 'weekly', 'daily', 'yearly', 'recurring', 'recurrence',
    'every monday', 'every tuesday', 'every wednesday', 'every thursday',
    'every friday', 'every saturday', 'every sunday',
    'every day', 'every week', 'every month', 'every year',
    'first friday', 'last monday', 'second tuesday', 'third wednesday',
    'each month', 'each week', 'each day'
]

DAYS_OF_WEEK = [
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
]

# ============================================================================
# Agent-Specific Action Keywords (from domain agents - now centralized)
# ============================================================================

# Keep Agent Actions
KEEP_CREATE_KEYWORDS = ['create', 'add', 'new', 'write', 'make']
KEEP_DELETE_KEYWORDS = ['delete', 'remove', 'trash']
KEEP_SEARCH_KEYWORDS = ['search', 'find', 'look for']

# Notion Agent Actions
NOTION_UPDATE_KEYWORDS = ['update', 'edit', 'modify', 'change page']

# ============================================================================
# Domain Emojis (from response_personalizer.py - now centralized)
# ============================================================================
DOMAIN_EMOJIS = {
    'email': '📧', 'mails': '📧', 'inbox': '📧',
    'calendar': '📅', 'schedule': '📅', 'event': '📅',
    'task': '✓', 'todo': '✓', 'tasks': '✓',
    'meeting': '👥', 'meetings': '👥',
    'reminder': '🔔', 'reminders': '🔔',
    'urgent': '⚠️', 'asap': '⚠️', 'critical': '⚠️',
    'important': '⭐', 'priority': '⭐',
    'error': '❌', 'failed': '❌', 'failure': '❌',
    'success': '✅', 'done': '✅', 'completed': '✅', 'complete': '✅',
    'note': '📝', 'notes': '📝',
    'search': '🔍', 'find': '🔍',
}

# ============================================================================
# Supervisor Configuration & Mappings (New)
# ============================================================================

DOMAIN_DISPLAY_NAMES = {
    'email': 'Gmail',
    'calendar': 'Google Calendar',
    'tasks': 'Tasks',
    'drive': 'Google Drive',
    'keep': 'Google Keep',
    'notes': 'Google Keep',
    'slack': 'Slack',
    'notion': 'Notion',
    'asana': 'Asana'
}

PROVIDER_MAPPINGS = {
    'email': 'gmail',
    'calendar': 'google_calendar',
    'tasks': 'google_tasks',
    'drive': 'google_drive',
    'keep': 'google_keep',
    'notes': 'google_keep',
    # Direct mappings for others
    'slack': 'slack',
    'notion': 'notion',
    'asana': 'asana'
}

DOMAIN_START_MESSAGES = {
    'email': 'Searching your emails...',
    'calendar': 'Checking your calendar...',
    'tasks': 'Looking at your tasks...',
    'notes': 'Checking your notes...',
    'weather': 'Getting weather information...',
    'maps': 'Looking up directions...',
    'notion': 'Searching Notion...',
    'drive': 'Searching Google Drive...',
    'research': 'Starting deep research...',
    'finance': 'Analyzing finance data...'
}

# Common aliases mapping to canonical domain keys
DOMAIN_ALIASES = {
    'gmail': 'email', 
    'mail': 'email',
    'google_calendar': 'calendar', 
    'gcal': 'calendar',
    'google_tasks': 'tasks', 
    'todo': 'tasks',
    'asana': 'tasks',
    'asana_tool': 'tasks',
    'keep': 'notes',
    'google_keep': 'notes',
    'google_drive': 'drive',
    'gdrive': 'drive'
}
