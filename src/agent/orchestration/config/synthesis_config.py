"""
Configuration for Context Synthesis

Centralizes all configuration constants for both cross-domain context enrichment
(orchestration.context_synthesizer) and entity-aware response formatting (response_formatter).

This is the single source of truth for all synthesis-related configuration values,
eliminating hardcoded constants throughout the codebase.

Integration Points:
- context_synthesizer.py: Uses all ENRICHMENT and CONTEXT configs
- response_formatter.py: Uses all RESPONSE_FORMATTING and PRIORITY configs
- execution_planner.py: May reference action/domain keywords
- orchestrator.py: Uses synthesis config for result formatting

No hardcoded values should appear in those modules - all should reference this config.
"""

from typing import Dict, List


class SynthesisConfig:
    """
    Centralized configuration for context synthesis and response formatting
    
    Defines thresholds, limits, and tunable parameters to eliminate hardcoded values
    and ensure consistency across context synthesis operations.
    
    All values are:
    - Configurable without code changes
    - Well-documented with purpose and usage
    - Validated for consistency
    - Organized by functional area
    
    Usage:
        >>> from synthesis_config import SynthesisConfig
        >>> max_items = SynthesisConfig.MAX_STANDARD_ITEMS
        >>> keywords = SynthesisConfig.get_action_keywords('create')
        >>> config_dict = SynthesisConfig.to_dict()
    """
    
    # ===== CROSS-DOMAIN ENRICHMENT =====
    ENRICHMENT_CONFIDENCE_THRESHOLD = 0.75
    """Confidence threshold for applying cross-domain enrichment (0.0-1.0)"""
    
    ENRICHMENT_MIN_RELEVANCE_SCORE = 0.6
    """Minimum relevance score for enrichment results"""
    
    MAX_ENRICHMENT_SOURCES = 5
    """Maximum number of sources to use for enrichment"""
    
    # ===== CONTEXT EXTRACTION =====
    MAX_SUBJECTS_TO_EXTRACT = 5
    """Maximum number of email subjects to extract from results"""
    
    MAX_CONTEXT_ITEMS = 15
    """Maximum number of items to include in context"""
    
    MAX_PRIORITY_ITEMS_TO_EXTRACT = 10
    """Maximum items to extract when formatting high-priority responses"""
    
    CONTEXT_WINDOW_DAYS = 7
    """Number of days to look back for context"""
    
    # ===== PATTERN MATCHING =====
    DOMAIN_TRANSITION_MIN_CONFIDENCE = 0.7
    """Minimum confidence for detecting domain transitions"""
    
    CROSS_DOMAIN_SIMILARITY_THRESHOLD = 0.65
    """Minimum similarity score for cross-domain matching"""
    
    # ===== RESPONSE FORMATTING LIMITS =====
    # Priority-based response limits (ordered by urgency)
    MAX_URGENT_ITEMS = 10
    """Maximum items to display in urgent responses"""
    
    MAX_TIME_SENSITIVE_ITEMS = 12
    """Maximum items to display in time-sensitive responses"""
    
    MAX_HIGH_PRIORITY_ITEMS = 15
    """Maximum items to display in high-priority responses"""
    
    MAX_STANDARD_ITEMS = 20
    """Maximum items to display in standard responses"""
    
    MAX_LOW_PRIORITY_ITEMS = 25
    """Maximum items to display in low-priority responses"""
    
    EXTRA_ITEMS_THRESHOLD = 15
    """Threshold above which to show 'and X more' message"""
    
    # ===== CONTEXT PRESERVATION =====
    MAX_CONTEXT_LENGTH = 250
    """Maximum characters to include in context suffixes (e.g., previous results)"""
    
    MAX_RELATED_ITEMS_CONTEXT = 3
    """Maximum related items to include in context"""
    
    # ===== PRIORITY KEYWORDS =====
    URGENT_KEYWORDS = [
        "urgent", "asap", "critical", "emergency", "immediately",
        "right now", "now", "this second", "urgent!", "critical!"
    ]
    """Keywords indicating urgent priority"""
    
    TIME_SENSITIVE_KEYWORDS = [
        "today", "now", "this morning", "this afternoon", "tonight",
        "this evening", "this week", "before end of day"
    ]
    """Keywords indicating time-sensitive context"""
    
    HIGH_PRIORITY_KEYWORDS = [
        "important", "high priority", "soon", "scheduled",
        "don't forget", "remember", "must", "need to"
    ]
    """Keywords indicating high priority"""
    
    LOW_PRIORITY_KEYWORDS = [
        "when you have time", "at some point", "eventually",
        "later", "someday", "optional", "nice to have"
    ]
    """Keywords indicating low priority"""
    
    # ===== ACTION KEYWORDS =====
    ACTION_KEYWORDS = {
        "create": ["create", "new", "make", "add", "schedule", "set up", "establish"],
        "find": ["find", "search", "get", "show", "list", "retrieve", "fetch"],
        "update": ["update", "modify", "change", "edit", "alter", "revise", "adjust"],
        "delete": ["delete", "remove", "cancel", "discard", "clear", "destroy"],
        "reply": ["reply", "respond", "answer", "message", "send", "compose"],
        "organize": ["organize", "sort", "arrange", "group", "categorize"],
        "analyze": ["analyze", "review", "check", "examine", "look at"],
    }
    """Keywords for identifying action types"""
    
    # ===== DOMAIN KEYWORDS =====
    DOMAIN_KEYWORDS = {
        "email": [
            "email", "mail", "message", "send", "recipient", "subject",
            "compose", "draft", "inbox", "sender", "attachment"
        ],
        "calendar": [
            "calendar", "meeting", "appointment", "event", "schedule",
            "attendees", "time", "when", "conflict", "availability"
        ],
        "task": [
            "task", "todo", "item", "action item", "follow up",
            "deadline", "due", "reminder", "checklist", "pending"
        ],
    }
    """Keywords for identifying domains"""
    
    # ===== RESPONSE FORMATTING =====
    RESPONSE_SEPARATOR = "\n---\n"
    """Separator between multiple response sections"""
    
    RESULT_ITEM_PREFIX = "• "
    """Prefix for list items in formatted responses"""
    
    MORE_ITEMS_MESSAGE = "and {count} more..."
    """Message template for indicating additional items"""
    
    NO_RESULTS_MESSAGE = "No results found."
    """Message to display when no results are available"""
    
    # ===== LOGGING & DEBUG =====
    LOG_ENRICHMENT_OPERATIONS = False
    """Whether to log cross-domain enrichment operations (verbose)"""
    
    LOG_CONTEXT_EXTRACTION = False
    """Whether to log context extraction operations (verbose)"""
    
    LOG_RESPONSE_FORMATTING = False
    """Whether to log response formatting operations (verbose)"""
    
    LOG_CONFIG_INITIALIZATION = True
    """Whether to log configuration initialization"""
    
    # ===== VALIDATION =====
    @classmethod
    def validate_config(cls) -> Dict[str, bool]:
        """
        Validate configuration values for consistency and sanity.
        
        Returns:
            Dictionary with validation results
        """
        issues = {}
        
        # Thresholds should be between 0 and 1
        threshold_attrs = [
            'ENRICHMENT_CONFIDENCE_THRESHOLD',
            'ENRICHMENT_MIN_RELEVANCE_SCORE',
            'DOMAIN_TRANSITION_MIN_CONFIDENCE',
            'CROSS_DOMAIN_SIMILARITY_THRESHOLD'
        ]
        for attr in threshold_attrs:
            value = getattr(cls, attr)
            if not (0.0 <= value <= 1.0):
                issues[attr] = f"Must be between 0 and 1, got {value}"
        
        # Item limits should be positive integers
        limit_attrs = [
            'MAX_SUBJECTS_TO_EXTRACT',
            'MAX_CONTEXT_ITEMS',
            'MAX_PRIORITY_ITEMS_TO_EXTRACT',
            'MAX_URGENT_ITEMS',
            'MAX_TIME_SENSITIVE_ITEMS',
            'MAX_HIGH_PRIORITY_ITEMS',
            'MAX_STANDARD_ITEMS',
            'MAX_LOW_PRIORITY_ITEMS',
            'EXTRA_ITEMS_THRESHOLD',
            'MAX_CONTEXT_LENGTH',
            'MAX_ENRICHMENT_SOURCES',
            'MAX_RELATED_ITEMS_CONTEXT',
            'CONTEXT_WINDOW_DAYS'
        ]
        for attr in limit_attrs:
            value = getattr(cls, attr)
            if not isinstance(value, int) or value <= 0:
                issues[attr] = f"Must be positive integer, got {value}"
        
        # Priority item limits should be in logical order
        if cls.MAX_URGENT_ITEMS > cls.MAX_TIME_SENSITIVE_ITEMS:
            issues['priority_limits'] = "URGENT items should not exceed TIME_SENSITIVE items"
        
        if cls.MAX_TIME_SENSITIVE_ITEMS > cls.MAX_HIGH_PRIORITY_ITEMS:
            issues['priority_limits_2'] = "TIME_SENSITIVE items should not exceed HIGH_PRIORITY items"
        
        if cls.MAX_HIGH_PRIORITY_ITEMS > cls.MAX_STANDARD_ITEMS:
            issues['priority_limits_3'] = "HIGH_PRIORITY items should not exceed STANDARD items"
        
        if cls.MAX_STANDARD_ITEMS > cls.MAX_LOW_PRIORITY_ITEMS:
            issues['priority_limits_4'] = "STANDARD items should not exceed LOW_PRIORITY items"
        
        # Keywords should be non-empty lists
        keyword_attrs = [
            'URGENT_KEYWORDS',
            'TIME_SENSITIVE_KEYWORDS',
            'HIGH_PRIORITY_KEYWORDS',
            'LOW_PRIORITY_KEYWORDS'
        ]
        for attr in keyword_attrs:
            value = getattr(cls, attr)
            if not isinstance(value, list) or len(value) == 0:
                issues[attr] = f"Must be non-empty list, got {value}"
        
        # Action and domain keywords should be dicts with non-empty lists
        if not isinstance(cls.ACTION_KEYWORDS, dict) or not cls.ACTION_KEYWORDS:
            issues['ACTION_KEYWORDS'] = "Must be non-empty dictionary"
        for action, keywords in cls.ACTION_KEYWORDS.items():
            if not isinstance(keywords, list) or len(keywords) == 0:
                issues[f'ACTION_KEYWORDS[{action}]'] = "Must be non-empty list"
        
        if not isinstance(cls.DOMAIN_KEYWORDS, dict) or not cls.DOMAIN_KEYWORDS:
            issues['DOMAIN_KEYWORDS'] = "Must be non-empty dictionary"
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            if not isinstance(keywords, list) or len(keywords) == 0:
                issues[f'DOMAIN_KEYWORDS[{domain}]'] = "Must be non-empty list"
        
        return issues
    
    @classmethod
    def get_action_keywords(cls, action: str) -> List[str]:
        """
        Get keywords for a specific action type.
        
        Args:
            action: Action type (e.g., 'create', 'find', 'update')
            
        Returns:
            List of keywords for the action, or empty list if not found
        """
        return cls.ACTION_KEYWORDS.get(action.lower(), [])
    
    @classmethod
    def get_domain_keywords(cls, domain: str) -> List[str]:
        """
        Get keywords for a specific domain.
        
        Args:
            domain: Domain (e.g., 'email', 'calendar', 'task')
            
        Returns:
            List of keywords for the domain, or empty list if not found
        """
        return cls.DOMAIN_KEYWORDS.get(domain.lower(), [])
    
    @classmethod
    def get_max_items_for_priority(cls, priority: str) -> int:
        """
        Get maximum items to display based on priority level.
        
        Args:
            priority: Priority level ('urgent', 'time_sensitive', 'high', 'standard', 'low')
            
        Returns:
            Maximum number of items to display
        """
        priority_map = {
            'urgent': cls.MAX_URGENT_ITEMS,
            'time_sensitive': cls.MAX_TIME_SENSITIVE_ITEMS,
            'high': cls.MAX_HIGH_PRIORITY_ITEMS,
            'standard': cls.MAX_STANDARD_ITEMS,
            'low': cls.MAX_LOW_PRIORITY_ITEMS,
        }
        return priority_map.get(priority.lower(), cls.MAX_STANDARD_ITEMS)
    
    @classmethod
    def get_priority_from_keywords(cls, text: str) -> str:
        """
        Determine priority level based on keywords in text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Priority level ('urgent', 'time_sensitive', 'high', 'low', or 'standard')
        """
        text_lower = text.lower()
        
        for keyword in cls.URGENT_KEYWORDS:
            if keyword in text_lower:
                return 'urgent'
        
        for keyword in cls.TIME_SENSITIVE_KEYWORDS:
            if keyword in text_lower:
                return 'time_sensitive'
        
        for keyword in cls.HIGH_PRIORITY_KEYWORDS:
            if keyword in text_lower:
                return 'high'
        
        for keyword in cls.LOW_PRIORITY_KEYWORDS:
            if keyword in text_lower:
                return 'low'
        
        return 'standard'
    
    @classmethod
    def get_action_from_keywords(cls, text: str) -> str:
        """
        Determine action type based on keywords in text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Action type or 'generic' if not determined
        """
        text_lower = text.lower()
        
        for action, keywords in cls.ACTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return action
        
        return 'generic'
    
    @classmethod
    def get_domain_from_keywords(cls, text: str) -> str:
        """
        Determine domain based on keywords in text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Domain name or 'general' if not determined
        """
        text_lower = text.lower()
        
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return domain
        
        return 'general'
    
    @classmethod
    def to_dict(cls) -> Dict[str, any]:
        """
        Export all configuration as dictionary.
        
        Returns:
            Dictionary with all configuration values
        """
        config_dict = {}
        
        for attr_name in dir(cls):
            # Skip private/magic attributes and methods
            if attr_name.startswith('_') or callable(getattr(cls, attr_name)):
                continue
            
            # Skip class attributes that are methods
            attr_value = getattr(cls, attr_name)
            if callable(attr_value):
                continue
            
            # Include all uppercase attributes (constants)
            if attr_name.isupper():
                config_dict[attr_name] = attr_value
        
        return config_dict
    
    @classmethod
    def __repr__(cls) -> str:
        """String representation for debugging"""
        validation_issues = cls.validate_config()
        status = "✓ VALID" if not validation_issues else f"✗ INVALID ({len(validation_issues)} issues)"
        
        return (
            f"SynthesisConfig {status}\n"
            f"  Item limits: {cls.MAX_URGENT_ITEMS}-{cls.MAX_STANDARD_ITEMS}-{cls.MAX_LOW_PRIORITY_ITEMS}\n"
            f"  Thresholds: confidence={cls.ENRICHMENT_CONFIDENCE_THRESHOLD}, "
            f"domain_transition={cls.DOMAIN_TRANSITION_MIN_CONFIDENCE}\n"
            f"  Keywords: {len(cls.ACTION_KEYWORDS)} actions, {len(cls.DOMAIN_KEYWORDS)} domains"
        )


