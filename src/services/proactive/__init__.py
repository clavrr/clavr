"""
Proactive Services Package

Services for proactive intelligence delivery:
- ProactiveContextService: Meeting prep and attendee context
- CrossStackContext: 360° topic summaries across all sources
"""
from .context_service import ProactiveContextService

# Backward-compatible alias (deprecated)
ContextService = ProactiveContextService

__all__ = [
    "ProactiveContextService",
    "ContextService",  # Deprecated alias for backward compatibility
]
