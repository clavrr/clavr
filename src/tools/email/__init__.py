"""
Email tool package - modular email operations

This package provides a refactored, maintainable structure for email operations:
- actions.py: Email actions (send, reply, mark, delete, archive, organize)
- search.py: Email search and listing operations
- indexing.py: Knowledge graph integration and email indexing
- categorization.py: Email categorization and insights
- constants.py: Configuration constants and patterns
- utils.py: Shared utility functions
"""

from .actions import EmailActions
from .search import EmailSearch
from .indexing import EmailIndexing
from .categorization import EmailCategorization

__all__ = [
    'EmailActions',
    'EmailSearch',
    'EmailIndexing',
    'EmailCategorization',
]
