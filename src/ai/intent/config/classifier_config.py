"""
Intent Classification Configuration

Centralized configuration for intent classification, fast paths, and routing.
Eliminates hardcoded values in classifier.py.
"""
from typing import Dict, Any, List

# ============================================================================
# Classification Strategy Configuration
# ============================================================================

# Minimum confidence threshold for pattern-only routing (skip LLM)
# If pattern matching returns >= this confidence, LLM is not called
PATTERN_CONFIDENCE_THRESHOLD = 0.85

# Minimum query length to attempt LLM analysis
MIN_QUERY_LENGTH_FOR_LLM = 3

# ============================================================================
# Fast Paths - Instant routing for common queries
# These bypass ALL processing (pattern + LLM) for maximum speed
# ============================================================================

FAST_ROUTES: Dict[str, Dict[str, Any]] = {
    # Email fast paths
    "check my email": {"domain": "email", "intent": "search", "confidence": "high", "routes_to": "email_tool"},
    "check my emails": {"domain": "email", "intent": "search", "confidence": "high", "routes_to": "email_tool"},
    "show my emails": {"domain": "email", "intent": "search", "confidence": "high", "routes_to": "email_tool"},
    "any new emails": {"domain": "email", "intent": "search", "confidence": "high", "routes_to": "email_tool"},
    "unread emails": {"domain": "email", "intent": "search", "confidence": "high", "routes_to": "email_tool"},
    "my inbox": {"domain": "email", "intent": "search", "confidence": "high", "routes_to": "email_tool"},
    
    # Task fast paths
    "show my tasks": {"domain": "task", "intent": "list", "confidence": "high", "routes_to": "task_tool"},
    "my tasks": {"domain": "task", "intent": "list", "confidence": "high", "routes_to": "task_tool"},
    "what tasks do i have": {"domain": "task", "intent": "list", "confidence": "high", "routes_to": "task_tool"},
    "list my tasks": {"domain": "task", "intent": "list", "confidence": "high", "routes_to": "task_tool"},
    "my todos": {"domain": "task", "intent": "list", "confidence": "high", "routes_to": "task_tool"},
    "show my todos": {"domain": "task", "intent": "list", "confidence": "high", "routes_to": "task_tool"},
    
    # Calendar fast paths
    "what meetings today": {"domain": "calendar", "intent": "list", "confidence": "high", "routes_to": "calendar_tool"},
    "what meetings do i have": {"domain": "calendar", "intent": "list", "confidence": "high", "routes_to": "calendar_tool"},
    "show my calendar": {"domain": "calendar", "intent": "list", "confidence": "high", "routes_to": "calendar_tool"},
    "my calendar": {"domain": "calendar", "intent": "list", "confidence": "high", "routes_to": "calendar_tool"},
    "what's on my calendar": {"domain": "calendar", "intent": "list", "confidence": "high", "routes_to": "calendar_tool"},
    "my meetings": {"domain": "calendar", "intent": "list", "confidence": "high", "routes_to": "calendar_tool"},
    "my schedule": {"domain": "calendar", "intent": "list", "confidence": "high", "routes_to": "calendar_tool"},
}


def get_fast_route(query: str) -> Dict[str, Any] | None:
    """
    Check if query matches a fast path.
    
    Args:
        query: User query (will be lowercased and stripped)
        
    Returns:
        Fast route dict if matched, None otherwise
    """
    normalized = query.lower().strip()
    if normalized in FAST_ROUTES:
        result = FAST_ROUTES[normalized].copy()
        result["score"] = 10
        result["fast_path"] = True
        return result
    return None
