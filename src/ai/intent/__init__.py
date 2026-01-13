"""
Intent Detection Module - Query intent classification and tool routing

Provides:
- Intent detection patterns and keyword lists
- Query complexity analysis
- Tool recommendation based on intent
- Entity extraction from queries
"""

# Import constants from config
from .config.intent_constants import (
    # Pattern lists
    EMAIL_PATTERNS,
    EMAIL_MANAGEMENT_PATTERNS,
    CALENDAR_PATTERNS,
    CALENDAR_QUESTION_PATTERNS,
    TASK_CREATE_PATTERNS,
    TASK_LIST_PATTERNS,
    TASK_ANALYSIS_PATTERNS,
    TASK_QUESTION_PATTERNS,
    TASK_COMPLETION_PATTERNS,
    MULTI_STEP_PATTERNS,
    ACTION_VERBS,
    CONTINUATION_PATTERNS,
    CONFIRMATION_PATTERNS,
    CONTEXT_FILTER_HEADERS,
    ANALYSIS_PATTERNS,
    COMPOSE_PATTERNS,
    COMPOSE_EXCLUDE_WORDS,
    SUMMARY_PATTERNS,
    FALLBACK_KEYWORDS,
    # Keyword lists
    TASK_KEYWORDS,
    CALENDAR_KEYWORDS,
    EMAIL_KEYWORDS,
)

from .core.classifier import classify_query_intent
from .core.analyzer import (
    analyze_query_complexity,
    extract_entities,
)

# Import helper functions from intent_patterns
from .intent_patterns import (
    has_email_keywords,
    has_calendar_keywords,
    has_task_keywords,
)

# Import domain detection utility
from .domain_detector import (
    DomainDetector,
    DomainResult,
    detect_domain,
    get_domain_detector,
)


__all__ = [
    # Pattern lists
    'EMAIL_PATTERNS',
    'EMAIL_MANAGEMENT_PATTERNS',
    'CALENDAR_PATTERNS',
    'CALENDAR_QUESTION_PATTERNS',
    'TASK_CREATE_PATTERNS',
    'TASK_LIST_PATTERNS',
    'TASK_ANALYSIS_PATTERNS',
    'TASK_QUESTION_PATTERNS',
    'TASK_COMPLETION_PATTERNS',
    'MULTI_STEP_PATTERNS',
    'ACTION_VERBS',
    'CONTINUATION_PATTERNS',
    'CONFIRMATION_PATTERNS',
    'CONTEXT_FILTER_HEADERS',
    'ANALYSIS_PATTERNS',
    'COMPOSE_PATTERNS',
    'COMPOSE_EXCLUDE_WORDS',
    'SUMMARY_PATTERNS',
    'FALLBACK_KEYWORDS',
    
    # Keyword lists
    'TASK_KEYWORDS',
    'CALENDAR_KEYWORDS',
    'EMAIL_KEYWORDS',
    
    # Functions
    'classify_query_intent',
    'extract_entities',
    'analyze_query_complexity',
    'has_email_keywords',
    'has_calendar_keywords',
    'has_task_keywords',
    
    # Domain detection
    'DomainDetector',
    'DomainResult',
    'detect_domain',
    'get_domain_detector',
]

