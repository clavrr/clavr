"""
Proactive Services Package

Services for proactive intelligence delivery:
- ContextService: Meeting prep and attendee context
- CrossStackContext: 360° topic summaries across all sources
"""
from .context_service import ContextService

__all__ = [
    "ContextService",
]
