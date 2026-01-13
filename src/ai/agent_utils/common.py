"""
Agent Utilities - Shared helper functions for agent operations

Centralizes common query detection, validation, and formatting logic used across
the agent system. This module provides lightweight, fast utility functions that
complement the more sophisticated intent detection and parsing systems.

Organization:
- Query Detection: Fast keyword-based domain detection
- Query Analysis: Entity extraction and domain classification
- Text Processing: Response cleaning and formatting
- Multi-step Formatting: Combining multiple step results

Integration Points:
- Used by Orchestrator and AutonomousOrchestrator for quick domain detection
- Used by parsers for initial query classification
- Used by response formatters for cleaning output
- Complements intent/intent_patterns.py for lightweight detection

NOTE: Pattern keyword lists are imported from intent/intent_patterns.py as the
single source of truth. This module provides fast utility wrappers.
"""
import re
from typing import Dict, List, Optional, Any, Tuple

from src.utils.logger import setup_logger

# Import centralized patterns
from src.agents.constants import RECURRENCE_PATTERNS, DAYS_OF_WEEK, MAX_KEYWORDS_PER_DOMAIN

logger = setup_logger(__name__)

# Import keyword lists from intent module (single source of truth)
try:
    from src.ai.intent import (
        TASK_CREATE_PATTERNS,
        TASK_LIST_PATTERNS,
        TASK_ANALYSIS_PATTERNS,
        CALENDAR_PATTERNS,
        EMAIL_PATTERNS,
        ACTION_VERBS
    )
    HAS_INTENT_PATTERNS = True
except ImportError:
    # Fallback if patterns not available
    HAS_INTENT_PATTERNS = False
    TASK_CREATE_PATTERNS = []
    TASK_LIST_PATTERNS = []
    TASK_ANALYSIS_PATTERNS = []
    CALENDAR_PATTERNS = []
    EMAIL_PATTERNS = []
    ACTION_VERBS = []

# Notion patterns (not in intent module, defined here)
NOTION_PATTERNS = [
    'notion', 'notion page', 'notion database', 'create page', 'new page',
    'workspace', 'notion workspace'
]

# Create flattened keyword lists for fast lookup
if HAS_INTENT_PATTERNS:
    TASK_KEYWORDS = list(set([
        kw for pattern_list in [TASK_CREATE_PATTERNS, TASK_LIST_PATTERNS, TASK_ANALYSIS_PATTERNS] 
        for pattern in pattern_list 
        for kw in pattern.split()
    ]))[:MAX_KEYWORDS_PER_DOMAIN]
else:
    TASK_KEYWORDS = []

if HAS_INTENT_PATTERNS:
    CALENDAR_KEYWORDS = list(set([
        kw for pattern in CALENDAR_PATTERNS 
        for kw in pattern.split()
    ]))[:MAX_KEYWORDS_PER_DOMAIN]
else:
    CALENDAR_KEYWORDS = []

if HAS_INTENT_PATTERNS:
    EMAIL_KEYWORDS = list(set([
        kw for pattern in EMAIL_PATTERNS 
        for kw in pattern.split()
    ]))[:MAX_KEYWORDS_PER_DOMAIN]
else:
    EMAIL_KEYWORDS = []

NOTION_KEYWORDS = list(set([
    kw for pattern in NOTION_PATTERNS 
    for kw in pattern.split()
]))[:MAX_KEYWORDS_PER_DOMAIN]

CREATION_VERBS = ACTION_VERBS[:MAX_KEYWORDS_PER_DOMAIN]

# Technical tags to remove from responses (for cleaner output)
TECHNICAL_TAGS = [
    r'\[OK\]\s*',
    r'\[ERROR\]\s*',
    r'\[WARNING\]\s*',
    r'\[INFO\]\s*',
    r'\[SEARCH\]\s*',
    r'\[CAL\]\s*',
    r'\[TASK\]\s*',
    r'\[EMAIL\]\s*',
    r'\[NOTION\]\s*',
    r'\[SYNTHESIS\]\s*',
    r'\[ORCHESTRATOR\]\s*',
]

# Markdown patterns to remove (for plain text output)
MARKDOWN_PATTERNS = [
    (r'\*\*([^*]+)\*\*', r'\1'),  # Bold
    (r'\*([^*]+)\*', r'\1'),      # Italic
    (r'`([^`]+)`', r'\1'),        # Code
    (r'#+\s*', ''),               # Headers
    (r'\[([^\]]+)\]\([^\)]+\)', r'\1'),  # Links
]


