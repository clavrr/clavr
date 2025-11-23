"""
Email Tool Utilities

Common utility functions for email operations to reduce duplication
and improve maintainability.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .constants import (
    LIMITS, TIME_PERIODS, PROMOTIONAL_PATTERNS, URGENT_PATTERNS,
    PAYMENT_PATTERNS, SEARCH_CONFIG
)


def format_email_timestamp(timestamp: str) -> str:
    """
    Format email timestamp to local timezone string.
    
    Handles various timestamp formats and converts to local timezone.
    Returns "Unknown time" if parsing fails.
    
    Args:
        timestamp: Email timestamp string (RFC 2822 format or ISO)
        
    Returns:
        Formatted timestamp string (YYYY-MM-DD HH:MM) or "Unknown time"
    """
    if not timestamp:
        return "Unknown time"
    
    try:
        dt = parsedate_to_datetime(timestamp)
        # Convert to local timezone if timezone-aware
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return timestamp or "Unknown time"


def is_promotional_email(message: Dict[str, Any]) -> bool:
    """
    Check if an email is promotional/newsletter/delivery notification.
    
    Uses comprehensive pattern matching to identify promotional emails
    that should be filtered out from priority/urgent results.
    
    Args:
        message: Email message dictionary with 'labels', 'subject', 'sender', etc.
        
    Returns:
        True if email is promotional, False otherwise
    """
    labels = message.get('labels', [])
    subject = message.get('subject', '').lower()
    sender = message.get('sender', '').lower()
    snippet = message.get('snippet', '').lower()
    body = message.get('body', '').lower()
    
    # Check Gmail category labels first (fastest check)
    is_promotional_category = (
        'CATEGORY_PROMOTIONS' in labels or
        'CATEGORY_UPDATES' in labels or
        'CATEGORY_SOCIAL' in labels
    )
    
    if is_promotional_category:
        return True
    
    # Check if technical notification (should NOT be filtered)
    is_technical_sender = any(
        tech_term in sender for tech_term in PROMOTIONAL_PATTERNS.TECHNICAL_SENDER_TERMS
    )
    is_technical_subject = any(
        tech_term in subject for tech_term in PROMOTIONAL_PATTERNS.TECHNICAL_SUBJECT_TERMS
    )
    
    if is_technical_sender or is_technical_subject:
        return False  # Never filter technical notifications
    
    # Check sender patterns
    is_promotional_sender = (
        any(news_term in sender for news_term in PROMOTIONAL_PATTERNS.SENDER_TERMS) or
        any(pattern in sender for pattern in PROMOTIONAL_PATTERNS.SENDER_PATTERNS)
    )
    
    # Check subject patterns
    is_promotional_subject = (
        any(promo_term in subject for promo_term in PROMOTIONAL_PATTERNS.SUBJECT_PROMO_TERMS) or
        any(news_term in subject for news_term in PROMOTIONAL_PATTERNS.SUBJECT_NEWSLETTER_TERMS)
    )
    
    # Check for delivery notifications
    is_delivery_notification = any(
        notif_term in subject for notif_term in PROMOTIONAL_PATTERNS.DELIVERY_NOTIFICATION_TERMS
    )
    
    # Combine all checks
    return (
        is_promotional_sender or
        is_promotional_subject or
        is_delivery_notification
    )


def is_urgent_email(message: Dict[str, Any]) -> bool:
    """
    Check if an email is urgent/priority based on content and labels.
    
    Urgent emails are those that require action or response:
    - IMPORTANT label from Gmail
    - Unread emails (not newsletters/notifications)
    - Emails with action-required keywords
    
    Args:
        message: Email message dictionary
        
    Returns:
        True if email is urgent, False otherwise
    """
    labels = message.get('labels', [])
    subject = message.get('subject', '').lower()
    body = message.get('body', '').lower()
    snippet = message.get('snippet', '').lower()
    
    # First check: promotional emails are NEVER urgent
    if is_promotional_email(message):
        return False
    
    # Priority 1: IMPORTANT label
    if 'IMPORTANT' in labels:
        return True
    
    # Priority 2: Unread emails (but exclude newsletters/notifications)
    if 'UNREAD' in labels:
        # Check if this is a newsletter/notification using constants
        sender_lower = message.get('sender', '').lower()
        is_newsletter_or_notification = (
            'CATEGORY_UPDATES' in labels or
            'CATEGORY_SOCIAL' in labels or
            any(notif_term in subject for notif_term in PROMOTIONAL_PATTERNS.DELIVERY_NOTIFICATION_TERMS) or
            any(news_term in subject for news_term in PROMOTIONAL_PATTERNS.SUBJECT_NEWSLETTER_TERMS) or
            any(news_term in sender_lower for news_term in PROMOTIONAL_PATTERNS.SENDER_TERMS)
        )
        
        if not is_newsletter_or_notification:
            return True
    
    # Priority 3: Action-required keywords
    all_text = f"{subject} {body} {snippet}"
    return any(
        keyword in all_text for keyword in URGENT_PATTERNS.ACTION_KEYWORDS
    )


def is_payment_related_email(message: Dict[str, Any]) -> bool:
    """
    Check if an email is payment-related (bills, invoices, subscriptions).
    
    Args:
        message: Email message dictionary
        
    Returns:
        True if email is payment-related, False otherwise
    """
    subject = message.get('subject', '').lower()
    snippet = message.get('snippet', '').lower()
    body = message.get('body', '').lower()
    
    all_text = f"{subject} {snippet} {body}"
    return any(
        payment_term in all_text for payment_term in PAYMENT_PATTERNS.PAYMENT_TERMS
    )


def filter_recent_emails(
    messages: List[Dict[str, Any]],
    hours: int = TIME_PERIODS.RECENT_EMAILS_HOURS
) -> List[Dict[str, Any]]:
    """
    Filter messages to only include those from the last N hours.
    
    Args:
        messages: List of email message dictionaries
        hours: Number of hours to look back (default: 48)
        
    Returns:
        Filtered list of recent messages
    """
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=hours)
    
    filtered = []
    for msg in messages:
        timestamp = msg.get('date', '')
        if not timestamp:
            continue  # Skip messages without timestamps
        
        try:
            dt = parsedate_to_datetime(timestamp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            if dt >= cutoff:
                filtered.append(msg)
        except Exception:
            continue  # Skip messages with unparseable dates
    
    return filtered


def calculate_fetch_limit(
    base_limit: int,
    has_date_filter: bool = False,
    is_priority_query: bool = False,
    is_from_query: bool = False
) -> int:
    """
    Calculate appropriate fetch limit based on query type.
    
    Different query types need different fetch limits to ensure
    we get enough results after filtering/prioritization.
    
    Args:
        base_limit: Base limit requested by user
        has_date_filter: Whether date filtering will be applied
        is_priority_query: Whether this is a priority/urgent query
        is_from_query: Whether this is a "from:" query
        
    Returns:
        Calculated fetch limit
    """
    limit = base_limit
    
    if is_priority_query:
        # Priority queries need more emails to find all urgent ones
        limit = max(LIMITS.PRIORITY_FETCH_MULTIPLIER * limit, LIMITS.MIN_PRIORITY_FETCH)
    elif has_date_filter:
        # Date filtering reduces results, so fetch more
        limit = LIMITS.DATE_FILTER_MULTIPLIER * limit
    elif is_from_query:
        # From queries benefit from more results for better matching
        limit = LIMITS.FROM_QUERY_MULTIPLIER * limit
    
    return limit


def extract_email_preview(message: Dict[str, Any], max_length: int = LIMITS.CONTENT_PREVIEW_LENGTH) -> str:
    """
    Extract preview text from email message.
    
    Args:
        message: Email message dictionary
        max_length: Maximum length of preview (default: 100)
        
    Returns:
        Preview text (truncated if needed)
    """
    body = message.get('body', '')
    if body:
        preview = body[:max_length].replace('\n', ' ')
        return f"{preview}..." if len(body) > max_length else preview
    return ""


def is_original_email(message: Dict[str, Any]) -> bool:
    """
    Check if email is an original (not a reply or forward).
    
    Args:
        message: Email message dictionary
        
    Returns:
        True if original email, False if reply/forward
    """
    subject = message.get('subject', '').lower()
    return not (subject.startswith('re:') or subject.startswith('fwd:'))


def is_our_reply(message: Dict[str, Any]) -> bool:
    """
    Check if email is a reply we sent.
    
    Args:
        message: Email message dictionary
        
    Returns:
        True if it's our reply, False otherwise
    """
    labels = message.get('labels', [])
    subject = message.get('subject', '').lower()
    return subject.startswith('re:') and 'SENT' in labels





