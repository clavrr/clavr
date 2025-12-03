"""
Configuration for Cross-Domain Query Handler

Centralizes all configuration constants for cross-domain query handling
to eliminate hardcoded values and ensure consistency.
"""


class CrossDomainConfig:
    """
    Configuration for cross-domain query detection, decomposition, and execution
    
    Defines confidence thresholds, execution modes, and tunable parameters
    to eliminate all hardcoded values and support easy customization.
    """
    
    # === Detection Confidence Thresholds ===
    PATTERN_MATCH_CONFIDENCE = 0.9
    """Confidence score when explicit pattern matches cross-domain query"""
    
    MIXED_DOMAIN_CONFIDENCE = 0.7
    """Confidence score when domain validator detects mixed domains"""
    
    KEYWORD_DETECTION_CONFIDENCE = 0.6
    """Confidence score when multiple domain keywords detected"""
    
    MIN_CROSS_DOMAIN_CONFIDENCE = 0.5
    """Minimum confidence threshold to treat as cross-domain query"""
    
    # === Execution Configuration ===
    ENABLE_PARALLEL_EXECUTION = True
    """Whether to execute independent sub-queries in parallel by default"""
    
    PARALLEL_EXECUTION_TIMEOUT = 30.0
    """Maximum seconds to wait for all parallel sub-queries to complete"""
    
    # === Dependency Resolution ===
    MAX_DEPENDENCY_DEPTH = 5
    """Maximum depth of dependency chain to prevent circular dependencies"""
    
    DEPENDENCY_TIMEOUT = 60.0
    """Maximum seconds to wait for dependent query chain"""
    
    # === Sub-Query Limits ===
    MAX_SUB_QUERIES = 10
    """Maximum number of sub-queries from single cross-domain query"""
    
    # === Logging ===
    LOG_PATTERN_MATCHING = True
    """Whether to log cross-domain pattern matching"""
    
    LOG_DEPENDENCY_DETECTION = True
    """Whether to log dependency detection operations"""
    
    LOG_EXECUTION_MODE = True
    """Whether to log selected execution mode"""
    
    # === Error Handling ===
    CONTINUE_ON_PARTIAL_FAILURE = True
    """Whether to continue if some sub-queries fail"""
    
    # === Response Formatting ===
    INCLUDE_DOMAIN_LABELS = True
    """Whether to include domain labels in synthesized response"""
    
    INCLUDE_ERROR_DETAILS = True
    """Whether to include error details in synthesized response"""
    
    # === Calendar-Only Detection ===
    # Patterns for queries that are calendar-specific (not cross-domain)
    CALENDAR_ONLY_PATTERNS = [
        r'\bcalendar\s+events?\b',
        r'\bmy\s+calendar\b',
        r'\bwhat.*calendar\b',
        r'\bshow.*calendar\b',
        r'\bmeetings?\s+(?:today|tomorrow|for)\b',
        r'\bevents?\s+(?:today|tomorrow|for|between)\b',
        r'\bwhat\s+events?\s+(?:do\s+i|i)\s+have\b',
        r'\bshow\s+(?:my\s+)?events?\b',
    ]
    """Regex patterns for calendar-only queries (not treated as cross-domain)"""
    
    # === Email-Only Detection ===
    # Patterns for queries that are email-specific (not cross-domain)
    EMAIL_ONLY_PATTERNS = [
        r'\btell\s+me\s+(?:about|more\s+about)\s+.*(?:email|message)',
        r'\bwhat\s+(?:is|was|does)\s+.*(?:email|message).*(?:about|say)',
        r'\bwhat\s+(?:email|message).*(?:did\s+i\s+receive|from)',
        r'\bwhen\s+(?:was|did).*(?:email|message).*(?:from|arrive)',
        r'\bhow\s+much.*(?:spent|spend|paid|purchase|bought)',
        r'\blast\s+(?:email|message).*(?:from|by)',
        r'\b(?:amazon|vercel|spotify|purchase|receipt|invoice|payment).*(?:email|message|spent|cost)',
        r'\bemail.*(?:about|regarding|concerning)',
        r'\bsummarize.*(?:email|message)',
        r'\bexplain.*(?:email|message)',
    ]
    """Regex patterns for email-only queries (not treated as cross-domain)"""
    
    # === Time Context Keywords ===
    TIME_CONTEXT_PATTERNS = [
        r'\btoday\b',
        r'\btomorrow\b',
        r'\bthis\s+week\b',
        r'\bnext\s+week\b',
        r'\bthis\s+month\b',
        r'\bnext\s+month\b',
    ]
    """Regex patterns for extracting time context"""
    
    # === Domain Keywords ===
    TASK_KEYWORDS = ['task', 'tasks', 'todo', 'todos']
    """Keywords indicating task domain"""
    
    CALENDAR_KEYWORDS = ['meeting', 'calendar', 'appointment']
    """Keywords indicating calendar domain (specific, not generic 'event')"""
    
    EMAIL_KEYWORDS = ['email', 'message', 'inbox', 'send']
    """Keywords indicating email domain"""
    
    NOTION_KEYWORDS = ['notion', 'page', 'database', 'document', 'wiki']
    """Keywords indicating Notion domain"""
    
    # Note: Slack is a platform/entry point, not a data source domain
    # Users interact WITH Slack, but the agent doesn't query Slack as a data source
    
    # === Action Keywords ===
    CREATE_KEYWORDS = ['create', 'add', 'new', 'schedule', 'book']
    """Keywords indicating create/add action"""
    
    SEARCH_KEYWORDS = ['search', 'find', 'look for']
    """Keywords indicating search action"""
    
    # === Dependency Pattern Keywords ===
    # Patterns for detecting dependencies between queries
    CREATE_FROM_EMAIL_PATTERN = r'create\s+task.*for\s+each\s+email'
    """Pattern: create tasks from emails"""
    
    EMAIL_ABOUT_MEETING_PATTERN = r'email.*about.*(meeting|event)'
    """Pattern: send email about meeting"""
    
    PREPARE_FOR_MEETING_PATTERN = r'prepare.*for.*(meeting|event)'
    """Pattern: prepare for meeting (multi-step)"""
