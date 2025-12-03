"""
Notion Parser Constants - Centralized configuration for Notion parsing

This module defines all constants used across the Notion parser module
to ensure consistency and enable easy configuration changes.

Usage:
    from .constants import NotionParserConfig
    
    limit = NotionParserConfig.DEFAULT_SEARCH_LIMIT
    confidence_threshold = NotionParserConfig.DEFAULT_CONFIDENCE_THRESHOLD
"""


class NotionParserConfig:
    """Configuration constants for Notion parser"""
    
    # Confidence thresholds
    DEFAULT_CONFIDENCE_THRESHOLD = 0.6
    LOW_CONFIDENCE_THRESHOLD = 0.5
    HIGH_CONFIDENCE_THRESHOLD = 0.85
    
    # LLM configuration
    LLM_TEMPERATURE = 0.1
    LLM_MAX_TOKENS = 2000
    LLM_MAX_TOKENS_BRIEF = 1500
    LLM_MAX_TOKENS_SUMMARY = 2000
    
    # Search limits
    DEFAULT_SEARCH_LIMIT = 5
    MAX_SEARCH_LIMIT = 50
    MIN_SEARCH_LIMIT = 1
    
    # Learning system configuration
    MAX_CORRECTIONS_STORED = 100
    MAX_SUCCESSFUL_QUERIES_STORED = 50
    SIMILARITY_THRESHOLD_LOW = 0.3
    SIMILARITY_THRESHOLD_HIGH = 0.6
    DEFAULT_SIMILAR_EXAMPLES_LIMIT = 3
    
    # Semantic matching configuration
    DEFAULT_SEMANTIC_THRESHOLD = 0.7
    GEMINI_THRESHOLD_MULTIPLIER = 0.95
    
    # Notion validation
    MIN_TITLE_LENGTH = 1
    MAX_TITLE_LENGTH = 200
    MIN_CONTENT_LENGTH = 0
    MAX_CONTENT_LENGTH = 10000
    
    # Display limits
    MAX_PAGES_DISPLAY = 10
    MAX_PAGES_PREVIEW = 5
    MAX_DATABASES_DISPLAY = 10


class NotionActionTypes:
    """All supported Notion actions"""
    SEARCH = "search"
    CREATE_PAGE = "create_page"
    UPDATE_PAGE = "update_page"
    GET_PAGE = "get_page"
    QUERY_DATABASE = "query_database"
    CREATE_DATABASE_ENTRY = "create_database_entry"
    UPDATE_DATABASE_ENTRY = "update_database_entry"
    CROSS_PLATFORM_SYNTHESIS = "cross_platform_synthesis"
    AUTO_MANAGE_DATABASE = "auto_manage_database"
    
    @classmethod
    def all(cls):
        """Get all action types"""
        return [
            cls.SEARCH, cls.CREATE_PAGE, cls.UPDATE_PAGE, cls.GET_PAGE,
            cls.QUERY_DATABASE, cls.CREATE_DATABASE_ENTRY, cls.UPDATE_DATABASE_ENTRY,
            cls.CROSS_PLATFORM_SYNTHESIS, cls.AUTO_MANAGE_DATABASE
        ]


class NotionEntityTypes:
    """Entity types extracted from Notion queries"""
    TITLE = "title"
    DATABASE_ID = "database_id"
    PAGE_ID = "page_id"
    QUERY = "query"
    PROPERTIES = "properties"
    CONTENT = "content"
    FILTERS = "filters"
    SORTS = "sorts"
    NUM_RESULTS = "num_results"
    DATABASES = "databases"
    EXTERNAL_CONTEXTS = "external_contexts"
    ACTION_TYPE = "action_type"
    SOURCE_SYSTEM = "source_system"
    ACTION_DATA = "action_data"


def get_action_validation_rules(action: str) -> dict:
    """
    Get validation rules for a Notion action
    
    Args:
        action: Notion action type
        
    Returns:
        Dictionary of required and optional parameters
    """
    rules = {
        NotionActionTypes.SEARCH: {
            "required": ["query", "database_id"],
            "optional": ["num_results"]
        },
        NotionActionTypes.CREATE_PAGE: {
            "required": ["database_id"],
            "optional": ["title", "properties", "content"]
        },
        NotionActionTypes.UPDATE_PAGE: {
            "required": ["page_id"],
            "optional": ["title", "properties", "content"]
        },
        NotionActionTypes.GET_PAGE: {
            "required": ["page_id"],
            "optional": []
        },
        NotionActionTypes.QUERY_DATABASE: {
            "required": ["database_id"],
            "optional": ["filters", "sorts"]
        },
        NotionActionTypes.CREATE_DATABASE_ENTRY: {
            "required": ["database_id"],
            "optional": ["properties"]
        },
        NotionActionTypes.UPDATE_DATABASE_ENTRY: {
            "required": ["page_id"],
            "optional": ["properties"]
        },
        NotionActionTypes.CROSS_PLATFORM_SYNTHESIS: {
            "required": ["query", "databases"],
            "optional": ["external_contexts"]
        },
        NotionActionTypes.AUTO_MANAGE_DATABASE: {
            "required": ["database_id", "action_type", "source_system", "action_data"],
            "optional": []
        },
    }
    
    return rules.get(action, {"required": [], "optional": []})

