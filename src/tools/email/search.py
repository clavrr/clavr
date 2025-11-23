"""
Email Search Module

Handles email search, listing, and filtering operations.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import re

from ...utils.logger import setup_logger
from ...integrations.gmail.service import EmailService
from ...core.email.gmail_constants import (
    GMAIL_SEARCH_PATTERNS, FOLDER_ALIASES
)
from .constants import LIMITS, SEARCH_CONFIG, TIME_PERIODS
from .utils import (
    is_promotional_email, is_urgent_email, is_payment_related_email,
    filter_recent_emails, calculate_fetch_limit, extract_email_preview,
    is_original_email, is_our_reply
)

logger = setup_logger(__name__)


class EmailSearch:
    """Email search and listing operations"""
    
    def __init__(self, email_service: EmailService, date_parser: Optional[Any] = None):
        """
        Initialize email search
        
        Args:
            email_service: Email service instance
            date_parser: Optional date parser for flexible date handling
        """
        self.email_service = email_service
        # Get Gmail client from email service (always available via service)
        self.google_client = getattr(email_service, 'gmail_client', None)
        self.date_parser = date_parser
    
    def search_emails(self, query: str, limit: int = LIMITS.DEFAULT_LIMIT, folder: str = "inbox") -> str:
        """
        Search emails with smart folder prioritization
        
        Returns formatted email list or empty string if no results
        """
        logger.info(f"[SEARCH] search_emails called with query: '{query}', folder: '{folder}'")
        
        # Check if Gmail client is available
        if not self.google_client or not self.google_client.is_available():
            error_msg = "Gmail is not available. Please make sure you're authenticated with Google."
            logger.warning(f"[SEARCH] {error_msg}")
            raise Exception(error_msg)
        
        try:
            # Parse date range from query for client-side filtering
            date_range = self._parse_date_range_from_query(query)
            fetch_limit = calculate_fetch_limit(
                limit,
                has_date_filter=date_range is not None,
                is_priority_query=False,
                is_from_query=query.startswith("from:")
            )
            
            # Detect if this is a keyword/topic search
            is_keyword_search = self._is_keyword_search(query)
            
            # Normalize folder name
            folder_normalized = FOLDER_ALIASES.get(folder.lower(), folder.lower())
            
            # Execute search based on query type
            if folder_normalized != "inbox" and folder_normalized in GMAIL_SEARCH_PATTERNS:
                messages = self._search_specific_folder(query, folder_normalized, fetch_limit)
            elif query.startswith("from:"):
                messages = self._search_from_query(query, limit)
            else:
                messages = self._search_with_priority(query, folder_normalized, limit, fetch_limit)
            
            # Apply client-side date filtering if date range specified
            if date_range and messages:
                messages = self._filter_messages_by_date_range(messages, date_range)
                logger.info(f"[SEARCH] After date filtering: {len(messages)} messages")
            
            # Check if query contains "new" or "recent" and filter to recent emails
            query_lower = query.lower()
            is_recent_query = any(term in query_lower for term in SEARCH_CONFIG.RECENT_QUERY_TERMS)
            has_time_specifier = any(word in query_lower for word in SEARCH_CONFIG.TIME_SPECIFIER_WORDS)
            
            if is_recent_query and not has_time_specifier:
                original_count = len(messages)
                messages = filter_recent_emails(messages, TIME_PERIODS.RECENT_EMAILS_HOURS)
                
                if messages:
                    filtered_count = original_count - len(messages)
                    logger.info(f"[SEARCH] Applied 'recent' filter - kept {len(messages)} emails")
                elif original_count > 0:
                    logger.warning(f"[SEARCH] 'recent' filter removed all {original_count} emails")
                    return ""
            
            # Limit to requested number after filtering
            messages = messages[:limit]
            
            # Filter priority queries (remove promotional emails)
            is_priority_query = any(term in query_lower for term in SEARCH_CONFIG.PRIORITY_QUERY_TERMS)
            if is_priority_query:
                messages = self._filter_priority_emails(messages)
            
            if not messages:
                return ""
            
            # Format emails for output
            return self._format_email_list(messages)
            
        except Exception as e:
            raise Exception(f"Failed to search Gmail: {str(e)}")
    
    def list_emails(self, folder: str = "inbox", limit: int = LIMITS.DEFAULT_LIMIT) -> str:
        """List emails from a specific folder"""
        return self.search_emails(query="", limit=limit, folder=folder)
    
    def _search_specific_folder(self, query: str, folder: str, fetch_limit: int) -> List[Dict[str, Any]]:
        """Search in a specific folder"""
        search_pattern = GMAIL_SEARCH_PATTERNS[folder]
        combined_query = f"{search_pattern} {query}".strip() if query else search_pattern
        logger.info(f"[SEARCH] Searching {folder} folder with query: '{combined_query}'")
        messages = self.google_client.list_messages(query=combined_query, max_results=fetch_limit)
        logger.info(f"[SEARCH] Found {len(messages)} messages in {folder}")
        return messages
    
    def _search_from_query(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search with 'from:' query (searches all messages, then prioritizes)"""
        try:
            logger.info(f"[SEARCH] Searching all messages with query: '{query}' (no label restriction)")
            from_query_limit = calculate_fetch_limit(limit, is_from_query=True)
            all_messages = self.google_client.list_messages(query=query, max_results=from_query_limit)
            logger.info(f"[SEARCH] Found {len(all_messages)} total messages matching '{query}'")
            
            # Remove duplicates and prioritize inbox/important/starred
            messages = self._deduplicate_and_prioritize(all_messages, limit)
            return messages
        except Exception as e:
            logger.error(f"[SEARCH] Failed to search with 'from:' query: {e}")
            return []
    
    def _search_with_priority(self, query: str, folder: str, limit: int, fetch_limit: int) -> List[Dict[str, Any]]:
        """Smart search with priority order"""
        messages = []
        seen_ids = set()
        
        query_lower = (query or "").lower()
        is_empty_query = not query or query.strip() == ""
        is_priority_query = any(term in query_lower for term in SEARCH_CONFIG.PRIORITY_QUERY_TERMS)
        
        if is_empty_query and folder == "inbox":
            is_priority_query = True
            logger.info(f"[SEARCH] Empty query in inbox context detected as priority query")
        
        is_priority_unread_query = "is:unread" in query_lower or is_priority_query
        
        # STEP 1: Search inbox
        try:
            if is_priority_query:
                priority_fetch_limit = calculate_fetch_limit(limit, is_priority_query=True)
                inbox_query = ""  # Empty query - rely on labelIds
                logger.info(f"[SEARCH] Priority query - fetching ALL inbox emails")
                inbox_messages = self.google_client.list_messages(
                    query=inbox_query,
                    max_results=priority_fetch_limit,
                    label_ids=['INBOX']
                )
            else:
                base_query = query if query else ""
                query_lower = base_query.lower()
                exclude_promotions = "-category:promotions" if "promo" not in query_lower else ""
                inbox_query = f"in:inbox {base_query} {exclude_promotions}".strip()
                inbox_messages = self.google_client.list_messages(query=inbox_query, max_results=fetch_limit)
            
            logger.info(f"[SEARCH] Found {len(inbox_messages)} messages in INBOX")
            
            for msg in inbox_messages:
                if msg['id'] not in seen_ids:
                    messages.append(msg)
                    seen_ids.add(msg['id'])
        except Exception as e:
            logger.warning(f"Failed to search INBOX: {e}")
        
        # STEP 2: Search additional folders (skip for priority queries)
        if not is_priority_unread_query:
            additional_folders = [
                ('STARRED', 'is:starred'),
                ('IMPORTANT', 'is:important'),
                ('CATEGORY_PERSONAL', 'category:primary'),
            ]
            
            for label_id, search_pattern in additional_folders:
                if len(messages) >= limit * SEARCH_CONFIG.SAFETY_LIMIT_MULTIPLIER:
                    break
                
                try:
                    combined_query = f"{search_pattern} {query}".strip() if query else search_pattern
                    folder_messages = self.google_client.list_messages(query=combined_query, max_results=fetch_limit)
                    
                    for msg in folder_messages:
                        if msg['id'] not in seen_ids:
                            messages.append(msg)
                            seen_ids.add(msg['id'])
                except Exception as e:
                    logger.warning(f"Failed to search {label_id}: {e}")
        else:
            logger.info(f"[SEARCH] Priority/unread query detected - only searching INBOX")
        
        # STEP 3: Prioritize results
        messages = self._prioritize_results(messages, limit)
        logger.info(f"[SEARCH] Total found: {len(messages)} messages")
        
        return messages
    
    def _filter_priority_emails(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out non-priority emails (promotional, newsletters, etc.)"""
        filtered_messages = []
        
        for msg in messages:
            labels = msg.get('labels', [])
            
            is_unread = 'UNREAD' in labels
            is_read = 'UNREAD' not in labels
            
            # First check if promotional - if so, skip
            if is_promotional_email(msg):
                continue
            
            # Check if payment-related (always include)
            is_payment_related = is_payment_related_email(msg)
            
            # Check if original email (not a reply we sent)
            is_original = is_original_email(msg)
            is_reply_we_sent = is_our_reply(msg)
            is_in_inbox = 'INBOX' in labels
            
            if is_payment_related:
                filtered_messages.append(msg)
            elif is_unread:
                filtered_messages.append(msg)
            elif is_read and is_original and not is_reply_we_sent and is_in_inbox:
                filtered_messages.append(msg)
        
        if filtered_messages:
            logger.info(f"[SEARCH] Filtered out promotional emails ({len(messages) - len(filtered_messages)} removed)")
        
        return filtered_messages
    
    def _deduplicate_and_prioritize(self, messages: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """Remove duplicates and prioritize messages by folder importance and urgency"""
        seen_ids = set()
        prioritized = []
        
        def collect_messages(criteria_func, label_check=None):
            for msg in messages:
                if is_promotional_email(msg):
                    continue
                if msg['id'] in seen_ids:
                    continue
                if label_check and label_check(msg):
                    prioritized.append(msg)
                    seen_ids.add(msg['id'])
                elif criteria_func(msg):
                    prioritized.append(msg)
                    seen_ids.add(msg['id'])
        
        # Collect in priority order: urgent > inbox > starred > important > primary
        collect_messages(lambda m: is_urgent_email(m))
        collect_messages(lambda m: False, lambda m: 'INBOX' in m.get('labels', []))
        collect_messages(lambda m: False, lambda m: 'STARRED' in m.get('labels', []))
        collect_messages(lambda m: False, lambda m: 'IMPORTANT' in m.get('labels', []))
        collect_messages(lambda m: False, lambda m: 'CATEGORY_PERSONAL' in m.get('labels', []))
        collect_messages(lambda m: True)
        
        return prioritized[:limit * SEARCH_CONFIG.SAFETY_LIMIT_MULTIPLIER]
    
    def _prioritize_results(self, messages: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """Prioritize search results by folder importance and urgency, then sort by date"""
        urgent_msgs = []
        inbox_msgs = []
        starred_msgs = []
        important_msgs = []
        primary_msgs = []
        other_msgs = []
        
        for msg in messages:
            if is_promotional_email(msg):
                continue
            
            is_urgent = is_urgent_email(msg)
            labels = msg.get('labels', [])
            
            if is_urgent:
                urgent_msgs.append(msg)
            elif 'INBOX' in labels:
                inbox_msgs.append(msg)
            elif 'STARRED' in labels:
                starred_msgs.append(msg)
            elif 'IMPORTANT' in labels:
                important_msgs.append(msg)
            elif 'CATEGORY_PERSONAL' in labels:
                primary_msgs.append(msg)
            else:
                other_msgs.append(msg)
        
        # Sort each group by date (newest first)
        def sort_by_date(msgs):
            from email.utils import parsedate_to_datetime
            from datetime import timezone
            
            def get_sort_key(msg):
                if 'internal_date' in msg:
                    return int(msg.get('internal_date', 0))
                date_str = msg.get('date', '')
                if date_str:
                    try:
                        dt = parsedate_to_datetime(date_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return int(dt.timestamp() * 1000)
                    except:
                        pass
                return 0
            
            return sorted(msgs, key=get_sort_key, reverse=True)
        
        urgent_msgs = sort_by_date(urgent_msgs)
        inbox_msgs = sort_by_date(inbox_msgs)
        starred_msgs = sort_by_date(starred_msgs)
        important_msgs = sort_by_date(important_msgs)
        primary_msgs = sort_by_date(primary_msgs)
        other_msgs = sort_by_date(other_msgs)
        
        prioritized = urgent_msgs + inbox_msgs + starred_msgs + important_msgs + primary_msgs + other_msgs
        
        logger.info(f"[SEARCH] Prioritized: {len(urgent_msgs)} urgent, {len(inbox_msgs)} inbox, {len(starred_msgs)} starred")
        
        return prioritized[:limit]
    
    def _is_keyword_search(self, query: str) -> bool:
        """Detect if query is a keyword/topic search vs general query"""
        query_lower = query.lower().strip()
        
        # Check if query matches general patterns (not a keyword search)
        if any(pattern in query_lower for pattern in SEARCH_CONFIG.GENERAL_QUERY_PATTERNS):
            if len(query_lower.split()) <= SEARCH_CONFIG.MAX_WORDS_FOR_GENERAL_QUERY:
                return False
        
        # Filter out action words and check for meaningful keywords
        meaningful_words = [
            w for w in query_lower.split() 
            if w not in SEARCH_CONFIG.ACTION_WORDS 
            and len(w) > SEARCH_CONFIG.MIN_WORD_LENGTH_FOR_KEYWORD
        ]
        
        return len(meaningful_words) > 0
    
    def _parse_date_range_from_query(self, query: str) -> Optional[Dict[str, datetime]]:
        """Parse date range from Gmail query string (after: and before: filters)"""
        try:
            from datetime import timezone
            
            after_match = re.search(r'after:(\d{4}/\d{2}/\d{2})', query)
            before_match = re.search(r'before:(\d{4}/\d{2}/\d{2})', query)
            
            if not after_match and not before_match:
                return None
            
            date_range = {}
            
            if after_match:
                date_str = after_match.group(1)
                after_utc = datetime.strptime(date_str, "%Y/%m/%d").replace(tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0)
                after_local = after_utc.astimezone()
                date_range['start'] = after_local.replace(hour=0, minute=0, second=0, microsecond=0)
            
            if before_match:
                date_str = before_match.group(1)
                before_utc = datetime.strptime(date_str, "%Y/%m/%d").replace(tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0)
                before_local = before_utc.astimezone()
                date_range['end'] = before_local.replace(hour=0, minute=0, second=0, microsecond=0)
            
            return date_range if date_range else None
            
        except Exception as e:
            logger.warning(f"Failed to parse date range from query: {e}")
            return None
    
    def _filter_messages_by_date_range(self, messages: List[Dict[str, Any]], date_range: Dict[str, datetime]) -> List[Dict[str, Any]]:
        """Filter messages to only include those within the specified date range"""
        try:
            from email.utils import parsedate_to_datetime
            from datetime import timezone
            
            filtered = []
            start_date = date_range.get('start')
            end_date = date_range.get('end')
            
            for message in messages:
                timestamp = message.get('date', '')
                if not timestamp:
                    filtered.append(message)
                    continue
                
                try:
                    dt = parsedate_to_datetime(timestamp)
                    if dt.tzinfo is not None:
                        dt_local = dt.astimezone()
                    else:
                        dt_local = dt.replace(tzinfo=timezone.utc).astimezone()
                    
                    in_range = True
                    
                    if 'start' in date_range:
                        start_of_day = date_range['start'].replace(hour=0, minute=0, second=0, microsecond=0)
                        if dt_local < start_of_day:
                            in_range = False
                    
                    if end_date and in_range:
                        if dt_local.date() >= end_date.date():
                            in_range = False
                    
                    if in_range:
                        filtered.append(message)
                        
                except Exception:
                    continue
            
            return filtered
            
        except Exception as e:
            logger.error(f"Failed to filter messages by date range: {e}")
            return messages
    
    def _format_email_list(self, messages: List[Dict[str, Any]]) -> str:
        """Format email list for output"""
        output = ""
        
        for i, message in enumerate(messages, 1):
            sender = message.get('sender', 'Unknown')
            subject = message.get('subject', '(No Subject)')
            timestamp = message.get('date', '')
            
            # Format timestamp
            try:
                if timestamp:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(timestamp)
                    if dt.tzinfo is not None:
                        dt = dt.astimezone()
                    formatted_time = dt.strftime('%Y-%m-%d %H:%M')
                else:
                    formatted_time = "Unknown time"
            except:
                formatted_time = timestamp or "Unknown time"
            
            # Check if unread
            labels = message.get('labels', [])
            unread_icon = "[UNREAD]" if "UNREAD" in labels else "[READ]"
            
            output += f"{i}. {unread_icon} **{subject}**\n"
            output += f"   From: {sender}\n"
            output += f"   Time: {formatted_time}\n"
            preview = extract_email_preview(message, LIMITS.CONTENT_PREVIEW_LENGTH)
            if preview:
                output += f"   Preview: {preview}\n"
            output += "\n"
        
        return output
