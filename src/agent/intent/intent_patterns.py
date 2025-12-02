"""
Intent Detection Patterns

Centralized pattern definitions for intent detection to improve maintainability.

Note: Keyword lists (TASK_KEYWORDS, CALENDAR_KEYWORDS, EMAIL_KEYWORDS) are defined
in utils.py to avoid duplication. Import them from there if needed.

This module provides comprehensive pattern matching for:
- Multi-step query detection
- Domain-specific intent classification  
- Tool routing and selection
- Query complexity analysis
"""
from typing import List, Dict, Any

# Import keyword lists from utils to avoid duplication
try:
    from ..utils import TASK_KEYWORDS, CALENDAR_KEYWORDS, EMAIL_KEYWORDS
    HAS_UTILS_KEYWORDS = True
except ImportError:
    # Fallback definitions
    TASK_KEYWORDS = ['task', 'tasks', 'todo', 'todos', 'reminder', 'deadline']
    CALENDAR_KEYWORDS = ['calendar', 'meeting', 'event', 'events', 'appointment', 'schedule'] 
    EMAIL_KEYWORDS = ['email', 'emails', 'message', 'messages', 'inbox', 'unread']
    HAS_UTILS_KEYWORDS = False

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
    'add deadline', 'deadline reminder', 'deadline todo'
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
    'what\'s on my calendar', 'what\'s on calendar', 'whats on my calendar', 'whats on calendar',
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
    'oldest emails', 'emails i haven\'t read', 'haven\'t read',
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

# Multi-step Query Patterns - Enhanced to catch implicit multi-step queries
MULTI_STEP_PATTERNS: List[str] = [
    'first', 'then', 'next step', 'finally', 'after that',
    'and then', 'followed by', 'also', 'additionally',
    'step 1', 'step 2', 'step 3', 'part 1', 'part 2',
    'do this', 'then do', 'after doing', 'before doing',
    # Implicit multi-step patterns
    'and', 'plus', 'along with', 'together with',
    'reschedule', 'reorganize', 'rearrange',  # These imply multiple operations
    'loop in', 'cc', 'bcc', 'include',  # Email multi-step
    'move', 'shift', 'change',  # Calendar multi-step
]

ACTION_VERBS: List[str] = [
    'create', 'schedule', 'send', 'find', 'search', 'list', 'show',
    'add', 'make', 'book', 'compose', 'write', 'delete', 'update',
    'analyze', 'check', 'get', 'fetch', 'organize', 'manage',
    'reschedule', 'reorganize', 'rearrange', 'move', 'shift',
    'reply', 'forward', 'follow up', 'summarize', 'plan',
    'schedule', 'book', 'cancel', 'complete', 'finish'
]

# CALENDAR_KEYWORDS moved to utils.py to avoid duplication
# Import from .utils if needed: from .utils import CALENDAR_KEYWORDS

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
# These headers are excluded from conversation context to avoid interfering with intent detection
CONTEXT_FILTER_HEADERS: List[str] = [
    "Email Contact Analysis", "Email Patterns Analysis", 
    "Email Category Analysis", "No overdue tasks found", 
    "Overdue Tasks", "Task Summary", "[OK] **No overdue",
    "You have", "Breakdown:", "Next Steps:", "Pending:", "Completed:"
]


# ============================================================================ 
# INTELLIGENT QUERY ANALYSIS FUNCTIONS
# ============================================================================

