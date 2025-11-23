"""
Tool Constants - Centralized configuration for all tools

This module defines all constants used across tools to ensure consistency
and enable easy configuration changes.

Usage:
    from .constants import ToolConfig
    
    confidence_threshold = ToolConfig.HIGH_CONFIDENCE_THRESHOLD
    max_display_items = ToolConfig.MAX_DISPLAY_ITEMS
"""


class ToolConfig:
    """Configuration constants for tools"""
    
    # Parser integration confidence thresholds
    HIGH_CONFIDENCE_THRESHOLD = 0.6
    LOW_CONFIDENCE_THRESHOLD = 0.5
    DEFAULT_CONFIDENCE_THRESHOLD = 0.5
    
    # LLM configuration
    DEFAULT_LLM_TEMPERATURE = 0.1
    DEFAULT_LLM_MAX_TOKENS = 2000
    
    # Display limits
    MAX_DISPLAY_ITEMS = 3
    MAX_DISPLAY_ITEMS_EXTENDED = 5
    MAX_PREVIEW_ITEMS = 3
    
    # Default values
    DEFAULT_ACTION_FALLBACK = "list"
    DEFAULT_ACTION_SEARCH = "search"


class ParserIntegrationConfig:
    """Configuration for parser integration in tools"""
    
    # Confidence thresholds for using parser results
    USE_PARSED_ACTION_THRESHOLD = ToolConfig.HIGH_CONFIDENCE_THRESHOLD
    LOW_CONFIDENCE_WARNING_THRESHOLD = ToolConfig.LOW_CONFIDENCE_THRESHOLD
    
    # Default action fallback (used when action is None or needs to be overridden)
    DEFAULT_ACTION_FALLBACK = ToolConfig.DEFAULT_ACTION_FALLBACK
    
    # Actions that can be overridden by parser
    OVERRIDABLE_ACTIONS = ["list", "search"]


class ToolLimits:
    """Default limits for tool operations"""
    
    MAX_EMAILS_DISPLAY = 3
    MAX_TASKS_DISPLAY = 10
    MAX_EVENTS_DISPLAY = 10
    MAX_ANALYTICS_ITEMS = 5
    MAX_ATTENDEES_DISPLAY = 3
    MAX_CONFLICTS_DISPLAY = 3
    MAX_FREE_SLOTS_DISPLAY = 10
    MAX_RECEIPTS_DISPLAY = 5
    MAX_BODY_PREVIEW_LENGTH = 100
    DEFAULT_TASK_LIST_LIMIT = 50
    MAX_GOOGLE_RESULTS = 100


class TaskTimingConfig:
    """Configuration for task timing relative to calendar events"""
    
    PREP_TASK_HOURS_BEFORE_EVENT = 2
    FOLLOWUP_TASK_DAYS_AFTER_EVENT = 1

