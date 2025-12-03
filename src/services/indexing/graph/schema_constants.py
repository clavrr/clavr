"""
Graph Schema Constants

Centralized configuration for schema validation and limits.
No hardcoded values - all configuration in one place.
"""

# Schema Version
SCHEMA_VERSION = "1.0.0"
SCHEMA_LAST_UPDATED = "2025-11-18"

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
