"""
Gmail Constants - Folder and Category Mappings
Centralized constants for Gmail folders, categories, and labels
"""

# Gmail Folder/Label Mappings
GMAIL_FOLDERS = {
    "inbox": "INBOX",
    "sent": "SENT",
    "drafts": "DRAFTS",
    "trash": "TRASH",
    "spam": "SPAM",
    "important": "IMPORTANT",
    "starred": "STARRED",
    "unread": "UNREAD",
    "read": "READ",
}

# Gmail Category Labels (for tabs)
GMAIL_CATEGORIES = {
    "primary": "CATEGORY_PERSONAL",  # Primary tab
    "social": "CATEGORY_SOCIAL",  # Social tab
    "promotions": "CATEGORY_PROMOTIONS",  # Promotions tab
    "updates": "CATEGORY_UPDATES",  # Updates tab
    "forums": "CATEGORY_FORUMS",  # Forums tab
}

# Gmail Chat Labels
GMAIL_CHAT_LABELS = {
    "chat": "CHAT",
    "mentions": "MENTIONS",
    "direct_messages": "DIRECT_MESSAGES",
    "spaces": "SPACES",
    "apps": "APPS",
}

# Search Priority Order (highest to lowest)
# When searching emails, prioritize these folders/categories first
SEARCH_PRIORITY_ORDER = [
    "inbox",  # Always check inbox first
    "important",  # Important emails next
    "starred",  # Starred emails
    "primary",  # Primary category
    "updates",  # Updates category
    "social",  # Social category
    "promotions",  # Promotions category
    "forums",  # Forums category
    "sent",  # Sent folder
    "drafts",  # Drafts folder
    "chat",  # Chat messages
]

# Gmail Search Query Patterns
GMAIL_SEARCH_PATTERNS = {
    "inbox": "in:inbox",
    "important": "is:important",
    "starred": "is:starred",
    "unread": "is:unread",
    "read": "is:read",
    "primary": "category:primary",
    "social": "category:social",
    "promotions": "category:promotions",
    "updates": "category:updates",
    "forums": "category:forums",
    "sent": "in:sent",
    "drafts": "in:drafts",
    "spam": "in:spam",
    "trash": "in:trash",
    "chat": "in:chats",
}

# Folder aliases (user-friendly names that map to Gmail folders/categories)
FOLDER_ALIASES = {
    "primary": "inbox",  # Primary folder = inbox
    "main": "inbox",  # Main folder = inbox
    "important": "important",  # Important label
    "starred": "starred",  # Starred label
    "unread": "unread",  # Unread label
    "new": "unread",  # New = unread
    "social": "social",  # Social category
    "promotions": "promotions",  # Promotions category
    "updates": "updates",  # Updates category
    "forums": "forums",  # Forums category
    "chat": "chat",  # Chat messages
    "chats": "chat",  # Chats = chat
    "messages": "chat",  # Messages = chat
    "mentions": "chat",  # Mentions = chat
    "direct": "chat",  # Direct messages = chat
}

# Natural language folder/category detection patterns
FOLDER_DETECTION_PATTERNS = {
    "inbox": ["inbox", "primary", "main", "mail", "emails"],
    "important": ["important", "priority", "urgent", "critical"],
    "starred": ["starred", "star", "favorite", "favorites", "bookmarked"],
    "unread": ["unread", "new", "unopened", "not read"],
    "social": ["social", "facebook", "twitter", "linkedin", "instagram"],
    "promotions": ["promotions", "promo", "deals", "offers", "sales"],
    "updates": ["updates", "notifications", "alerts", "notices"],
    "forums": ["forums", "discussions", "groups", "mailing list"],
    "sent": ["sent", "outbox", "outgoing"],
    "drafts": ["drafts", "draft", "unsent", "pending"],
    "chat": ["chat", "chats", "messages", "direct", "mentions", "spaces"],
}

