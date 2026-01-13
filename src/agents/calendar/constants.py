
"""
Constants for Calendar Agent
"""

# System emails to block during attendee resolution
SYSTEM_EMAIL_BLOCKLIST = [
    'noreply', 'no-reply', 'notifications', 'alert', 
    'bounce', 'support', 'donotreply'
]

# Patterns for regex-based title extraction fallback
TITLE_FALLBACK_PATTERNS = [
    r'(?:schedule|book|create|set up|add)\s+(?:a\s+)?(.+?)\s+(?:meeting|session|appointment|call|event)',
    r'(?:schedule|book|create|set up|add)\s+(?:a\s+)?(.+?)\s+(?:tomorrow|today|at\s+\d|for\s+\d|on\s+)',
    r'(.+?)\s+(?:meeting|session|appointment|call)\s+(?:tomorrow|today|at\s+\d|for\s+\d)',
]

# Regex to detect email pattern
EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

# Regex to detect duration in end_time (e.g., "1 hour")
DURATION_IN_ENDTIME_PATTERN = r'(\d+)\s*(?:h|hr|hour|min|m\b)'

# AQL Query for Person Resolution
AQL_RESOLVE_PERSON = """
    FOR p IN Person 
        FILTER CONTAINS(LOWER(p.name), LOWER(@name)) 
        FILTER NOT CONTAINS(LOWER(p.email), 'noreply')
        FILTER NOT CONTAINS(LOWER(p.email), 'no-reply')
        FILTER NOT CONTAINS(LOWER(p.email), 'notifications')
        FILTER NOT CONTAINS(LOWER(p.email), 'alert')
        FILTER NOT CONTAINS(LOWER(p.email), 'support')
        SORT LENGTH(p.name) ASC
        LIMIT 1
        RETURN p
"""