def analyze_query_complexity(query: str) -> Dict[str, any]:
    """
    Analyze query complexity and characteristics
    
    Returns:
        Dict with complexity metrics and routing recommendations
    """
    query_lower = query.lower()
    
    # Multi-step indicators
    multi_step_count = sum(1 for pattern in MULTI_STEP_PATTERNS if pattern in query_lower)
    action_verb_count = sum(1 for verb in ACTION_VERBS if verb in query_lower)
    
    # Domain detection - check task patterns FIRST to avoid false matches with email patterns
    domains = []
    # Check task patterns first (most specific)
    if any(pattern in query_lower for pattern in (TASK_QUESTION_PATTERNS + TASK_CREATE_PATTERNS + 
                                                 TASK_LIST_PATTERNS + TASK_ANALYSIS_PATTERNS)):
        domains.append('task')
    # Check calendar patterns second
    if any(pattern in query_lower for pattern in CALENDAR_PATTERNS + CALENDAR_QUESTION_PATTERNS):
        domains.append('calendar')
    # Check email patterns last (least specific, can match task queries like "do i have")
    if any(pattern in query_lower for pattern in EMAIL_PATTERNS + EMAIL_MANAGEMENT_PATTERNS):
        # Only add email if query doesn't explicitly mention tasks/calendar
        has_task_keywords = any(keyword in query_lower for keyword in ['task', 'tasks', 'todo', 'todos', 'reminder', 'deadline'])
        has_calendar_keywords = any(keyword in query_lower for keyword in ['calendar', 'meeting', 'meetings', 'event', 'events', 'appointment', 'schedule'])
        if not has_task_keywords and not has_calendar_keywords:
            domains.append('email')
    
    # Complexity scoring
    complexity_score = 0
    complexity_score += multi_step_count * 2  # Multi-step indicators worth 2 points
    complexity_score += action_verb_count * 1  # Action verbs worth 1 point
    complexity_score += len(domains) * 1  # Each domain worth 1 point
    
    # Determine complexity level
    if complexity_score >= 4:
        complexity_level = "high"
        recommended_execution = "orchestrated"
    elif complexity_score >= 2:
        complexity_level = "medium" 
        recommended_execution = "orchestrated"
    else:
        complexity_level = "low"
        recommended_execution = "standard"
    
    return {
        "complexity_score": complexity_score,
        "complexity_level": complexity_level,
        "multi_step_indicators": multi_step_count,
        "action_verbs_detected": action_verb_count,
        "domains_detected": domains,
        "cross_domain": len(domains) > 1,
        "recommended_execution": recommended_execution,
        "should_use_orchestration": complexity_score >= 2
    }


def classify_query_intent(query: str) -> Dict[str, str]:
    """
    Classify the primary intent of a query
    
    Returns:
        Dict with intent classification and confidence
    """
    query_lower = query.lower()
    
    # CRITICAL: Check task patterns FIRST to avoid false matches with email patterns
    # (e.g., "What tasks do I have" matches 'do i have' in EMAIL_PATTERNS)
    if any(pattern in query_lower for pattern in TASK_QUESTION_PATTERNS):
        return {"primary_intent": "task_listing", "confidence": "high", "domain": "task"}
    elif any(pattern in query_lower for pattern in TASK_CREATE_PATTERNS):
        return {"primary_intent": "task_creation", "confidence": "high", "domain": "task"}
    elif any(pattern in query_lower for pattern in TASK_ANALYSIS_PATTERNS):
        return {"primary_intent": "task_analysis", "confidence": "high", "domain": "task"}
    elif any(pattern in query_lower for pattern in TASK_LIST_PATTERNS):
        return {"primary_intent": "task_listing", "confidence": "medium", "domain": "task"}
    
    # Calendar intent classification (check before email to avoid false matches)
    elif any(pattern in query_lower for pattern in CALENDAR_QUESTION_PATTERNS):
        return {"primary_intent": "calendar_query", "confidence": "high", "domain": "calendar"}
    elif any(pattern in query_lower for pattern in CALENDAR_PATTERNS):
        return {"primary_intent": "calendar_management", "confidence": "medium", "domain": "calendar"}
    
    # Email intent classification (check LAST to avoid false matches)
    elif any(pattern in query_lower for pattern in EMAIL_MANAGEMENT_PATTERNS):
        return {"primary_intent": "email_management", "confidence": "high", "domain": "email"}
    elif any(pattern in query_lower for pattern in EMAIL_PATTERNS):
        return {"primary_intent": "email_operation", "confidence": "medium", "domain": "email"}
    
    # General patterns
    elif any(pattern in query_lower for pattern in ANALYSIS_PATTERNS):
        return {"primary_intent": "analysis", "confidence": "medium", "domain": "general"}
    elif any(pattern in query_lower for pattern in SUMMARY_PATTERNS):
        return {"primary_intent": "summarization", "confidence": "medium", "domain": "general"}
    
    # Default classification
    return {"primary_intent": "general_query", "confidence": "low", "domain": "general"}


def recommend_tools(query: str, tools_dict: Dict[str, Any]) -> List[str]:
    """
    Recommend tools using intelligent parser-based routing.
    
    This function uses parsers from tools to determine which tool should handle a query.
    It leverages the existing parser infrastructure which has sophisticated LLM-based
    domain detection and action classification.
    
    Args:
        query: User query
        tools_dict: Dict mapping tool names to tool instances (required - allows parser access)
        
    Returns:
        List of recommended tool names (ordered by priority)
        
    Raises:
        ValueError: If tools_dict is None, empty, or not a dictionary
    """
    # Type check: ensure tools_dict is a dictionary, not a list
    if isinstance(tools_dict, list):
        raise ValueError(
            f"recommend_tools() now requires a dictionary of tool instances, not a list. "
            f"Received list: {tools_dict}. "
            f"Please pass a dict like {{'email': email_tool, 'calendar': calendar_tool}} "
            f"where each tool instance has a 'parser' attribute."
        )
    
    if not tools_dict or not isinstance(tools_dict, dict):
        raise ValueError(
            f"tools_dict is required for parser-based routing. "
            f"Expected Dict[str, Any], got {type(tools_dict).__name__}"
        )
    
    return _recommend_tools_with_parsers(query, tools_dict)


