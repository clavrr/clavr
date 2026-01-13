"""
Intent Pattern Constants

Centralized pattern definitions for intent detection.
All pattern lists are extracted here for better maintainability.
"""
from typing import List, Dict

# Keyword lists - this is the source of truth
# These are used by intent detection and should be comprehensive
TASK_KEYWORDS = ['task', 'tasks', 'todo', 'todos', 'reminder', 'deadline', 'overdue', 'pending']
CALENDAR_KEYWORDS = ['calendar', 'meeting', 'event', 'events', 'appointment', 'schedule', 'agenda'] 
EMAIL_KEYWORDS = ['email', 'emails', 'message', 'messages', 'inbox', 'unread', 'mail']

# Email Management Patterns (highest priority)
EMAIL_MANAGEMENT_PATTERNS: List[str] = [
    'semantic search', 'search across folders', 'organize emails',
    'bulk delete', 'bulk archive', 'categorize emails', 'email insights',
    'cleanup inbox', 'email cleanup', 'manage emails', 'organize inbox',
    'find similar emails', 'email patterns', 'email analytics',
    'categories dominate', 'dominating categories', 'email categories',
    'what categories', 'category analysis', 'inbox categories',
    'topics', 'common topics', 'most common', 'what topics',
    'response time', 'email response time', 'reply patterns', 'email behavior',
    'email habits', 'email trends', 'response patterns',
    'who have i been emailing', 'most contacts', 'frequent contacts',
    'emailing the most', 'top contacts', 'contact analysis', 'who do i email',
    'email frequency', 'who i email most', 'my contacts',
    'urgent matters', 'urgent emails', 'most urgent', 'priority emails',
    'important emails', 'inbox analysis', 'inbox summary', 'email summary',
    'what matters', 'urgent in my inbox', 'priority matters', 'inbox priority',
    'urgent items', 'important items', 'urgent messages', 'important messages',
    'inbox urgent', 'urgent inbox', 'priority inbox', 'inbox important'
]

# Task-specific Patterns
TASK_QUESTION_PATTERNS: List[str] = [
    'what tasks', 'tasks do i have', 'tasks have i', 'my tasks', 'which tasks',
    "what's on my tasks", "what's on my task", "on my tasks", "on my task",
    "tasks today", "task today", "tasks for today", "task for today",
    "my tasks today", "my task today"
]

TASK_CREATE_PATTERNS: List[str] = [
    'create task', 'add task', 'new task', 'task to',
    'todo', 'reminder', 'set up task',
    'make task', 'add todo', 'create todo', 'schedule a task',
    'schedule task', 'task about', 'task for',
    'deadline task', 'task deadline', 'create deadline',
    'add deadline', 'deadline reminder', 'deadline todo',
    # Natural phrasing patterns (implicit task creation)
    'please add', 'add this to', 'add to my list',
    'add this', 'add a', 'put on my list', 'put this on',
    'add it to', 'make it high priority', 'high priority',
    'catching up with', 'need to', 'remind me to',
    'remember to', 'don\'t forget to', 'gotta',
]

TASK_LIST_PATTERNS: List[str] = [
    'show tasks', 'list tasks', 'my tasks', 'task list',
    'what tasks', 'which tasks', 'all tasks', 'get tasks',
    'display tasks', 'view tasks', 'task overview',
    'tasks do i have', 'tasks have i',
    "what's on my tasks", "what's on my task", "on my tasks", "on my task",
    "tasks today", "task today", "tasks for today", "task for today"
]

TASK_ANALYSIS_PATTERNS: List[str] = [
    'overdue tasks', 'tasks overdue', 'which tasks are overdue',
    'pending tasks', 'completed tasks', 'task status',
    'task analysis', 'task summary', 'task report',
    'how many tasks', 'count tasks', 'number of tasks',
    'total tasks', 'total number of tasks', 'task count',
    'tasks due today', 'tasks due tomorrow', 'due today', 'due tomorrow',
    'how many tasks due', 'tasks i have due'
]

TASK_COMPLETION_PATTERNS: List[str] = [
    'mark as complete', 'mark complete', 'mark done',
    'complete', 'done', 'finish'
]

# Calendar-specific Patterns
CALENDAR_QUESTION_PATTERNS: List[str] = [
    'what meetings', 'meetings do i have', 'meetings have i', 'my meetings', 'which meetings',
    'what calendar events', 'calendar events do i have', 'my calendar events', 'which calendar events',
    'what events', 'events do i have', 'events have i', 'my events', 'which events',
    'calendar events', 'calendar tomorrow', 'events tomorrow', 'calendar today', 'events today',
    'what do i have on my calendar', 'what do i have on calendar', 'do i have on my calendar',
    'what do i have today', 'what do i have tomorrow', 'what do i have this week',
    "what's on my calendar", "what's on calendar", 'whats on my calendar', 'whats on calendar',
    "what do i have on my calendar right now", "what's on my calendar right now", 'what is on my calendar right now',
    'what do i have currently', 'what do i have now', "what's on my calendar now", 'what is on my calendar now',
    'when is my meeting', 'when is my', 'when are my meetings', 'when are my',
    'when is the meeting', 'when is the', 'when are the meetings', 'when are the',
    'what time is my meeting', 'what time is my', 'what time are my meetings', 'what time are my',
    'what time is the meeting', 'what time is the', 'what time are the meetings', 'what time are the'
]

