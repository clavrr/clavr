"""
Email Query Handlers

Handles email query operations: list, unread, search, semantic_search, organize, categorize, insights, cleanup, bulk operations.
This module centralizes query handling logic to keep the main EmailTool class clean.
"""
from typing import Optional, List, Dict, Any

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class EmailQueryHandlers:
    """
    Handles email query operations.
    
    This class centralizes query handling to improve maintainability
    and keep the main EmailTool class focused on orchestration.
    """
    
    def __init__(self, email_tool):
        """
        Initialize query handlers.
        
        Args:
            email_tool: Parent EmailTool instance for accessing services, config, etc.
        """
        self.email_tool = email_tool
        self.email_service = email_tool.email_service if hasattr(email_tool, 'email_service') else None
        self.formatting_handlers = email_tool.formatting_handlers if hasattr(email_tool, 'formatting_handlers') else None
    
    def handle_list(
        self,
        limit: int,
        folder: str,
        query: Optional[str],
        **kwargs
    ) -> str:
        """Handle list emails action"""
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for listing emails
        if workflow_emitter:
            self.email_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr checking your emails...",
                data={'action': 'list', 'folder': folder}
            )
        
        emails = self.email_service.list_recent_emails(limit=limit, folder=folder)
        return self.formatting_handlers.format_email_list(emails, f"Recent emails in {folder}", query or "")
    
    def handle_unread(
        self,
        limit: int,
        query: Optional[str],
        **kwargs
    ) -> str:
        """Handle list unread emails action"""
        emails = self.email_service.list_unread_emails(limit=limit)
        return self.formatting_handlers.format_email_list(emails, "Unread emails", query or "")
    
    def handle_search(
        self,
        query: Optional[str],
        folder: str,
        limit: int,
        **kwargs
    ) -> str:
        """Handle search emails action"""
        if not query:
            return "[ERROR] Please provide 'query' for search action"

        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')

        # Emit workflow event for searching emails
        if workflow_emitter:
            self.email_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr searching emails...",
                data={'action': 'search', 'query': query}
            )

        # CRITICAL: Try to get sender from EmailParser first (if available)
        # The EmailParser already extracted it during action detection
        sender_name = None
        subject_text = None
        
        # Try to get sender from parser's extracted entities if available
        if hasattr(self.email_tool, 'parser') and self.email_tool.parser:
            try:
                # Re-parse to get entities (sender extraction)
                parsed = self.email_tool.parser.parse_query_to_params(
                    query=query,
                    user_id=getattr(self.email_tool, '_user_id', None),
                    session_id=None
                )
                entities = parsed.get('entities', {})
                # Check if sender was extracted by parser
                if 'sender' in entities:
                    parser_sender = entities['sender']
                    # CRITICAL: Validate parser-extracted sender - if it's too short or looks wrong, ignore it
                    # e.g., if parser extracted "'The'" instead of "'The Core'", we should re-extract
                    # Strip quotes first to check the actual content
                    sender_content = parser_sender.strip().strip("'\"")
                    if parser_sender and len(sender_content) > 2 and sender_content.lower() not in ['the', 'a', 'an']:
                        sender_name = parser_sender
                        logger.info(f"[EMAIL] Using parser-extracted sender: '{sender_name}'")
                    else:
                        logger.debug(f"[EMAIL] Parser-extracted sender '{parser_sender}' looks invalid (content: '{sender_content}', too short or common word), will re-extract")
                # Check if subject was extracted by parser
                if 'subject' in entities:
                    subject_text = entities['subject']
                    logger.info(f"[EMAIL] Using parser-extracted subject: '{subject_text}'")
            except Exception as e:
                logger.debug(f"[EMAIL] Could not get sender from parser: {e}")

        # CRITICAL: For content queries asking about a specific sender's email,
        # extract sender name AND subject (if mentioned) and search for emails matching both
        # Example: "What is the email from 'The Core' with the subject 'X' all about?" → search for "from:The Core" AND "subject:X"
        query_lower = query.lower()
        is_content_query = any(phrase in query_lower for phrase in [
            'what is', 'what was', 'what does', 'what did', 'tell me about', 
            'tell me more about', 'all about', 'say', 'about'
        ])
        
        # Extract sender name if not already extracted by parser (or if parser extraction was invalid) and query mentions "from X" or "X's email" or "email from X"
        if not sender_name and is_content_query:
            # Pattern 1: "What is the Core's email all about?" → "Core" or "The Core"
            if "'s email" in query_lower or "s email" in query_lower:
                # Extract text before "'s email" or "s email"
                match_idx = query_lower.find("'s email")
                if match_idx == -1:
                    match_idx = query_lower.find("s email")
                if match_idx > 0:
                    # Get words before the match (preserve original case)
                    before_match = query[:match_idx].strip()
                    # Extract the last meaningful word/phrase (likely the sender name)
                    # CRITICAL: Include "The" if it's part of the sender name (e.g., "The Core")
                    words = before_match.split()
                    # Skip common words at the end, but keep "The" if it's followed by a capitalized word
                    skip_words = ['a', 'an', 'what', 'is', 'was', 'does', 'did', 'tell', 'me', 'about', 'all']
                    sender_parts = []
                    for i, word in enumerate(reversed(words)):
                        word_lower = word.lower()
                        # Keep "The" if it's followed by a capitalized word (likely part of sender name)
                        if word_lower == 'the' and i > 0 and words[-(i+1)][0].isupper():
                            sender_parts.insert(0, word)
                        elif word_lower not in skip_words:
                            sender_parts.insert(0, word)
                        elif sender_parts:  # If we already found sender parts, stop
                            break
                    if sender_parts:
                        sender_name = " ".join(sender_parts)
                        logger.info(f"[EMAIL] Extracted sender from possessive pattern: '{sender_name}'")
            
            # Pattern 2: "What was the email from The Core all about?" → "The Core"
            # Pattern 3: "What is the email from 'The Core' with the subject 'X' all about?" → "The Core" + "X"
            if "from" in query_lower and not sender_name:
                from_idx = query_lower.find("from")
                # Use original query (preserve case) for extraction
                after_from = query[from_idx + 4:].strip()
                after_from_lower = after_from.lower()
                
                # CRITICAL: First check for quoted sender name (e.g., "'The Core'" or '"The Core"')
                import re
                quoted_match = re.search(r'["\']([^"\']+)["\']', after_from)
                if quoted_match:
                    quoted_sender = quoted_match.group(1).strip()
                    # Check if there's a "with" or "subject" pattern after the quote
                    quote_end = quoted_match.end()
                    after_quote = after_from[quote_end:].strip().lower()
                    if "with" in after_quote and ("subject" in after_quote or "titled" in after_quote):
                        # Subject is coming - extract it
                        sender_name = quoted_sender
                        logger.info(f"[EMAIL] Extracted quoted sender (with subject): '{sender_name}'")
                        
                        # Extract subject
                        subject_patterns = ["with the subject", "with subject", "subject", "titled", "titled as"]
                        subject_idx = None
                        for pattern in subject_patterns:
                            if pattern in after_quote:
                                subject_idx = after_quote.find(pattern)
                                break
                        
                        if subject_idx is not None:
                            after_subject_pattern = after_from[quote_end + subject_idx:].strip()
                            # Try to extract quoted subject
                            quoted_subject_match = re.search(r'["\']([^"\']+)["\']', after_subject_pattern)
                            if quoted_subject_match:
                                subject_text = quoted_subject_match.group(1)
                                logger.info(f"[EMAIL] Extracted quoted subject: '{subject_text}'")
                            else:
                                # Extract subject words until stop words
                                subject_stop_words = ['all', 'about', 'yesterday', 'today', 'what', 'was', 'is', 'did', 'say']
                                subject_parts = []
                                for word in after_subject_pattern.split():
                                    if word.lower() in subject_stop_words:
                                        break
                                    subject_parts.append(word)
                                if subject_parts:
                                    subject_text = " ".join(subject_parts)
                                    logger.info(f"[EMAIL] Extracted subject: '{subject_text}'")
                    else:
                        # No subject - just use the quoted sender
                        sender_name = quoted_sender
                        logger.info(f"[EMAIL] Extracted quoted sender: '{sender_name}'")
                
                # If no quoted sender found, check for subject patterns
                elif any(pattern in after_from_lower for pattern in ["with the subject", "with subject", "subject", "titled"]):
                    subject_patterns = ["with the subject", "with subject", "subject", "titled", "titled as"]
                    subject_idx = None
                    for pattern in subject_patterns:
                        if pattern in after_from_lower:
                            subject_idx = after_from_lower.find(pattern)
                            break
                    
                    if subject_idx is not None:
                        # Extract sender name (stop at subject pattern, preserve case)
                        sender_text = after_from[:subject_idx].strip()
                        stop_words = ['yesterday', 'today', 'about', 'all', 'the', 'email', 'emails', 'message', 'messages', 'what', 'was', 'is', 'did', 'say', 'received', 'with']
                        sender_parts = []
                        for word in sender_text.split():
                            if word.lower() in stop_words:
                                break
                            sender_parts.append(word)
                        if sender_parts:
                            sender_name = " ".join(sender_parts).strip("'\"")
                            logger.info(f"[EMAIL] Extracted sender from 'from' pattern (with subject): '{sender_name}'")
                        
                        # Extract subject (after subject pattern)
                        after_subject_pattern = after_from[subject_idx:].strip()
                        # Try to extract quoted subject first
                        quoted_subject_match = re.search(r'["\']([^"\']+)["\']', after_subject_pattern)
                        if quoted_subject_match:
                            subject_text = quoted_subject_match.group(1)
                            logger.info(f"[EMAIL] Extracted quoted subject: '{subject_text}'")
                        else:
                            # Extract subject words until stop words
                            subject_stop_words = ['all', 'about', 'yesterday', 'today', 'what', 'was', 'is', 'did', 'say']
                            subject_parts = []
                            for word in after_subject_pattern.split():
                                if word.lower() in subject_stop_words:
                                    break
                                subject_parts.append(word)
                            if subject_parts:
                                subject_text = " ".join(subject_parts)
                                logger.info(f"[EMAIL] Extracted subject: '{subject_text}'")
                else:
                    # No subject mentioned - just extract sender
                    # CRITICAL: Check for "all about" phrase first, then stop at individual stop words
                    if "all about" in after_from_lower:
                        # Stop at "all about" phrase (preserve case)
                        all_about_idx = after_from_lower.find("all about")
                        sender_text = after_from[:all_about_idx].strip()
                    else:
                        sender_text = after_from
                    
                    # Remove quotes if present
                    sender_text = sender_text.strip("'\"")
                    
                    stop_words = ['yesterday', 'today', 'about', 'all', 'the', 'email', 'emails', 'message', 'messages', 'what', 'was', 'is', 'did', 'say', 'received']
                    sender_parts = []
                    for word in sender_text.split():
                        if word.lower() in stop_words:
                            break
                        sender_parts.append(word)
                    if sender_parts:
                        sender_name = " ".join(sender_parts).strip("'\"")
                        logger.info(f"[EMAIL] Extracted sender from 'from' pattern: '{sender_name}'")
        
        # CRITICAL: If both sender and subject are extracted, search with BOTH filters
        # This ensures we get the exact email, not all emails from the sender
        if sender_name and subject_text:
            # Use structured search with both sender and subject filters
            logger.info(f"[EMAIL] Content query with sender '{sender_name}' AND subject '{subject_text}', using structured search")
            emails = self.email_service.search_emails(
                query=None,  # Don't use raw query, use structured filters
                folder=folder,
                limit=limit,
                from_email=sender_name,
                subject=subject_text
            )
        elif sender_name:
            # Only sender extracted - search by sender
            sender_search_query = f'from:"{sender_name}"'
            logger.info(f"[EMAIL] Content query detected with sender '{sender_name}', using search query: '{sender_search_query}'")
            emails = self.email_service.search_emails(query=sender_search_query, folder=folder, limit=limit)
        else:
            # Use original query for search
            emails = self.email_service.search_emails(query=query, folder=folder, limit=limit)
        
        return self.formatting_handlers.format_email_list(emails, f"Search results for '{query}'", query)
    
    def handle_semantic_search(
        self,
        query: Optional[str],
        limit: int,
        **kwargs
    ) -> str:
        """Handle semantic search emails action"""
        if not query:
            return "[ERROR] Please provide 'query' for semantic_search action"
        results = self.email_service.semantic_search(query=query, limit=limit)
        return self.formatting_handlers.format_email_list(results, f"Semantic search results for '{query}'", query)
    
    def handle_organize(
        self,
        category: Optional[str],
        folder: str,
        limit: int,
        dry_run: bool,
        **kwargs
    ) -> str:
        """Handle organize emails action"""
        return self.email_tool._organize_emails_wrapper(category, folder, limit, dry_run)
    
    def handle_categorize(
        self,
        query: Optional[str],
        folder: str,
        limit: int,
        dry_run: bool,
        **kwargs
    ) -> str:
        """Handle categorize emails action"""
        return self.email_tool._categorize_emails_wrapper(query, folder, limit, dry_run)
    
    def handle_insights(
        self,
        folder: str,
        limit: int,
        **kwargs
    ) -> str:
        """Handle email insights action"""
        return self.email_tool._email_insights_wrapper(folder, limit)
    
    def handle_cleanup(
        self,
        limit: int,
        dry_run: bool,
        **kwargs
    ) -> str:
        """Handle cleanup inbox action"""
        return self.email_tool._cleanup_inbox_wrapper(limit, dry_run)
    
    def handle_bulk_delete(
        self,
        criteria: Optional[str],
        **kwargs
    ) -> str:
        """Handle bulk delete emails action"""
        if not criteria:
            return "[ERROR] Please provide 'criteria' for bulk_delete action"
        # Note: Bulk operations with criteria are handled by the tool's advanced logic
        # Could be moved to service layer in future iterations
        return f"[INFO] Bulk delete with criteria '{criteria}' - feature in development"
    
    def handle_bulk_archive(
        self,
        criteria: Optional[str],
        **kwargs
    ) -> str:
        """Handle bulk archive emails action"""
        if not criteria:
            return "[ERROR] Please provide 'criteria' for bulk_archive action"
        return f"[INFO] Bulk archive with criteria '{criteria}' - feature in development"


