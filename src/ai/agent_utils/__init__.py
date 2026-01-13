"""
Agent Utils Module - Shared utility functions for agent operations

Provides:
- Common query detection, validation, and formatting logic
- Multi-step response formatting
- Text processing utilities
"""

from .common import (
    # Query Detection
    has_task_keywords,
    has_calendar_keywords,
    has_email_keywords,
    has_notion_keywords,
    is_task_creation_query,
    is_calendar_creation_query,
    is_notion_creation_query,
    should_not_decompose_query,
    get_query_domain,
    get_query_domains,
    is_multi_domain_query,
    extract_query_entities,
    
    # Text Processing
    clean_response_text,
    format_multi_step_response,
    extract_search_topic,
    truncate_text,
    normalize_query,
)

__all__ = [
    # Query Detection
    'has_task_keywords',
    'has_calendar_keywords',
    'has_email_keywords',
    'has_notion_keywords',
    'is_task_creation_query',
    'is_calendar_creation_query',
    'is_notion_creation_query',
    'should_not_decompose_query',
    'get_query_domain',
    'get_query_domains',
    'is_multi_domain_query',
    'extract_query_entities',
    
    # Text Processing
    'clean_response_text',
    'format_multi_step_response',
    'extract_search_topic',
    'truncate_text',
    'normalize_query',
]
