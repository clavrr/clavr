"""
Email Categorization Module

Handles email categorization, insights, and analysis operations.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import json

from ...utils.logger import setup_logger
from .constants import LIMITS, TIME_PERIODS, PROMOTIONAL_PATTERNS

logger = setup_logger(__name__)

# Constants for categorization
MAX_AI_CATEGORIZATION_BATCH = 20  # Max emails to categorize with AI at once
ARCHIVE_RECOMMENDATION_THRESHOLD = 100  # Recommend archiving if more than this many emails
NOTIFICATIONS_WARNING_THRESHOLD = 20  # Warn if more than this many notification emails
SPAM_WARNING_THRESHOLD = 10  # Warn if more than this many spam emails
# Use OLD_EMAIL_DAYS from TIME_PERIODS constant (180 days = 6 months)

# Email categories
EMAIL_CATEGORIES = ["work", "personal", "finance", "travel", "shopping", "notifications", "other"]


class EmailCategorization:
    """Email categorization and insights operations"""
    
    def __init__(self, llm_client: Optional[Any] = None, classifier: Optional[Any] = None):
        """
        Initialize email categorization
        
        Args:
            llm_client: LLM client for AI categorization
            classifier: Query classifier for NLP support
        """
        self.llm_client = llm_client
        self.classifier = classifier
    
    def categorize_emails(self, emails: List[Dict[str, Any]], category: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Categorize list of emails
        
        Args:
            emails: List of email dictionaries
            category: Optional preferred category
            
        Returns:
            Dictionary mapping categories to email lists
        """
        categories = {cat: [] for cat in EMAIL_CATEGORIES}
        
        for email in emails:
            cat = self._determine_email_category(email, category)
            categories[cat].append(email)
        
        return {k: v for k, v in categories.items() if v}
    
    def ai_categorize_emails(self, emails: List[Dict[str, Any]], query: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Use AI to categorize emails with LLM support"""
        if self.llm_client and emails:
            try:
                email_summaries = []
                batch_emails = emails[:MAX_AI_CATEGORIZATION_BATCH]
                for i, email in enumerate(batch_emails, 1):
                    subject = email.get('subject', 'No Subject')
                    sender = email.get('sender', 'Unknown')
                    email_summaries.append(f"{i}. Subject: {subject} | From: {sender}")
                
                categories_str = ', '.join(EMAIL_CATEGORIES)
                prompt = f"""Categorize these emails into: {categories_str}.
Return only the mapping as JSON: {{"1": "work", "2": "personal", ...}}

Emails:
{chr(10).join(email_summaries)}

JSON mapping:"""
                
                from langchain_core.messages import HumanMessage
                response = self.llm_client.invoke([HumanMessage(content=prompt)])
                categorization_text = response.content.strip()
                
                if '```' in categorization_text:
                    categorization_text = categorization_text.split('```')[1].strip()
                    if categorization_text.startswith('json'):
                        categorization_text = categorization_text[4:].strip()
                
                categorization = json.loads(categorization_text)
                
                categorized = {cat: [] for cat in EMAIL_CATEGORIES}
                for i, email in enumerate(batch_emails):
                    cat = categorization.get(str(i+1), "other")
                    categorized[cat].append(email)
                
                # Process remaining emails with heuristics
                for email in emails[MAX_AI_CATEGORIZATION_BATCH:]:
                    cat = self._determine_email_category(email, query)
                    categorized[cat].append(email)
                
                return {k: v for k, v in categorized.items() if v}
                
            except Exception as e:
                logger.warning(f"LLM categorization failed, using heuristics: {e}")
        
        return self.categorize_emails(emails, query)
    
    def _determine_email_category(self, email: Dict[str, Any], preferred_category: Optional[str]) -> str:
        """Determine email category using simple heuristics"""
        if preferred_category:
            return preferred_category.lower()
        
        subject = email.get('subject', '').lower()
        sender = email.get('sender', '').lower()
        body = email.get('body', '').lower()
        
        work_keywords = ['meeting', 'project', 'deadline', 'report', 'client', 'business', 'work', 'office']
        if any(keyword in subject or keyword in body for keyword in work_keywords):
            return "work"
        
        finance_keywords = ['bank', 'payment', 'invoice', 'bill', 'credit', 'debit', 'account', 'transaction']
        if any(keyword in subject or keyword in body for keyword in finance_keywords):
            return "finance"
        
        travel_keywords = ['flight', 'hotel', 'booking', 'travel', 'trip', 'vacation', 'airline']
        if any(keyword in subject or keyword in body for keyword in travel_keywords):
            return "travel"
        
        # Shopping includes delivery/shipping notifications - check this BEFORE notifications
        # Use delivery notification terms from constants
        shopping_keywords = PROMOTIONAL_PATTERNS.DELIVERY_NOTIFICATION_TERMS + ['order', 'purchase', 'receipt', 'store', 'shop']
        if any(keyword in subject or keyword in body for keyword in shopping_keywords):
            return "shopping"
        
        # Generic notifications checked AFTER specific categories
        notification_keywords = ['notification', 'alert', 'reminder', 'update', 'newsletter']
        if any(keyword in subject or keyword in body for keyword in notification_keywords):
            return "notifications"
        
        personal_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']
        if any(domain in sender for domain in personal_domains):
            return "personal"
        
        return "other"
    
    def analyze_email_patterns(self, emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze email patterns and generate insights"""
        insights = {
            'top_senders': {},
            'volume_trend': {},
            'categories': {},
            'recommendations': []
        }
        
        sender_counts = {}
        for email in emails:
            sender = email.get('sender', 'Unknown')
            sender_counts[sender] = sender_counts.get(sender, 0) + 1
        
        insights['top_senders'] = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)
        
        categorized = self.categorize_emails(emails, None)
        insights['categories'] = {cat: len(email_list) for cat, email_list in categorized.items()}
        
        if len(emails) > ARCHIVE_RECOMMENDATION_THRESHOLD:
            insights['recommendations'].append("Consider archiving old emails to improve performance")
        
        if insights['categories'].get('notifications', 0) > NOTIFICATIONS_WARNING_THRESHOLD:
            insights['recommendations'].append("You have many notification emails - consider unsubscribing from unnecessary ones")
        
        if insights['categories'].get('spam', 0) > SPAM_WARNING_THRESHOLD:
            insights['recommendations'].append("Consider setting up better spam filters")
        
        return insights
    
    def identify_cleanup_candidates(self, emails: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Identify emails that can be cleaned up"""
        candidates = {
            "delete": [],
            "archive": [],
            "move": []
        }
        
        for email in emails:
            subject = email.get('subject', '').lower()
            sender = email.get('sender', '').lower()
            body = email.get('body', '').lower()
            
            # Don't mark delivery/shipping notifications for cleanup
            # Use delivery notification terms from constants
            is_delivery_notification = any(keyword in subject or keyword in body for keyword in PROMOTIONAL_PATTERNS.DELIVERY_NOTIFICATION_TERMS)
            
            # Use promotional patterns from constants
            promo_keywords = ['unsubscribe'] + PROMOTIONAL_PATTERNS.SUBJECT_TERMS[:3]  # First few promo terms
            if any(keyword in subject for keyword in promo_keywords):
                candidates['delete'].append(email)
            elif self._is_old_email(email):
                candidates['archive'].append(email)
            elif not is_delivery_notification and any(keyword in subject for keyword in ['notification', 'alert', 'reminder']):
                # Only move non-delivery notifications
                candidates['move'].append(email)
        
        return {k: v for k, v in candidates.items() if v}
    
    def _is_old_email(self, email: Dict[str, Any]) -> bool:
        """Check if email is old (more than OLD_EMAIL_DAYS days)"""
        try:
            from email.utils import parsedate_to_datetime
            
            timestamp = email.get('date', '')
            if not timestamp:
                return False
            
            dt = parsedate_to_datetime(timestamp)
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            
            # Use constant for old email threshold from TIME_PERIODS
            old_threshold = datetime.now().astimezone() - timedelta(days=TIME_PERIODS.OLD_EMAIL_DAYS)
            return dt < old_threshold
            
        except Exception:
            return False
