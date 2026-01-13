"""
Tool Recommendation Logic

Contains the complex parser-based tool recommendation logic.
Pattern constants and classification functions have been moved to the new modular structure.
"""
from typing import List, Dict, Any

from .config.intent_constants import (
    TASK_KEYWORDS,
    CALENDAR_KEYWORDS,
    EMAIL_KEYWORDS,
)
from .domain_detector import get_domain_detector


def _get_domain_keywords() -> Dict[str, List[str]]:
    """
    Get domain keywords from config or use defaults.
    
    Returns:
        Dict mapping domain names to keyword lists
    """
    try:
        from src.utils.config import load_config
        import yaml
        from pathlib import Path
        
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "intent_keywords.yaml"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                return {
                    'task': config.get('task_keywords', []),
                    'calendar': config.get('calendar_keywords', []),
                    'email': config.get('email_actions', []) + config.get('general_actions', [])
                }
    except Exception:
        pass
    
    return {
        'task': list(TASK_KEYWORDS),
        'calendar': list(CALENDAR_KEYWORDS),
        'email': list(EMAIL_KEYWORDS)
    }


def _detect_domain_hints(query: str) -> Dict[str, float]:
    """
    Detect weak domain hints from keywords (optional signal, not hardcoded filter).
    
    Returns:
        Dict mapping domain names to hint strength (0.0-1.0)
    """
    query_lower = query.lower()
    keywords = _get_domain_keywords()
    hints = {}
    
    for domain, keyword_list in keywords.items():
        matches = sum(1 for kw in keyword_list if kw.lower() in query_lower)
        if matches > 0:
            hints[domain] = min(matches * 0.1, 0.3)
    
    return hints


# Re-export domain detection functions from centralized DomainDetector
# This eliminates duplicate implementations across intent_patterns.py and utils/common.py
def has_email_keywords(query: str) -> bool:
    """Check if query contains email keywords (uses centralized DomainDetector)."""
    return get_domain_detector().is_domain(query, 'email')

def has_calendar_keywords(query: str) -> bool:
    """Check if query contains calendar keywords (uses centralized DomainDetector)."""
    return get_domain_detector().is_domain(query, 'calendar')

def has_task_keywords(query: str) -> bool:
    """Check if query contains task keywords (uses centralized DomainDetector)."""
    return get_domain_detector().is_domain(query, 'task')
