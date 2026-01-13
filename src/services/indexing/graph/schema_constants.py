"""
Graph Schema Constants

Centralized configuration for schema validation and limits.
No hardcoded values - all configuration in one place.
"""

# Schema Version
SCHEMA_VERSION = "2.0.0"  # Major version bump for new node/relationship types
SCHEMA_LAST_UPDATED = "2025-12-15"

# =============================================================================
# RELATIONSHIP STRENGTH & DECAY CONSTANTS
# =============================================================================

# Default strength for new relationships (0.0 - 1.0)
DEFAULT_RELATIONSHIP_STRENGTH = 0.5

# Maximum relationship strength
MAX_RELATIONSHIP_STRENGTH = 1.0

# Minimum relationship strength before pruning
MIN_RELATIONSHIP_STRENGTH = 0.05

# Strength increment per interaction (logarithmic growth)
STRENGTH_INCREMENT_BASE = 0.1

# Decay rate per day of inactivity (strength *= (1 - decay_rate))
DEFAULT_DECAY_RATE = 0.02  # 2% decay per day

# Days without interaction before decay starts
DECAY_GRACE_PERIOD_DAYS = 7

# =============================================================================
# RELATIONSHIP CONTEXT CONSTANTS
# =============================================================================

# Valid relationship context types (describes WHY entities are connected)
RELATIONSHIP_CONTEXT_TYPES = {
    "collaboration",    # Working together on projects/tasks
    "communication",    # Email/Slack exchanges
    "mentioned",        # One entity mentioned in context of another
    "scheduled",        # Calendar/meeting relationship
    "delegation",       # Task assignment/delegation
    "reference",        # Document/content reference
    "ownership",        # Owns/manages relationship
    "membership",       # Part of team/project/group
    "hierarchy",        # Reports to/manages
    "social",           # Personal/social connection
}

# Sentiment score range for relationships (-1.0 to 1.0)
MIN_RELATIONSHIP_SENTIMENT = -1.0
MAX_RELATIONSHIP_SENTIMENT = 1.0
NEUTRAL_SENTIMENT = 0.0

# Cross-app entity linking thresholds
CROSS_APP_LINKING_TITLE_SIMILARITY_THRESHOLD = 0.75
CROSS_APP_LINKING_ENTITY_OVERLAP_THRESHOLD = 0.5
CROSS_APP_LINKING_TIME_PROXIMITY_HOURS = 24  # Events within 24h may be related

# =============================================================================
# TEMPORAL CONSTANTS
# =============================================================================

# Granularity levels for TimeBlock nodes
TIME_GRANULARITIES = {"hour", "day", "week", "month", "quarter", "year"}
DEFAULT_TIME_GRANULARITY = "day"

# TimeBlock ID format: "timeblock:{granularity}:{iso_date}"
TIMEBLOCK_ID_PREFIX = "timeblock"

# Maximum timeblocks to create in a single batch
MAX_TIMEBLOCKS_PER_BATCH = 365

# =============================================================================
# CONFIDENCE THRESHOLDS
# =============================================================================

# Minimum confidence for entity resolution matches
MIN_ENTITY_RESOLUTION_CONFIDENCE = 0.6

# High confidence threshold (auto-merge entities)
HIGH_CONFIDENCE_THRESHOLD = 0.9

# Low confidence threshold (require user confirmation)
LOW_CONFIDENCE_THRESHOLD = 0.5

# Query Defaults
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_LIMIT = 1000
DEFAULT_TRAVERSAL_DEPTH = 2
MAX_TRAVERSAL_DEPTH = 10

# Property Validation
MAX_STRING_LENGTH = 10000
MAX_ARRAY_LENGTH = 1000
MIN_STRING_LENGTH = 1

# Email Validation
EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
MAX_EMAIL_LENGTH = 254

# Numeric Validation
MIN_RECEIPT_TOTAL = 0.0
MAX_RECEIPT_TOTAL = 1000000.0  # $1M limit for sanity
MIN_CONFIDENCE_SCORE = 0.0
MAX_CONFIDENCE_SCORE = 1.0

# Date Validation
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
ISO_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

# Status Values
VALID_ACTION_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
VALID_PRIORITY_LEVELS = {"low", "medium", "high", "urgent"}

# Property Type Categories
STRING_PROPERTIES = {
    "subject", "sender", "body", "email", "name", "filename", 
    "merchant", "description", "title", "thread_id", "status"
}

NUMERIC_PROPERTIES = {
    "total", "confidence", "priority"
}

DATE_PROPERTIES = {
    "date", "start_time", "end_time", "created_at", "updated_at"
}

ARRAY_PROPERTIES = {
    "recipients", "tags", "categories", "attachments"
}

BOOLEAN_PROPERTIES = {
    "is_read", "is_starred", "is_archived", "is_deleted"
}

# Error Messages
ERROR_MISSING_REQUIRED_PROPERTY = "Missing required property '{property}' for node type '{node_type}'"
ERROR_INVALID_PROPERTY_TYPE = "Invalid type for property '{property}': expected {expected}, got {actual}"
ERROR_INVALID_RELATIONSHIP = "Invalid relationship: {from_type} -[{rel_type}]-> {to_type}"
ERROR_PROPERTY_TOO_LONG = "Property '{property}' exceeds maximum length of {max_length}"
ERROR_PROPERTY_TOO_SHORT = "Property '{property}' is below minimum length of {min_length}"
ERROR_INVALID_EMAIL_FORMAT = "Invalid email format for property '{property}': {value}"
ERROR_INVALID_DATE_FORMAT = "Invalid date format for property '{property}': {value}"
ERROR_VALUE_OUT_OF_RANGE = "Value for property '{property}' is out of range: {value} (min: {min}, max: {max})"
ERROR_INVALID_STATUS = "Invalid status '{value}' for property '{property}'. Valid values: {valid}"
