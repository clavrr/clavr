"""
RAG Query Rules and Constants

Externalized configuration for query enhancement and result reranking logic.
"""

# Common synonyms and related terms (email-specific)
SYNONYMS = {
    'new': ['recent', 'latest', 'fresh', 'current', 'unread', 'newest'],
    'old': ['previous', 'past', 'earlier', 'archived', 'older'],
    'urgent': ['important', 'priority', 'critical', 'immediate', 'asap', 'urgent'],
    'meeting': ['appointment', 'call', 'conference', 'session', 'meeting'],
    'email': ['message', 'mail', 'correspondence', 'email', 'emails', 'messages'],
    'task': ['todo', 'action', 'item', 'work', 'task', 'tasks'],
    'deadline': ['due date', 'due', 'deadline', 'cutoff'],
    'message': ['email', 'mail', 'correspondence', 'message', 'messages'],
    'mail': ['email', 'message', 'correspondence', 'mail'],
    'find': ['search', 'locate', 'get', 'show', 'list'],
    'show': ['display', 'list', 'find', 'get'],
    'from': ['by', 'sent by', 'sender'],
}

# Content-based urgency/importance indicators (not domain-specific)
# These patterns help identify urgent/important emails based on content, not sender
URGENCY_SUBJECT_PATTERNS = {
    'urgent', 'important', 'priority', 'critical', 'asap', 'as soon as possible',
    'action required', 'action needed', 'please respond', 'response needed',
    'deadline', 'due date', 'due today', 'overdue',
    'security alert', 'security', 'alert', 'warning', 'notification',
    'payment', 'billing', 'invoice', 'receipt', 'account',
    'verification', 'verify', 'confirm', 'confirmation',
    'meeting', 'appointment', 'call', 'schedule',
    'emergency', 'immediate', 'time sensitive',
    'cancelled', 'canceled'
}

# Content keywords that indicate importance (from email body)
IMPORTANCE_CONTENT_KEYWORDS = {
    'deadline', 'due', 'urgent', 'important', 'priority', 'asap',
    'meeting', 'appointment', 'call', 'schedule', 'cancel',
    'payment', 'invoice', 'billing', 'account', 'security',
    'verification', 'confirm', 'action required', 'please respond',
    'project', 'assignment', 'homework', 'exam', 'test', 'grade',
    'interview', 'offer', 'job', 'opportunity', 'contract'
}

# Sender patterns that might indicate automated/notification emails
NOTIFICATION_SENDER_PATTERNS = {
    'noreply', 'no-reply', 'notifications', 'alerts', 'notify',
    'automated', 'system', 'do-not-reply', 'donotreply'
}

# Temporal patterns mapping regex to normalized keys
TEMPORAL_PATTERNS = {
    r'\btoday\b': 'today',
    r'\byesterday\b': 'yesterday',
    r'\btomorrow\b': 'tomorrow',
    r'\bthis week\b': 'this_week',
    r'\blast week\b': 'last_week',
    r'\bnext week\b': 'next_week',
    r'\bthis month\b': 'this_month',
    r'\blast month\b': 'last_month',
    r'\brecent\b': 'recent',
    r'\bnew\b': 'recent',
}

# Common stopwords to ignore during entity extraction even if capitalized
COMMON_ENTITY_STOPWORDS = {
    'The', 'A', 'An', 'If', 'When', 'How', 'What', 'Who', 'Where', 
    'And', 'Or', 'But', 'To', 'From', 'In', 'On', 'At', 'By', 'For', 'With',
    'This', 'That', 'These', 'Those', 'Is', 'Are', 'Was', 'Were', 'Be', 'Been',
    'Have', 'Has', 'Had', 'Do', 'Does', 'Did', 'Can', 'Could', 'Will', 'Would', 'Should'
}

# Stopwords for search tokenization (lowercase)
SEARCH_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
    'could', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those'
}

# Adaptive Reranking Weights for different intents
RERANKING_WEIGHTS = {
    'recent': {
        'semantic_weight': 0.25,
        'keyword_weight': 0.15,
        'metadata_weight': 0.15,
        'recency_weight': 0.45,  # Heavily favor recent emails
        'description': 'Optimized for recent/latest queries'
    },
    'action': {
        'semantic_weight': 0.30,
        'keyword_weight': 0.35,  # Keywords are critical for actions
        'metadata_weight': 0.20,
        'recency_weight': 0.15,
        'description': 'Optimized for action queries (send, delete, archive)'
    },
    'search': {
        'semantic_weight': 0.50,  # Prioritize semantic understanding
        'keyword_weight': 0.20,
        'metadata_weight': 0.15,
        'recency_weight': 0.15,
        'description': 'Optimized for general search queries'
    },
    'specific': {
        'semantic_weight': 0.25,
        'keyword_weight': 0.25,
        'metadata_weight': 0.35,  # Names, dates, labels matter most
        'recency_weight': 0.15,
        'description': 'Optimized for specific queries (names, dates, labels)'
    },
    'sender': {  # Alias for specific
        'semantic_weight': 0.25,
        'keyword_weight': 0.25,
        'metadata_weight': 0.35,
        'recency_weight': 0.15,
        'description': 'Optimized for sender queries (from/by)'
    },
    'priority': {
        'semantic_weight': 0.25,
        'keyword_weight': 0.30,
        'metadata_weight': 0.30,  # Importance flags are metadata
        'recency_weight': 0.15,
        'description': 'Optimized for high-priority items'
    },
    'financial': {
        'semantic_weight': 0.30,
        'keyword_weight': 0.40,  # Specific keywords like "invoice" are key
        'metadata_weight': 0.15,
        'recency_weight': 0.15,
        'description': 'Optimized for financial queries'
    },
    'temporal': {
        'semantic_weight': 0.20,
        'keyword_weight': 0.20,
        'metadata_weight': 0.20,
        'recency_weight': 0.40,  # Recency is paramount
        'description': 'Optimized for time-based queries'
    },
    'historical': {
        'semantic_weight': 0.80,  # Focus on meaning, not recency
        'keyword_weight': 0.10,
        'metadata_weight': 0.05,
        'recency_weight': 0.05,  # Minimal weight for recency to allow old results
        'description': 'Optimized for deep archival search and historical context'
    },
    'default': {
        'semantic_weight': 0.40,
        'keyword_weight': 0.20,
        'metadata_weight': 0.20,
        'recency_weight': 0.20,
        'description': 'Balanced weights for general queries'
    }
}
