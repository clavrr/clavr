"""
Email Parser - Refactored with modular handlers

This parser understands natural language email queries and converts them into
structured email operations. It provides:

- Intent classification (send, search, list, reply, etc.)
- Entity extraction (recipient, sender, subject, keywords)
- Advanced search with RAG and hybrid capabilities
- Conversational response generation
- Email analytics and insights

The parser uses LLM-powered classification when available, falling back to
pattern-based parsing for reliability.
"""
import re
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from langchain.tools import BaseTool

from .base_parser import BaseParser
from ...utils.logger import setup_logger
from ..intent import EMAIL_PATTERNS, EMAIL_MANAGEMENT_PATTERNS
from ..utils import EMAIL_KEYWORDS, has_email_keywords
from .email.constants import EmailActionTypes, EmailParserConfig
from .email.sender_extractor import SenderExtractor

logger = setup_logger(__name__)


class EmailParser(BaseParser):
    """
    Email Parser with modular handlers
    
    This parser delegates functionality to specialized handler modules:
    - action_handlers: Email actions (search, send, reply, etc.)
    - classification_handlers: Query classification and intent detection  
    - composition_handlers: Email composition and scheduling
    - conversational_handlers: Natural language response generation
    - feedback_handlers: Learning from user feedback
    - llm_generation_handlers: LLM-powered email generation
    - management_handlers: Email management operations
    - multi_step_handlers: Multi-step query processing
    - query_processing_handlers: Query parsing and execution
    - search_handlers: Advanced search with RAG and hybrid capabilities
    - summarization_handlers: Email summarization
    - utility_handlers: Common utility functions
    """
    
    def __init__(self, rag_service=None, memory=None, config=None, user_first_name: Optional[str] = None, workflow_emitter: Optional[Any] = None):
        super().__init__(rag_service, memory, config)
        self.name = "email"
        self.config = config
        self.user_first_name = user_first_name  # Store user's first name for personalization
        self.workflow_emitter = workflow_emitter  # Store workflow emitter for event emission
    
        # Initialize feedback storage (required by feedback_handlers)
        self.feedback_store = []
        # Set feedback file path from constants if config available
        if config:
            from .email.constants import EmailParserConfig
            self.feedback_file = EmailParserConfig.FEEDBACK_FILE_PATH
        else:
            self.feedback_file = "./data/email_parser_feedback.json"  # Default fallback
        
        # Initialize core components
        self.classifier = None
        self.date_parser = None
        self.llm_client = None
        self.sender_extractor = SenderExtractor(self)
        
        # Initialize NLP utilities if config available
        if config:
            try:
                from ...ai.query_classifier import QueryClassifier
                self.classifier = QueryClassifier(config)
                logger.info("QueryClassifier initialized")
            except Exception as e:
                logger.warning(f"QueryClassifier not available: {e}")
            
            try:
                from ...utils import FlexibleDateParser
                self.date_parser = FlexibleDateParser(config)
                logger.info("FlexibleDateParser initialized")
            except Exception as e:
                logger.warning(f"FlexibleDateParser not available: {e}")
            
            try:
                from ...ai.llm_factory import LLMFactory
                self.llm_client = LLMFactory.get_llm_for_provider(
                    config,
                    temperature=EmailParserConfig.LLM_TEMPERATURE,
                    max_tokens=EmailParserConfig.LLM_MAX_TOKENS
                )
                logger.info(f"LLM client initialized (temp={EmailParserConfig.LLM_TEMPERATURE}, max_tokens={EmailParserConfig.LLM_MAX_TOKENS})")
            except Exception as e:
                logger.warning(f"LLM client not available: {e}")
        
        # Initialize semantic matcher and learning system
        try:
            from .email.semantic_matcher import EmailSemanticPatternMatcher
            self.semantic_matcher = EmailSemanticPatternMatcher(config)
        except Exception as e:
            logger.warning(f"EmailSemanticPatternMatcher not available: {e}")
            self.semantic_matcher = None
            
        try:
            from .email.learning_system import EmailLearningSystem
            self.learning_system = EmailLearningSystem(self)
        except Exception as e:
            logger.warning(f"EmailLearningSystem not available: {e}")
            self.learning_system = None
        
        # Initialize all handler modules
        self._initialize_handlers()
        
        # Load feedback and learned patterns
        try:
            self.feedback_handlers.load_feedback()
            self.feedback_handlers.load_learned_patterns()
        except Exception as e:
            logger.warning(f"Could not load feedback/patterns: {e}")
    
    def _initialize_handlers(self):
        """Initialize all modular handlers in the correct dependency order"""
        try:
            # Initialize base handlers first (no dependencies)
            from .email.utility_handlers import EmailUtilityHandlers
            self.utility_handlers = EmailUtilityHandlers(self)
            
            from .email.query_processing_handlers import EmailQueryProcessingHandlers
            self.query_processing_handlers = EmailQueryProcessingHandlers(self)
            
            from .email.feedback_handlers import EmailFeedbackHandlers
            self.feedback_handlers = EmailFeedbackHandlers(self)
            
            # Initialize handlers that depend on utility handlers
            from .email.classification_handlers import EmailClassificationHandlers
            self.classification_handlers = EmailClassificationHandlers(self)
            
            from .email.search_handlers import EmailSearchHandlers
            self.search_handlers = EmailSearchHandlers(self)
            
            from .email.composition_handlers import EmailCompositionHandlers
            self.composition_handlers = EmailCompositionHandlers(self)
            
            from .email.llm_generation_handlers import EmailLLMGenerationHandlers
            self.llm_generation_handlers = EmailLLMGenerationHandlers(self)
            
            from .email.conversational_handlers import EmailConversationalHandlers
            self.conversational_handlers = EmailConversationalHandlers(self)
            
            from .email.management_handlers import EmailManagementHandlers
            self.management_handlers = EmailManagementHandlers(self)
            
            # Initialize handlers that depend on other handlers
            from .email.summarization_handlers import EmailSummarizationHandlers
            self.summarization_handlers = EmailSummarizationHandlers(self)
            
            from .email.action_handlers import EmailActionHandlers
            self.action_handlers = EmailActionHandlers(self)
            
            from .email.multi_step_handlers import EmailMultiStepHandlers
            self.multi_step_handlers = EmailMultiStepHandlers(self)
            
            logger.info("All email handler modules initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize email handlers: {e}")
            raise
    
    def parse_query_to_params(self, query: str, user_id: Optional[int] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Parse email query into structured parameters WITHOUT executing the tool
        
        This enables proper tool integration where the tool calls the parser
        and uses the structured result.
        
        Args:
            query: User query
            user_id: Optional user ID for context
            session_id: Optional session ID for context
            
        Returns:
            Dictionary with:
                - action: str (e.g., 'send', 'search', 'list', 'reply')
                - entities: Dict[str, Any] (e.g., recipient, subject, sender, search_term)
                - confidence: float (0.0-1.0)
                - metadata: Dict[str, Any] (suggestions, detected patterns, etc.)
        """
        try:
            logger.info(f"[EMAIL] EmailParser.parse_query_to_params called with query: '{query}'")
            
            # Extract actual query from conversation context
            actual_query = self.query_processing_handlers.extract_actual_query(query)
            
            # CRITICAL: Explicitly reject task/calendar queries - they don't belong to email domain
            query_lower = actual_query.lower()
            task_keywords = ['task', 'tasks', 'todo', 'todos', 'reminder', 'deadline']
            calendar_keywords = ['meeting', 'meetings', 'event', 'events', 'appointment', 'calendar', 'schedule']
            email_keywords = ['email', 'emails', 'message', 'messages', 'inbox', 'mail']
            
            # If query is explicitly about tasks (not emails), reject it
            has_task_keywords = any(keyword in query_lower for keyword in task_keywords)
            has_calendar_keywords = any(keyword in query_lower for keyword in calendar_keywords)
            has_email_keywords = any(keyword in query_lower for keyword in email_keywords)
            
            logger.debug(f"[EMAIL] Domain detection - task: {has_task_keywords}, calendar: {has_calendar_keywords}, email: {has_email_keywords}, query: '{actual_query}'")
            
            # If query mentions tasks/calendar but NOT emails, reject
            if (has_task_keywords or has_calendar_keywords) and not has_email_keywords:
                logger.info(f"[EMAIL] Rejecting query - explicitly about tasks/calendar, not emails: '{actual_query}' (task={has_task_keywords}, calendar={has_calendar_keywords}, email={has_email_keywords})")
                return {
                    "action": "reject",
                    "entities": {},
                    "confidence": 0.0,
                    "metadata": {"reason": "Query is about tasks/calendar, not emails"}
                }
            
            # Detect email action
            action = self.classification_handlers.detect_email_action(actual_query)
            
            # Ensure action is a string (safety check)
            if not isinstance(action, str):
                logger.warning(f"[EMAIL] Action is not a string: {type(action)}, converting to string")
                action = str(action) if action else "list"
            
            logger.info(f"[EMAIL] Detected action: {action}")
            
            # Extract entities based on action
            entities = self._extract_entities_for_action(actual_query, action)
            
            # Calculate confidence based on pattern matches and entity extraction
            confidence = self._calculate_confidence(actual_query, action, entities)
            
            # Generate metadata (suggestions, warnings, etc.)
            metadata = self._generate_metadata(actual_query, action, entities)
            
            return {
                "action": action,
                "entities": entities,
                "confidence": confidence,
                "metadata": metadata
            }
            
        except Exception as e:
            logger.error(f"[EMAIL] Error in parse_query_to_params: {e}")
            return {
                "action": "error",
                "entities": {},
                "confidence": 0.0,
                "metadata": {"error": str(e)}
            }
    
    def _extract_entities_for_action(self, query: str, action: str) -> Dict[str, Any]:
        """Extract entities relevant to the detected action using LLM classifier"""
        entities = {}
        
        # CRITICAL: Use LLM classifier to extract entities (including date_range)
        # This ensures we use the rich LLM-powered parser instead of hardcoded patterns
        llm_entities = {}
        if self.classifier:
            try:
                import inspect
                import asyncio
                classify_method = self.classifier.classify_query
                if inspect.iscoroutinefunction(classify_method):
                    try:
                        loop = asyncio.get_running_loop()
                        # Can't run async in sync context - will use fallback
                    except RuntimeError:
                        classification = asyncio.run(classify_method(query))
                        if classification and isinstance(classification, dict):
                            llm_entities = classification.get('entities', {})
                            if isinstance(llm_entities, dict):
                                # Extract date_range from LLM classification
                                if 'date_range' in llm_entities:
                                    entities['date_range'] = llm_entities['date_range']
                                # Extract other entities
                                if 'senders' in llm_entities:
                                    entities['senders'] = llm_entities['senders']
                                if 'sender' in llm_entities:
                                    entities['sender'] = llm_entities['sender']
                                if 'search_term' in llm_entities:
                                    entities['search_term'] = llm_entities['search_term']
                                if 'keywords' in llm_entities:
                                    entities['keywords'] = llm_entities['keywords']
                                if 'folder' in llm_entities:
                                    entities['folder'] = llm_entities['folder']
                else:
                    classification = classify_method(query)
                    if classification and isinstance(classification, dict):
                        llm_entities = classification.get('entities', {})
                        if isinstance(llm_entities, dict):
                            # Extract date_range from LLM classification
                            if 'date_range' in llm_entities:
                                entities['date_range'] = llm_entities['date_range']
                            # Extract other entities
                            if 'senders' in llm_entities:
                                entities['senders'] = llm_entities['senders']
                            if 'sender' in llm_entities:
                                entities['sender'] = llm_entities['sender']
                            if 'search_term' in llm_entities:
                                entities['search_term'] = llm_entities['search_term']
                            if 'keywords' in llm_entities:
                                entities['keywords'] = llm_entities['keywords']
                            if 'folder' in llm_entities:
                                entities['folder'] = llm_entities['folder']
            except Exception as e:
                logger.debug(f"[EMAIL] LLM entity extraction failed: {e}, using fallback")
        
        # Fallback to pattern-based extraction for specific actions if LLM didn't extract them
        if action == "send":
            # Extract recipient, subject, body
            recipient = entities.get('recipient') or self.composition_handlers.extract_email_recipient(query)
            subject = entities.get('subject') or self.composition_handlers.extract_email_subject(query)
            if recipient:
                entities['recipient'] = recipient
            if subject:
                entities['subject'] = subject
            # Check for schedule time
            schedule_time = self.composition_handlers.extract_schedule_time(query)
            if schedule_time:
                entities['schedule_time'] = schedule_time
        elif action == "search":
            # Use LLM-extracted search_term if available, otherwise fallback
            if 'search_term' not in entities:
                entities['search_term'] = self._extract_search_term(query)
            # Use LLM-extracted sender if available, otherwise fallback
            if 'sender' not in entities and 'senders' not in entities:
                sender = self._extract_sender(query)
                if sender:
                    entities['sender'] = sender
        elif action == "reply":
            # Extract email ID or reference
            if 'email_id' not in entities:
                entities['email_id'] = self._extract_email_reference(query)
        elif action in ["mark_read", "mark_unread", "archive"]:
            # Extract email filters
            if not entities:
                entities.update(self._extract_generic_entities(query))
        elif action == "summarize":
            # Extract summarization scope
            if 'scope' not in entities:
                entities['scope'] = self._extract_summarize_scope(query)
        else:
            # Generic entity extraction - merge with LLM entities
            if not entities:
                entities = self._extract_generic_entities(query)
        
        # CRITICAL: Also use FlexibleDateParser to extract date_range if LLM didn't find it
        # This ensures "last hour" type queries are properly parsed
        if 'date_range' not in entities and self.date_parser:
            try:
                # FlexibleDateParser.parse() returns Optional[Tuple[datetime, datetime]]
                date_tuple = self.date_parser.parse(query)
                if date_tuple and isinstance(date_tuple, tuple) and len(date_tuple) == 2:
                    start, end = date_tuple
                    # Convert to dict format expected by the rest of the code
                    entities['date_range'] = {
                        'start': start,
                        'end': end
                    }
                    logger.info(f"[EMAIL] Date parser extracted date_range: start={start}, end={end}")
            except Exception as e:
                logger.debug(f"[EMAIL] Date parser extraction failed: {e}")
        
        return entities
    
    def _extract_search_term(self, query: str) -> str:
        """Extract search term from query"""
        # Remove common search prefixes
        search_patterns = [
            r'search\s+(?:for\s+)?(.+)',
            r'find\s+(?:emails?\s+)?(?:about\s+)?(.+)',
            r'show\s+(?:me\s+)?(?:emails?\s+)?(?:about\s+)?(.+)',
            r'looking\s+for\s+(.+)'
        ]
        
        for pattern in search_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # Default: use the whole query
        return query
    
    def _extract_sender(self, query: str) -> Optional[str]:
        """Extract sender from query"""
        sender_patterns = [
            r'from\s+([^\s]+(?:@[^\s]+)?)',
            r'sent\s+by\s+([^\s]+)',
            r'sender\s*:\s*([^\s]+)'
        ]
        
        for pattern in sender_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
    
    def _extract_email_reference(self, query: str) -> Optional[str]:
        """Extract email ID or reference from query"""
        # Try to find explicit email ID
        id_match = re.search(r'email\s+id\s*:?\s*(\w+)', query, re.IGNORECASE)
        if id_match:
            return id_match.group(1)
        
        # Look for 'last email', 'recent email', etc.
        if re.search(r'\b(?:last|recent|latest)\s+email', query, re.IGNORECASE):
            return "LAST"
        
        return None
    
    def _extract_summarize_scope(self, query: str) -> str:
        """Extract summarization scope from query"""
        if re.search(r'\b(?:today|today\'s)\b', query, re.IGNORECASE):
            return "today"
        elif re.search(r'\b(?:yesterday|yesterday\'s)\b', query, re.IGNORECASE):
            return "yesterday"
        elif re.search(r'\b(?:this\s+week|week)\b', query, re.IGNORECASE):
            return "week"
        elif re.search(r'\b(?:unread)\b', query, re.IGNORECASE):
            return "unread"
        else:
            return "recent"

    def _extract_generic_entities(self, query: str) -> Dict[str, Any]:
        """Extract common entities from query"""
        entities = {}
        
        # Extract email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, query)
        if emails:
            entities['emails'] = emails
        
        # Extract dates if date parser available
        if self.date_parser:
            try:
                # Use parse_date_expression instead of parse() to get dict result
                date_info = self.date_parser.parse_date_expression(query)
                # Ensure date_info is a dict, not a list
                if date_info and isinstance(date_info, dict):
                    entities['date_info'] = date_info
                elif date_info:
                    logger.warning(f"[EMAIL] Date parser returned non-dict type: {type(date_info)}, skipping")
            except Exception as e:
                logger.debug(f"Date parsing failed: {e}")
        
        return entities
    
    def _calculate_confidence(self, query: str, action: str, entities: Dict[str, Any]) -> float:
        """Calculate confidence score for the parsing result"""
        confidence = 0.5  # Base confidence
        
        # Check pattern matches - EMAIL_PATTERNS is a list, not a dict
        # Check if any pattern in EMAIL_PATTERNS matches the query
        for pattern in EMAIL_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                confidence += 0.2
                break
        
        # Boost confidence if key entities are found
        if action == "send" and all(k in entities for k in ['recipient', 'subject']):
            confidence += 0.2
        elif action == "search" and 'search_term' in entities:
            confidence += 0.15
        elif action == "reply" and 'email_id' in entities:
            confidence += 0.2
        
        # Cap confidence at 1.0
        return min(confidence, 1.0)
    
    def _generate_metadata(self, query: str, action: str, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Generate metadata with suggestions and warnings"""
        metadata = {
            "original_query": query,
            "detected_patterns": [],
            "suggestions": []
        }
        
        # Add warnings for low-confidence parses
        if action == "send" and 'recipient' not in entities:
            metadata['suggestions'].append("No recipient found. Please specify who to send the email to.")
        
        if action == "search" and not entities.get('search_term'):
            metadata['suggestions'].append("Search term is very broad. Consider being more specific.")
        
        return metadata

    def parse_query(self, query: str, tool: BaseTool, user_id: Optional[int] = None, session_id: Optional[str] = None) -> str:
        """
        DEPRECATED: Main query parsing method - delegates to appropriate handlers
        
        This method is deprecated. Use parse_query_to_params() instead for better tool integration.
        
        Args:
            query: User query
            tool: Email tool to use
            user_id: Optional user ID for context
            session_id: Optional session ID for context
            
        Returns:
            Parsed result
        """
        try:
            # CRITICAL: Validate query is not empty before processing
            if not query or not query.strip():
                logger.warning(f"[EMAIL] parse_query called with empty query, defaulting to list action")
                # Default to list action for empty queries
                return self.action_handlers.handle_list_action(tool, "in:inbox")
            
            logger.info(f"[EMAIL] EmailParser.parse_query called with query: '{query}'")
            
            # Extract actual query from conversation context
            actual_query = self.query_processing_handlers.extract_actual_query(query)
            
            # CRITICAL: Validate extracted query is not empty
            if not actual_query or not actual_query.strip():
                logger.warning(f"[EMAIL] extract_actual_query returned empty from query: '{query[:100]}', using original query")
                actual_query = query.strip() if query.strip() else "in:inbox"
            
            # CRITICAL: Check if this is a task/calendar query first - reject immediately
            query_lower = actual_query.lower()
            task_keywords = ['task', 'tasks', 'todo', 'todos', 'reminder', 'deadline']
            calendar_keywords = ['meeting', 'meetings', 'event', 'events', 'appointment', 'calendar', 'schedule']
            email_keywords = ['email', 'emails', 'message', 'messages', 'inbox', 'mail']
            
            has_task_keywords = any(keyword in query_lower for keyword in task_keywords)
            has_calendar_keywords = any(keyword in query_lower for keyword in calendar_keywords)
            has_email_keywords = any(keyword in query_lower for keyword in email_keywords)
            
            logger.debug(f"[EMAIL] Domain detection in parse_query - task: {has_task_keywords}, calendar: {has_calendar_keywords}, email: {has_email_keywords}, query: '{actual_query}'")
            
            # If query mentions tasks/calendar but NOT emails, reject
            if (has_task_keywords or has_calendar_keywords) and not has_email_keywords:
                logger.info(f"[EMAIL] Rejecting query in parse_query - explicitly about tasks/calendar, not emails: '{actual_query}' (task={has_task_keywords}, calendar={has_calendar_keywords}, email={has_email_keywords})")
                return f"[ERROR] This query is about tasks/calendar, not emails. Please use the tasks or calendar tool instead."
            
            # Multi-step query handling
            if self.multi_step_handlers.is_multi_step_query(actual_query):
                return self.multi_step_handlers.handle_multi_step_query(actual_query, tool, user_id, session_id)
            
            # Detect email action
            action = self.classification_handlers.detect_email_action(actual_query)
            logger.info(f"[EMAIL] Detected action: {action}")
            
            # Route to appropriate handler based on action
            if action == "search":
                return self.action_handlers.handle_search_action(tool, actual_query)
            elif action == "send":
                return self.composition_handlers.parse_and_send_email(tool, actual_query)
            elif action == "reply":
                return self.action_handlers.handle_reply_action(tool, actual_query)
            elif action == "unread":
                return self.management_handlers.handle_unread_action(tool, actual_query)
            elif action == "mark_read":
                return self.management_handlers.handle_mark_read_action(tool, actual_query)
            elif action == "mark_unread":
                return self.management_handlers.handle_mark_unread_action(tool, actual_query)
            elif action == "archive":
                return self.management_handlers.handle_archive_action(tool, actual_query)
            elif action == "summarize":
                return self.summarization_handlers.handle_summarize_action(tool, actual_query)
            elif action == "urgency_analysis":
                return self.action_handlers.handle_urgency_analysis_action(tool, actual_query)
            elif action == "contact_analysis":
                return self.action_handlers.handle_contact_analysis_action(tool, actual_query)
            elif action == "category_analysis":
                return self.action_handlers.handle_category_analysis_action(tool, actual_query)
            elif action == "email_patterns":
                return self.action_handlers.handle_email_patterns_action(tool, actual_query)
            elif action == "insights":
                return self.action_handlers.handle_insights_action(tool, actual_query)
            elif action == "semantic_search":
                return self.action_handlers.handle_semantic_search_action(tool, actual_query)
            elif action == "organize":
                return self.action_handlers.handle_organize_action(tool, actual_query)
            elif action == "bulk_delete":
                return self.action_handlers.handle_bulk_delete_action(tool, actual_query)
            elif action == "schedule":
                return self.composition_handlers.parse_and_schedule_email(tool, actual_query)
            elif action == "list":
                return self.action_handlers.handle_list_action(tool, actual_query)
            else:
                # Default to list action
                return self.action_handlers.handle_list_action(tool, actual_query)
                
        except Exception as e:
            logger.error(f"[EMAIL] Error in parse_query: {e}", exc_info=True)
            return f"[ERROR] An error occurred while processing your email query: {str(e)}"
    
    def get_supported_tools(self) -> List[str]:
        """Return list of tool names this parser supports"""
        return ['email']
    
    def validate_tool(self, tool: BaseTool) -> bool:
        """Validate that the tool supports email operations"""
        return super().validate_tool(tool)
    
    def extract_entities(self, query: str) -> Dict[str, Any]:
        """Extract email-specific entities from query"""
        return self.query_processing_handlers.extract_entities(query)
    
    def learn_from_feedback(self, original_query: str, user_correction: str, result_was_correct: bool = False):
        """Learn from user feedback to improve future parsing"""
        return self.feedback_handlers.learn_from_feedback(original_query, user_correction, result_was_correct)
    
    def get_feedback_stats(self) -> Dict[str, Any]:
        """Get feedback statistics"""
        return self.feedback_handlers.get_feedback_stats()
    
    def clear_feedback(self):
        """Clear all feedback (for testing/reset)"""
        return self.feedback_handlers.clear_feedback()
    
    # Tool-specific routing methods for different email tools
    def handle_email_tool(self, query: str, tool: BaseTool, user_id: Optional[int] = None, session_id: Optional[str] = None) -> str:
        """Handle standard EmailTool queries"""
        return self.parse_query(query, tool, user_id, session_id)
    
    def handle_email_management_tool(self, query: str, tool: BaseTool, user_id: Optional[int] = None, session_id: Optional[str] = None) -> str:
        """Handle EmailManagementTool queries"""
        return self.management_handlers.handle_email_management_tool(query, tool, user_id, session_id)
    
    def handle_summarize_tool(self, query: str, tool: BaseTool, user_id: Optional[int] = None, session_id: Optional[str] = None) -> str:
        """Handle SummarizeTool queries"""
        return self.management_handlers.handle_summarize_tool(query, tool, user_id, session_id)