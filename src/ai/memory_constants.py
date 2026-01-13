"""
Conversation Memory Constants

Centralized constants for conversation memory management.
"""
from typing import List

# Log Prefix Constants
LOG_OK = "[OK]"
LOG_ERROR = "[ERROR]"
LOG_INFO = "[INFO]"
LOG_WARNING = "[WARNING]"

# Message Roles
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
VALID_ROLES: List[str] = [ROLE_USER, ROLE_ASSISTANT]

# Default Values
DEFAULT_MESSAGE_LIMIT = 10
DEFAULT_MAX_AGE_MINUTES = 30
DEFAULT_CLEANUP_DAYS = 30
DEFAULT_CONTEXT_LIMIT = 10
DEFAULT_CONVERSATION_LIST_LIMIT = 50
DEFAULT_CONVERSATION_MESSAGES_LIMIT = 1000  # Large limit to get all messages

# Preview and Display Limits
PREVIEW_MESSAGE_LENGTH = 50
DEFAULT_PREVIEW_TEXT = "New conversation"

# Session ID Display Length
SESSION_ID_DISPLAY_LENGTH = 8

# Entity Types for Context Extraction
ENTITY_TYPES: List[str] = ['people', 'meetings', 'tasks', 'emails']