# ============================================================================
# QUERY DETECTION HELPERS
# ============================================================================

def _has_keywords(query: str, keywords: List[str], case_sensitive: bool = False) -> bool:
    """
    Generic helper to check if query contains any of the given keywords.
    
    Args:
        query: User query string
        keywords: List of keywords to check for
        case_sensitive: Whether to perform case-sensitive matching
        
    Returns:
        True if any keyword is found in query
    """
    if not query or not keywords:
        return False
    
    if case_sensitive:
        return any(keyword in query for keyword in keywords)
    else:
        query_lower = query.lower()
        return any(keyword.lower() in query_lower for keyword in keywords)


def has_task_keywords(query: str) -> bool:
    """
    Check if query contains task-related keywords.
    
    Args:
        query: User query string
        
    Returns:
        True if query contains task keywords
    """
    return _has_keywords(query, TASK_KEYWORDS)


def has_calendar_keywords(query: str) -> bool:
    """
    Check if query contains calendar-related keywords.
    
    Args:
        query: User query string
        
    Returns:
        True if query contains calendar keywords
    """
    return _has_keywords(query, CALENDAR_KEYWORDS)


def has_email_keywords(query: str) -> bool:
    """
    Check if query contains email-related keywords.
    
    Args:
        query: User query string
        
    Returns:
        True if query contains email keywords
    """
    return _has_keywords(query, EMAIL_KEYWORDS)


def has_notion_keywords(query: str) -> bool:
    """
    Check if query contains Notion-related keywords.
    
    Args:
        query: User query string
        
    Returns:
        True if query contains Notion keywords
    """
    if not NOTION_KEYWORDS:
        # Fallback to basic Notion detection
        notion_basic = ['notion', 'page', 'database', 'workspace']
        return _has_keywords(query, notion_basic)
    return _has_keywords(query, NOTION_KEYWORDS)


def _is_creation_query(query: str, domain_keywords: List[str]) -> bool:
    """
    Generic helper to detect creation queries for a specific domain.
    
    Args:
        query: User query string
        domain_keywords: Domain-specific keywords to check for
        
    Returns:
        True if this is a creation query for the domain
    """
    has_creation_verb = _has_keywords(query, CREATION_VERBS)
    has_domain_keyword = _has_keywords(query, domain_keywords)
    return has_creation_verb and has_domain_keyword


def is_task_creation_query(query: str) -> bool:
    """
    Detect if a query is a task creation request.
    
    Task creation queries should NEVER be decomposed or split, as they
    represent a single atomic operation (e.g., "create a task about going
    to Cleveland Commons tonight").
    
    Args:
        query: User query string
        
    Returns:
        True if this is a task creation query
    """
    return _is_creation_query(query, TASK_KEYWORDS)


def is_calendar_creation_query(query: str) -> bool:
    """
    Detect if a query is a calendar event creation request.
    
    Calendar creation queries should NEVER be decomposed, as they represent
    a single atomic operation (e.g., "create a calendar event about meeting
    tomorrow at 5 pm and add attendee").
    
    Args:
        query: User query string
        
    Returns:
        True if this is a calendar creation query
    """
    query_lower = query.lower()
    
    # Check standard calendar keywords
    has_calendar_keyword = _has_keywords(query, CALENDAR_KEYWORDS)
    has_creation_verb = _has_keywords(query, CREATION_VERBS)
    
    # If it has both, it's definitely a calendar creation query
    if has_calendar_keyword and has_creation_verb:
        return True
    
    # ENHANCED: Also detect calendar queries by recurrence patterns
    # Queries like "set up monthly review" or "create weekly standup" are calendar queries
    # even if they don't explicitly say "meeting" or "event"
    # Using centralized RECURRENCE_PATTERNS
    
    has_recurrence = any(pattern in query_lower for pattern in RECURRENCE_PATTERNS)
    
    # Day of week references (using centralized DAYS_OF_WEEK)
    has_day_reference = any(day in query_lower for day in DAYS_OF_WEEK)
    
    # If query has creation verb + (recurrence pattern OR day reference), it's likely a calendar query
    if has_creation_verb and (has_recurrence or has_day_reference):
        logger.debug(f"Detected calendar creation query by recurrence/day pattern: '{query}'")
        return True
    
    return False


