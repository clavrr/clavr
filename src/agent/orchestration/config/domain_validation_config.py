"""
Domain Validation Configuration - Centralized config for domain validation behavior

This module provides all configuration values for domain detection and validation,
eliminating hardcoded thresholds and weights scattered throughout the codebase.
"""

from typing import Dict, Tuple


class DomainValidationConfig:
    """Configuration for domain validation thresholds, weights, and behavior"""
    
    # ============================================================================
    # SCORING WEIGHTS - Used in detect_domain() for pattern matching
    # ============================================================================
    
    # How much each pattern type contributes to domain score (0.0 - 1.0)
    STRONG_INDICATOR_WEIGHT = 0.4      # Regex patterns like r'\btask\b'
    KEYWORD_WEIGHT = 0.2               # Direct keyword matches
    QUESTION_PATTERN_WEIGHT = 0.15     # Question-specific patterns
    ACTION_PATTERN_WEIGHT = 0.15       # Action-specific patterns
    
    # ============================================================================
    # CONFIDENCE THRESHOLDS - Used in routing validation
    # ============================================================================
    
    # Threshold for detecting mixed-domain queries (when multiple domains score high)
    MIXED_DOMAIN_THRESHOLD = 0.3
    
    # Confidence level when mixed domain is detected
    MIXED_DOMAIN_CONFIDENCE = 0.6
    
    # Confidence for mixed query that matches target domain
    MIXED_QUERY_MATCH_CONFIDENCE = 0.7
    
    # Confidence for mixed query that does NOT match target domain
    MIXED_QUERY_MISMATCH_CONFIDENCE = 0.4
    
    # Confidence when domain cannot be detected (GENERAL domain)
    GENERAL_DOMAIN_CONFIDENCE = 0.5
    
    # Threshold above which to reject mismatches in strict mode
    STRICT_MODE_THRESHOLD = 0.6
    
    # Confidence assigned when mismatch is rejected
    MISMATCH_REJECT_CONFIDENCE = 0.2
    
    # Confidence assigned when mismatch is warned about (non-strict mode)
    MISMATCH_WARNING_CONFIDENCE = 0.4
    
    # Minimum confidence required for execution plan validation to pass
    MIN_VALIDATION_CONFIDENCE = 0.3
    
    # Bonus confidence added for exact domain match
    EXACT_MATCH_BONUS = 0.15
    
    # ============================================================================
    # WEIGHTED AVERAGING - Used when combining domain and parser confidence
    # ============================================================================
    
    # Weight for domain detection confidence in combined scoring
    DOMAIN_DETECTION_WEIGHT = 0.7
    
    # Weight for parser confidence in combined scoring
    PARSER_CONFIDENCE_WEIGHT = 0.3
    
    # ============================================================================
    # MISMATCH MESSAGES - Maps (detected_domain, target_domain) to user messages
    # ============================================================================
    
    MISMATCH_MESSAGES: Dict[Tuple[str, str], str] = {
        ('task', 'calendar'): (
            "This appears to be a task query, not a calendar query. "
            "Use the task tool instead."
        ),
        ('calendar', 'task'): (
            "This appears to be a calendar query, not a task query. "
            "Use the calendar tool instead."
        ),
        ('email', 'task'): (
            "This appears to be an email query, not a task query. "
            "Use the email tool instead."
        ),
        ('email', 'calendar'): (
            "This appears to be an email query, not a calendar query. "
            "Use the email tool instead."
        ),
        ('task', 'email'): (
            "This appears to be a task query, not an email query. "
            "Use the task tool instead."
        ),
        ('calendar', 'email'): (
            "This appears to be a calendar query, not an email query. "
            "Use the calendar tool instead."
        ),
        ('notion', 'task'): (
            "This appears to be a Notion query, not a task query. "
            "Use the Notion tool instead."
        ),
        ('notion', 'calendar'): (
            "This appears to be a Notion query, not a calendar query. "
            "Use the Notion tool instead."
        ),
        ('notion', 'email'): (
            "This appears to be a Notion query, not an email query. "
            "Use the Notion tool instead."
        ),
        ('task', 'notion'): (
            "This appears to be a task query, not a Notion query. "
            "Use the task tool instead."
        ),
        ('calendar', 'notion'): (
            "This appears to be a calendar query, not a Notion query. "
            "Use the calendar tool instead."
        ),
        ('email', 'notion'): (
            "This appears to be an email query, not a Notion query. "
            "Use the email tool instead."
        ),
    }


def get_mismatch_message_for_domains(detected_domain, target_domain) -> str:
    """
    Get mismatch message for domain pair.
    
    Args:
        detected_domain: Detected Domain enum or string
        target_domain: Target Domain enum or string
        
    Returns:
        User-friendly mismatch message
    """
    # Handle both enum and string inputs
    detected_key = detected_domain.value if hasattr(detected_domain, 'value') else detected_domain
    target_key = target_domain.value if hasattr(target_domain, 'value') else target_domain
    
    return DomainValidationConfig.MISMATCH_MESSAGES.get(
        (detected_key, target_key),
        f"Domain mismatch: detected {detected_key}, routing to {target_key}"
    )
