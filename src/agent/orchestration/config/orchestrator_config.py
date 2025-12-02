"""
Configuration for Pattern-Based Orchestrator

This module centralizes all configuration constants for the Orchestrator class
to eliminate hardcoded values and ensure consistency across the application.
"""


class OrchestratorConfig:
    """
    Configuration class for Pattern-Based Orchestrator
    
    Defines LLM settings, execution thresholds, and timeout values
    used by the pattern-based orchestrator for standard workflows.
    """
    
    # === LLM Configuration ===
    LLM_TEMPERATURE = 0.1
    """Temperature for LLM sampling - controls creativity/randomness (0.1 = deterministic)"""
    
    LLM_MAX_TOKENS = 8000
    """Maximum tokens to generate in LLM responses - increased to prevent truncation"""
    
    LLM_MAX_TOKENS_RETRY = 16000
    """Maximum tokens for retry when truncation is detected"""
    
    # === Execution Thresholds ===
    MIN_MEMORY_CONFIDENCE = 0.5
    """Minimum confidence threshold for using memory recommendations"""
    
    CROSS_DOMAIN_CONFIDENCE_THRESHOLD = 0.7
    """Minimum confidence for detecting cross-domain queries"""
    
    # === Timeout Configuration ===
    STEP_EXECUTION_TIMEOUT = 30.0
    """Maximum seconds to wait for a single step execution (default: 30s)"""
    
    QUERY_DECOMPOSITION_TIMEOUT = 10.0
    """Maximum seconds to wait for query decomposition (default: 10s)"""
    
    EXECUTION_PLAN_TIMEOUT = 10.0
    """Maximum seconds to create execution plan (default: 10s)"""
    
    # === Context Synthesis ===
    MAX_CONTEXT_LENGTH = 2000
    """Maximum characters for context enrichment in queries"""
    
    MAX_PREVIOUS_RESULTS = 5
    """Maximum number of previous results to include in context"""
    
    # === Retry Configuration ===
    MAX_STEP_RETRIES = 2
    """Maximum retries for a single step on failure"""
    
    # === Response Formatting ===
    MAX_ERRORS_TO_DISPLAY = 3
    """Maximum number of errors to display in formatted response"""
    
    MAX_ERROR_MESSAGES = 3
    """Maximum number of error messages to include in response"""
    
    QUERY_PREVIEW_LENGTH = 50
    """Number of characters to display in query preview logging"""
    
    # === Logging ===
    LOG_EXECUTION_DETAILS = True
    """Whether to log detailed execution information"""
    
    LOG_CONTEXT_ENRICHMENT = True
    """Whether to log context enrichment operations"""
    
    # === Execution Planner (Tool Selection & Validation) ===
    MIN_VALIDATION_CONFIDENCE = 0.6
    """Minimum confidence threshold for domain validation warnings (0.0-1.0)"""
    
    ENABLE_DOMAIN_VALIDATION = True
    """Whether to enable domain validation in execution planning"""
    
    ENABLE_STRICT_VALIDATION = True
    """Whether to use strict mode for domain validation"""
    
    AUTO_CORRECT_ROUTING = True
    """Whether to auto-correct misrouted queries based on validation"""
    
    # === Tool Selection Strategy ===
    TOOL_SELECTION_STRATEGY = "cascade"
    """
    Tool selection strategy:
    - "cascade": Try intent_patterns → memory → constants → heuristic (recommended)
    - "conservative": Only use intent_patterns and constants
    - "memory_first": Prioritize memory recommendations over patterns
    """
    
    INTENT_MATCH_MIN_SCORE = 0.5
    """Minimum score for intent matching in tool selection"""
    
    # === Parser Confidence Thresholds ===
    PARSER_HIGH_CONFIDENCE_THRESHOLD = 0.8
    """Minimum confidence for high-confidence parser routing (0.0-1.0)"""
    
    PARSER_MIN_CONFIDENCE_THRESHOLD = 0.7
    """Minimum confidence for parser-based tool selection (0.0-1.0)"""
    
    # === Dependency Resolution ===
    DETECT_CIRCULAR_DEPENDENCIES = True
    """Whether to detect and warn about circular dependencies"""
    
    MAX_DEPENDENCY_DEPTH = 10
    """Maximum allowed dependency chain depth before warning"""
    
    # === Domain Extraction ===
    DOMAIN_EXTRACTION_CACHE = True
    """Whether to cache domain extraction results for tools"""
    
    # === Tool Capability Analysis ===
    ANALYZE_TOOL_CAPABILITIES = True
    """Whether to analyze tool capabilities for planning"""
    
    ASSUME_PARALLEL_SAFE = True
    """Whether to assume tools are safe for parallel execution"""
    
    # === Query Decomposition ===
    DEFAULT_ACTION = "list"
    """Default action when no action verb is detected in query"""
    
    CONTEXT_KEYWORDS = ['them', 'those', 'previous', 'above', 'mentioned', 'from that']
    """Keywords that indicate the query needs previous results as context"""
