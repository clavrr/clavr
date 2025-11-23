"""
Notion Tool Constants

Configuration constants and patterns for Notion operations.
"""

# Default values
DEFAULT_SEARCH_RESULTS = 5
MAX_SEARCH_RESULTS = 50
DEFAULT_PAGE_CONTENT_LENGTH = 2000

# LLM configuration constants
LLM_TEMPERATURE = 0.7  # Default temperature for LLM calls

# Display limits
MAX_PAGES_TO_DISPLAY = 50  # Maximum pages to display in formatted results

# Action types
ACTION_SEARCH = "search"
ACTION_CREATE_PAGE = "create_page"
ACTION_UPDATE_PAGE = "update_page"
ACTION_GET_PAGE = "get_page"
ACTION_QUERY_DATABASE = "query_database"
ACTION_CROSS_PLATFORM_SYNTHESIS = "cross_platform_synthesis"
ACTION_AUTO_MANAGE_DATABASE = "auto_manage_database"

# Source systems for auto-management
SOURCE_CALENDAR = "calendar"
SOURCE_SLACK = "slack"
SOURCE_EMAIL = "email"
SOURCE_TASKS = "tasks"

# Action types for auto-management
ACTION_MEETING_HELD = "meeting_held"
ACTION_EMAIL_SENT = "email_sent"
ACTION_TASK_COMPLETED = "task_completed"
ACTION_MESSAGE_POSTED = "message_posted"

# Property types
PROPERTY_TITLE = "title"
PROPERTY_RICH_TEXT = "rich_text"
PROPERTY_NUMBER = "number"
PROPERTY_SELECT = "select"
PROPERTY_MULTI_SELECT = "multi_select"
PROPERTY_DATE = "date"
PROPERTY_CHECKBOX = "checkbox"
PROPERTY_URL = "url"
PROPERTY_EMAIL = "email"
PROPERTY_PHONE = "phone_number"

