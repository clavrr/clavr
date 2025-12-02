"""
Formatting Module - Response formatting and context synthesis

Provides:
- ResponseFormatter: Entity-aware response formatting
- ContextSynthesizer: Entity-aware context synthesis (legacy, see orchestration/components for cross-domain synthesis)
"""

from .response_formatter import ResponseFormatter

# Note: ContextSynthesizer in orchestration/components is for cross-domain synthesis
# The root-level context_synthesizer.py is legacy and can be removed if unused

__all__ = [
    'ResponseFormatter'
]

