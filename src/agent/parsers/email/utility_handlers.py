"""
Email Utility Handlers

Handles all utility and helper functions for email parsing:
- Sender extraction from queries
- Email detail parsing from results
- Email ID extraction
- Email context formatting
- Result merging and deduplication
- Email extraction from various result formats

This module contains low-level utility functions used across other email modules.
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from ....utils.logger import setup_logger
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for utility operations
MAX_PREVIEW_LENGTH = 300
DEFAULT_MAX_RESULTS_EXTRACTION = EmailParserConfig.DEFAULT_EMAIL_LIMIT
MAX_SNIPPET_LENGTH = 200


class EmailUtilityHandlers:
    """
    Handles all utility and helper functions for email operations.
    
    This includes:
    - Parsing email search results (parse_email_search_result)
    - Extracting email IDs (extract_email_id_from_result)
    - Formatting email context (format_email_context_response)
    - Extracting senders from queries (extract_sender_from_query)
    - Extracting emails from result strings (extract_emails_from_result_string)
    - Extracting emails from RAG results (extract_emails_from_rag_result)
    - Merging search results (merge_search_results)
    - Detecting folders from queries (detect_folder_from_query)
    - Formatting email search with content (format_email_search_with_content)
    """
    
    def __init__(self, email_parser):
        """
        Initialize utility handlers.
        
        Args:
            email_parser: Parent EmailParser instance for accessing tools, config, etc.
        """
        self.email_parser = email_parser
    
    def parse_email_search_result(self, result: str) -> Optional[Dict[str, str]]:
        """
        Parse email search result to extract email details
        
        Extracts subject, sender, time, preview, and ID from formatted email result.
        Handles both single email results and the first email from multi-email results.
        
        Args:
            result: Formatted email search result string
            
        Returns:
            Dictionary with email details or None if parsing fails
        """
        if not result or "No emails found" in result:
            return None
        
        email_details = {}
        
        # Try to extract subject
        subject_match = re.search(r'\*\*([^*]+)\*\*', result)
        if subject_match:
            email_details['subject'] = subject_match.group(1).strip()
        
        # Try to extract sender
        sender_patterns = [
            r'From:\s*([^\n]+)',
            r'from\s+([A-Za-z\s]+)',
        ]
        for pattern in sender_patterns:
            sender_match = re.search(pattern, result, re.IGNORECASE)
            if sender_match:
                email_details['sender'] = sender_match.group(1).strip()
                break
        
        # Try to extract time/date
        time_patterns = [
            r'Time:\s*([^\n]+)',
            r'Received:\s*([^\n]+)',
            r'(\d{1,2}/\d{1,2}/\d{2,4})',
        ]
        for pattern in time_patterns:
            time_match = re.search(pattern, result, re.IGNORECASE)
            if time_match:
                email_details['time'] = time_match.group(1).strip()
                break
        
        # Try to extract preview/snippet
        preview_patterns = [
            r'Preview:\s*([^\n]+)',
            r'Content:\s*([^\n]+)',
        ]
        for pattern in preview_patterns:
            preview_match = re.search(pattern, result, re.IGNORECASE)
            if preview_match:
                email_details['preview'] = preview_match.group(1).strip()
                break
        
        # Try to extract email ID
        id_match = re.search(r'ID:\s*([a-zA-Z0-9]+)', result, re.IGNORECASE)
        if id_match:
            email_details['id'] = id_match.group(1).strip()
        
        return email_details if email_details else None
    
    def extract_email_id_from_result(self, result: str) -> Optional[str]:
        """
        Extract email ID from result string
        
        Args:
            result: Email search result containing ID
            
        Returns:
            Email ID string or None if not found
        """
        if not result:
            return None
        
        # Try to extract ID from result
        id_match = re.search(r'ID:\s*([a-zA-Z0-9]+)', result, re.IGNORECASE)
        if id_match:
            return id_match.group(1).strip()
        
        # Try alternative formats
        id_match = re.search(r'message_id[:\s]+([a-zA-Z0-9]+)', result, re.IGNORECASE)
        if id_match:
            return id_match.group(1).strip()
        
        return None
    
    def format_email_context_response(self, email_details: Dict[str, str], sender: str) -> str:
        """
        Format email details into a contextual response
        
        Creates a natural language summary of email details including subject,
        sender, date, and preview content.
        
        Args:
            email_details: Dictionary of email fields (subject, sender, time, preview)
            sender: Sender name for response formatting
            
        Returns:
            Formatted response string
        """
        response = f"[EMAIL] Email from {sender}"
        
        if email_details.get('subject'):
            response += f" about \"{email_details['subject']}\""
        
        if email_details.get('time'):
            response += f" (received on {email_details['time']})"
        
        preview = email_details.get('preview')
        if preview and isinstance(preview, str):
            if len(preview) > MAX_PREVIEW_LENGTH:
                preview = preview[:MAX_PREVIEW_LENGTH] + "..."
            response += f". {preview}"
        
        return response
    
    def extract_sender_from_query(self, query: str) -> Optional[str]:
        """
        Extract sender name/email from query - handles multi-word names and 'or' queries
        
        Supports complex queries like:
        - "from John Smith"
        - "from Amex Recruiting or American Express"
        - "email from alice@example.com"
        
        Args:
            query: User query containing sender information
            
        Returns:
            Extracted sender name/email or None
        """
        logger.info(f"[EMAIL] Extracting sender from query: '{query}'")
        
        query_lower = query.lower()
        
        # CRITICAL: Check for time-based queries FIRST - these are NOT sender queries
        # Patterns like "from the last hour", "from the last day", "from the last week", etc.
        time_based_patterns = [
            r'from\s+the\s+last\s+(hour|day|week|month|year|few\s+hours|few\s+days)',
            r'from\s+the\s+past\s+(hour|day|week|month|year|few\s+hours|few\s+days)',
            r'in\s+the\s+last\s+(hour|day|week|month|year|few\s+hours|few\s+days)',
            r'in\s+the\s+past\s+(hour|day|week|month|year|few\s+hours|few\s+days)',
            r'since\s+(?:the\s+)?(?:last|past)\s+(hour|day|week|month|year|few\s+hours|few\s+days)',
            r'from\s+the\s+last\s+\d+\s+(hours?|days?|weeks?|months?|years?)',
            r'from\s+the\s+past\s+\d+\s+(hours?|days?|weeks?|months?|years?)',
        ]
        
        for pattern in time_based_patterns:
            if re.search(pattern, query_lower):
                logger.info(f"[EMAIL] Detected time-based query (not a sender query): '{query}'")
                return None
        
        # FIRST: Check for "or" queries with multiple senders (e.g., "Amex Recruiting or American Express")
        # Extract everything between "from" and stop words like "today", "yesterday", "?", or end of query
        # CRITICAL: Check for "all about" phrase first, then individual stop words
        if "all about" in query_lower and "from" in query_lower:
            # Stop at "all about" phrase
            from_idx = query_lower.find("from")
            all_about_idx = query_lower.find("all about")
            if from_idx < all_about_idx:
                sender_text = query[from_idx + 4:query.lower().find("all about")].strip()
                
                # CRITICAL: Handle quoted sender names (e.g., "'The Core'" or '"The Core"')
                # Find ALL quoted strings - the first one should be the sender
                quoted_matches = list(re.finditer(r'["\']([^"\']+)["\']', sender_text))
                if quoted_matches:
                    # Use the first quoted match as the sender
                    sender = quoted_matches[0].group(1).strip()
                    logger.info(f"[EMAIL] Extracted quoted sender (stopped at 'all about'): '{sender}'")
                    return sender
                
                # If no quotes, check if there's a "with" or "subject" pattern that indicates subject is coming
                # e.g., "from The Core with the subject 'X'"
                if "with" in sender_text.lower() and ("subject" in sender_text.lower() or "titled" in sender_text.lower()):
                    # Extract sender before "with"
                    with_idx = sender_text.lower().find("with")
                    sender_text = sender_text[:with_idx].strip()
                
                # Clean up the extracted sender - remove trailing stop words
                sender = re.sub(r'\s+(what|is|the|email|emails|with|subject).*$', '', sender_text, flags=re.IGNORECASE).strip()
                # Remove any remaining quotes
                sender = sender.strip("'\"")
                # Skip if it's just noise words or common verbs/auxiliary words
                skip_words = ['did', 'does', 'do', 'when', 'what', 'who', 'where', 'why', 'how', 'the', 'my', 'me', 'i', 'was', 'were', 'are', 'is', 'about', 'any', 'have', 'has', 'had', 'been', 'being', 'get', 'got', 'new', 'recent']
                # Check if sender is just skip words or combinations of them
                sender_words = sender.lower().split()
                if all(word in skip_words for word in sender_words) or sender.lower() in skip_words:
                    logger.debug(f"[EMAIL] Rejected sender '{sender}' - contains only common verbs/auxiliary words")
                    # Don't return this sender, but continue to next pattern
                elif sender and len(sender) > 1 and sender.lower() not in skip_words:
                    logger.info(f"[EMAIL] Extracted sender (stopped at 'all about'): '{sender}'")
                    return sender
        
        # Stop words that indicate end of sender name
        # CRITICAL: Include time-based phrases AND common verbs/auxiliary words to prevent false matches
        stop_words = r'\b(today|yesterday|tomorrow|this week|last week|last hour|last day|last month|last year|past hour|past day|past week|past month|past year|few hours|few days|all about|about|regarding|that|email|emails|messages|subject|with|do|does|did|have|has|had|are|were|was|is|get|got|new|recent|\?|$)'
        or_pattern = r'from\s+((?:(?!' + stop_words + r').)+?)(?:\s+' + stop_words + r'|$)'
        or_match = re.search(or_pattern, query, re.IGNORECASE)
        if or_match:
            sender_text = or_match.group(1).strip()
            # Check if it contains "or"
            if ' or ' in sender_text.lower():
                # Split by "or" and extract senders
                parts = re.split(r'\s+or\s+', sender_text, flags=re.IGNORECASE)
                if len(parts) >= 2:
                    # Take the first sender (we'll handle multiple senders in the search query builder)
                    first_sender = parts[0].strip()
                    # Clean up - remove trailing words like "what", "about", etc.
                    first_sender = re.sub(r'\s+(what|about|is|the|email|emails|do|does|have|has).*$', '', first_sender, flags=re.IGNORECASE)
                    # Validate sender is not just common verbs
                    skip_words = ['did', 'does', 'do', 'when', 'what', 'who', 'where', 'why', 'how', 'the', 'my', 'me', 'i', 'was', 'were', 'are', 'is', 'about', 'any', 'have', 'has', 'had', 'been', 'being', 'get', 'got', 'new', 'recent']
                    sender_words = first_sender.lower().split()
                    if first_sender and len(first_sender) > 1 and first_sender.lower() not in skip_words and not all(word in skip_words for word in sender_words):
                        logger.info(f"[EMAIL] Found first sender in 'or' query: '{first_sender}'")
                        return first_sender
        
        # SECOND: Try patterns that handle multi-word names (company names with spaces)
        # Include temporal words like "today", "yesterday", "this week" as stop words
        # CRITICAL: Include "all about" as a stop phrase, time-based phrases, AND common verbs/auxiliary words
        temporal_stop_words = r'(?:today|yesterday|tomorrow|this week|last week|last hour|last day|last month|last year|past hour|past day|past week|past month|past year|few hours|few days|this month|last month|this year|last year)'
        verb_stop_words = r'(?:do|does|did|have|has|had|are|were|was|is|get|got|new|recent)'
        content_stop_phrases = r'(?:all about|about|what|is|the|email|emails)'
        patterns = [
            # Pattern 1: "from [Name/Company] all about" - stop at "all about" phrase
            r'from\s+([A-Za-z0-9\s@._-]+?)\s+all\s+about',
            # Pattern 2: "from [Name/Company] today/yesterday/etc" - direct match for temporal queries
            r'from\s+([A-Za-z0-9\s@._-]+?)\s+' + temporal_stop_words,
            # Pattern 3: "from [Name/Company]" - capture everything up to temporal words, verbs, question mark, or common keywords
            r'from\s+([A-Za-z0-9\s@._-]+?)(?:\s+(?:' + temporal_stop_words + r'|' + verb_stop_words + r'|' + content_stop_phrases + r'|\?)|$)',
            # Pattern 4: "emails from [Name]"
            r'emails?\s+from\s+([A-Za-z0-9\s@._-]+?)(?:\s+(?:' + temporal_stop_words + r'|' + verb_stop_words + r'|' + content_stop_phrases + r'|\?)|$)',
            # Pattern 5: Just email address
            r'\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                sender = match.group(1).strip()
                
                # Clean up the extracted sender
                # Remove trailing question marks and common words
                sender = sender.rstrip('?').strip()
                
                # Remove trailing temporal words, verbs, and other stop words (including "all about")
                sender = re.sub(r'\s+(all\s+about|today|yesterday|tomorrow|this week|last week|this month|last month|what|about|is|the|email|emails|do|does|did|have|has|had|are|were|was|is|get|got|new|recent).*$', '', sender, flags=re.IGNORECASE)
                sender = sender.strip()
                
                # Skip if it's just noise words or common verbs/auxiliary words
                skip_words = ['did', 'does', 'do', 'when', 'what', 'who', 'where', 'why', 'how', 'the', 'my', 'me', 'i', 'was', 'were', 'are', 'is', 'about', 'any', 'have', 'has', 'had', 'been', 'being', 'get', 'got', 'new', 'recent']
                # Check if sender is just skip words or combinations of them
                sender_words = sender.lower().split()
                if sender.lower() in skip_words or all(word in skip_words for word in sender_words):
                    logger.debug(f"[EMAIL] Rejected sender '{sender}' - contains only common verbs/auxiliary words")
                    # Don't return this sender, try next pattern
                elif sender and len(sender) > 1:
                    # Valid sender found - must be at least 2 characters and not just common words
                    logger.info(f"[EMAIL] Extracted sender: '{sender}'")
                    return sender
        
        logger.info(f"[EMAIL] Could not extract sender from query")
        return None
    
    def extract_emails_from_result_string(self, result_str: str, tool) -> List[Dict[str, Any]]:
        """
        Extract email objects from a result string
        
        Parses formatted result string and attempts to fetch full email messages
        using the email tool if message IDs are available.
        
        Args:
            result_str: Formatted email search result string
            tool: Email tool instance with google_client
            
        Returns:
            List of email message dictionaries
        """
        emails = []
        if not result_str:
            return emails
        
        try:
            # Parse the result string to extract email details
            email_details = self.parse_email_search_result(result_str)
            if email_details:
                # Try to get the actual message using the ID if available
                message_id = email_details.get('id')
                if message_id and hasattr(tool, 'google_client') and tool.google_client:
                    try:
                        message = tool.google_client.get_message(message_id)
                        if message:
                            emails.append(message)
                    except:
                        pass
        except Exception as e:
            logger.warning(f"[EMAIL] Could not extract emails from result string: {e}")
        
        return emails
    
    def extract_emails_from_rag_result(self, rag_result_str: str, tool, max_results: int = DEFAULT_MAX_RESULTS_EXTRACTION) -> List[Dict[str, Any]]:
        """
        Extract email message objects from RAG search result
        
        Attempts to get raw RAG results with message IDs, then fetches full messages from Gmail.
        Falls back to parsing the formatted result string if raw results aren't available.
        
        Args:
            rag_result_str: Formatted RAG search result string
            tool: Email tool instance with google_client and rag_engine
            max_results: Maximum number of emails to extract
            
        Returns:
            List of email message dictionaries
        """
        emails = []
        try:
            # First, try to get raw RAG results if we have access to the RAG tool
            # This is more efficient than parsing the formatted string
            if hasattr(tool, 'rag_engine') and tool.rag_engine:
                # We need to re-run the RAG search to get raw results
                # But we don't have the original query here, so we'll parse from the string
                pass  # Will fall through to parsing
            
            # Parse from formatted result string and fetch messages by ID
            if hasattr(tool, 'google_client') and tool.google_client:
                # Extract message IDs from RAG result if they're embedded
                # RAG results might have message IDs in metadata
                # Try to extract from the formatted string by looking for patterns
                
                # Method 1: Extract subjects and fetch messages
                subject_pattern = r'\*\*([^*]+)\*\*'
                subjects = re.findall(subject_pattern, rag_result_str)
                
                seen_subjects = set()
                for subject in subjects[:max_results]:  # Get more to account for duplicates
                    if subject in seen_subjects:
                        continue
                    seen_subjects.add(subject)
                    
                    try:
                        # Search for email with this subject
                        messages = tool.google_client.list_messages(
                            query=f'subject:"{subject}"',
                            max_results=1
                        )
                        if messages:
                            emails.append(messages[0])
                    except Exception as e:
                        logger.debug(f"[EMAIL] Could not fetch email for subject '{subject}': {e}")
                        continue
                
                logger.info(f"[EMAIL] Extracted {len(emails)} emails from RAG results using subject matching")
        except Exception as e:
            logger.warning(f"[EMAIL] Could not extract emails from RAG result: {e}")
        
        return emails
    
    def merge_search_results(self, direct_results: List[Dict[str, Any]], 
                           rag_results: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """
        Merge and deduplicate search results from direct and RAG searches
        
        Prioritizes direct search results, then adds RAG results that aren't duplicates.
        Results are sorted by date (newest first).
        
        Args:
            direct_results: List of email dicts from direct search
            rag_results: List of email dicts from RAG search
            limit: Maximum number of results to return
            
        Returns:
            Merged and deduplicated list of emails
        """
        seen_ids = set()
        merged = []
        
        # Add direct search results first (higher priority)
        for email in direct_results:
            email_id = email.get('id')
            if email_id and email_id not in seen_ids:
                email['_source'] = 'direct'
                merged.append(email)
                seen_ids.add(email_id)
        
        # Add RAG results that aren't duplicates
        for email in rag_results:
            email_id = email.get('id')
            if email_id and email_id not in seen_ids:
                email['_source'] = 'rag'
                merged.append(email)
                seen_ids.add(email_id)
        
        # Sort by date (newest first)
        try:
            merged.sort(key=lambda x: x.get('internalDate', 0), reverse=True)
        except:
            pass  # Skip sorting if internalDate not available
        
        # Limit results
        return merged[:limit]
    
    def detect_folder_from_query(self, query: str) -> Optional[str]:
        """
        Detect email folder/label from query
        
        Recognizes common folder names like inbox, sent, drafts, spam, trash.
        
        Args:
            query: User query that may contain folder reference
            
        Returns:
            Folder name or None if not detected
        """
        query_lower = query.lower()
        
        folder_map = {
            'inbox': 'INBOX',
            'sent': 'SENT',
            'drafts': 'DRAFT',
            'spam': 'SPAM',
            'trash': 'TRASH',
            'starred': 'STARRED',
            'important': 'IMPORTANT',
        }
        
        for keyword, folder in folder_map.items():
            if keyword in query_lower:
                logger.info(f"[EMAIL] Detected folder from query: {folder}")
                return folder
        
        return None
    
    def format_email_search_with_content(self, result: str, sender: str) -> str:
        """
        Format email search result to include content when query asks 'what was it about'
        
        Enhances basic search results with email content preview for contextual queries.
        
        Args:
            result: Basic email search result string
            sender: Sender name for formatting
            
        Returns:
            Enhanced result with content preview
        """
        if "Gmail Search Results" not in result or "No emails found" in result:
            return result
        
        # Parse the first email from the result
        email_details = self.parse_email_search_result(result)
        if email_details:
            response = f"[EMAIL] Email from {sender}"
            
            if email_details.get('subject'):
                response += f" about \"{email_details['subject']}\""
            
            if email_details.get('time'):
                response += f" (received on {email_details['time']})"
            
            preview = email_details.get('preview')
            if preview and isinstance(preview, str):
                if len(preview) > MAX_PREVIEW_LENGTH:
                    preview = preview[:MAX_PREVIEW_LENGTH] + "..."
                response += f". {preview}"
            
            return response
        
        return result
