"""
Configuration constants for ClavrAgent

Centralizes all hardcoded values, patterns, and timeouts used by ClavrAgent.
"""


class ClavrAgentConfig:
    """Configuration constants for ClavrAgent"""
    
    # === Streaming Configuration ===
    DEFAULT_CHUNK_SIZE = 3
    """Default number of characters per chunk when streaming text"""
    
    STREAM_CHUNK_DELAY_SECONDS = 0.02
    """Delay between text chunks for natural streaming effect (20ms)"""
    
    MAX_STREAM_WAIT_TIME_SECONDS = 30.0
    """Maximum time to wait for execution when streaming (30 seconds)"""
    
    STREAM_EVENT_TIMEOUT_SECONDS = 0.1
    """Timeout for waiting for events in stream loop (100ms)"""
    
    STREAM_TASK_COMPLETION_TIMEOUT_SECONDS = 5.0
    """Timeout for ensuring execution task completes (5 seconds)"""
    
    # === LLM Enhancement Configuration ===
    ENHANCEMENT_LLM_TEMPERATURE = 0.7
    """Temperature for LLM when enhancing robotic responses"""
    
    # === Memory System Configuration ===
    MEMORY_CLEAR_MAX_AGE_DAYS = 30
    """Maximum age in days for clearing old memory patterns"""
    
    # === Statistics Keys ===
    STATS_QUERIES_PROCESSED = "queries_processed"
    STATS_ORCHESTRATED_QUERIES = "orchestrated_queries"
    STATS_SIMPLE_QUERIES = "simple_queries"
    STATS_SUCCESS_RATE = "success_rate"
    STATS_TOTAL_EXECUTION_TIME = "total_execution_time"
    STATS_AVERAGE_EXECUTION_TIME = "average_execution_time"
    
    # === Robotic Response Patterns ===
    # String patterns that indicate robotic responses
    ROBOTIC_STRING_PATTERNS = [
        "You have",
        "event(s):",
        "task(s):",
        "email(s):",
        "Here are",
        "Here is",
        "Results:",
        "Query:",
        "•",  # Bullet points
        "**",  # Markdown bold
    ]
    
    # Regex patterns for more complex robotic response detection
    ROBOTIC_REGEX_PATTERNS = [
        r'You have \d+ events?:',
        r'You have \d+ event\(s\):',
        r'^\s*[\*\-•]\s',  # Bullet points at start of line
        r'^\d+\.\s',  # Numbered lists
    ]

