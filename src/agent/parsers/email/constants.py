"""
Email Parser Constants - Centralized configuration for email parsing

This module defines all constants used across the email parser module
to ensure consistency and enable easy configuration changes.

Usage:
    from .constants import EmailActionTypes, EmailParserConfig
    
    action = EmailActionTypes.SEND
    confidence_threshold = EmailParserConfig.DEFAULT_CONFIDENCE_THRESHOLD
"""


class EmailActionTypes:
    """All supported email actions"""
    SEND = "send"
    REPLY = "reply"
    SEARCH = "search"
    LIST = "list"
    UNREAD = "unread"
    MARK_READ = "mark_read"
    MARK_UNREAD = "mark_unread"
    DELETE = "delete"
    ARCHIVE = "archive"
    ORGANIZE = "organize"
    CATEGORIZE = "categorize"
    INSIGHTS = "insights"
    CLEANUP = "cleanup"
    SCHEDULE = "schedule"
    EXTRACT_TASKS = "extract_tasks"
    AUTO_PROCESS = "auto_process"
    SUMMARIZE = "summarize"
    SENTIMENT = "sentiment"
    DRAFT = "draft"
    
    @classmethod
    def all(cls):
        """Get all action types"""
        return [
            cls.SEND, cls.REPLY, cls.SEARCH, cls.LIST, cls.UNREAD,
            cls.MARK_READ, cls.MARK_UNREAD, cls.DELETE, cls.ARCHIVE,
            cls.ORGANIZE, cls.CATEGORIZE, cls.INSIGHTS, cls.CLEANUP,
            cls.SCHEDULE, cls.EXTRACT_TASKS, cls.AUTO_PROCESS,
            cls.SUMMARIZE, cls.SENTIMENT, cls.DRAFT
        ]


class EmailParserConfig:
    """Configuration constants for email parser"""
    
    # Confidence thresholds
    DEFAULT_CONFIDENCE_THRESHOLD = 0.6
    LOW_CONFIDENCE_THRESHOLD = 0.5
    HIGH_CONFIDENCE_THRESHOLD = 0.85
    
    # LLM configuration
    LLM_TEMPERATURE = 0.1
    LLM_MAX_TOKENS = 4000
    LLM_MAX_TOKENS_BRIEF = 2000
    LLM_MAX_TOKENS_SUMMARY = 3000
    
    # File paths (can be overridden via config)
    FEEDBACK_FILE_PATH = "./data/email_parser_feedback.json"
    LEARNED_PATTERNS_PATH = "./data/email_parser_learned_patterns.json"
    
    # Date range configuration
    DATE_RANGE_DAYS_BACK = 30
    RECENT_EMAIL_HOURS = 48  # For "new" emails
    
    # Email limits
    DEFAULT_EMAIL_LIMIT = 20
    MAX_EMAIL_LIMIT = 100
    MIN_EMAIL_LIMIT = 1
    
    # Search configuration
    DEFAULT_FOLDER = "inbox"
    HYBRID_SEARCH_CONFIDENCE_THRESHOLD = 0.7
    
    # Retry configuration
    MAX_RETRY_ATTEMPTS = 3
    RETRY_DELAY_SECONDS = 1
    
    # Cache configuration
    CACHE_TTL_SECONDS = 3600  # 1 hour
    CACHE_MAX_SIZE = 1000


class EmailEntityTypes:
    """Entity types extracted from email queries"""
    RECIPIENT = "recipient"
    SENDER = "sender"
    SUBJECT = "subject"
    BODY = "body"
    KEYWORDS = "keywords"
    DATE_RANGE = "date_range"
    FOLDER = "folder"
    ATTACHMENT = "attachment"
    PRIORITY = "priority"
    CATEGORY = "category"
    LABEL = "label"
    SEARCH_TERM = "search_term"
    SCHEDULE_TIME = "schedule_time"


class EmailFolderTypes:
    """Gmail folder/label types"""
    INBOX = "inbox"
    SENT = "sent"
    DRAFT = "draft"
    TRASH = "trash"
    SPAM = "spam"
    STARRED = "starred"
    UNREAD = "unread"
    ARCHIVE = "archive"
    
    @classmethod
    def all(cls):
        """Get all standard folder types"""
        return [
            cls.INBOX, cls.SENT, cls.DRAFT, cls.TRASH,
            cls.SPAM, cls.STARRED, cls.UNREAD, cls.ARCHIVE
        ]


