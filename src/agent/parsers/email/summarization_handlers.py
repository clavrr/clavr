"""
Email Summarization Handlers

Handles all email summarization operations:
- Email summary generation with LLM
- Content summarization
- Bulk email summarization
- Summary formatting and personalization

This module provides intelligent summarization capabilities for emails
and other content, with support for different formats and lengths.
"""
import re
from typing import Dict, Any, Optional
from langchain.tools import BaseTool
from langchain_core.messages import HumanMessage

from ....utils.logger import setup_logger
from ...utils import has_email_keywords
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for summarization handlers
DEFAULT_SUMMARY_LIMIT = EmailParserConfig.DEFAULT_EMAIL_LIMIT
EXPLICIT_LIMIT_10 = 10
CONTENT_PREVIEW_LENGTH = 100
MIN_BODY_CONTENT_LENGTH = 200


class EmailSummarizationHandlers:
    """
    Handles all email summarization operations.
    
    This includes:
    - Email content summarization
    - Bulk email summarization
    - Summary formatting (bullet points, paragraphs, etc.)
    - LLM-based intelligent summarization
    """
    
    def __init__(self, email_parser):
        """
        Initialize summarization handlers.
        
        Args:
            email_parser: Parent EmailParser instance for accessing llm_client, config, etc.
        """
        self.email_parser = email_parser
        self.llm_client = email_parser.llm_client
        self.config = email_parser.config
        self.utility_handlers = email_parser.utility_handlers
        self.llm_generation_handlers = email_parser.llm_generation_handlers
    
    def handle_summarize_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle summarization action with LLM support
        
        Args:
            tool: Email/Summarize tool
            query: User query
            
        Returns:
            Summarization result
        """
        if not self.email_parser.validate_tool(tool):
            return "[ERROR] Invalid tool provided"
        
        try:
            # CRITICAL: Validate query is not empty
            if not query or not query.strip():
                logger.warning(f"[EMAIL] handle_summarize_action called with empty query, defaulting to inbox")
                query = "in:inbox"
            
            # Extract actual query from conversation context if present
            # Use query_processing_handlers directly (utility_handlers doesn't have this method)
            actual_query = self.email_parser.query_processing_handlers.extract_actual_query(query)
            
            # CRITICAL: Validate extracted query is not empty
            if not actual_query or not actual_query.strip():
                if query and query.strip():
                    actual_query = query.strip()
                    logger.debug(f"[EMAIL] extract_actual_query returned empty in summarize, using original query")
                else:
                    logger.warning(f"[EMAIL] Both extract_actual_query and original query are empty in summarize, defaulting to inbox")
                    actual_query = "in:inbox"
            
            logger.info(f"[EMAIL] EmailParser._handle_summarize_action called with query: '{actual_query}'")
            
            query_lower = actual_query.lower()
            
            # CRITICAL: Detect if query is asking to summarize EMAILS (not text content)
            # Use centralized email keywords + temporal indicators
            temporal_keywords = ["today", "yesterday", "this week", "this month", "past", "last", "recent", "new"]
            has_temporal_keywords = any(keyword in query_lower for keyword in temporal_keywords)
            query_has_email_keywords = has_email_keywords(query) or has_temporal_keywords
            
            # Check for summary patterns that indicate email summarization
            email_summary_patterns = [
                "summary of", "summarize", "summaries", "key points", 
                "brief summary", "overview of", "what are", "what is"
            ]
            has_summary_pattern = any(pattern in query_lower for pattern in email_summary_patterns)
            
            # CRITICAL FIX: If query mentions emails, it's ALWAYS an email summary request
            # (since we're in _handle_summarize_action, the "summary" part is implied by the action)
            # Only require summary patterns if NO email keywords are present (to avoid false positives)
            is_email_summary_request = query_has_email_keywords  # Changed: removed requirement for summary_pattern
            
            logger.info(f"[EMAIL] Email summary request detected: {is_email_summary_request} (has_email_keywords: {query_has_email_keywords}, has_summary_pattern: {has_summary_pattern})")
            
            if is_email_summary_request:
                # This is an email summary request - fetch emails first, then summarize
                logger.info("[EMAIL] Detected email summary request - fetching emails first")
                
                # CRITICAL: Check if tool supports email search (EmailTool) vs text summarization (SummarizeTool)
                # SummarizeTool doesn't have search action, so we need EmailTool
                tool_type_str = str(type(tool)).lower()
                is_email_tool = (
                    'email' in tool_type_str or 
                    hasattr(tool, 'google_client') or 
                    hasattr(tool, '_search_google_emails') or
                    hasattr(tool, '_run_google_gmail')
                )
                
                if not is_email_tool:
                    logger.error(f"[EMAIL] Tool {type(tool)} is not EmailTool - cannot fetch emails! Tool type: {tool_type_str}")
                    return "I see you're asking for an email summary, but I received a text summarization tool instead of an email tool. This means the system routed your request incorrectly. Please try asking directly: 'summary of my unread emails from the past 3 days' and I'll fetch and summarize your actual emails."
                
                try:
                    # Determine limit (default to reasonable number for summaries)
                    limit = DEFAULT_SUMMARY_LIMIT  # Get more emails for better summary
                    if "10 emails" in query_lower or "ten emails" in query_lower:
                        limit = EXPLICIT_LIMIT_10
                    elif "5 emails" in query_lower or "five emails" in query_lower:
                        limit = 5
                    
                    # CRITICAL: Use RAG/hybrid search when appropriate for better email discovery
                    # Check if query should use RAG or hybrid search
                    use_hybrid = self.email_parser._should_use_hybrid_search(query)
                    use_rag = self.email_parser._should_use_rag(query) if not use_hybrid else False
                    
                    logger.info(f"[EMAIL] Email summary - use_hybrid: {use_hybrid}, use_rag: {use_rag}")
                    
                    emails_result = None
                    
                    if use_hybrid:
                        # Use hybrid search (combines direct + RAG) for better results
                        logger.info(f"[EMAIL] Using HYBRID search for email summary: '{query}'")
                        try:
                            # Build structured query parts for direct search
                            search_query_parts = []
                            
                            # Check for unread filter
                            if "unread" in query_lower:
                                search_query_parts.append("is:unread")
                            
                            # Check for inbox filter
                            if "inbox" in query_lower or "received" in query_lower:
                                search_query_parts.append("in:inbox")
                            else:
                                search_query_parts.append("in:inbox")
                            
                            # Check for date filters
                            from datetime import datetime, timedelta, timezone
                            now_utc = datetime.now(timezone.utc)
                            now_local = now_utc.astimezone()
                            
                            if "past 3 days" in query_lower or "last 3 days" in query_lower:
                                three_days_ago = now_local - timedelta(days=3)
                                after_date = three_days_ago.astimezone(timezone.utc).strftime("%Y/%m/%d")
                                search_query_parts.append(f"after:{after_date}")
                            elif "past 7 days" in query_lower or "last week" in query_lower or "this week" in query_lower:
                                seven_days_ago = now_local - timedelta(days=7)
                                after_date = seven_days_ago.astimezone(timezone.utc).strftime("%Y/%m/%d")
                                search_query_parts.append(f"after:{after_date}")
                            elif "today" in query_lower:
                                today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                                after_date = today_start.astimezone(timezone.utc).strftime("%Y/%m/%d")
                                search_query_parts.append(f"after:{after_date}")
                            elif "yesterday" in query_lower:
                                yesterday_start = (now_local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                                after_date = yesterday_start.astimezone(timezone.utc).strftime("%Y/%m/%d")
                                before_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime("%Y/%m/%d")
                                search_query_parts.append(f"after:{after_date}")
                                search_query_parts.append(f"before:{before_date}")
                            
                            # Check for sender filter
                            sender = self.utility_handlers.extract_sender_from_query(actual_query)
                            if sender:
                                if ' ' in sender:
                                    search_query_parts.append(f'from:"{sender}"')
                                else:
                                    search_query_parts.append(f"from:{sender}")
                            
                            search_query = " ".join(search_query_parts) if search_query_parts else "in:inbox"
                            
                            emails_result = self.email_parser._hybrid_search(tool, actual_query, search_query, "inbox", limit)
                            logger.info(f"[EMAIL] Hybrid search returned {len(emails_result) if emails_result else 0} chars")
                        except Exception as e:
                            logger.warning(f"[EMAIL] Hybrid search failed for summary: {e}, falling back to direct search")
                            use_hybrid = False
                    
                    if use_rag and not emails_result:
                        # Use RAG semantic search for topic-based queries
                        logger.info(f"[EMAIL] Using RAG semantic search for email summary: '{actual_query}'")
                        try:
                            emails_result = tool._run(action="semantic_search", query=actual_query, folder="inbox", limit=limit)
                            logger.info(f"[EMAIL] RAG search returned {len(emails_result) if emails_result else 0} chars")
                            
                            # If RAG returns no results, fallback to direct search
                            if emails_result and ("No semantically similar" in emails_result or "No emails found" in emails_result):
                                logger.info(f"[EMAIL] RAG search returned no results, falling back to direct search")
                                emails_result = None
                        except Exception as e:
                            logger.warning(f"[EMAIL] RAG search failed for summary: {e}, falling back to direct search")
                            emails_result = None
                    
                    if not emails_result:
                        # Fallback to direct Gmail search
                        logger.info(f"[EMAIL] Using direct Gmail search for email summary")
                        
                        # Build search query from the user's request
                        search_query_parts = []
                        
                        # Check for unread filter
                        if "unread" in query_lower:
                            search_query_parts.append("is:unread")
                        
                        # Check for inbox filter
                        if "inbox" in query_lower or "received" in query_lower:
                            search_query_parts.append("in:inbox")
                        else:
                            # Default to inbox if not specified
                            search_query_parts.append("in:inbox")
                        
                        # Check for date filters
                        from datetime import datetime, timedelta, timezone
                        now_utc = datetime.now(timezone.utc)
                        now_local = now_utc.astimezone()
                        
                        if "past 3 days" in query_lower or "last 3 days" in query_lower:
                            three_days_ago = now_local - timedelta(days=3)
                            after_date = three_days_ago.astimezone(timezone.utc).strftime("%Y/%m/%d")
                            search_query_parts.append(f"after:{after_date}")
                        elif "past 7 days" in query_lower or "last week" in query_lower or "this week" in query_lower:
                            seven_days_ago = now_local - timedelta(days=7)
                            after_date = seven_days_ago.astimezone(timezone.utc).strftime("%Y/%m/%d")
                            search_query_parts.append(f"after:{after_date}")
                        elif "today" in query_lower:
                            today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                            after_date = today_start.astimezone(timezone.utc).strftime("%Y/%m/%d")
                            search_query_parts.append(f"after:{after_date}")
                        elif "yesterday" in query_lower:
                            yesterday_start = (now_local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                            after_date = yesterday_start.astimezone(timezone.utc).strftime("%Y/%m/%d")
                            before_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime("%Y/%m/%d")
                            search_query_parts.append(f"after:{after_date}")
                            search_query_parts.append(f"before:{before_date}")
                        
                        # Check for sender filter
                        sender = self.utility_handlers.extract_sender_from_query(actual_query)
                        if sender:
                            if ' ' in sender:
                                search_query_parts.append(f'from:"{sender}"')
                            else:
                                search_query_parts.append(f"from:{sender}")
                        
                        # Build final search query
                        search_query = " ".join(search_query_parts) if search_query_parts else "in:inbox"
                        
                        logger.info(f"[EMAIL] Fetching emails with direct search query: '{search_query}', limit: {limit}")
                        
                        # Fetch emails using EmailTool
                        emails_result = tool._run(
                            action="search",
                            query=search_query,
                            limit=limit,
                            folder="inbox"
                        )
                    
                    logger.info(f"[EMAIL] Email fetch result length: {len(emails_result) if emails_result else 0} chars")
                    
                    # Check if we got emails
                    if emails_result and ("[OK]" in emails_result or "found" in emails_result.lower() or "matching" in emails_result.lower()):
                        # Check if no emails found - return empty, let LLM generate response
                        if "no emails found" in emails_result.lower() or "no emails matching" in emails_result.lower() or "don't see any" in emails_result.lower() or not emails_result.strip():
                            # Return empty - final safeguard will generate LLM response
                            return ""
                        
                        # Use LLM to generate a conversational summary of the emails
                        if self.llm_client:
                            try:
                                # Generate conversational email summary
                                summary = self.llm_generation_handlers.generate_email_summary_with_llm_for_multiple_emails(emails_result, actual_query)
                                if summary:
                                    logger.info(f"[EMAIL] Generated conversational email summary ({len(summary)} chars)")
                                    return summary
                                else:
                                    logger.warning("[EMAIL] Summary generation returned None, falling back to formatted result")
                            except Exception as e:
                                logger.error(f"[EMAIL] Failed to generate email summary: {e}", exc_info=True)
                                # Fallback: use the regular summary method
                                try:
                                    format_type = self._detect_summarize_format(actual_query)
                                    length = self._detect_summarize_length(actual_query)
                                    focus = self._extract_summarize_focus(actual_query)
                                    summary = self.llm_generation_handlers.generate_summary_with_llm(format_type, length, focus)
                                    if summary:
                                        return summary
                                except Exception as e2:
                                    logger.error(f"[EMAIL] Fallback summary also failed: {e2}")
                        
                        # If LLM not available or failed, return formatted result
                        return emails_result
                    else:
                        # No emails found - return empty, let final safeguard generate LLM response
                        return ""
                        
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"[EMAIL] Failed to fetch emails for summarization: {e}", exc_info=True)
                    # Check if error is because tool doesn't support search action
                    if "search" in error_msg.lower() or "action" in error_msg.lower() or "not supported" in error_msg.lower():
                        return "I see you're asking for an email summary, but the tool I received doesn't support email search. Please ask me directly about your emails (e.g., 'summary of my unread emails from the past 3 days') so I can use the correct email tool to fetch and summarize your actual emails."
                    return f"I encountered an error while fetching your emails: {error_msg}. Could you try rephrasing your request?"
            
            # Not an email summary request - treat as text content summarization
            # BUT: Only do this if we're CERTAIN it's not an email request (double-check)
            query_lower_final = actual_query.lower()
            final_email_check = any(keyword in query_lower_final for keyword in ["email", "emails", "message", "messages", "inbox", "unread", "received"])
            if final_email_check:
                logger.warning(f"[EMAIL] Query has email keywords but was not detected as email summary request - this might be a bug!")
                return "I see your query mentions emails, but I'm not able to fetch them with the current tool. Please ask me directly about your emails (e.g., 'summary of my unread emails') so I can use the email tool to fetch and summarize them."
            
            # Extract content to summarize
            content = self._extract_summarize_content(actual_query)
            logger.info(f"[EMAIL] Extracted content for text summarization: '{content[:CONTENT_PREVIEW_LENGTH]}...'")
            
            # Determine format
            format_type = self._detect_summarize_format(actual_query)
            logger.info(f"[EMAIL] Detected format: {format_type}")
            
            # Determine length
            length = self._detect_summarize_length(actual_query)
            logger.info(f"[EMAIL] Detected length: {length}")
            
            # Determine focus
            focus = self._extract_summarize_focus(actual_query)
            logger.info(f"[EMAIL] Extracted focus: {focus}")
            
            # Use LLM for intelligent summarization if available
            if self.llm_client:
                try:
                    summary = self.llm_generation_handlers.generate_summary_with_llm(content, format_type, length, focus)
                    logger.info(f"[EMAIL] Generated LLM summary ({len(summary)} chars)")
                    return summary
                except Exception as e:
                    logger.warning(f"LLM summarization failed: {e}")
                    return f"[ERROR] LLM summarization failed: {str(e)}"
            
            # If no LLM and no email fetching needed, return error
            return "[ERROR] Summarization requires LLM support or email content. Please provide content to summarize or ensure LLM is configured."
            
        except Exception as e:
            logger.error(f"Summarize action failed: {e}", exc_info=True)
            return f"[ERROR] Error parsing summarize query: {str(e)}"
    
    def _detect_summarize_format(self, query: str) -> str:
        """Detect summary format from query - delegates to llm_generation_handlers"""
        return self.llm_generation_handlers.detect_summarize_format(query)
    
    def _detect_summarize_length(self, query: str) -> str:
        """Detect summary length from query - delegates to llm_generation_handlers"""
        return self.llm_generation_handlers.detect_summarize_length(query)
    
    def _extract_summarize_focus(self, query: str) -> Optional[str]:
        """Extract summary focus from query - delegates to llm_generation_handlers"""
        return self.llm_generation_handlers.extract_summarize_focus(query)
    
    def _extract_summarize_content(self, query: str) -> str:
        """Extract content to summarize from query"""
        # Try to extract content after "summarize", "summary of", etc.
        patterns = [
            r'summarize\s+(?:the\s+)?(.+)',
            r'summary\s+of\s+(.+)',
            r'give\s+me\s+a\s+summary\s+of\s+(.+)',
            r'create\s+a\s+summary\s+of\s+(.+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # If no pattern matched, return the full query
        return query
    
    def handle_email_summary_query(self, tool: BaseTool, query: str, sender: str, 
                                   email_details: Dict[str, str], search_result: str) -> str:
        """
        Handle queries that ask "what is the email about" after a search
        
        Args:
            tool: Email tool
            query: Original user query
            sender: Sender name
            email_details: Parsed email details from search result
            search_result: Original search result string
            
        Returns:
            Summary response
        """
        logger.info(f"[EMAIL] Generating summary for email from {sender}")
        
        # Extract message ID from email_details or search_result
        message_id = email_details.get('id') or self.email_parser._extract_email_id_from_result(search_result)
        
        # CRITICAL: Check for full body content from index first (most efficient)
        body_content = (
            email_details.get('body') or  # Full body from index
            email_details.get('full_content') or  # Legacy field name
            email_details.get('preview', '')  # Fallback to preview
        )
        subject = email_details.get('subject', '')
        thread_id = email_details.get('thread_id')
        
        # If we don't have full content from index, fetch it from Gmail API
        if not body_content or len(body_content) < MIN_BODY_CONTENT_LENGTH:
            # Try multiple ways to access the Gmail client
            gmail_client = None
            if hasattr(tool, 'email_service') and tool.email_service:
                # EmailTool uses email_service which has gmail_client
                gmail_client = getattr(tool.email_service, 'gmail_client', None)
            elif hasattr(tool, 'google_client') and tool.google_client:
                # Direct google_client access (legacy)
                gmail_client = tool.google_client
            
            if gmail_client and message_id:
                try:
                    logger.info(f"[EMAIL] Fetching full email content for message_id: {message_id}")
                    full_email = gmail_client.get_message(message_id)
                    if full_email:
                        body_content = full_email.get('body', '') or full_email.get('snippet', '')
                        thread_id = full_email.get('thread_id') or thread_id
                        if body_content:
                            logger.info(f"[EMAIL] Retrieved full email content ({len(body_content)} chars)")
                except Exception as e:
                    logger.warning(f"[EMAIL] Could not fetch full email content: {e}", exc_info=True)
        
        if not body_content:
            body_content = email_details.get('preview', '') or email_details.get('snippet', '')
        
        # Fetch thread context if available
        thread_context = None
        # Try multiple ways to access the Gmail client
        gmail_client = None
        if hasattr(tool, 'email_service') and tool.email_service:
            gmail_client = getattr(tool.email_service, 'gmail_client', None)
        elif hasattr(tool, 'google_client') and tool.google_client:
            gmail_client = tool.google_client
        
        if thread_id and gmail_client:
            try:
                logger.info(f"[EMAIL] Fetching thread context for thread_id: {thread_id}, filtering for sender: {sender}")
                thread_messages = gmail_client.get_thread_messages(thread_id)
                if thread_messages and len(thread_messages) > 1:
                    # Filter messages to only include those from the requested sender
                    import re
                    sender_normalized = sender.lower()
                    sender_name_match = re.search(r'^([^<]+)', sender, re.IGNORECASE)
                    if sender_name_match:
                        sender_name_normalized = sender_name_match.group(1).strip().lower()
                    else:
                        sender_name_normalized = sender_normalized
                    
                    filtered_messages = []
                    for msg in thread_messages:
                        msg_sender = msg.get('sender', 'Unknown')
                        msg_sender_lower = msg_sender.lower()
                        is_from_sender = (
                            sender_normalized in msg_sender_lower or
                            sender_name_normalized in msg_sender_lower or
                            any(part.lower() == sender_name_normalized for part in re.split(r'[<>\s@,]+', msg_sender_lower) if part)
                        )
                        if is_from_sender:
                            filtered_messages.append(msg)
                    
                    if filtered_messages:
                        thread_parts = []
                        for msg in filtered_messages:
                            msg_sender = msg.get('sender', 'Unknown')
                            msg_date = msg.get('date', '')
                            msg_subject = msg.get('subject', '')
                            msg_body = msg.get('body', '') or msg.get('snippet', '')
                            clean_msg_body = re.sub(r'\s+', ' ', msg_body).strip()
                            thread_parts.append(
                                f"From: {msg_sender}\n"
                                f"Date: {msg_date}\n"
                                f"Subject: {msg_subject}\n"
                                f"Content: {clean_msg_body}"
                            )
                        if thread_parts:
                            thread_context = "\n\n---\n\n".join(thread_parts)
                            logger.info(f"[EMAIL] Built thread context with {len(filtered_messages)} messages from {sender}")
            except Exception as e:
                logger.warning(f"[EMAIL] Could not fetch thread context: {e}", exc_info=True)
        
        # Clean body content
        if body_content:
            import re
            body_content = re.sub(r'<[^>]+>', '', body_content)
            body_content = re.sub(r'\s+', ' ', body_content).strip()
            body_content = re.sub(r'^.*?On.*?wrote:.*?\n', '', body_content, flags=re.DOTALL | re.IGNORECASE)
            body_content = re.sub(r'^.*?From:.*?\n', '', body_content, flags=re.MULTILINE | re.IGNORECASE)
            body_content = body_content.strip()
        
        # Generate summary using LLM
        if self.llm_client and body_content:
            try:
                summary = self.llm_generation_handlers.generate_email_summary_with_llm(
                    sender=sender,
                    subject=subject,
                    body=body_content,
                    thread_context=thread_context
                )
                if summary:
                    return f"[EMAIL] {summary}"
            except Exception as e:
                logger.warning(f"[EMAIL] LLM summary generation failed: {e}")
        
        # Fallback: return basic info
        response_parts = []
        if subject:
            response_parts.append(f"Email from {sender} about \"{subject}\"")
        else:
            response_parts.append(f"Email from {sender}")
        
        if body_content:
            preview = body_content[:500] + "..." if len(body_content) > 500 else body_content
            response_parts.append(f"The email content: {preview}")
        
        return "[EMAIL] " + ". ".join(response_parts) if response_parts else search_result
