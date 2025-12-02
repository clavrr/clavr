"""
Intent Detection Module - Query intent classification and tool routing

Provides:
- Intent detection patterns and keyword lists
- Query complexity analysis
- Tool recommendation based on intent
- Entity extraction from queries
"""

# Import everything from intent_patterns
from .intent_patterns import *

# Explicitly export common items for clarity
__all__ = [
    # Pattern lists
    'EMAIL_PATTERNS',
    'EMAIL_MANAGEMENT_PATTERNS',
    'CALENDAR_PATTERNS',
    'CALENDAR_QUESTION_PATTERNS',
    'CALENDAR_ADVANCED_ACTION_PATTERNS',
    'CALENDAR_FOLLOWUP_PATTERNS',
    'CALENDAR_ACTION_ITEM_PATTERNS',
    'TASK_CREATE_PATTERNS',
    'TASK_LIST_PATTERNS',
    'TASK_ANALYSIS_PATTERNS',
    'TASK_QUESTION_PATTERNS',
    'MULTI_STEP_PATTERNS',
    'ACTION_VERBS',
    
    # Keyword lists
    'TASK_KEYWORDS',
    'CALENDAR_KEYWORDS',
    'EMAIL_KEYWORDS',
    
    # Functions
    'classify_query_intent',
    'extract_entities',
    'analyze_query_complexity',
    'recommend_tools',
    'should_use_orchestration',
    'get_execution_strategy',
    'has_email_keywords',
    'has_calendar_keywords',
    'has_task_keywords'
]