def is_notion_creation_query(query: str) -> bool:
    """
    Detect if a query is a Notion page/database creation request.
    
    Args:
        query: User query string
        
    Returns:
        True if this is a Notion creation query
    """
    return _is_creation_query(query, NOTION_KEYWORDS)


def should_not_decompose_query(query: str) -> bool:
    """
    Check if a query should NOT be decomposed into multiple steps.
    
    Some queries represent atomic operations that should be executed as
    a single step, even if they contain words like "and".
    
    Examples that should NOT be decomposed:
    - "Create a task about going to Cleveland Commons tonight and add reminder"
    - "Schedule monthly review meeting and invite team"
    - "Send email about project update and cc manager"
    - "Create a Notion page about project and add to database"
    
    Args:
        query: User query string
        
    Returns:
        True if query should NOT be decomposed
    """
    # Task creation queries should never be decomposed
    if is_task_creation_query(query):
        logger.debug(f"Query identified as task creation - will not decompose: '{query}'")
        return True
    
    # Calendar creation queries should never be decomposed
    if is_calendar_creation_query(query):
        logger.debug(f"Query identified as calendar creation - will not decompose: '{query}'")
        return True
    
    # Notion creation queries should never be decomposed
    if is_notion_creation_query(query):
        logger.debug(f"Query identified as Notion creation - will not decompose: '{query}'")
        return True
    
    # Check for other atomic operations
    query_lower = query.lower()
    
    # Single email composition with complex content
    if ('compose' in query_lower or 'send email' in query_lower or 'write email' in query_lower):
        # These are atomic email operations even with "and"
        atomic_email_patterns = [
            'and cc', 'and bcc', 'and attach', 'and include',
            'and schedule send', 'and mark important'
        ]
        if any(pattern in query_lower for pattern in atomic_email_patterns):
            logger.debug(f"Query identified as atomic email operation - will not decompose: '{query}'")
            return True
    
    # Single complex search operations
    # IMPORTANT: Only treat as atomic if it has search refinement keywords, NOT sequencing keywords
    search_patterns = [
        'find emails', 'search emails', 'get emails', 'show emails',
        'find meetings', 'search meetings', 'get meetings', 'show meetings',
        'find tasks', 'search tasks', 'get tasks', 'show tasks',
        'find pages', 'search pages', 'get pages', 'show pages',  # Notion
        'find databases', 'search databases', 'get databases', 'show databases',  # Notion
    ]
    
    # Sequencing keywords that indicate multi-step (NOT atomic)
    sequencing_keywords = [
        'and then', 'then', 'and create', 'and schedule', 'and send',
        'followed by', 'after that', 'next', 'also', 'additionally'
    ]
    
    # First check if query has sequencing keywords - if so, it's NOT atomic
    if any(seq_kw in query_lower for seq_kw in sequencing_keywords):
        logger.debug(f"Query contains sequencing keywords - WILL decompose: '{query}'")
        return False
    
    if any(pattern in query_lower for pattern in search_patterns):
        # Check if it's a complex search with additional criteria (still atomic)
        # These are search refinement keywords, not sequencing
        complex_criteria = [
            'and from', 'and to', 'and subject', 'and containing',
            'and between', 'and after', 'and before', 'and during',
            'and with', 'and about', 'and regarding', 'and in database',  # Notion
            'and in workspace', 'and with tags', 'and with properties',  # Notion
        ]
        if any(criteria in query_lower for criteria in complex_criteria):
            logger.debug(f"Query identified as complex search operation - will not decompose: '{query}'")
            return True
    
    return False


def get_query_domain(query: str) -> str:
    """
    Determine the primary domain of a query.
    
    Uses keyword counting to identify the most likely domain. Returns 'general'
    if no domain keywords are found.
    
    Args:
        query: User query string
        
    Returns:
        Primary domain: 'task', 'calendar', 'email', 'notion', or 'general'
    """
    if not query:
        return 'general'
    
    query_lower = query.lower()
    
    # Count domain keywords
    task_count = sum(1 for keyword in TASK_KEYWORDS if keyword in query_lower)
    calendar_count = sum(1 for keyword in CALENDAR_KEYWORDS if keyword in query_lower)
    email_count = sum(1 for keyword in EMAIL_KEYWORDS if keyword in query_lower)
    notion_count = sum(1 for keyword in NOTION_KEYWORDS 
                      if keyword in query_lower)
    
    # Return domain with highest count
    domain_counts: Dict[str, int] = {
        'task': task_count,
        'calendar': calendar_count,
        'email': email_count,
        'notion': notion_count
    }
    
    max_domain = max(domain_counts, key=lambda k: domain_counts[k])
    max_count = domain_counts[max_domain]
    
    return max_domain if max_count > 0 else 'general'