def _get_domain_keywords() -> Dict[str, List[str]]:
    """
    Get domain keywords from config or use defaults.
    
    Returns:
        Dict mapping domain names to keyword lists
    """
    try:
        from ...utils.config import load_config
        import yaml
        from pathlib import Path
        
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "intent_keywords.yaml"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                return {
                    'task': config.get('task_keywords', []),
                    'calendar': config.get('calendar_keywords', []),
                    'email': config.get('email_actions', []) + config.get('general_actions', [])
                }
    except Exception:
        pass
    
    # Fallback to imported keywords or minimal defaults
    try:
        from ..utils import TASK_KEYWORDS, CALENDAR_KEYWORDS, EMAIL_KEYWORDS
        return {
            'task': TASK_KEYWORDS,
            'calendar': CALENDAR_KEYWORDS,
            'email': EMAIL_KEYWORDS
        }
    except ImportError:
        # Minimal fallback
        return {
            'task': ['task', 'tasks', 'todo', 'todos', 'reminder', 'deadline'],
            'calendar': ['calendar', 'meeting', 'meetings', 'event', 'events', 'appointment', 'schedule'],
            'email': ['email', 'emails', 'message', 'messages', 'inbox', 'mail']
        }


def _detect_domain_hints(query: str) -> Dict[str, float]:
    """
    Detect weak domain hints from keywords (optional signal, not hardcoded filter).
    
    Returns:
        Dict mapping domain names to hint strength (0.0-1.0)
    """
    query_lower = query.lower()
    keywords = _get_domain_keywords()
    hints = {}
    
    for domain, keyword_list in keywords.items():
        matches = sum(1 for kw in keyword_list if kw.lower() in query_lower)
        if matches > 0:
            # Normalize hint strength (more matches = stronger hint, but cap at 0.3)
            hints[domain] = min(matches * 0.1, 0.3)
    
    return hints