class EmailPriorities:
    """Email priority levels"""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    
    @classmethod
    def all(cls):
        """Get all priority levels"""
        return [cls.CRITICAL, cls.HIGH, cls.NORMAL, cls.LOW]


class EmailCategories:
    """Predefined email categories"""
    WORK = "work"
    PERSONAL = "personal"
    FINANCE = "finance"
    TRAVEL = "travel"
    SHOPPING = "shopping"
    PROMOTIONS = "promotions"
    SOCIAL = "social"
    UPDATES = "updates"
    
    @classmethod
    def all(cls):
        """Get all categories"""
        return [
            cls.WORK, cls.PERSONAL, cls.FINANCE, cls.TRAVEL,
            cls.SHOPPING, cls.PROMOTIONS, cls.SOCIAL, cls.UPDATES
        ]


class EmailSearchPatterns:
    """Regex patterns for email query parsing"""
    
    # Sender patterns
    SENDER_PATTERNS = [
        r'from\s+([^\s@]+@[^\s]+)',      # email address
        r'from\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',  # name
        r'sender\s*:\s*([^\s]+)',         # explicit sender
    ]
    
    # Recipient patterns
    RECIPIENT_PATTERNS = [
        r'to\s+([^\s@]+@[^\s]+)',        # email address
        r'to\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',  # name
    ]
    
    # Subject patterns
    SUBJECT_PATTERNS = [
        r'subject\s*:\s*([^,;]+)',
        r'subject.*?["\']([^"\']+)["\']',
    ]
    
    # Date patterns
    DATE_PATTERNS = [
        r'\b(today|tomorrow|yesterday)\b',
        r'\b(this|next|last)\s+(week|month|year)\b',
        r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b',
    ]


class EmailKeywordSynonyms:
    """Keyword synonym mappings for email search expansion"""
    DEFAULT_SYNONYMS = {
        "email": ["message", "mail"],
        "important": ["urgent", "critical", "priority"],
        "project": ["initiative", "work", "task"],
        "meeting": ["appointment", "call", "conference"],
        "budget": ["financial", "spending", "cost"],
        "approval": ["sign-off", "approval", "authorized"],
        "document": ["file", "attachment", "paper"],
        "unread": ["new", "unopened"],
    }


class EmailResponseTemplates:
    """Response message templates"""
    
    SEND_SUCCESS = "Email sent successfully to {recipient}"
    REPLY_SUCCESS = "Reply sent successfully"
    MARK_READ_SUCCESS = "Marked email as read"
    MARK_UNREAD_SUCCESS = "Marked email as unread"
    DELETE_SUCCESS = "Email deleted successfully"
    ARCHIVE_SUCCESS = "Email archived successfully"
    
    ERROR_NO_RECIPIENT = "Please provide a recipient email address"
    ERROR_NO_SUBJECT = "Please provide an email subject"
    ERROR_NO_BODY = "Please provide email body content"
    ERROR_NO_MESSAGE_ID = "Please provide a message ID"
    ERROR_SERVICE_UNAVAILABLE = "Email service is currently unavailable"
    ERROR_PARSING_FAILED = "Failed to parse email query"
    
    NO_EMAILS_FOUND = "No emails found matching your criteria"
    EMAILS_NOT_AVAILABLE = "Emails are not available. Please check your account settings."


def get_action_validation_rules(action: str) -> dict:
    """
    Get validation rules for an email action
    
    Args:
        action: Email action type
        
    Returns:
        Dictionary of required and optional parameters
    """
    rules = {
        EmailActionTypes.SEND: {
            "required": ["to", "subject", "body"],
            "optional": ["schedule_time"]
        },
        EmailActionTypes.REPLY: {
            "required": ["message_id", "body"],
            "optional": []
        },
        EmailActionTypes.MARK_READ: {
            "required": ["message_id"],
            "optional": []
        },
        EmailActionTypes.MARK_UNREAD: {
            "required": ["message_id"],
            "optional": []
        },
        EmailActionTypes.DELETE: {
            "required": ["message_id"],
            "optional": []
        },
        EmailActionTypes.ARCHIVE: {
            "required": ["message_id"],
            "optional": []
        },
        EmailActionTypes.SEARCH: {
            "required": ["query"],
            "optional": ["folder", "limit"]
        },
        EmailActionTypes.LIST: {
            "required": [],
            "optional": ["folder", "limit"]
        },
        EmailActionTypes.UNREAD: {
            "required": [],
            "optional": ["folder", "limit"]
        },
    }
    
    return rules.get(action, {"required": [], "optional": []})