def get_synthesis_config() -> SynthesisConfig:
    """
    Get the global SynthesisConfig instance.
    
    This ensures a single config instance is used across the orchestrator,
    allowing environment-based overrides without code changes.
    
    Returns:
        SynthesisConfig class (configuration values accessed via class methods)
        
    Example:
        >>> config = get_synthesis_config()
        >>> max_items = config.MAX_STANDARD_ITEMS
        >>> priority = config.get_priority_from_keywords("urgent meeting today")
    """
    return SynthesisConfig


def validate_synthesis_config() -> bool:
    """
    Validate SynthesisConfig for consistency and sanity.
    
    Should be called during application startup to catch configuration issues early.
    
    Returns:
        True if valid, False if there are issues
        
    Raises:
        ValueError if critical validation issues are found
    """
    config = get_synthesis_config()
    issues = config.validate_config()
    
    if issues:
        error_msg = "SynthesisConfig validation failed:\n"
        for key, issue in issues.items():
            error_msg += f"  {key}: {issue}\n"
        raise ValueError(error_msg)
    
    if config.LOG_CONFIG_INITIALIZATION:
        print(f"[SYNTHESIS] Config valid: {len(config.to_dict())} configuration values loaded")
    
    return True


"""
INTEGRATION GUIDE - How to use SynthesisConfig across the codebase

1. CONTEXT SYNTHESIZER (context_synthesizer.py)
   ============================================
   Instead of:
       if confidence > SynthesisConfig.ENRICHMENT_CONFIDENCE_THRESHOLD:
           apply_enrichment()
   
   Use:
       config = get_synthesis_config()
       if confidence > config.ENRICHMENT_CONFIDENCE_THRESHOLD:
           apply_enrichment()

2. RESPONSE FORMATTER (response_formatter.py)
   ==========================================
   Instead of:
       if len(items) > SynthesisConfig.MAX_STANDARD_ITEMS:
           show_more_message()
   
   Use:
       config = get_synthesis_config()
       priority = config.get_priority_from_keywords(query)
       max_items = config.get_max_items_for_priority(priority)
       if len(items) > max_items:
           show_more_message()

3. EXECUTION PLANNER (execution_planner.py)
   ========================================
   Instead of:
       if "create" in query.lower():  # DUPLICATED!
           action = "create"
   
   Use:
       config = get_synthesis_config()
       action = config.get_action_from_keywords(query)

4. ORCHESTRATOR (orchestrator.py)
   ============================
   Instead of:
       separator = "\\n---\\n"  # HARDCODED!
       result = separator.join(results)
   
   Use:
       config = get_synthesis_config()
       result = config.RESPONSE_SEPARATOR.join(results)

5. STARTUP INITIALIZATION (main.py or __init__.py)
   ================================================
   Add validation early in application startup:
       from synthesis_config import validate_synthesis_config
       
       try:
           validate_synthesis_config()
       except ValueError as e:
           logger.error(f"Configuration error: {e}")
           raise

6. ENVIRONMENT OVERRIDES (future feature)
   =====================================
   To enable environment-based overrides, subclass SynthesisConfig:
       
       class ProductionSynthesisConfig(SynthesisConfig):
           MAX_URGENT_ITEMS = 5  # More restrictive
           LOG_ENRICHMENT_OPERATIONS = False  # Less verbose
       
       def get_synthesis_config():
           if os.getenv('ENVIRONMENT') == 'production':
               return ProductionSynthesisConfig
           return SynthesisConfig
"""