def get_query_domains(query: str) -> List[str]:
    """
    Get all domains detected in a query (for multi-domain queries).
    
    Args:
        query: User query string
        
    Returns:
        List of detected domains (e.g., ['email', 'calendar'])
    """
    domains = []
    
    if has_task_keywords(query):
        domains.append('task')
    if has_calendar_keywords(query):
        domains.append('calendar')
    if has_email_keywords(query):
        domains.append('email')
    if has_notion_keywords(query):
        domains.append('notion')
    
    return domains if domains else ['general']


def extract_query_entities(query: str) -> Dict[str, List[str]]:
    """
    Extract entities from a query for better processing.
    
    This is a lightweight entity extraction function. For more sophisticated
    extraction, use the intent/extract_entities function which uses LLM.
    
    Args:
        query: User query string
        
    Returns:
        Dictionary with extracted entities by type:
        - times: Time references found
        - domains: Domains detected
        - actions: Action verbs found
        - priorities: Priority indicators found
    """
    entities: Dict[str, List[str]] = {
        'times': [],
        'domains': [],
        'actions': [],
        'priorities': []
    }
    
    if not query:
        return entities
    
    query_lower = query.lower()
    
    # Extract time references
    time_words = ['today', 'tomorrow', 'next week', 'this week', 'urgent', 'asap', 
                  'yesterday', 'next month', 'this month', 'next year']
    entities['times'] = [word for word in time_words if word in query_lower]
    
    # Extract domains
    if has_task_keywords(query):
        entities['domains'].append('task')
    if has_calendar_keywords(query):
        entities['domains'].append('calendar')
    if has_email_keywords(query):
        entities['domains'].append('email')
    if has_notion_keywords(query):
        entities['domains'].append('notion')
    
    # Extract actions
    entities['actions'] = [verb for verb in CREATION_VERBS if verb in query_lower]
    
    # Extract priorities
    priority_words = ['urgent', 'important', 'critical', 'low priority', 'high priority', 
                     'asap', 'immediately', 'soon']
    entities['priorities'] = [word for word in priority_words if word in query_lower]
    
    return entities


def is_multi_domain_query(query: str) -> bool:
    """
    Check if a query involves multiple domains.
    
    Args:
        query: User query string
        
    Returns:
        True if query involves multiple domains
    """
    domains = get_query_domains(query)
    # FIX: Was returning True for single-domain queries due to inverted logic
    return len(domains) > 1


# ============================================================================
# TEXT PROCESSING HELPERS
# ============================================================================

def extract_search_topic(query: str, pattern: Optional[str] = None) -> Optional[str]:
    """
    Extract search topic from a query using pattern matching.
    
    Args:
        query: User query string
        pattern: Optional regex pattern (uses default if not provided)
        
    Returns:
        Extracted search topic or None
    """
    if not query:
        return None
    
    if not pattern:
        # Default pattern for email/task/notion searches
        pattern = r'(?:find|search|look for|get|show).*?(?:about|for|containing|with|in)\s+([^,\.]+)'
    
    match = re.search(pattern, query, re.IGNORECASE)
    if match:
        topic = match.group(1).strip()
        # Clean up common prefixes
        topic = re.sub(r'^(current query|user response):\s*', '', topic, flags=re.IGNORECASE)
        return topic.strip()
    
    return None


def clean_response_text(text: str, remove_markdown: bool = True, remove_tags: bool = True) -> str:
    """
    Clean up response text to make it more conversational.
    
    Removes technical tags, excessive formatting, and makes responses
    feel more natural and human-like.
    
    Args:
        text: Raw response text
        remove_markdown: Whether to remove markdown formatting
        remove_tags: Whether to remove technical tags
        
    Returns:
        Cleaned, conversational text
    """
    if not text:
        return ""
    
    # Remove technical tags (case-insensitive)
    if remove_tags:
        for tag_pattern in TECHNICAL_TAGS:
            text = re.sub(tag_pattern, '', text, flags=re.IGNORECASE)
    
    # Remove markdown formatting
    if remove_markdown:
        for pattern, replacement in MARKDOWN_PATTERNS:
            text = re.sub(pattern, replacement, text)
    
    # Remove excessive line breaks
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Remove excessive whitespace
    text = re.sub(r' {2,}', ' ', text)
    
    # Remove leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    
    return text.strip()


