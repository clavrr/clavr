"""
Notion tool package - modular Notion operations

This package provides a refactored, maintainable structure for Notion operations:
- search.py: Graph-grounded search and cross-platform synthesis
- actions.py: Page CRUD operations and database queries
- auto_management.py: Autonomous database management
- constants.py: Configuration constants and patterns
- utils.py: Shared utility functions
"""

from .search import NotionSearch
from .actions import NotionActions
from .auto_management import NotionAutoManagement
from .constants import (
    DEFAULT_SEARCH_RESULTS,
    MAX_SEARCH_RESULTS,
    DEFAULT_PAGE_CONTENT_LENGTH,
    ACTION_SEARCH,
    ACTION_CREATE_PAGE,
    ACTION_UPDATE_PAGE,
    ACTION_GET_PAGE,
    ACTION_QUERY_DATABASE,
    ACTION_CROSS_PLATFORM_SYNTHESIS,
    ACTION_AUTO_MANAGE_DATABASE,
    SOURCE_CALENDAR,
    SOURCE_SLACK,
    SOURCE_EMAIL,
    SOURCE_TASKS,
    ACTION_MEETING_HELD,
    ACTION_EMAIL_SENT,
    ACTION_TASK_COMPLETED,
    ACTION_MESSAGE_POSTED,
)

__all__ = [
    # Classes
    'NotionSearch',
    'NotionActions',
    'NotionAutoManagement',
    
    # Constants
    'DEFAULT_SEARCH_RESULTS',
    'MAX_SEARCH_RESULTS',
    'DEFAULT_PAGE_CONTENT_LENGTH',
    'ACTION_SEARCH',
    'ACTION_CREATE_PAGE',
    'ACTION_UPDATE_PAGE',
    'ACTION_GET_PAGE',
    'ACTION_QUERY_DATABASE',
    'ACTION_CROSS_PLATFORM_SYNTHESIS',
    'ACTION_AUTO_MANAGE_DATABASE',
    'SOURCE_CALENDAR',
    'SOURCE_SLACK',
    'SOURCE_EMAIL',
    'SOURCE_TASKS',
    'ACTION_MEETING_HELD',
    'ACTION_EMAIL_SENT',
    'ACTION_TASK_COMPLETED',
    'ACTION_MESSAGE_POSTED',
]



