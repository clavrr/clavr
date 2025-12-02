"""
Email Action Handlers - List, search, send, reply operations

This module contains handlers for primary email CRUD operations.
Extracted from email_parser.py to reduce file size and improve maintainability.
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for action handlers
DEFAULT_LIST_LIMIT = EmailParserConfig.DEFAULT_EMAIL_LIMIT
DEFAULT_PRIMARY_FOLDER_LIMIT = 5
EXPLICIT_LIMIT_10 = 10
EXPLICIT_LIMIT_5 = 5
EXPLICIT_LIMIT_3 = 3
SINGLE_RESULT_LIMIT = 1
WEEK_FILTER_DAYS = 7
MONTH_FILTER_DAYS = 30


class EmailActionHandlers:
    """Handlers for email CRUD operations (list, search, send, reply)"""
    
    def __init__(self, parser):
        """
        Initialize action handlers with reference to main parser.
        
        Args:
            parser: EmailParser instance for accessing shared methods and attributes
        """
        self.parser = parser
        self.llm_client = parser.llm_client
        self.rag_service = parser.rag_service
    
    def _is_valid_sender_name(self, sender: str) -> bool:
        """
        Validate that a sender name is valid (not just common verbs/auxiliary words)
        
        Args:
            sender: Sender name to validate
            
        Returns:
            True if sender is valid, False otherwise
        """
        if not sender or not sender.strip():
            return False
        
        sender_lower = sender.lower().strip()
        
        # Common verbs/auxiliary words that should not be treated as sender names
        invalid_words = {'do', 'does', 'did', 'have', 'has', 'had', 'are', 'were', 'was', 'is', 'get', 'got', 
                        'what', 'when', 'where', 'why', 'how', 'who', 'the', 'my', 'me', 'i', 'about', 'any',
                        'new', 'recent', 'been', 'being', 'and', 'or', 'to', 'from', 'email', 'message', 'emails'}
        
        # Check if sender is just invalid words
        if sender_lower in invalid_words:
            return False
        
        # Check if all words in sender are invalid words
        sender_words = sender_lower.split()
        if all(word in invalid_words for word in sender_words):
            return False
        
        # Must have at least 2 characters
        if len(sender_lower) < 2:
            return False
        
        # Must contain at least one letter (or be an email address)
        if not re.search(r'[a-zA-Z]', sender) and '@' not in sender:
            return False
        
        return True
    
    def _format_email_list_to_string(self, emails: List[Dict[str, Any]], limit: int = DEFAULT_LIST_LIMIT) -> str:
        """
        Format a list of email dictionaries into a formatted string for conversational handlers.
        
        Args:
            emails: List of email dictionaries from Gmail API
            limit: Maximum number of emails to format
            
        Returns:
            Formatted string representation of emails
        """
        if not emails:
            return "No emails found."
        
        formatted_lines = []
        formatted_lines.append(f"Gmail Search Results ({len(emails)}):\n")
        
        for i, email in enumerate(emails[:limit], 1):
            # CRITICAL: Use 'from' field first (Gmail API standard), then 'sender' as fallback
            sender = email.get('from') or email.get('sender', 'Unknown')
            # Ensure sender is not empty or just whitespace
            if not sender or not sender.strip():
                sender = 'Unknown'
            
            # CRITICAL: Subject should never be empty - check for various formats
            subject = email.get('subject', '')
            if not subject or subject.strip() == '' or subject == 'No Subject':
                subject = '(No Subject)'
            
            date = email.get('date', '')
            snippet = email.get('snippet', '') or email.get('body', '')
            
            # Check if unread
            labels = email.get('labels', [])
            unread_status = "[UNREAD]" if "UNREAD" in labels else "[READ]"
            
            formatted_lines.append(f"{i}. {unread_status} **{subject}**")
            formatted_lines.append(f"   From: {sender}")
            if date:
                formatted_lines.append(f"   Date: {date}")
            if snippet:
                preview = snippet[:200].replace('\n', ' ')
                formatted_lines.append(f"   Preview: {preview}...")
            formatted_lines.append("")
        
        return "\n".join(formatted_lines)
    
    def handle_list_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle email listing action with date filtering.
        
        Supports:
        - Date-based filtering (today, yesterday, this week, etc.)
        - "New emails" queries (maps to unread)
        - "Most recent" queries
        - Primary folder queries
        
        Args:
            tool: Email tool instance
            query: User query
            
        Returns:
            Formatted email list or conversational response
        """
        # Extract actual query from conversation context first
        actual_query = self.parser.query_processing_handlers.extract_actual_query(query)
        # CRITICAL: If extract_actual_query returns empty, use original query to preserve time filters
        if not actual_query or not actual_query.strip():
            # Only use original query if it's not empty, otherwise default to inbox
            if query and query.strip():
                actual_query = query.strip()
                logger.debug(f"[EMAIL] extract_actual_query returned empty, using original query: '{query[:100]}'")
            else:
                # Both are empty - this shouldn't happen, but handle gracefully
                logger.warning(f"[EMAIL] Both extract_actual_query and original query are empty, defaulting to inbox")
                actual_query = "in:inbox"
        query_lower = actual_query.lower()
        
        # If query contains a sender name, it should have been handled as search, not list
        # But if it somehow got here, don't filter by date - search all emails
        sender = self.parser.utility_handlers.extract_sender_from_query(actual_query)
        if sender:
            logger.warning(f"[EMAIL] List action received sender-specific query, redirecting to search: '{sender}'")
            return self.handle_search_action(tool, actual_query)
        
        # Check if query asks for "new" or "today" emails
        # Detect "most recent" queries - these should be more flexible
        is_most_recent_query = any(phrase in query_lower for phrase in [
            "most recent", "latest", "last email", "recent email", "recent emails"
        ])
        
        # Detect if user is asking for "new" emails (should be unread)
        is_new_email_query = any(phrase in query_lower for phrase in [
            "new emails", "new email", "new messages", "new message"
        ])
        
        # Detect "primary folder" queries - map to inbox
        is_primary_folder_query = any(phrase in query_lower for phrase in [
            "primary folder", "primary inbox", "main folder", "main inbox"
        ])
        
        # Handle "primary folder" queries - just show inbox emails
        if is_primary_folder_query:
            logger.info(f"[EMAIL] Primary folder query - showing inbox emails")
            # Use higher limit for "today" queries to avoid truncation
            # Check if query mentions "today" using date parser if available
            is_today_query = False
            if self.parser.date_parser:
                try:
                    # FlexibleDateParser.parse() returns Optional[Tuple[datetime, datetime]]
                    parsed_date_tuple = self.parser.date_parser.parse(actual_query)
                    if parsed_date_tuple and isinstance(parsed_date_tuple, tuple) and len(parsed_date_tuple) == 2:
                        start, end = parsed_date_tuple
                        # Check if date range includes today
                        now = datetime.now(timezone.utc)
                        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                        if start and start <= today_start:
                            is_today_query = True
                except Exception:
                    # Fallback: check for "today" in query
                    is_today_query = "today" in query_lower
            
            # Use higher limit for today queries to show all emails
            if is_today_query or "today" in query_lower:
                explicit_limit = EmailParserConfig.DEFAULT_EMAIL_LIMIT  # Use default limit (20) for today
            else:
                # For "new emails" queries, use higher limit (DEFAULT_EMAIL_LIMIT = 20) to show more emails
                # Only use limit=10 if explicitly requested, otherwise use DEFAULT_EMAIL_LIMIT for "new emails" queries
                if is_new_email_query:
                    explicit_limit = EXPLICIT_LIMIT_10 if any(phrase in query_lower for phrase in ["10 emails", "ten emails"]) else EmailParserConfig.DEFAULT_EMAIL_LIMIT
                else:
                    explicit_limit = EXPLICIT_LIMIT_10 if any(phrase in query_lower for phrase in ["10 emails", "ten emails"]) else DEFAULT_PRIMARY_FOLDER_LIMIT
            
            if is_new_email_query:
                result = tool._run(action="unread", limit=explicit_limit)
            else:
                result = tool._run(action="search", query="in:inbox", limit=explicit_limit)
            
            # CRITICAL: ALWAYS generate conversational response using LLM
            if self.llm_client and result:
                try:
                    user_first_name = getattr(self.parser, 'user_first_name', None)
                    conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(
                        result, actual_query, user_first_name=user_first_name
                    )
                    if conversational_response and conversational_response.strip():
                        return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
                except Exception as e:
                    logger.warning(f"[EMAIL] Failed to generate conversational response: {e}, cleaning up result")
                    return self.parser.conversational_handlers.final_cleanup_conversational_response(result)
            elif not result or not result.strip():
                # Empty result - generate LLM response
                if self.llm_client:
                    try:
                        user_first_name = getattr(self.parser, 'user_first_name', None)
                        llm_response = self.parser.conversational_handlers.generate_conversational_email_response(
                            "", actual_query, user_first_name=user_first_name
                        )
                        if llm_response and llm_response.strip():
                            return self.parser.conversational_handlers.final_cleanup_conversational_response(llm_response.strip())
                    except Exception as e:
                        logger.error(f"[EMAIL] Failed to generate LLM response for empty result: {e}")
                return ""
            
            # Fallback: clean up robotic patterns
            return self.parser.conversational_handlers.final_cleanup_conversational_response(result)
        
        # For "most recent" queries, try today first, but fallback to recent if no results
        if is_most_recent_query:
            # Try to get most recent email from today first
            today_query = "in:inbox"
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone()
            today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end_local = today_start_local + timedelta(days=1)
            today_start_utc = today_start_local.astimezone(timezone.utc)
            today_end_utc = today_end_local.astimezone(timezone.utc)
            after_date = today_start_utc.strftime("%Y/%m/%d")
            before_date = today_end_utc.strftime("%Y/%m/%d")
            today_query_with_date = f"{today_query} after:{after_date} before:{before_date}"
            
            logger.info(f"[EMAIL] Most recent query - trying today first: {today_query_with_date}")
            result = tool._run(action="search", query=today_query_with_date, limit=SINGLE_RESULT_LIMIT)
            
            # If no results today, fallback to most recent overall
            if "No emails found" in result or "no emails found" in result.lower():
                logger.info(f"[EMAIL] No emails today, falling back to most recent overall")
                fallback_result = tool._run(action="search", query="in:inbox", limit=SINGLE_RESULT_LIMIT)
                # Generate conversational response using LLM
                if self.llm_client and fallback_result:
                    try:
                        user_first_name = getattr(self.parser, 'user_first_name', None)
                        conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(
                            fallback_result, query, user_first_name=user_first_name
                        )
                        if conversational_response and conversational_response.strip():
                            return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
                    except Exception as e:
                        logger.warning(f"[EMAIL] Failed to generate conversational response: {e}")
                return self.parser.conversational_handlers.final_cleanup_conversational_response(fallback_result) if fallback_result else ""
            else:
                # Generate conversational response using LLM
                if self.llm_client and result:
                    try:
                        user_first_name = getattr(self.parser, 'user_first_name', None)
                        conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(
                            result, query, user_first_name=user_first_name
                        )
                        if conversational_response and conversational_response.strip():
                            return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
                    except Exception as e:
                        logger.warning(f"[EMAIL] Failed to generate conversational response: {e}")
                return self.parser.conversational_handlers.final_cleanup_conversational_response(result) if result else ""
        
        # Parse date filter from query using FlexibleDateParser if available
        date_filter = None
        date_range = None
        hours_to_filter = None
        
        # CRITICAL: First check for time-based queries (hours, not days) - these need newer_than: filter
        time_based_patterns = [
            (r'last\s+hour|past\s+hour', 1),
            (r'last\s+(\d+)\s+hours?|past\s+(\d+)\s+hours?', None),  # Will extract number
            (r'few\s+hours?', 2),
            (r'last\s+hour\s+or\s+so', 1),  # Handle "last hour or so"
        ]
        
        for pattern, default_hours in time_based_patterns:
            match = re.search(pattern, query_lower)
            if match:
                hours_to_filter = default_hours
                if default_hours is None:
                    # Extract number from match
                    hours_to_filter = int(match.group(1) or match.group(2) or 1)
                logger.info(f"[EMAIL] Detected time-based query: last {hours_to_filter} hour(s)")
                break
        
        # Use FlexibleDateParser to intelligently parse temporal references
        if self.parser.date_parser and not hours_to_filter:
            try:
                # Parse the query to extract date range
                # FlexibleDateParser.parse() returns Optional[Tuple[datetime, datetime]]
                parsed_date_tuple = self.parser.date_parser.parse(actual_query)
                if parsed_date_tuple and isinstance(parsed_date_tuple, tuple) and len(parsed_date_tuple) == 2:
                    start, end = parsed_date_tuple
                    date_range = {'start': start, 'end': end}
                    
                    # Determine date filter type based on parsed dates
                    now = datetime.now(timezone.utc)
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    yesterday_start = today_start - timedelta(days=1)
                    week_start = today_start - timedelta(days=7)
                    
                    if start and end:
                        # Normalize dates to compare only the date part (ignore time)
                        start_date = start.date() if hasattr(start, 'date') else start
                        end_date = end.date() if hasattr(end, 'date') else end
                        today_date = today_start.date() if hasattr(today_start, 'date') else today_start
                        yesterday_date = yesterday_start.date() if hasattr(yesterday_start, 'date') else yesterday_start
                        
                        # Check if it's today (start <= today and end >= today)
                        if start_date <= today_date and end_date >= today_date:
                            date_filter = "today"
                        # Check if it's yesterday (start date is yesterday and end date is before today)
                        elif start_date == yesterday_date and end_date < today_date:
                            date_filter = "yesterday"
                        # Check if it's this week
                        elif start_date <= week_start.date() if hasattr(week_start, 'date') else week_start:
                            date_filter = "week"
                        else:
                            date_filter = "custom"  # Custom date range
                    
                    logger.info(f"[EMAIL] Date parser extracted: {date_filter} (start: {start}, end: {end})")
            except Exception as e:
                logger.warning(f"[EMAIL] Date parser failed: {e}, falling back to pattern matching")
        
        # Fallback to pattern matching if date parser unavailable or failed
        # CRITICAL: Skip fallback if hours_to_filter is already set (time-based query detected)
        if not date_filter and not hours_to_filter:
            # Check for "yesterday" (highest priority)
            if any(phrase in query_lower for phrase in ["yesterday", "yesterday's"]):
                date_filter = "yesterday"
            # Check for "today"
            elif any(phrase in query_lower for phrase in ["today", "today's"]):
                date_filter = "today"
            # Check for other time periods with "new emails"
            elif is_new_email_query:
                # Check for time period
                if any(phrase in query_lower for phrase in ["new today", "today's", "from today"]):
                    date_filter = "today"
                elif any(phrase in query_lower for phrase in ["this week", "this week's", "last week"]):
                    date_filter = "week"
                elif any(phrase in query_lower for phrase in ["this month", "this month's", "last month"]):
                    date_filter = "month"
                else:
                    # Default "new emails" without date means recent/unread
                    return tool._run(action="unread", limit=EmailParserConfig.DEFAULT_EMAIL_LIMIT)
        
        logger.info(f"[EMAIL] Email list action - date_filter: {date_filter}, hours_to_filter: {hours_to_filter}, is_new_email_query: {is_new_email_query}")
        
        # Build search query with proper filters
        search_parts = ["in:inbox"]  # Always limit to inbox
        
        if is_new_email_query or any(phrase in query_lower for phrase in ["new", "unread"]):
            search_parts.append("is:unread")  # Only unread emails for "new" queries
        
        # If date filter specified, add it
        # CRITICAL: Handle time-based queries (hours) FIRST - these need newer_than: filter
        if hours_to_filter is not None:
            # Use newer_than: for hour-level precision (Gmail supports hours)
            search_parts.append(f"newer_than:{hours_to_filter}h")
            logger.info(f"[EMAIL] Added time-based filter: newer_than:{hours_to_filter}h")
        elif date_range and date_filter == "custom":
            # Use parsed date range from FlexibleDateParser
            start = date_range.get('start')
            end = date_range.get('end')
            if start and end:
                # Format dates for Gmail (YYYY/MM/DD format in UTC)
                # Ensure timezone-aware
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                
                start_utc = start.astimezone(timezone.utc)
                end_utc = end.astimezone(timezone.utc)
                
                after_date = start_utc.strftime("%Y/%m/%d")
                before_date = end_utc.strftime("%Y/%m/%d")
                search_parts.append(f"after:{after_date}")
                search_parts.append(f"before:{before_date}")
                logger.info(f"[EMAIL] Custom date filter: after:{after_date} before:{before_date}")
        elif date_filter == "yesterday":
            # Search for emails from yesterday
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone()
            
            # Get yesterday's start and end in local timezone
            today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start_local = today_start_local - timedelta(days=1)
            yesterday_end_local = today_start_local
            
            # Convert to UTC for Gmail query
            yesterday_start_utc = yesterday_start_local.astimezone(timezone.utc)
            yesterday_end_utc = yesterday_end_local.astimezone(timezone.utc)
            
            after_date = yesterday_start_utc.strftime("%Y/%m/%d")
            before_date = yesterday_end_utc.strftime("%Y/%m/%d")
            
            search_parts.append(f"after:{after_date}")
            search_parts.append(f"before:{before_date}")
            logger.info(f"[EMAIL] Yesterday filter: after:{after_date} before:{before_date}")
        elif date_filter == "today":
            # Similar handling for today
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone()
            
            today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end_local = today_start_local + timedelta(days=1)
            
            today_start_utc = today_start_local.astimezone(timezone.utc)
            today_end_utc = today_end_local.astimezone(timezone.utc)
            
            after_date = today_start_utc.strftime("%Y/%m/%d")
            before_date = today_end_utc.strftime("%Y/%m/%d")
            
            search_parts.append(f"after:{after_date}")
            search_parts.append(f"before:{before_date}")
            logger.info(f"[EMAIL] Today filter: after:{after_date} before:{before_date}")
        elif date_filter == "week":
            search_parts.append(f"newer_than:{WEEK_FILTER_DAYS}d")
        elif date_filter == "month":
            search_parts.append("newer_than:1m")
        
        search_query = " ".join(search_parts)
        logger.info(f"[EMAIL] Final search query: '{search_query}'")
        
        # Use higher limit for "today" and time-based queries (like "last hour") to avoid truncation
        # For "new emails today" or "last hour", we want to show all emails, not just 5
        search_limit = DEFAULT_LIST_LIMIT
        if date_filter == "today" or (is_new_email_query and "today" in query_lower):
            search_limit = EmailParserConfig.DEFAULT_EMAIL_LIMIT  # Use default limit (20) for today queries
            logger.info(f"[EMAIL] Using higher limit ({search_limit}) for today query to avoid truncation")
        elif hours_to_filter is not None:
            # CRITICAL: For time-based queries (last hour, etc.), use higher limit to get all emails
            search_limit = EmailParserConfig.DEFAULT_EMAIL_LIMIT  # Use default limit (20) for time-based queries
            logger.info(f"[EMAIL] Using higher limit ({search_limit}) for time-based query (last {hours_to_filter} hour(s)) to avoid truncation")
        
        # CRITICAL: Execute search directly using Gmail client to avoid double conversational response generation
        # If we call tool._run(action="search"), it will generate a conversational response in handle_search_action,
        # and then we'll generate another one here, causing double processing and wrong query detection
        if hasattr(self.parser, 'google_client') and self.parser.google_client:
            try:
                emails = self.parser.google_client.list_messages(query=search_query, max_results=search_limit)
                if not emails:
                    return "I couldn't find any emails matching that query."
                # Format results into a string that conversational handlers can process
                formatted_result = self._format_email_list_to_string(emails, limit=search_limit)
                
                # Generate conversational response using LLM with the ORIGINAL query (not the Gmail query string)
                if self.llm_client and formatted_result:
                    try:
                        # Pass user_first_name for personalization
                        user_first_name = getattr(self.parser, 'user_first_name', None)
                        conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(
                            formatted_result, query, user_first_name=user_first_name
                        )
                        if conversational_response and conversational_response.strip():
                            return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
                    except Exception as e:
                        logger.warning(f"[EMAIL] Failed to generate conversational response: {e}, using formatted result")
                
                return formatted_result
            except Exception as e:
                logger.error(f"[EMAIL] Direct Gmail query execution failed: {e}, falling back to tool._run", exc_info=True)
                # Fallback to tool._run if direct execution fails
                result = tool._run(action="search", query=search_query, limit=search_limit)
                return result
        else:
            # Fallback: use tool._run if google_client not available
            result = tool._run(action="search", query=search_query, limit=search_limit)
            return result
    
    def handle_send_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle email sending action (including scheduling).
        
        Detects scheduling intent and routes to appropriate handler.
        
        Args:
            tool: Email tool instance
            query: User query
            
        Returns:
            Send/schedule confirmation
        """
        # Detect if query contains scheduling intent
        query_lower = query.lower()
        schedule_keywords = ['schedule', 'send later', 'send at', 'send tomorrow', 'send next', 'delay', 'remind me to send']
        
        is_scheduling = any(keyword in query_lower for keyword in schedule_keywords)
        
        if is_scheduling:
            logger.info(f"[EMAIL] Detected scheduling intent in query: '{query}'")
            return self.parser._parse_and_schedule_email(tool, query)
        else:
            return self.parser._parse_and_send_email(tool, query)
    
    def handle_reply_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle email reply action.
        
        Args:
            tool: Email tool instance
            query: User query (contains reply body)
            
        Returns:
            Reply confirmation
        """
        return tool._run(action="reply", body=query)
    
    def handle_search_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle email search action.
        
        Supports:
        - Sender-based search
        - Content-based search
        - "When was the last time" queries
        - Hybrid search (RAG + direct)
        
        Args:
            tool: Email tool instance
            query: User query
            
        Returns:
            Search results or conversational response
        """
        logger.info(f"[EMAIL] EmailParser._handle_search_action called with query: '{query}'")
        
        # CRITICAL: Validate query is not empty
        if not query or not query.strip():
            logger.warning(f"[EMAIL] handle_search_action called with empty query, defaulting to inbox search")
            query = "in:inbox"
        
        # Extract actual query from conversation context first
        actual_query = self.parser.query_processing_handlers.extract_actual_query(query)
        
        # CRITICAL: Validate extracted query is not empty
        if not actual_query or not actual_query.strip():
            if query and query.strip():
                actual_query = query.strip()
                logger.debug(f"[EMAIL] extract_actual_query returned empty in search, using original query")
            else:
                logger.warning(f"[EMAIL] Both extract_actual_query and original query are empty in search, defaulting to inbox")
                actual_query = "in:inbox"
        
        query_lower = actual_query.lower()
        
        # CRITICAL: If actual_query is already a Gmail query string (like 'in:inbox'), execute it directly
        # to avoid infinite recursion. Don't call tool._run() again.
        if actual_query and (actual_query.startswith("in:") or actual_query.startswith("from:") or 
                            actual_query.startswith("after:") or actual_query.startswith("before:") or
                            actual_query.startswith("is:") or actual_query.startswith("has:") or
                            actual_query.startswith("subject:") or actual_query.startswith("label:")):
            # This is already a Gmail query - execute directly using google_client
            logger.info(f"[EMAIL] Detected Gmail query string, executing directly: '{actual_query}'")
            if hasattr(self.parser, 'google_client') and self.parser.google_client:
                try:
                    limit = DEFAULT_LIST_LIMIT
                    # Use google_client.list_messages() to execute the query directly
                    emails = self.parser.google_client.list_messages(query=actual_query, max_results=limit)
                    if not emails:
                        return "I couldn't find any emails matching that query."
                    # Format results into a string that conversational handlers can process
                    formatted_result = self._format_email_list_to_string(emails, limit=limit)
                    # Generate conversational response if LLM available
                    if self.llm_client and formatted_result:
                        try:
                            conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(formatted_result, actual_query)
                            if conversational_response and conversational_response.strip():
                                return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
                        except Exception as e:
                            logger.warning(f"[EMAIL] Failed to generate conversational response: {e}")
                    return self.parser.conversational_handlers.final_cleanup_conversational_response(formatted_result) if formatted_result else ""
                except Exception as e:
                    logger.error(f"[EMAIL] Direct Gmail query execution failed: {e}", exc_info=True)
                    return f"Error executing search: {str(e)}"
            else:
                logger.warning(f"[EMAIL] google_client not available, cannot execute Gmail query directly")
                return f"Error: Gmail client not initialized. Cannot execute query: '{actual_query}'"
        
        # Intelligently detect temporal/"when" queries using LLM-based classification
        try:
            temporal_detection = self.parser.classification_handlers.detect_temporal_query(actual_query)
            asks_when = temporal_detection.get("asks_when", False)
            is_last_email_query = temporal_detection.get("is_last_email_query", False)
            confidence = temporal_detection.get("confidence", 0.0)
            
            # If query asks "when" or about "last email", route to handle_last_email_query
            if asks_when or is_last_email_query:
                logger.info(f"[EMAIL] Detected temporal/last email query (asks_when={asks_when}, is_last_email_query={is_last_email_query}, confidence={confidence})")
                sender = self.parser.utility_handlers.extract_sender_from_query(actual_query)
                if sender:
                    logger.info(f"[EMAIL] Routing temporal query with sender '{sender}' to handle_last_email_query")
                    return self.handle_last_email_query(tool, actual_query)
        except Exception as e:
            logger.debug(f"[EMAIL] Temporal query detection failed: {e}, continuing with normal flow")
        
        # Check if query contains a sender name
        sender = self.parser.utility_handlers.extract_sender_from_query(actual_query)
        if sender:
            logger.info(f"[EMAIL] Found sender '{sender}' in query, checking if this is a 'what about' query")
            
            # CRITICAL: Use intelligent LLM-based detection for "what about" queries
            # Use the parser's existing classification handler (no need to create new instance)
            try:
                what_about_detection = self.parser.classification_handlers.detect_what_about_query(actual_query)
                asks_what_about = what_about_detection.get("asks_what_about", False)
                asks_summary = what_about_detection.get("asks_summary", False)
                confidence = what_about_detection.get("confidence", 0.0)
                
                if asks_what_about or asks_summary:
                    logger.info(f"[EMAIL] Query asks 'what about' or 'summary' (confidence: {confidence}) - routing to handle_last_email_query for comprehensive summary")
                    return self.handle_last_email_query(tool, actual_query)
            except Exception as e:
                logger.debug(f"[EMAIL] 'What about' detection failed, continuing with search: {e}")
            
            logger.info(f"[EMAIL] Searching for emails from sender '{sender}'")
            
            # CRITICAL: Check if query mentions "today" and add date filter
            date_filter_parts = []
            if self.parser.date_parser:
                try:
                    # Parse date expression from query
                    # FlexibleDateParser.parse() returns Optional[Tuple[datetime, datetime]]
                    date_tuple = self.parser.date_parser.parse(actual_query)
                    if date_tuple and isinstance(date_tuple, tuple) and len(date_tuple) == 2:
                        start, end = date_tuple
                        # Format dates for Gmail (YYYY/MM/DD format in UTC)
                        start_utc = start.astimezone(timezone.utc) if start.tzinfo else timezone.utc.localize(start)
                        end_utc = end.astimezone(timezone.utc) if end.tzinfo else timezone.utc.localize(end)
                        after_date = start_utc.strftime("%Y/%m/%d")
                        before_date = end_utc.strftime("%Y/%m/%d")
                        date_filter_parts = [f"after:{after_date}", f"before:{before_date}"]
                        logger.info(f"[EMAIL] Added date filter for sender search: after:{after_date} before:{before_date}")
                except Exception as e:
                    logger.warning(f"[EMAIL] Failed to parse date from query: {e}")
                    # Fallback: check for "today" keyword
                    if "today" in query_lower:
                        now_utc = datetime.now(timezone.utc)
                        now_local = now_utc.astimezone()
                        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                        today_end_local = today_start_local + timedelta(days=1)
                        today_start_utc = today_start_local.astimezone(timezone.utc)
                        today_end_utc = today_end_local.astimezone(timezone.utc)
                        after_date = today_start_utc.strftime("%Y/%m/%d")
                        before_date = today_end_utc.strftime("%Y/%m/%d")
                        date_filter_parts = [f"after:{after_date}", f"before:{before_date}"]
                        logger.info(f"[EMAIL] Added 'today' date filter (fallback): after:{after_date} before:{before_date}")
            elif "today" in query_lower:
                # Fallback if date parser not available
                now_utc = datetime.now(timezone.utc)
                now_local = now_utc.astimezone()
                today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                today_end_local = today_start_local + timedelta(days=1)
                today_start_utc = today_start_local.astimezone(timezone.utc)
                today_end_utc = today_end_local.astimezone(timezone.utc)
                after_date = today_start_utc.strftime("%Y/%m/%d")
                before_date = today_end_utc.strftime("%Y/%m/%d")
                date_filter_parts = [f"after:{after_date}", f"before:{before_date}"]
                logger.info(f"[EMAIL] Added 'today' date filter (no date parser): after:{after_date} before:{before_date}")
            
            # Use LLM to intelligently detect if query is asking "what about" or requesting summary
            what_about_detection = self.parser.classification_handlers.detect_what_about_query(actual_query)
            asks_what_about = what_about_detection.get("is_what_about") and what_about_detection.get("confidence", 0) >= 0.7
            logger.info(f"[EMAIL] LLM detected 'what about': {asks_what_about} (confidence: {what_about_detection.get('confidence', 0.0)})")
            
            # Build search queries with date filters if applicable
            base_queries = [
                f"from:{sender}",
                f"from:*{sender}*",
                sender
            ]
            
            # Add date filters to each query if we have them
            if date_filter_parts:
                search_queries = [
                    f"{base_query} {' '.join(date_filter_parts)}" for base_query in base_queries
                ]
            else:
                search_queries = base_queries
            
            result = None
            for search_query in search_queries:
                logger.info(f"[EMAIL] Trying search query: '{search_query}'")
                # Limit to 1 result if asking "what about" (singular email question)
                limit = SINGLE_RESULT_LIMIT if asks_what_about else DEFAULT_LIST_LIMIT
                result = tool._run(action="search", query=search_query, limit=limit)
                
                if result and "No emails found" not in result:
                    logger.info(f"[EMAIL] Found emails with query: '{search_query}'")
                    break
            
            if not result or "No emails found" in result:
                # Validate sender before using in response
                if sender and self._is_valid_sender_name(sender):
                    return f"[EMAIL] I couldn't find any emails from {sender}."
                else:
                    # Invalid or missing sender - use generic message
                    logger.debug(f"[EMAIL] Invalid sender '{sender}' detected, using generic no-results message")
                    return f"[EMAIL] I couldn't find any emails matching your search."
            
            # If asking "what about", generate a summary instead of just listing
            if asks_what_about:
                logger.info(f"[EMAIL] Query asks 'what about' - generating summary for email from {sender}")
                # Parse the result to get email details
                email_details = self.parser.utility_handlers.parse_email_search_result(result)
                if email_details:
                    # Use the summarization handler to generate a summary
                    return self.parser.summarization_handlers.handle_email_summary_query(
                        tool, actual_query, sender, email_details, result
                    )
                else:
                    # Fallback: try to generate conversational response
                    logger.warning(f"[EMAIL] Could not parse email details from result, using conversational response")
            
            # Generate conversational response
            if self.llm_client:
                try:
                    user_first_name = getattr(self.parser, 'user_first_name', None)
                    conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(
                        result, actual_query, user_first_name=user_first_name
                    )
                    if conversational_response and conversational_response.strip():
                        return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
                except Exception as e:
                    logger.warning(f"[EMAIL] Failed to generate conversational response: {e}")
            
            return self.parser.conversational_handlers.final_cleanup_conversational_response(result) if result else ""
        
        # Regular search handling
        # Use composition_handlers.extract_search_query instead of non-existent _extract_search_query
        search_query = self.parser.composition_handlers.extract_search_query(actual_query, [])
        
        # CRITICAL: If search_query is already a Gmail query string, execute it directly to avoid recursion
        # BUT: If this is being called from handle_list_action (via tool._run), we should return raw results
        # and let handle_list_action generate the conversational response to avoid double processing
        if search_query and (search_query.startswith("in:") or search_query.startswith("from:") or 
                            search_query.startswith("after:") or search_query.startswith("before:") or
                            search_query.startswith("is:") or search_query.startswith("has:") or
                            search_query.startswith("subject:") or search_query.startswith("label:")):
            # Execute directly using google_client
            logger.info(f"[EMAIL] search_query is Gmail query string, executing directly: '{search_query}'")
            if hasattr(self.parser, 'google_client') and self.parser.google_client:
                try:
                    emails = self.parser.google_client.list_messages(query=search_query, max_results=DEFAULT_LIST_LIMIT)
                    if not emails:
                        return "I couldn't find any emails matching that query."
                    # Format results into a string that conversational handlers can process
                    formatted_result = self._format_email_list_to_string(emails, limit=DEFAULT_LIST_LIMIT)
                    
                    # Generate conversational response here (direct search action)
                    if self.llm_client and formatted_result:
                        try:
                            conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(formatted_result, actual_query)
                            if conversational_response and conversational_response.strip():
                                return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
                        except Exception as e:
                            logger.warning(f"[EMAIL] Failed to generate conversational response: {e}")
                    return self.parser.conversational_handlers.final_cleanup_conversational_response(formatted_result) if formatted_result else ""
                except Exception as e:
                    logger.error(f"[EMAIL] Direct Gmail query execution failed: {e}", exc_info=True)
                    return f"Error executing search: {str(e)}"
            else:
                logger.warning(f"[EMAIL] google_client not available, cannot execute Gmail query directly")
                return f"Error: Gmail client not initialized. Cannot execute query: '{search_query}'"
        
        # Check if we should use hybrid search (RAG + direct)
        if self._should_use_hybrid_search(actual_query):
            return self._hybrid_search(tool, actual_query, search_query, "inbox", DEFAULT_LIST_LIMIT)
        else:
            # Direct search only - but only if search_query is NOT a Gmail query string
            # (if it is, we already handled it above)
            if not (search_query and (search_query.startswith("in:") or search_query.startswith("from:") or 
                                     search_query.startswith("after:") or search_query.startswith("before:") or
                                     search_query.startswith("is:") or search_query.startswith("has:") or
                                     search_query.startswith("subject:") or search_query.startswith("label:"))):
                result = tool._run(action="search", query=search_query, limit=DEFAULT_LIST_LIMIT)
            else:
                # This shouldn't happen, but just in case
                result = ""
            
            # Generate conversational response
            if self.llm_client and result:
                try:
                    user_first_name = getattr(self.parser, 'user_first_name', None)
                    conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(
                        result, actual_query, user_first_name=user_first_name
                    )
                    if conversational_response and conversational_response.strip():
                        return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
                except Exception as e:
                    logger.warning(f"[EMAIL] Failed to generate conversational response: {e}")
            
            return self.parser.conversational_handlers.final_cleanup_conversational_response(result) if result else ""
    
    def _should_use_hybrid_search(self, query: str) -> bool:
        """
        Determine if hybrid search (RAG + direct) should be used.
        
        Args:
            query: User query
            
        Returns:
            True if hybrid search should be used
        """
        if not self.rag_service:
            return False
        
        query_lower = query.lower()
        
        # Use hybrid for semantic/content queries
        semantic_indicators = [
            "about", "regarding", "related to", "concerning",
            "discussing", "mentioned", "talked about"
        ]
        
        return any(indicator in query_lower for indicator in semantic_indicators)
    
    def _should_use_rag(self, query: str) -> bool:
        """
        Determine if RAG should be used for this query.
        
        Args:
            query: User query
            
        Returns:
            True if RAG should be used
        """
        # Same as hybrid search check
        return self._should_use_hybrid_search(query)
    
    def _hybrid_search(self, tool: BaseTool, query: str, search_query: str, folder: str, limit: int) -> str:
        """
        Execute hybrid search combining RAG semantic search with direct Gmail search.
        
        Args:
            tool: Email tool instance
            query: Original user query
            search_query: Processed search query
            folder: Email folder to search
            limit: Maximum results
            
        Returns:
            Combined search results
        """
        logger.info(f"[EMAIL] Executing hybrid search (RAG + direct) for query: '{query}'")
        
        # Get RAG results
        rag_results = []
        if self.rag_service:
            try:
                rag_results_raw = self.rag_service.search(query, top_k=limit)
                rag_results = self.parser._extract_emails_from_rag_result(str(rag_results_raw), tool, limit)
                logger.info(f"[EMAIL] RAG returned {len(rag_results)} results")
            except Exception as e:
                logger.warning(f"[EMAIL] RAG search failed: {e}")
        
        # Get direct search results
        direct_result = tool._run(action="search", query=search_query, limit=min(limit, EmailParserConfig.MAX_EMAIL_LIMIT))
        direct_results = self.parser._extract_emails_from_result_string(direct_result, tool)
        logger.info(f"[EMAIL] Direct search returned {len(direct_results)} results")
        
        # Merge results
        merged_results = self.parser._merge_search_results(direct_results, rag_results)
        logger.info(f"[EMAIL] Merged to {len(merged_results)} unique results")
        
        # Format results
        if not merged_results:
            return "[EMAIL] No emails found matching your query."
        
        # Generate conversational response
        formatted_result = "\n\n".join([
            f"From: {email.get('from', 'Unknown')}\nSubject: {email.get('subject', 'No Subject')}\nDate: {email.get('date', 'Unknown')}\n{email.get('snippet', '')}"
            for email in merged_results[:limit]
        ])
        
        if self.llm_client:
            try:
                user_first_name = getattr(self.parser, 'user_first_name', None)
                conversational_response = self.parser.conversational_handlers.generate_conversational_email_response(
                    formatted_result, query, user_first_name=user_first_name
                )
                if conversational_response and conversational_response.strip():
                    return self.parser.conversational_handlers.final_cleanup_conversational_response(conversational_response.strip())
            except Exception as e:
                logger.warning(f"[EMAIL] Failed to generate conversational response: {e}")
        
        return self.parser.conversational_handlers.final_cleanup_conversational_response(formatted_result)
    
    def handle_last_email_query(self, tool: BaseTool, query: str) -> str:
        """
        Handle "when was the last time" or "when did X respond" queries.
        Also handles "what is the email from X about" queries by generating summaries.
        
        Args:
            tool: Email tool instance
            query: User query
            
        Returns:
            Information about the last email from sender, or summary if asking "what about"
        """
        sender = self.parser.utility_handlers.extract_sender_from_query(query)
        
        if not sender:
            return "[EMAIL] I couldn't determine who you're asking about. Please specify a sender name."
        
        # Use LLM to intelligently detect if query is asking "what about" or requesting summary
        what_about_detection = self.parser.classification_handlers.detect_what_about_query(query)
        asks_what_about = what_about_detection.get("asks_what_about", False)
        asks_summary = what_about_detection.get("asks_summary", False)
        logger.info(f"[EMAIL] LLM detected 'what about': {asks_what_about}, 'summary': {asks_summary} (confidence: {what_about_detection.get('confidence', 0.0)})")
        
        # CRITICAL: For "what about" queries, fetch email directly to get full body content
        # Don't use tool._run() which returns formatted strings - use email_service directly
        if asks_what_about or asks_summary:
            logger.info(f"[EMAIL] Query asks 'what about' - fetching email directly for comprehensive summary from {sender}")
            
            # Use email_service to search and get actual email objects (not formatted strings)
            if hasattr(tool, 'email_service') and tool.email_service:
                try:
                    # Extract date filters from query using intelligent date parser
                    after_date = None
                    before_date = None
                    
                    # Use FlexibleDateParser if available to extract date filters
                    parsed_date_range = None
                    if hasattr(tool.email_service, 'date_parser') and tool.email_service.date_parser:
                        try:
                            # FlexibleDateParser.parse() returns Optional[Tuple[datetime, datetime]]
                            parsed_date_tuple = tool.email_service.date_parser.parse(query)
                            if parsed_date_tuple and isinstance(parsed_date_tuple, tuple) and len(parsed_date_tuple) == 2:
                                start, end = parsed_date_tuple
                                parsed_date_range = {'start': start, 'end': end}
                        except Exception as e:
                            logger.debug(f"[EMAIL] Date parser failed: {e}")
                    
                    if parsed_date_range and 'start' in parsed_date_range and 'end' in parsed_date_range:
                        import pytz
                        utc_tz = pytz.UTC
                        
                        start_dt = parsed_date_range['start']
                        end_dt = parsed_date_range['end']
                        
                        # Ensure timezone-aware
                        if start_dt.tzinfo is None:
                            from ....core.calendar.utils import get_user_timezone
                            tz_name = get_user_timezone(tool.email_service.config) if tool.email_service.config else 'UTC'
                            user_tz = pytz.timezone(tz_name)
                            start_dt = user_tz.localize(start_dt)
                        
                        if end_dt.tzinfo is None:
                            from ....core.calendar.utils import get_user_timezone
                            tz_name = get_user_timezone(tool.email_service.config) if tool.email_service.config else 'UTC'
                            user_tz = pytz.timezone(tz_name)
                            end_dt = user_tz.localize(end_dt)
                        
                        # Convert to UTC and format as Gmail API date format
                        start_utc = start_dt.astimezone(utc_tz)
                        end_utc = end_dt.astimezone(utc_tz)
                        
                        after_date = start_utc.strftime("%Y/%m/%d")
                        before_date = end_utc.strftime("%Y/%m/%d")
                        
                        logger.info(f"[EMAIL] Extracted date range from query: after={after_date}, before={before_date}")
                    
                    # Search using email_service to get email objects with full body
                    # Use from_email parameter instead of query for better filtering
                    emails = tool.email_service.search_emails(
                        from_email=sender,
                        after_date=after_date,
                        before_date=before_date,
                        limit=1
                    )
                    
                    if emails and len(emails) > 0:
                        email = emails[0]
                        message_id = email.get('id')
                        body_content = email.get('body', '') or email.get('snippet', '')
                        subject = email.get('subject', '')
                        
                        # If we don't have full body, fetch it
                        if not body_content or len(body_content) < 200:
                            if message_id:
                                full_email = tool.email_service.get_email(message_id)
                                if full_email:
                                    body_content = full_email.get('body', '') or full_email.get('snippet', '')
                        
                        # Generate comprehensive summary using full body
                        if body_content and len(body_content.strip()) > 0:
                            logger.info(f"[EMAIL] Generating comprehensive summary (body length: {len(body_content)})")
                            
                            # Use summarization handler with full email data
                            email_details = {
                                'id': message_id,
                                'subject': subject,
                                'body': body_content,  # Full body content
                                'full_content': body_content,
                                'sender': sender,
                                'from': email.get('from', email.get('sender', sender)),
                                'date': email.get('date', ''),
                                'thread_id': email.get('threadId', '')
                            }
                            
                            return self.parser.summarization_handlers.handle_email_summary_query(
                                tool, query, sender, email_details, ""
                            )
                except Exception as e:
                    logger.warning(f"[EMAIL] Failed to fetch email directly: {e}", exc_info=True)
                    # Fall through to search-based approach
        
        # Fallback: Search for emails from this sender (for non-content queries)
        search_queries = [f"from:{sender}", f"from:*{sender}*", sender]
        
        result = None
        for search_query in search_queries:
            result = tool._run(action="search", query=search_query, limit=SINGLE_RESULT_LIMIT)
            if result and "No emails found" not in result:
                break
        
        if not result or "No emails found" in result:
            # Validate sender before using in response
            if sender and self._is_valid_sender_name(sender):
                return f"[EMAIL] I couldn't find any emails from {sender}."
            else:
                # Invalid or missing sender - use generic message
                logger.debug(f"[EMAIL] Invalid sender '{sender}' detected, using generic no-results message")
                return f"[EMAIL] I couldn't find any emails matching your search."
        
        # If asking "what about", generate a summary (fallback path)
        if asks_what_about:
            logger.info(f"[EMAIL] Query asks 'what about' - generating summary for email from {sender} (fallback path)")
            # Parse the result to get email details
            email_details = self.parser.utility_handlers.parse_email_search_result(result)
            if email_details:
                # Use the summarization handler to generate a summary
                return self.parser.summarization_handlers.handle_email_summary_query(
                    tool, query, sender, email_details, result
                )
            else:
                # Fallback: try to extract info from result string
                logger.warning(f"[EMAIL] Could not parse email details from result, using fallback")
                return result
        
        # Otherwise, just return date information
        email_details = self.parser.utility_handlers.parse_email_search_result(result)
        if email_details and email_details.get('date'):
            date_str = email_details['date']
            # Validate sender before using in response
            if sender and self._is_valid_sender_name(sender):
                return f"[EMAIL] The last email you received from {sender} was on {date_str}"
            else:
                return f"[EMAIL] The last email matching your search was on {date_str}"
        
        # Validate sender before using in response
        if sender and self._is_valid_sender_name(sender):
            return f"[EMAIL] I couldn't find any emails from {sender}."
        else:
            # Invalid or missing sender - use generic message
            logger.debug(f"[EMAIL] Invalid sender '{sender}' detected, using generic no-results message")
            return f"[EMAIL] I couldn't find any emails matching your search."