def format_multi_step_response(results: List[Dict[str, Any]], 
                               include_failures: bool = True,
                               max_results: Optional[int] = None) -> str:
    """
    Format multiple step results into a natural, conversational response.
    
    Combines results from multiple steps into a cohesive response that
    feels natural and human-like, not robotic.
    
    Args:
        results: List of step result dictionaries with keys:
            - success: bool - Whether step succeeded
            - result: str - Step result text
            - action: str - Action performed
            - has_data: bool - Whether result contains data
        include_failures: Whether to include failed steps in response
        max_results: Optional limit on number of results to include
        
    Returns:
        Formatted conversational response
    """
    if not results:
        return "I wasn't able to complete that request. Could you try rephrasing it or providing more details?"
    
    # Group results by success/failure
    successful_results = [r for r in results if r.get("success", False)]
    failed_results = [r for r in results if not r.get("success", False)]
    
    # Apply max_results limit if specified
    if max_results and len(successful_results) > max_results:
        successful_results = successful_results[:max_results]
    
    response_parts = []
    
    # Format successful results naturally
    for result in successful_results:
        step_result = result.get('result', '')
        action = result.get("action", "")
        has_data = result.get("has_data", True)
        
        # Clean up the result
        step_result = clean_response_text(step_result)
        
        # Make "no results" messages more conversational
        if not has_data and action in ["find", "search", "list", "get", "show"]:
            step_result = _get_no_results_message(action)
        
        if step_result.strip():
            response_parts.append(step_result)
    
    # Handle failures gracefully
    if include_failures and failed_results:
        failure_messages = [
            f"I had trouble with {result.get('action', 'that')}: {clean_response_text(result.get('result', 'An error occurred'))}"
            for result in failed_results
        ]
        if failure_messages:
            response_parts.append(" ".join(failure_messages))
    
    # Join naturally with varied connectors
    return _join_response_parts(response_parts)


def _get_no_results_message(action: str) -> str:
    """
    Generate a conversational "no results" message based on action type.
    
    Args:
        action: The action that was performed
        
    Returns:
        Conversational no-results message
    """
    action_lower = action.lower()
    
    if "email" in action_lower:
        return "I couldn't find any emails matching that search."
    elif "task" in action_lower:
        return "I don't see any tasks matching that criteria."
    elif "calendar" in action_lower or "meeting" in action_lower:
        return "I couldn't find any calendar events matching that."
    elif "notion" in action_lower or "page" in action_lower or "database" in action_lower:
        return "I couldn't find any Notion pages or databases matching that."
    else:
        return "I couldn't find anything matching that search."


def _join_response_parts(parts: List[str]) -> str:
    """
    Join response parts naturally with varied connectors.
    
    Args:
        parts: List of response parts to join
        
    Returns:
        Joined conversational response
    """
    if not parts:
        return ""
    
    if len(parts) == 1:
        return parts[0]
    
    if len(parts) == 2:
        return f"{parts[0]} Also, {parts[1].lower()}"
    
    # Multiple parts - use natural flow
    response = parts[0]
    for i, part in enumerate(parts[1:], 1):
        if i == len(parts) - 1:
            response += f" Finally, {part.lower()}"
        else:
            response += f" Also, {part.lower()}"
    
    return response


def truncate_text(text: str, max_length: int = 200, suffix: str = "...") -> str:
    """
    Truncate text to a maximum length, preserving word boundaries.
    
    Args:
        text: Text to truncate
        max_length: Maximum length (including suffix)
        suffix: Suffix to append if truncated
        
    Returns:
        Truncated text
    """
    if not text or len(text) <= max_length:
        return text
    
    # Truncate at word boundary
    truncated = text[:max_length - len(suffix)]
    last_space = truncated.rfind(' ')
    
    if last_space > 0:
        truncated = truncated[:last_space]
    
    return truncated + suffix


def normalize_query(query: str) -> str:
    """
    Normalize a query for consistent processing.
    
    Removes extra whitespace, normalizes case, and cleans up common issues.
    
    Args:
        query: Raw query string
        
    Returns:
        Normalized query string
    """
    if not query:
        return ""
    
    # Remove extra whitespace
    query = re.sub(r'\s+', ' ', query)
    
    # Remove leading/trailing whitespace
    query = query.strip()
    
    return query
