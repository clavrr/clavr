"""
Node ID Utilities - Standardized ID generation for knowledge graph nodes

This module provides centralized functions for generating deterministic node IDs
to ensure consistency across all crawlers and enable cross-source entity resolution.
"""
import hashlib
from typing import Optional


def generate_person_id(
    email: Optional[str] = None,
    source: Optional[str] = None,
    source_id: Optional[str] = None
) -> str:
    """
    Generate a standardized Person node ID.
    
    Uses email-first strategy to enable cross-source merging:
    - Same email across Gmail, Calendar, Drive, Slack → same Person node ID
    - Falls back to source-prefixed ID for platforms without email
    
    Args:
        email: Email address (preferred - enables cross-source merging)
        source: Source platform name (e.g., 'slack', 'notion', 'asana')
        source_id: Platform-specific user ID
        
    Returns:
        Deterministic node ID like 'person_a1b2c3d4e5f6' (from email)
        or 'person_slack_U12345' (fallback)
        
    Raises:
        ValueError: If neither email nor (source + source_id) provided
        
    Examples:
        >>> generate_person_id(email='alice@company.com')
        'person_b7e6c8da1a2f'
        
        >>> generate_person_id(source='slack', source_id='U12345678')
        'person_slack_U12345678'
    """
    if email:
        # Normalize email for consistent hashing
        normalized = email.lower().strip()
        hash_val = hashlib.md5(normalized.encode()).hexdigest()[:12]
        return f"person_{hash_val}"
    elif source and source_id:
        # Normalize source_id to be URL/document-safe
        safe_id = str(source_id).replace('-', '_').replace('@', '_at_').replace('.', '_')
        return f"person_{source}_{safe_id}"
    else:
        raise ValueError("Either email or (source + source_id) required for Person ID generation")


def generate_identity_id(identity_type: str, value: str) -> str:
    """
    Generate a standardized Identity node ID.
    
    Args:
        identity_type: Type of identity (e.g., 'email', 'phone', 'slack')
        value: The identity value
        
    Returns:
        Deterministic node ID like 'identity_email_a1b2c3d4e5f6'
    """
    normalized = value.lower().strip()
    hash_val = hashlib.md5(normalized.encode()).hexdigest()[:12]
    return f"identity_{identity_type}_{hash_val}"