CALENDAR_PATTERNS: List[str] = [
    'schedule meeting', 'book meeting', 'create event',
    'calendar event', 'add to calendar', 'calendar schedule',
    'meeting schedule', 'appointment', 'calendar list',
    'show calendar', 'my calendar', 'schedule meeting',
    'schedule appointment', 'schedule event', 'meeting',
    'meeting invitations', 'meeting invitation', 'invitations',
    'accept meeting', 'decline meeting', 'respond to meeting',
    'meeting requests', 'calendar invitations', 'show meetings',
    'list meetings', 'upcoming meetings', 'meeting calendar',
    'what meetings', 'meetings do i have', 'meetings this week'
]

# Email Patterns
EMAIL_PATTERNS: List[str] = [
    'send email', 'send an email', 'compose email', 'write email',
    'draft email', 'email send', 'email to', 'send to',
    'reply to', 'reply email', 'forward email', 'email list',
    'show emails', 'my emails', 'recent emails', 'email search',
    'list emails', 'check emails', 'read emails',
    'unread emails', 'unread', 'left unread', 'oldest unread',
    'which emails', 'emails have i left', 'longest unread',
    'oldest emails', "emails i haven't read", "haven't read",
    'show me all emails', 'find emails', 'search for emails',
    'emails about', 'emails from', 'emails containing',
    'emails with', 'emails regarding', 'emails related to',
    'new emails', 'new email', 'do i have', 'have i received',
    'check my emails', 'check my email', 'any new emails',
    'any emails today', 'emails today', 'new messages today'
]

# Analysis Patterns
ANALYSIS_PATTERNS: List[str] = [
    'analyze email', 'email analysis', 'sentiment analysis',
    'priority analysis', 'email priority', 'analyze message'
]

# Compose Patterns
COMPOSE_PATTERNS: List[str] = [
    'compose email', 'draft email', 'write email',
    'create email', 'email composition', 'send an email'
]

COMPOSE_EXCLUDE_WORDS: List[str] = [
    'do i have', 'show me', 'list', 'find', 'search', 'get', 'check', 'what', 'any new'
]

# Summary Patterns
SUMMARY_PATTERNS: List[str] = [
    'summarize email', 'email summary', 'key points',
    'email summary', 'summarize message', 'brief summary'
]

# Fallback Keywords
FALLBACK_KEYWORDS: Dict[str, List[str]] = {
    'task': ['task', 'todo', 'reminder', 'deadline'],
    'analysis': ['analyze', 'sentiment', 'priority'],
    'compose': ['compose', 'draft', 'write', 'reply'],
    'summary': ['summarize', 'summary', 'key points'],
    'calendar': ['calendar', 'meeting', 'schedule', 'event'],
    'email': ['email', 'message', 'inbox', 'from', 'sender']
}

# Multi-step Query Patterns
MULTI_STEP_PATTERNS: List[str] = [
    'first', 'then', 'next step', 'finally', 'after that',
    'and then', 'followed by', 'also', 'additionally',
    'step 1', 'step 2', 'step 3', 'part 1', 'part 2',
    'do this', 'then do', 'after doing', 'before doing',
    'and', 'plus', 'along with', 'together with',
    'reschedule', 'reorganize', 'rearrange',
    'loop in', 'cc', 'bcc', 'include',
    'move', 'shift', 'change',
]

ACTION_VERBS: List[str] = [
    'create', 'schedule', 'send', 'find', 'search', 'list', 'show',
    'add', 'make', 'book', 'compose', 'write', 'delete', 'update',
    'analyze', 'check', 'get', 'fetch', 'organize', 'manage',
    'reschedule', 'reorganize', 'rearrange', 'move', 'shift',
    'reply', 'forward', 'follow up', 'summarize', 'plan',
    'schedule', 'book', 'cancel', 'complete', 'finish'
]

# Task Continuation Patterns
CONTINUATION_PATTERNS: List[str] = [
    'yes', 'no', 'ok', 'sure', 'that works', 'good', 'fine',
    'accept', 'decline', 'confirm', 'cancel', 'proceed',
    'next', 'continue', 'go ahead', 'do it', 'make it',
    'send it', 'schedule it', 'create it', 'add it'
]

CONFIRMATION_PATTERNS: List[str] = [
    'would you like', 'should i', 'do you want', 'shall i',
    'confirm', 'proceed', 'continue', 'accept', 'decline',
    'which', 'what time', 'when', 'where', 'how'
]

# Conversation Context Filter Headers
CONTEXT_FILTER_HEADERS: List[str] = [
    "Email Contact Analysis", "Email Patterns Analysis", 
    "Email Category Analysis", "No overdue tasks found", 
    "Overdue Tasks", "Task Summary", "[OK] **No overdue",
    "You have", "Breakdown:", "Next Steps:", "Pending:", "Completed:"
]