def _recommend_tools_with_parsers(query: str, tools_dict: Dict[str, Any]) -> List[str]:
    """
    Use parsers from tools to intelligently route queries.
    
    This leverages the existing parser infrastructure which has sophisticated
    LLM-based domain detection and action classification. Parser confidence is
    the primary signal, with optional keyword hints as weak signals.
    
    Key improvements:
    - Evaluates ALL parsers (no hardcoded filtering)
    - Uses parser confidence as primary signal
    - Keywords are optional weak hints (not hard filters)
    - Trusts parser rejection mechanism
    """
    from ...utils.logger import setup_logger
    logger = setup_logger(__name__)
    
    # Get optional domain hints (weak signal, not hard filter)
    domain_hints = _detect_domain_hints(query)
    
    tool_scores = {}
    parser_results = {}
    
    # Evaluate ALL parsers - trust their domain expertise and rejection mechanism
    for tool_name, tool in tools_dict.items():
        parser = getattr(tool, 'parser', None)
        if not parser:
            continue
        
        try:
            # Use parser to detect if this query belongs to this tool's domain
            # Parsers return 'reject' action if query doesn't belong to their domain
            parsed = parser.parse_query_to_params(query)
            
            action = parsed.get('action', '')
            confidence = parsed.get('confidence', 0.0)
            metadata = parsed.get('metadata', {})
            
            parser_results[tool_name] = {
                'action': action,
                'confidence': confidence,
                'metadata': metadata
            }
            
            # If parser explicitly rejects, respect that decision
            if action == 'reject':
                logger.debug(f"[ROUTING] Parser for {tool_name} rejected query: {query[:50]}")
                continue
            
            # Use parser confidence as primary signal
            base_score = confidence
            
            # Apply optional weak keyword hints (only if parser already has decent confidence)
            if confidence >= 0.5:
                # Determine tool domain from tool name
                tool_domain = None
                tool_name_lower = tool_name.lower()
                if 'email' in tool_name_lower or 'mail' in tool_name_lower:
                    tool_domain = 'email'
                elif 'task' in tool_name_lower or 'todo' in tool_name_lower:
                    tool_domain = 'task'
                elif 'calendar' in tool_name_lower or 'event' in tool_name_lower or 'meeting' in tool_name_lower:
                    tool_domain = 'calendar'
                
                # Apply weak hint boost if domain matches (max 0.1 boost)
                if tool_domain and tool_domain in domain_hints:
                    hint_boost = domain_hints[tool_domain] * 0.3  # Very weak boost
                    base_score = min(confidence + hint_boost, 1.0)
                    if hint_boost > 0:
                        logger.debug(f"[ROUTING] Applied weak keyword hint for {tool_name}: +{hint_boost:.3f}")
            
            # Only recommend tools with minimum confidence threshold
            if confidence >= 0.5:
                tool_scores[tool_name] = base_score
                logger.info(f"[ROUTING] Parser for {tool_name} accepted query with confidence {base_score:.2f} (action: {action})")
            else:
                logger.debug(f"[ROUTING] Parser for {tool_name} has low confidence {confidence:.2f}, skipping")
        
        except Exception as e:
            logger.debug(f"[ROUTING] Parser for {tool_name} failed: {e}")
            continue
    
    # If no parsers accepted, check if any explicitly rejected
    if not tool_scores:
        rejections = [tool for tool, result in parser_results.items() if result.get('action') == 'reject']
        if rejections:
            logger.info(f"[ROUTING] All parsers rejected query. Rejections: {rejections}")
        else:
            logger.debug("[ROUTING] No parser accepted query and no explicit rejections")
        
        # Fallback to LLM with parser context
        return _recommend_tools_with_llm(query, list(tools_dict.keys()), parser_rejections=rejections)
    
    # Sort tools by confidence score (highest first)
    recommended = sorted(tool_scores.items(), key=lambda x: x[1], reverse=True)
    
    # Filter out low-confidence tools (keep only those with confidence >= 0.6 or top 2)
    filtered_recommended = []
    for tool_name, score in recommended:
        if score >= 0.6 or len(filtered_recommended) < 2:
            filtered_recommended.append((tool_name, score))
        else:
            break
    
    if filtered_recommended:
        result = [tool_name for tool_name, score in filtered_recommended]
        logger.info(f"[ROUTING] Parser-based routing: {result} (scores: {[f'{s:.2f}' for _, s in filtered_recommended]})")
        return result
    
    # If filtered results are empty, fallback to LLM
    logger.debug("[ROUTING] No parser met confidence threshold, falling back to LLM analysis")
    return _recommend_tools_with_llm(query, list(tools_dict.keys()))


def _recommend_tools_with_llm(query: str, available_tools: List[str], parser_rejections: List[str] = None) -> List[str]:
    """
    Fallback: Use LLM to analyze query and recommend tools.
    
    This is used when parsers aren't available or when no parser accepts the query.
    Can use parser rejection information to inform LLM decision.
    
    Args:
        query: User query
        available_tools: List of available tool names
        parser_rejections: Optional list of tools that explicitly rejected the query
    """
    from ...utils.logger import setup_logger
    from ...ai.llm_factory import LLMFactory
    from ...utils.config import Config
    from langchain_core.messages import HumanMessage
    import json
    import re
    
    logger = setup_logger(__name__)
    
    try:
        config = Config.from_env()
        llm = LLMFactory.get_llm_for_provider(config, temperature=0.3)
        
        if not llm:
            return _recommend_tools_pattern_fallback(query, available_tools)
        
        # Build context about parser rejections if available
        rejection_context = ""
        if parser_rejections:
            rejection_context = f"\n\nIMPORTANT: The following tools explicitly rejected this query: {', '.join(parser_rejections)}. " \
                               f"These tools determined the query does NOT belong to their domain. " \
                               f"Consider this when making your recommendation."
        
        prompt = f"""Analyze this user query and determine which tool(s) should handle it.

Query: "{query}"

Available tools: {', '.join(available_tools)}

For each tool, determine if the query belongs to that tool's domain:
- "tasks" tool: queries about tasks, todos, reminders, deadlines, task management
- "calendar" tool: queries about meetings, events, appointments, scheduling, calendar
- "email" tool: queries about emails, messages, inbox, sending emails

Analyze the query semantically and contextually. Consider:
- The primary intent of the query
- Which domain the query most naturally belongs to
- Whether the query might require multiple tools (multi-domain queries){rejection_context}

Respond with ONLY valid JSON:
{{
    "recommended_tools": ["tool1", "tool2", ...],
    "reasoning": "brief explanation"
}}"""
        
        response = llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        if not isinstance(response_text, str):
            response_text = str(response_text) if response_text else ""
        
        if response_text:
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                result = json.loads(json_match.group(0))
                recommended = result.get('recommended_tools', [])
                
                # Filter to only include available tools and exclude rejected tools
                recommended = [t for t in recommended if t in available_tools]
                if parser_rejections:
                    # Remove tools that explicitly rejected
                    recommended = [t for t in recommended if t not in parser_rejections]
                    if recommended != result.get('recommended_tools', []):
                        logger.info(f"[ROUTING] Filtered out rejected tools: {parser_rejections}")
                
                if recommended:
                    logger.info(f"[ROUTING] LLM-based routing: {recommended}")
                    return recommended
    
    except Exception as e:
        logger.debug(f"[ROUTING] LLM-based routing failed: {e}")
    
    # Final fallback to pattern matching (but only as last resort)
    return _recommend_tools_pattern_fallback(query, available_tools)


