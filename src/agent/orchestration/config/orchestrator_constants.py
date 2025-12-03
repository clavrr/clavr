"""
Orchestrator Constants

Centralized constants for the orchestrator system to improve maintainability.
Integrates with intent patterns and memory system for consistent behavior.

This module provides:
- Tool name mappings for orchestration
- Context extraction patterns (regex)
- Logging prefixes
- Strategy and error recovery patterns
- Orchestrator-specific utilities

"""
from typing import List, Dict, Pattern
import re

# Import shared patterns from intent module (single source of truth)
from ...intent import (
    MULTI_STEP_PATTERNS,
)

# Log Prefix Constants - Used throughout orchestrator for consistent logging
LOG_AI = "[AI]"
LOG_ALERT = "[ALERT]"
LOG_CONTEXT = "[CONTEXT]"
LOG_ERROR = "[ERROR]"
LOG_FAST = "[FAST]"
LOG_INFO = "[INFO]"
LOG_LLM = "[LLM]"
LOG_OK = "[OK]"
LOG_RESTART = "[RESTART]"
LOG_SEARCH = "[SEARCH]"
LOG_STATS = "[STATS]"
LOG_TASK = "[TASK]"
LOG_WARNING = "[WARNING]"

# Multi-step Query Separators - Use intent_patterns.MULTI_STEP_PATTERNS for detection
# This is an alias for backward compatibility
MULTI_STEP_SEPARATORS: List[str] = MULTI_STEP_PATTERNS

# Advanced Multi-step Indicators - More sophisticated pattern detection
MULTI_STEP_INDICATORS: Dict[str, List[str]] = {
    'sequence': ['first', 'then', 'next', 'finally', 'after that'],
    'conjunction': ['and', 'plus', 'also', 'additionally', 'along with'],
    'conditional': ['if', 'when', 'after', 'before', 'unless'],
    'temporal': ['today', 'tomorrow', 'this week', 'next week', 'later'],
    'implicit': ['reschedule', 'reorganize', 'rearrange', 'move', 'shift']
}

# NOTE: ACTION_PATTERNS removed - use intent_patterns.ACTION_VERBS instead
# NOTE: DOMAIN_PATTERNS removed - use intent_patterns.*_PATTERNS (EMAIL_PATTERNS, CALENDAR_PATTERNS, etc.) instead

# Comprehensive Action to Intent Mapping - Aligned with intent patterns
ACTION_MAP: Dict[str, str] = {
    # Display/Retrieval
    'show': 'display',
    'list': 'list', 
    'find': 'search',
    'search': 'search',
    'get': 'retrieve',
    'fetch': 'retrieve',
    
    # Creation
    'create': 'create',
    'add': 'create',
    'make': 'create',
    'new': 'create',
    
    # Scheduling
    'schedule': 'schedule',
    'book': 'schedule',
    'plan': 'schedule',
    
    # Communication
    'send': 'communicate',
    'compose': 'communicate',
    'write': 'communicate',
    'reply': 'communicate',
    'forward': 'communicate',
    
    # Modification
    'update': 'modify',
    'edit': 'modify',
    'modify': 'modify',
    'change': 'modify',
    'reschedule': 'modify',
    'move': 'modify',
    
    # Deletion
    'delete': 'delete',
    'remove': 'delete',
    'cancel': 'delete',
    
    # Analysis
    'analyze': 'analyze',
    'check': 'analyze',
    'review': 'analyze',
    'summarize': 'analyze'
}

# Enhanced Intent to Tool Mapping - Integration with actual tools
INTENT_TO_TOOL_MAP: Dict[str, str] = {
    # Task Management
    'task': 'tasks',
    'tasks': 'tasks',
    'todo': 'tasks',
    'reminder': 'tasks',
    
    # Calendar Management
    'calendar': 'calendar',
    'event': 'calendar',
    'meeting': 'calendar',
    'appointment': 'calendar',
    'schedule': 'calendar',
    
    # Email Management
    'email': 'email',
    'emails': 'email',
    'message': 'email',
    'messages': 'email',
    'email_management': 'email',
    'mail': 'email',
    
    # Specific Email Functions
    'analysis': 'analyze_email',
    'compose': 'compose_email',
    'summary': 'summarize',
    'summarize': 'summarize',
    
    # Search and Retrieval
    'search': 'search_engine',
    'find': 'search_engine',
    'lookup': 'search_engine'
}

# NOTE: DOMAIN_PATTERNS removed - use intent_patterns.*_PATTERNS instead:
# - For email: use EMAIL_PATTERNS
# - For calendar: use CALENDAR_PATTERNS  
# - For tasks: use TASK_CREATE_PATTERNS, TASK_LIST_PATTERNS, TASK_ANALYSIS_PATTERNS

