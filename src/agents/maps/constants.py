
"""
Constants for Maps Agent
"""

# Regex Patterns
DISTANCE_FROM_TO = r'from\s+([^to]+)\s+to\s+(.+)'
DISTANCE_BETWEEN_AND = r'between\s+([^and]+)\s+and\s+(.+)'
DIRECTIONS_TO = r'(?:get to|navigate to|directions to)\s+(.+)'
GEOCODE_LOCATION = r'(?:where is|location of|find|coordinates of)\s+(.+)'
CLEAN_PUNCTUATION = r'[?.!]+$'
