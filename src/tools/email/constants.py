"""
Email Tool Constants

Centralized configuration for email operations, limits, timeouts, and patterns.
All hardcoded values should be moved here for maintainability.
"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class EmailLimits:
    """Default limits for email operations"""
    DEFAULT_LIMIT: int = 10
    MAX_LIMIT: int = 100
    BATCH_SIZE: int = 10
    PRIORITY_FETCH_MULTIPLIER: int = 5
    MIN_PRIORITY_FETCH: int = 100
    DATE_FILTER_MULTIPLIER: int = 3
    FROM_QUERY_MULTIPLIER: int = 2
    UNINDEXED_SAMPLE_SIZE: int = 50
    MAX_ITEMS_IN_RECEIPT: int = 20
    CONTENT_PREVIEW_LENGTH: int = 100
    CONTENT_SNIPPET_LENGTH: int = 200
    BODY_SNIPPET_LENGTH: int = 1500
    RECEIPT_ATTACHMENT_LENGTH: int = 5000
    REGULAR_ATTACHMENT_LENGTH: int = 2000
    MAX_BODY_LENGTH_FOR_PROMPT: int = 4000  # Maximum body length for LLM prompts
    MIN_BODY_LENGTH_THRESHOLD: int = 200  # Minimum body length to consider fetching full content
    PREVIEW_LENGTH_FOR_EMAIL: int = 500  # Preview length for email content in context
    MAX_EMAILS_FOR_LLM_CONTEXT: int = 20  # Maximum emails to include in LLM prompt
    MAX_EMAILS_FOR_DISPLAY: int = 20  # Maximum emails to display in fallback response


@dataclass
class EmailTimePeriods:
    """Time periods for email filtering (in hours)"""
    RECENT_EMAILS_HOURS: int = 48
    OLD_EMAIL_DAYS: int = 180
    DEFAULT_OLD_DAYS: int = 180


@dataclass
class EmailSearchConfig:
    """Configuration for email search behavior"""
    EXCLUDE_PROMOTIONS_BY_DEFAULT: bool = True
    SAFETY_LIMIT_MULTIPLIER: int = 10
    PRIORITY_QUERY_TERMS: List[str] = field(default_factory=lambda: [
        "priority", "urgent", "immediate attention", "important"
    ])
    RECENT_QUERY_TERMS: List[str] = field(default_factory=lambda: [
        "new", "recent", "latest"
    ])
    TIME_SPECIFIER_WORDS: List[str] = field(default_factory=lambda: [
        "week", "month", "year", "ago"
    ])
    ACTION_WORDS: List[str] = field(default_factory=lambda: [
        "show", "find", "search", "list", "get", "display", "look"
    ])
    GENERAL_QUERY_PATTERNS: List[str] = field(default_factory=lambda: [
        "show", "list", "display", "recent", "new", "latest", "unread",
        "all emails", "my emails", "emails", "messages"
    ])
    MIN_WORD_LENGTH_FOR_KEYWORD: int = 3  # Minimum word length to be considered meaningful
    MAX_WORDS_FOR_GENERAL_QUERY: int = 3  # Max words for general query pattern detection


# Shared promotional subject terms (used by both SUBJECT_TERMS and SUBJECT_PROMO_TERMS)
_PROMOTIONAL_SUBJECT_TERMS = [
    'offer', 'sale', 'discount', 'deal', 'flash', 'promo', 'promotion',
    'special', 'limited time', 'save', '% off', 'coupon', 'code',
    'extended', 'fall flash', 'order by', 'rush delivery',
    'black friday', 'cyber monday', 'just for you', 'heads up',
    'watch tonight', 'new stories', '$100 off', '$50 off',
    'new episodes', 'check out', 'shop now', 'buy now'
]


@dataclass
class PromotionalEmailPatterns:
    """Patterns for detecting promotional/newsletter emails"""
    SENDER_TERMS: List[str] = field(default_factory=lambda: [
        'noreply', 'no-reply', 'marketing', 'promo', 'offers', 'deals',
        'newsletter', 'weekly', 'info@', 'news@', 'updates@', 'notifications@',
        'messaging.', 'email.', '@newsletters.', '@email.', '@messaging.',
        'disneyplus', 'meta', 'bestbuy', 'wired', 'usps', 'informeddelivery',
        'auto-reply', 'autoreply', 'notification', 'notifications'
    ])
    SENDER_PATTERNS: List[str] = field(default_factory=lambda: [
        '@email.', '@messaging.', '@newsletters.', '@marketing.',
        '.com>', 'notification@', 'notifications@', 'noreply@', 'no-reply@'
    ])
    SUBJECT_TERMS: List[str] = field(default_factory=lambda: _PROMOTIONAL_SUBJECT_TERMS.copy())
    # SUBJECT_PROMO_TERMS is an alias for SUBJECT_TERMS (kept for backward compatibility)
    # Use SUBJECT_TERMS instead to avoid duplication
    SUBJECT_PROMO_TERMS: List[str] = field(default_factory=lambda: _PROMOTIONAL_SUBJECT_TERMS.copy())
    SUBJECT_NEWSLETTER_TERMS: List[str] = field(default_factory=lambda: [
        'weekly', 'newsletter', 'digest', 'roundup', 'recap',
        'this week', 'this month', 'stories to watch'
    ])
    DELIVERY_NOTIFICATION_TERMS: List[str] = field(default_factory=lambda: [
        'expected delivery', 'delivery by', 'tracking', 'shipped',
        'order confirmation', 'your order', 'order #', 'arriving by',
        'informed delivery', 'package', 'shipment'
    ])
    TECHNICAL_SENDER_TERMS: List[str] = field(default_factory=lambda: [
        'vercel', 'github', 'gitlab', 'circleci', 'travis', 'jenkins',
        'deployment', 'ci', 'build'
    ])
    TECHNICAL_SUBJECT_TERMS: List[str] = field(default_factory=lambda: [
        'deployment', 'failed', 'error', 'build', 'vercel', 'github',
        'ci/cd', 'pipeline'
    ])


@dataclass
class UrgentEmailPatterns:
    """Patterns for detecting urgent/priority emails"""
    ACTION_KEYWORDS: List[str] = field(default_factory=lambda: [
        'payment', 'pay', 'invoice', 'billing', 'due', 'overdue', 'past due',
        'missed payment', 'payment method', 'update payment', 'payment failed',
        'account issue', 'account problem', 'account suspended', 'account locked',
        'verification required', 'verify', 'confirm', 'action required',
        'action needed', 'response required', 'please respond', 'reply needed',
        'deadline', 'expires', 'expiring', 'urgent', 'asap', 'as soon as possible',
        'immediately', 'critical', 'security alert', 'suspicious activity',
        'time sensitive', 'needs attention', 'attention required'
    ])


@dataclass
class PaymentRelatedPatterns:
    """Patterns for detecting payment-related emails"""
    PAYMENT_TERMS: List[str] = field(default_factory=lambda: [
        'payment due', 'invoice due', 'billing due', 'payment overdue', 'past due',
        'missed payment', 'payment method', 'update payment', 'payment failed',
        'subscription renewal', 'subscription expires', 'subscription expiring',
        'cancel subscription', 'cancelled subscription', 'renewal required'
    ])


# LLM configuration constants
LLM_TEMPERATURE = 0.7  # Default temperature for LLM calls
LLM_TEMPERATURE_LOW = 0.1  # Low temperature for classification tasks
LLM_MAX_TOKENS = 4000  # Maximum tokens for LLM responses

# Instantiate configs
LIMITS = EmailLimits()
TIME_PERIODS = EmailTimePeriods()
SEARCH_CONFIG = EmailSearchConfig()
PROMOTIONAL_PATTERNS = PromotionalEmailPatterns()
URGENT_PATTERNS = UrgentEmailPatterns()
PAYMENT_PATTERNS = PaymentRelatedPatterns()

