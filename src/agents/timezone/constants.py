
"""
Constants for Timezone Agent
"""

# Location Extraction Patterns
LOCATION_PATTERNS = [
    r'time\s+(?:is\s+it\s+)?in\s+(.+?)(?:\?|$)',
    r'what\s+time\s+(?:is\s+it\s+)?in\s+(.+?)(?:\?|$)',
    r'current\s+time\s+in\s+(.+?)(?:\?|$)',
    r'time\s+in\s+(.+?)(?:\?|$)',
]

# Time Difference Patterns
TIME_DIFF_BETWEEN_AND = r'between\s+([^and]+)\s+and\s+(.+?)(?:\?|$)'

# Time Conversion Patterns
TIME_CONVERT_PATTERNS = [
    # "what time is it in X when it's TIME in Y"
    r"what\s+time\s+(?:is\s+it\s+)?in\s+(.+?)\s+when\s+(?:it'?s?\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+in\s+(.+?)(?:\?|$)",
    # "when it's TIME in X, what time in Y"
    r"when\s+(?:it'?s?\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+in\s+(.+?)[,\s]+what\s+time\s+(?:is\s+it\s+)?in\s+(.+?)(?:\?|$)",
    # "convert TIME in X to Y"
    r"convert\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:in\s+)?(.+?)\s+to\s+(.+?)(?:\s+time)?(?:\?|$)",
    # "TIME X time in Y" (e.g., "3pm New York time in Tokyo")
    r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(.+?)\s+time\s+in\s+(.+?)(?:\?|$)",
]

# Time Parse Patterns
TIME_12H = r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)'
TIME_24H = r'(\d{1,2}):(\d{2})'
TIME_SIMPLE_INT = r'^(\d{1,2})$'

CLEAN_PUNCTUATION = r'[?.!]+$'
CLEAN_LEADING_THE = r'^(?:the\s+)'
