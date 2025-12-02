"""
Email Query Processing Handlers - Handle query execution, confirmation, and clarification
"""
from typing import Dict, Any, Optional
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from .constants import EmailParserConfig

logger = setup_logger(__name__)


class EmailQueryProcessingHandlers:
    """Handles query processing, confirmation, and clarification for email operations"""
    
    def __init__(self, email_parser):
        self.email_parser = email_parser
    
    def extract_actual_query(self, query: str) -> str:
        """
        Extract the actual user query from conversation context
        
        Args:
            query: Full query with conversation context
            
        Returns:
            Just the actual user query
        """
        # CRITICAL: Handle empty or None queries
        if not query or not isinstance(query, str):
            return ""
        
        query = query.strip()
        if not query:
            return ""
        
        # Look for "Current query:" pattern
        if "Current query:" in query:
            parts = query.split("Current query:")
            if len(parts) > 1:
                actual_query = parts[1].split("[Context:")[0].strip()
                # Only return if we actually extracted something
                if actual_query:
                    return actual_query
        
        # Look for "User:" pattern (for conversation context)
        if "User:" in query:
            # Find the last "User:" occurrence
            user_parts = query.split("User:")
            if len(user_parts) > 1:
                # Get the last user message
                last_user_part = user_parts[-1]
                # Extract just the user message content
                if "Assistant:" in last_user_part:
                    actual_query = last_user_part.split("Assistant:")[0].strip()
                else:
                    actual_query = last_user_part.strip()
                # Only return if we actually extracted something
                if actual_query:
                    return actual_query
        
        # If no conversation context, return as-is (already validated as non-empty)
        return query
    
    def ask_for_clarification(self, query: str, classification: Dict[str, Any]) -> str:
        """Ask user for clarification when confidence is low"""
        missing_info = []
        entities = classification.get('entities', {})
        
        intent = classification.get('intent', 'unknown')
        
        if intent == 'send' and not entities.get('recipients'):
            missing_info.append("Who should I send this to? (Please provide an email address)")
        
        if intent == 'search':
            if not entities.get('senders') and not entities.get('keywords'):
                missing_info.append("What should I search for? (sender, topic, keyword)")
            if not entities.get('date_range'):
                missing_info.append("When are you looking for? (today, last week, etc.)")
        
        if missing_info:
            msg = "🤔 I'm not entirely sure what you need. Could you clarify:\n\n"
            for info in missing_info:
                msg += f"• {info}\n"
            msg += f"\nYour query: \"{query}\""
            return msg
        
        return f"I'm not sure how to handle your request. Could you try rephrasing?\n\nYour query: \"{query}\""
    
    def execute_with_classification(self, tool: BaseTool, query: str, classification: Dict[str, Any],
                                     user_id: Optional[int], session_id: Optional[str]) -> str:
        """Execute query using LLM classification with advanced features"""
        intent = classification.get('intent', 'list')
        entities = classification.get('entities', {})
        limit = classification.get('limit', EmailParserConfig.DEFAULT_EMAIL_LIMIT)
        
        # CRITICAL: Handle summarize intent for email summaries
        if intent == 'summarize':
            logger.info(f"[EMAIL] Executing summarize action via classification")
            return self.email_parser.summarization_handlers.handle_summarize_action(tool, query)
        
        # PHASE 2: Context-aware search
        if intent in ['search', 'list']:
            query_lower = query.lower()
            
            # CRITICAL: For priority queries, route to _handle_search_action to leverage hybrid search (direct + RAG)
            # This ensures priority queries get the full power of RAG semantic search
            is_priority_query = any(term in query_lower for term in ["priority", "urgent", "immediate attention", "important"])
            if is_priority_query:
                logger.info(f"[EMAIL] Priority query detected in classification - routing to _handle_search_action for hybrid search (direct + RAG)")
                return self.email_parser.action_handlers.handle_search_action(tool, query)
            
            # Use LLM to intelligently detect if query asks "what is the email about" - this needs summary generation
            what_about_detection = self.email_parser.classification_handlers.detect_what_about_query(query)
            asks_what_about = what_about_detection.get("asks_what_about", False)
            asks_summary = what_about_detection.get("asks_summary", False)
            logger.info(f"[EMAIL] LLM detected 'what about': {asks_what_about}, 'summary': {asks_summary} (confidence: {what_about_detection.get('confidence', 0.0)})")
            
            # Check if this is a "what was the email about" query that needs special handling
            # IMPORTANT: Route to _handle_last_email_query if:
            # 1. Query asks "what about" AND has a sender, OR
            # 2. Query asks "what about" AND has temporal context ("when was the last time", etc.)
            if asks_what_about or asks_summary:
                sender = entities.get('senders', [None])[0] if entities.get('senders') else None
                if not sender:
                    # Try to extract sender from query
                    sender = self.email_parser.utility_handlers.extract_sender_from_query(query)
                
                # Check for temporal context using LLM classification if available
                has_temporal_context = False
                if self.email_parser.classifier:
                    try:
                        import inspect
                        import asyncio
                        classify_method = self.email_parser.classifier.classify_query
                        if inspect.iscoroutinefunction(classify_method):
                            try:
                                loop = asyncio.get_running_loop()
                            except RuntimeError:
                                classification = asyncio.run(classify_method(query))
                                if classification and isinstance(classification, dict):
                                    entities_from_classification = classification.get('entities', {})
                                    date_range = entities_from_classification.get('date_range') if isinstance(entities_from_classification, dict) else None
                                    has_temporal_context = date_range is not None or "when" in query_lower or "last" in query_lower
                        else:
                            classification = classify_method(query)
                            if classification and isinstance(classification, dict):
                                entities_from_classification = classification.get('entities', {})
                                date_range = entities_from_classification.get('date_range') if isinstance(entities_from_classification, dict) else None
                                has_temporal_context = date_range is not None or "when" in query_lower or "last" in query_lower
                    except Exception:
                        has_temporal_context = "when was the last time" in query_lower or "last email from" in query_lower
                else:
                    has_temporal_context = "when was the last time" in query_lower or "last email from" in query_lower
                
                # If we have a sender and query asks "what about", route to summary handler
                if sender:
                    logger.info(f"[EMAIL] Query asks 'what about' with sender '{sender}' - routing to summary handler")
                    return self.email_parser.action_handlers.handle_last_email_query(tool, query)
                # Also route if query has temporal context
                elif has_temporal_context:
                    logger.info(f"[EMAIL] Query asks 'what about' with temporal context - routing to summary handler")
                    return self.email_parser.action_handlers.handle_last_email_query(tool, query)
            
            # Detect if query asks for singular "email" vs plural "emails"
            # CRITICAL: Also detect "the last email", "last email", "most recent email" - these should return only 1 result
            is_singular = (
                " email " in query_lower or 
                " email?" in query_lower or 
                query_lower.endswith(" email") or
                query_lower.endswith(" email?") or
                "the last email" in query_lower or
                "last email" in query_lower or
                "most recent email" in query_lower or
                "latest email" in query_lower
            ) and "emails" not in query_lower
            
            # Adjust limit based on singular/plural
            adjusted_limit = 1 if is_singular else limit
            if is_singular:
                logger.info(f"[EMAIL] Detected singular 'email' query (or 'last email') - limiting results to 1")
            
            search_query = self.email_parser.search_handlers.build_advanced_search_query(classification, user_id, session_id, query)
            search_result = tool._run(action="search", query=search_query, limit=adjusted_limit)
            
            # CRITICAL: If query asks "what is the email about" and we got results, generate summary
            if asks_what_about and search_result and ("found" in search_result.lower() or "matching" in search_result.lower()):
                # Extract sender(s) for summary
                senders = entities.get('senders', [])
                if not senders:
                    extracted_sender = self.email_parser.utility_handlers.extract_sender_from_query(query)
                    if extracted_sender:
                        senders = [extracted_sender]
                
                if senders:
                    # Parse the search result to get email details
                    email_details = self.email_parser.utility_handlers.parse_email_search_result(search_result)
                    if email_details:
                        # Fetch full email content and generate summary
                        sender_name = senders[0] if senders else "the sender"
                        return self.email_parser.summarization_handlers.handle_email_summary_query(tool, query, sender_name, email_details, search_result)
            
            return search_result
        
        # PHASE 3: LLM email generation for send
        elif intent == 'send':
            recipients = entities.get('recipients', [])
            if not recipients:
                return "[ERROR] I couldn't find a recipient. Please specify an email address."
            
            # Use LLM to generate email
            email_content = self.email_parser.llm_generation_handlers.generate_email_with_llm(query, recipients[0], entities)
            
            subject = entities.get('subjects', [None])[0] if entities.get('subjects') else None
            return tool._run(
                action="send",
                to=recipients[0],
                subject=subject or "Quick Update",
                body=email_content
            )
        
        elif intent == 'reply':
            return tool._run(action="reply", body=query)
        else:
            return tool._run(action="list", limit=limit)
    
    def extract_entities(self, query: str) -> Dict[str, Any]:
        """
        Extract email-specific entities from query
        
        Args:
            query: User query
            
        Returns:
            Dictionary of extracted entities
        """
        # Get base entities from parent parser
        entities = {}
        if hasattr(self.email_parser, 'extract_entities'):
            try:
                entities = self.email_parser.extract_entities(query)
            except AttributeError:
                # If parent doesn't have extract_entities, start fresh
                entities = {}
        
        # Add email-specific entities
        entities.update({
            'recipient': self.email_parser.composition_handlers.extract_email_recipient(query),
            'subject': self.email_parser.composition_handlers.extract_email_subject(query),
            'action': self.email_parser.classification_handlers.detect_email_action(query),
            'has_email_address': bool(self.email_parser.composition_handlers.extract_email_recipient(query))
        })
        
        return entities
