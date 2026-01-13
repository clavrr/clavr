"""
Preprocessing Module - Text normalization and query enhancement

Provides preprocessing utilities for agent queries:
- TextNormalizer: Spell-check, typo correction, dialect transformation
- Normalization rules: Common typos, action corrections, dialect patterns

Usage:
    from src.ai.preprocessing import TextNormalizer, normalize_query
    
    normalizer = TextNormalizer()
    result = normalizer.normalize("schedul meeing wit john tomorow")
    # result['normalized_text'] = "schedule meeting with john tomorrow"
    
    # Quick helper function
    cleaned = normalize_query("lemme check my emails")
    # cleaned = "let me check my email"
"""

from typing import Optional
from .text_normalizer import TextNormalizer

from .normalization_rules import (
    GLOBAL_TYPOS,
    DOMAIN_RULES,
    DIALECT_TRANSFORMATIONS,
)


def normalize_query(query: str, domain: Optional[str] = None) -> str:
    """
    Quick helper to normalize a query string.
    
    Args:
        query: Raw user query
        domain: Optional domain hint (email, calendar, tasks)
        
    Returns:
        Normalized query string
    """
    normalizer = TextNormalizer()
    result = normalizer.normalize(query, context={'domain': domain})
    return result['normalized_text']


__all__ = [
    'TextNormalizer',
    'GLOBAL_TYPOS',
    'DOMAIN_RULES',
    'DIALECT_TRANSFORMATIONS',
    'normalize_query',
]