# Priority Keywords - For task and event prioritization
PRIORITY_KEYWORDS: Dict[str, List[str]] = {
    'high': ['urgent', 'asap', 'critical', 'important', 'high priority'],
    'medium': ['normal', 'medium priority', 'standard'],
    'low': ['low priority', 'when possible', 'later', 'eventually']
}

# Enhanced Empty Result Patterns - For better result validation
EMPTY_RESULT_PATTERNS: List[str] = [
    "no emails found", "no results", "no messages", "found 0",
    "could not find", "nothing found", "no matching",
    "no events", "no tasks", "empty", "zero results",
    "not found", "no data", "no entries", "no items",
    "search returned nothing", "query returned no results"
]

# Comprehensive Context Extraction Patterns - For intelligent parsing
# Compiled regex patterns for better performance
EMAIL_PATTERN: Pattern[str] = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
DATE_PATTERN: Pattern[str] = re.compile(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b')
TITLE_PATTERN: Pattern[str] = re.compile(r'\*\*(.*?)\*\*')
COUNT_PATTERN: Pattern[str] = re.compile(r'\((\d+)\)\s*:')
SEARCH_QUERY_PATTERN: Pattern[str] = re.compile(r'(?:find|search|look for).*?(?:emails|email|messages).*?(?:about|for|containing)\s+([^,]*)')
SEARCH_QUERY_FALLBACK_PATTERN: Pattern[str] = re.compile(r'(?:emails?|email).*?(?:about|for)\s+([^,]*)')

# Time and Date Extraction Patterns
TIME_PATTERNS: Dict[str, Pattern[str]] = {
    'absolute': re.compile(r'\b(?:at\s+)?(\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?)\b'),
    'relative': re.compile(r'\b(?:in\s+)?(\d+)\s+(minutes?|hours?|days?|weeks?)\b'),
    'today': re.compile(r'\b(today|this\s+(?:morning|afternoon|evening))\b'),
    'tomorrow': re.compile(r'\b(tomorrow|next\s+(?:morning|afternoon|evening))\b'),
    'week': re.compile(r'\b(this|next)\s+week\b'),
    'month': re.compile(r'\b(this|next)\s+month\b')
}

# Enhanced LLM Context Extraction Fields - For structured data extraction
CONTEXT_EXTRACTION_FIELDS: List[str] = [
    'search_topic',
    'key_findings', 
    'relevant_count',
    'subjects',
    'important_entities',
    'action_items',
    'deadlines',
    'priorities',
    'recipients',
    'time_references',
    'domain_context'
]

# Enhanced Query Enhancement Keywords - For intelligent query expansion
VAGUE_TASK_KEYWORDS: List[str] = [
    'review', 'create a task', 'review them', 'Review them',
    'look at', 'check', 'examine', 'handle', 'deal with',
    'process', 'manage', 'organize', 'take care of'
]

CONTEXT_ADDITION_KEYWORDS: List[str] = [
    'result_count', 'subjects', 'emails', 'dates',
    'participants', 'locations', 'attachments',
    'priorities', 'deadlines', 'status'
]

# Memory Integration Keywords - For memory system integration
MEMORY_TRIGGERS: Dict[str, List[str]] = {
    'pattern_learning': ['similar to', 'like before', 'as usual', 'the same way'],
    'user_preference': ['my preference', 'I usually', 'typically', 'normally'],
    'context_reuse': ['from last time', 'previous', 'again', 'repeat']
}

# Orchestration Strategy Keywords - For execution strategy selection
STRATEGY_KEYWORDS: Dict[str, List[str]] = {
    'parallel': ['simultaneously', 'at the same time', 'together', 'concurrently'],
    'sequential': ['first', 'then', 'after', 'followed by', 'next'],
    'conditional': ['if', 'when', 'unless', 'provided that', 'only if'],
    'optional': ['maybe', 'perhaps', 'if possible', 'optionally', 'if needed']
}

# Error Recovery Patterns - For robust error handling
ERROR_RECOVERY_PATTERNS: Dict[str, List[str]] = {
    'retry': ['try again', 'retry', 'attempt again'],
    'fallback': ['use alternative', 'try different', 'fallback'],
    'skip': ['skip', 'ignore', 'continue without'],
    'abort': ['stop', 'cancel', 'abort', 'give up']
}

# Success Validation Patterns - For execution success confirmation
SUCCESS_PATTERNS: List[str] = [
    'completed successfully', 'done', 'finished', 'created',
    'scheduled', 'sent', 'found', 'updated', 'deleted',
    'saved', 'processed', 'executed', 'accomplished'
]

FAILURE_PATTERNS: List[str] = [
    'failed', 'error', 'couldn\'t', 'unable', 'not found',
    'permission denied', 'timeout', 'connection error',
    'invalid', 'missing', 'not available'
]