def _recommend_tools_pattern_fallback(query: str, available_tools: List[str]) -> List[str]:
    """
    Pattern-based fallback (last resort only).
    
    This should rarely be used - only when LLM and parsers are unavailable.
    """
    query_lower = query.lower()
    recommended_tools = []
    
    # Task keywords
    if any(keyword in query_lower for keyword in ['task', 'tasks', 'todo', 'todos', 'reminder', 'deadline']):
        task_tools = [tool for tool in available_tools if any(kw in tool.lower() for kw in ['task', 'todo', 'reminder'])]
        recommended_tools.extend(task_tools)
    
    # Calendar keywords (only if no task keywords)
    if not recommended_tools and any(keyword in query_lower for keyword in ['calendar', 'meeting', 'meetings', 'event', 'events', 'appointment', 'schedule']):
        calendar_tools = [tool for tool in available_tools if any(kw in tool.lower() for kw in ['calendar', 'meeting', 'event', 'schedule'])]
        recommended_tools.extend(calendar_tools)
    
    # Email keywords (only if no task/calendar keywords)
    if not recommended_tools and any(keyword in query_lower for keyword in ['email', 'emails', 'message', 'messages', 'inbox', 'mail']):
        email_tools = [tool for tool in available_tools if 'email' in tool.lower() or 'mail' in tool.lower()]
        recommended_tools.extend(email_tools)
    
    return recommended_tools if recommended_tools else available_tools[:1]  # Return first available tool as last resort


def extract_entities(query: str) -> Dict[str, List[str]]:
    """
    Extract entities from query for better processing
    
    Returns:
        Dict with extracted entities by type
    """
    query_lower = query.lower()
    entities = {
        "time_references": [],
        "priorities": [],
        "actions": [],
        "domains": []
    }
    
    # Time references
    time_words = ["today", "tomorrow", "next week", "this week", "overdue", "urgent", "deadline"]
    entities["time_references"] = [word for word in time_words if word in query_lower]
    
    # Priority indicators
    priority_words = ["urgent", "important", "priority", "critical", "asap"]
    entities["priorities"] = [word for word in priority_words if word in query_lower]
    
    # Actions
    entities["actions"] = [verb for verb in ACTION_VERBS if verb in query_lower]
    
    # Domains
    if any(pattern in query_lower for pattern in EMAIL_PATTERNS + EMAIL_MANAGEMENT_PATTERNS):
        entities["domains"].append("email")
    if any(pattern in query_lower for pattern in CALENDAR_PATTERNS + CALENDAR_QUESTION_PATTERNS):
        entities["domains"].append("calendar")
    if any(pattern in query_lower for pattern in (TASK_QUESTION_PATTERNS + TASK_CREATE_PATTERNS +
                                                 TASK_LIST_PATTERNS + TASK_ANALYSIS_PATTERNS)):
        entities["domains"].append("task")
    
    return entities


def should_use_orchestration(query: str) -> bool:
    """
    Determine if query should use orchestrated execution
    
    Returns:
        Boolean indicating if orchestration is recommended
    """
    analysis = analyze_query_complexity(query)
    return analysis["should_use_orchestration"]


def get_execution_strategy(query: str) -> Dict[str, any]:
    """
    Get comprehensive execution strategy for a query
    
    Returns:
        Dict with complete execution recommendations
    """
    complexity = analyze_query_complexity(query)
    intent = classify_query_intent(query)
    entities = extract_entities(query)
    
    return {
        "complexity": complexity,
        "intent": intent, 
        "entities": entities,
        "use_orchestration": complexity["should_use_orchestration"],
        "recommended_execution": complexity["recommended_execution"],
        "primary_domain": intent["domain"],
        "estimated_steps": max(1, complexity["multi_step_indicators"] + 1)
    }

