
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

# AQL Query for Person Resolution — Primary (Person collection, always exists)
# Scores: exact match (1.0) > starts with (0.8) > contains (0.6)
AQL_RESOLVE_PERSON = """
LET name_lower = LOWER(@name)
FOR p IN Person
    FILTER p.email != null AND p.email != ""
    LET p_name = LOWER(p.name)
    FILTER CONTAINS(p_name, name_lower)
    LET match_score = (
        p_name == name_lower ? 1.0 :
        STARTS_WITH(p_name, name_lower) ? 0.8 :
        0.6
    )
    FILTER NOT CONTAINS(LOWER(p.email), 'noreply')
    FILTER NOT CONTAINS(LOWER(p.email), 'no-reply')
    FILTER NOT CONTAINS(LOWER(p.email), 'notifications')
    FILTER NOT CONTAINS(LOWER(p.email), 'alert')
    FILTER NOT CONTAINS(LOWER(p.email), 'bounce')
    SORT match_score DESC, LENGTH(p.name) ASC
    LIMIT 3
    RETURN { name: p.name, email: p.email, score: match_score, source: "person" }
"""

# Supplementary AQL: Search Contact collection
AQL_RESOLVE_CONTACT = """
LET name_lower = LOWER(@name)
FOR c IN Contact
    FILTER c.email != null AND c.email != ""
    LET c_name = LOWER(c.name || "")
    LET c_email = LOWER(c.email)
    FILTER CONTAINS(c_name, name_lower) OR CONTAINS(c_email, name_lower)
    LET match_score = (
        c_name == name_lower ? 1.0 :
        STARTS_WITH(c_name, name_lower) ? 0.8 :
        CONTAINS(c_name, name_lower) ? 0.6 :
        0.4
    )
    SORT match_score DESC
    LIMIT 3
    RETURN { name: c.name, email: c.email, score: match_score, source: "contact" }
"""

# Supplementary AQL: Search KNOWS edges (user's known contacts with aliases)
AQL_RESOLVE_KNOWS = """
LET name_lower = LOWER(@name)
FOR edge IN KNOWS
    LET person = DOCUMENT(edge._to)
    FILTER person != null AND person.email != null AND person.email != ""
    LET alias_match = (
        edge.aliases != null AND LENGTH(
            FOR a IN (edge.aliases || [])
                FILTER CONTAINS(LOWER(a), name_lower)
                RETURN 1
        ) > 0
    )
    LET name_match = CONTAINS(LOWER(person.name || ""), name_lower)
    FILTER alias_match OR name_match
    LET match_score = (alias_match ? 0.9 : 0.7)
    LET freq_boost = MIN([(edge.frequency || 0) / 100.0, 0.3])
    SORT match_score + freq_boost DESC
    LIMIT 3
    RETURN { name: person.name, email: person.email, score: match_score + freq_boost, source: "knows" }
"""


