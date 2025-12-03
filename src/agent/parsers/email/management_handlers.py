"""
Email Management Handlers - Handle email management operations like mark read/unread, archive, etc.
"""
import re
from typing import Optional

try:
    from langchain_core.tools import BaseTool
except ImportError:
    from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from ...utils import has_email_keywords
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for management handlers
DEFAULT_UNREAD_LIMIT = 5
EXPLICIT_LIMIT_10 = 10
EXPLICIT_LIMIT_5 = 5
EXPLICIT_LIMIT_3 = 3


class EmailManagementHandlers:
    """Handles email management operations and tool routing"""
    
    def __init__(self, email_parser):
        self.email_parser = email_parser
        self.llm_client = email_parser.llm_client
    
    def handle_mark_read_action(self, tool: BaseTool, query: str) -> str:
        """Handle mark as read action"""
        return tool._run(action="mark_read", message_id="recent")
    
    def handle_mark_unread_action(self, tool: BaseTool, query: str) -> str:
        """Handle mark as unread action"""
        return tool._run(action="mark_unread", message_id="recent")
    
    def handle_unread_action(self, tool: BaseTool, query: str) -> str:
        """Handle unread emails listing action"""
        logger.info(f"[EMAIL] EmailParser.handle_unread_action called with query: '{query}'")
        
        # Only use limit=10 if user explicitly requests 10 emails
        query_lower = query.lower()
        explicit_limit = None
        if any(phrase in query_lower for phrase in ["10 emails", "ten emails", "10 new emails", "ten new emails"]):
            explicit_limit = EXPLICIT_LIMIT_10
        elif any(phrase in query_lower for phrase in ["5 emails", "five emails"]):
            explicit_limit = EXPLICIT_LIMIT_5
        elif any(phrase in query_lower for phrase in ["3 emails", "three emails"]):
            explicit_limit = EXPLICIT_LIMIT_3
        
        # Default to DEFAULT_UNREAD_LIMIT if no explicit limit
        limit = explicit_limit if explicit_limit else DEFAULT_UNREAD_LIMIT
        result = tool._run(action="unread", limit=limit)
        
        # Generate conversational response
        if self.llm_client:
            try:
                conversational_response = self.email_parser.conversational_handlers.generate_conversational_email_response(result, query)
                if conversational_response:
                    return conversational_response
            except Exception as e:
                logger.warning(f"[EMAIL] Failed to generate conversational response: {e}, using formatted result")
        
        return result
    
    def handle_archive_action(self, tool: BaseTool, query: str) -> str:
        """Handle email archiving action"""
        try:
            logger.info(f"[EMAIL] EmailParser.handle_archive_action called with query: '{query}'")
            
            # Extract search criteria from query
            search_query = self.email_parser.composition_handlers.extract_search_query(query, ["archive", "move to archive"])
            
            # Get message ID from query if specified
            message_id = self.extract_message_id(query)
            
            # Archive the email(s)
            return tool._run(action="archive", message_id=message_id, search_query=search_query)
            
        except Exception as e:
            logger.error(f"Archive action failed: {e}", exc_info=True)
            return f"[ERROR] Error archiving email: {str(e)}"
    
    def extract_message_id(self, query: str) -> Optional[str]:
        """Extract message ID from query if specified"""
        patterns = [
            r'id[:\s]+([a-zA-Z0-9_-]+)',
            r'message[:\s]+([a-zA-Z0-9_-]+)',
            r'email[:\s]+([a-zA-Z0-9_-]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
    
    def handle_email_management_tool(self, query: str, tool: BaseTool, user_id: Optional[int], session_id: Optional[str]) -> str:
        """Handle EmailManagementTool operations"""
        logger.info(f"[EMAIL] Handling EmailManagementTool query: '{query}'")
        
        query_lower = query.lower()
        
        # Detect action based on query
        if "semantic" in query_lower or "search" in query_lower:
            search_query = self.email_parser.composition_handlers.extract_search_query(query, ["search", "semantic search", "find"])
            return tool._run(action="search", query=search_query, folder="all", limit=EmailParserConfig.DEFAULT_EMAIL_LIMIT)
        elif "organize" in query_lower:
            return tool._run(action="organize", category=None, folder="all", limit=EmailParserConfig.DEFAULT_EMAIL_LIMIT, dry_run=True)
        elif "bulk delete" in query_lower or "delete all" in query_lower:
            criteria = self.extract_criteria_for_bulk_operation(query)
            return tool._run(action="bulk_delete", criteria=criteria, folder="all", limit=EmailParserConfig.MAX_EMAIL_LIMIT, dry_run=True)
        elif "bulk archive" in query_lower:
            criteria = self.extract_criteria_for_bulk_operation(query)
            return tool._run(action="bulk_archive", criteria=criteria, folder="all", limit=EmailParserConfig.MAX_EMAIL_LIMIT, dry_run=True)
        elif "categorize" in query_lower:
            return tool._run(action="categorize", query=query, folder="all", limit=EmailParserConfig.DEFAULT_EMAIL_LIMIT, dry_run=True)
        elif "insights" in query_lower or "analytics" in query_lower:
            return tool._run(action="insights", folder="all", limit=EmailParserConfig.MAX_EMAIL_LIMIT)
        elif "cleanup" in query_lower or "clean up" in query_lower:
            return tool._run(action="cleanup", limit=EmailParserConfig.MAX_EMAIL_LIMIT, dry_run=True)
        else:
            return tool._run(action="list", folder="all", limit=EmailParserConfig.DEFAULT_EMAIL_LIMIT)
    
    def handle_summarize_tool(self, query: str, tool: BaseTool, user_id: Optional[int], session_id: Optional[str]) -> str:
        """Handle SummarizeTool operations"""
        logger.info(f"[EMAIL] Handling SummarizeTool query: '{query}'")
        
        query_lower = query.lower()
        
        # Check if this is actually an email summary request
        temporal_keywords = ["today", "yesterday", "this week", "this month", "past", "last", "recent", "new"]
        has_temporal_keywords = any(keyword in query_lower for keyword in temporal_keywords)
        query_has_email_keywords = has_email_keywords(query) or has_temporal_keywords
        
        email_summary_patterns = [
            "summary of", "summarize", "summaries", "key points", 
            "brief summary", "overview of", "what are", "what is"
        ]
        has_summary_pattern = any(pattern in query_lower for pattern in email_summary_patterns)
        
        is_email_summary_request = query_has_email_keywords and has_summary_pattern
        
        if is_email_summary_request:
            return "I see you're asking for an email summary. Please ask me directly about your emails (e.g., 'summary of my unread emails') rather than using the summarize tool. I'll fetch and summarize your actual emails."
        
        # This is a text summarization request - proceed normally
        content = self.email_parser.summarization_handlers.extract_summarize_content(query)
        format_type = self.email_parser.summarization_handlers.detect_summarize_format(query)
        length = self.email_parser.summarization_handlers.detect_summarize_length(query)
        return tool._run(content=content, format=format_type, length=length)
    
    def extract_criteria_for_bulk_operation(self, query: str) -> str:
        """Extract criteria for bulk operations"""
        query_lower = query.lower()
        if "old" in query_lower:
            return "old"
        elif "unread" in query_lower:
            return "unread"
        elif "spam" in query_lower or "promo" in query_lower:
            return "spam"
        elif "large" in query_lower:
            return "large"
        else:
            return "old"
