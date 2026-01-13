
"""
Constants for Weather Agent
"""

# Location Extraction Patterns
WEATHER_LOCATION_PATTERNS = [
    r'weather\s+(?:in|for|at)\s+(.+?)(?:\?|$)',
    r'(?:in|for|at)\s+(.+?)\s+weather',
    r'weather\s+(.+?)(?:\?|$)',
    r'(?:what\'?s?|how\'?s?)\s+(?:the\s+)?weather\s+(?:like\s+)?(?:in|for|at)\s+(.+?)(?:\?|$)',
]

# Cleanup Patterns
WEATHER_CLEANUP_SUFFIX = r'\s+(today|tomorrow|this week|right now|currently)$'
WEATHER_CLEANUP_PUNCTUATION = r'[?.!]+$'
