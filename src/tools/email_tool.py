"""
Email Tool for Gmail operations - Service Layer Integration

This tool provides natural language interface for Gmail operations through
the EmailService business logic layer.

Architecture:
    EmailTool → EmailService → GoogleGmailClient → Gmail API
    
The service layer provides:
- Clean business logic interfaces
- Centralized error handling
- Shared code between tools and workers
- Better testability
"""
from typing import Optional, Any, List, Dict
from datetime import datetime
from pydantic import BaseModel, Field, PrivateAttr

from .base_tool import ClavrBaseTool
from ..integrations.gmail.service import EmailService
from ..integrations.gmail.exceptions import (
    EmailServiceException,
    ServiceUnavailableException
)
from .email.constants import LIMITS
from .constants import ToolConfig, ParserIntegrationConfig, ToolLimits
from ..utils.logger import setup_logger
from ..utils.config import Config
from ..ai.prompts import (
    EMAIL_CONVERSATIONAL_LIST,
    EMAIL_CONVERSATIONAL_EMPTY
)

# Import modular components (for advanced features not in service layer)
from .email import (
    EmailIndexing,
    EmailCategorization
)
from .email.ai_analyzer import EmailAIAnalyzer

logger = setup_logger(__name__)

# Import RAG engine for optional indexing
try:
    from ..ai.rag import RAGEngine
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False


class EmailActionInput(BaseModel):
    """Input schema for email operations"""
    action: str = Field(
        description="Action to perform: 'list', 'unread', 'send', 'reply', 'mark_read', 'mark_unread', 'search', 'semantic_search', 'organize', 'bulk_delete', 'bulk_archive', 'categorize', 'insights', 'cleanup', 'schedule', 'extract_tasks', 'auto_process', 'summarize'"
    )
    to: Optional[str] = Field(default=None, description="Recipient email address")
    subject: Optional[str] = Field(default=None, description="Email subject")
    body: Optional[str] = Field(default=None, description="Email body content")
    query: Optional[str] = Field(default=None, description="Search query or email content")
    message_id: Optional[str] = Field(default=None, description="Message ID (for reply, mark operations, task extraction)")
    limit: Optional[int] = Field(default=LIMITS.DEFAULT_LIMIT, description="Number of emails to retrieve")
    folder: Optional[str] = Field(default="inbox", description="Folder to search (inbox, sent, etc.)")
    category: Optional[str] = Field(default=None, description="Category for organization: 'work', 'personal', 'finance', 'travel', 'shopping'")
    criteria: Optional[str] = Field(default=None, description="Criteria for bulk operations: 'old', 'unread', 'spam', 'large'")
    dry_run: Optional[bool] = Field(default=False, description="Preview changes without executing")
    schedule_time: Optional[str] = Field(default=None, description="Time to schedule email (ISO format)")
    auto_create_tasks: Optional[bool] = Field(default=False, description="Automatically create tasks from extracted action items")


class EmailTool(ClavrBaseTool):
    """
    Email operations tool using Gmail API with service layer integration
    
    Capabilities:
    - List emails from inbox
    - Send new emails (immediate or scheduled)
    - Reply to existing emails
    - Mark emails as read/unread
    - Search emails (including semantic search with RAG)
    - Organize and categorize emails
    - Bulk operations (delete, archive)
    - Email insights and analytics
    - Inbox cleanup
    
    Architecture:
        EmailTool → EmailService → GoogleGmailClient → Gmail API
    
    Examples:
        "Show my recent emails"
        "Send an email to john@example.com about the meeting"
        "Reply to the last email"
        "Mark email 123 as read"
        "Search for emails from boss"
        "Find all emails about project budget using semantic search"
        "Organize my emails by category"
        "Delete all old promotional emails"
        "Clean up my inbox automatically"
    """
    
    name: str = "email"
    description: str = (
        "Manage Gmail emails with advanced capabilities. "
        "Can list emails, send new ones (immediately or scheduled), reply to existing emails, "
        "mark as read/unread, search, organize by category, "
        "perform bulk operations, provide insights, and clean up inbox. "
        "Supports semantic search using RAG for better email discovery."
    )
    args_schema: type[BaseModel] = EmailActionInput
    
    # Config and credentials
    config: Optional[Config] = None
    _user_id: Optional[str] = PrivateAttr(default=None)
    _credentials: Optional[Any] = PrivateAttr(default=None)
    
    # Email service (business logic layer)
    _email_service: Optional[EmailService] = PrivateAttr(default=None)
    
    # RAG engine for semantic search and indexing
    _rag_engine: Optional[Any] = PrivateAttr(default=None)
    
    # Modular components (lazy-loaded) - for advanced features not in service layer
    _indexing: Optional[EmailIndexing] = PrivateAttr(default=None)
    _categorization: Optional[EmailCategorization] = PrivateAttr(default=None)
    _ai_analyzer: Optional[EmailAIAnalyzer] = PrivateAttr(default=None)
    
    # Parser for intelligent query understanding
    _parser: Optional[Any] = PrivateAttr(default=None)
    
    # LLM client for AI features
    _llm_client: Optional[Any] = PrivateAttr(default=None)
    
    # Context tracking for follow-up queries (stores last shown email list)
    _last_email_list: Optional[List[Dict[str, Any]]] = PrivateAttr(default=None)
    _last_email_list_query: Optional[str] = PrivateAttr(default=None)
    
    def __init__(
        self,
        config: Optional[Config] = None,
        user_id: Optional[str] = None,
        credentials: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        **kwargs
    ):
        """Initialize email tool with optional RAG integration"""
        super().__init__(**kwargs)
        self.config = config
        self._user_id = user_id
        self._credentials = credentials
        self._rag_engine = rag_engine
        self._last_email_list = None
        self._last_email_list_query = None
        
        # Initialize handlers (use _set_attr to bypass Pydantic validation)
        from .email.formatting_handlers import EmailFormattingHandlers
        from .email.action_handlers import EmailActionHandlers
        from .email.query_handlers import EmailQueryHandlers
        
        self._set_attr('formatting_handlers', EmailFormattingHandlers(self))
        self._set_attr('action_handlers', EmailActionHandlers(self))
        self._set_attr('query_handlers', EmailQueryHandlers(self))
        
        logger.info(f"[EMAIL] EmailTool initialized - user_id={user_id}, has_credentials={credentials is not None}, has_rag={rag_engine is not None}")
    
    @property
    def rag_engine(self) -> Optional[Any]:
        """Get RAG engine for email indexing and semantic search"""
        return self._rag_engine
    
    @property
    def email_service(self) -> EmailService:
        """Get or create the Email service with user credentials"""
        if self._email_service is None and self.config:
            logger.info(f"[EMAIL] Initializing EmailService - user_id={self._user_id}, has_credentials={self._credentials is not None}")
            
            # Get credentials if not already provided
            credentials = self._credentials
            if not credentials and self._user_id:
                logger.info(f"[EMAIL] Attempting to load credentials from session for user_id={self._user_id}")
                credentials = self._get_credentials_from_session(self._user_id, service_name="EMAIL")
            
            # Create email service with credentials
            # CRITICAL: Set hybrid_coordinator IMMEDIATELY if available, not later
            hybrid_coordinator = None
            try:
                # Get hybrid coordinator from indexing module BEFORE creating EmailService
                if self._rag_engine:
                    from ..services.indexing import IntelligentEmailIndexer
                    
                    # Try to create indexer to get hybrid coordinator
                    temp_indexer = IntelligentEmailIndexer(
                        config=self.config,
                        google_client=None,  # Will be set later
                        llm_client=self._llm_client,
                        rag_engine=self._rag_engine,
                        use_knowledge_graph=True
                    )
                    # Get coordinator from indexer (it's stored as hybrid_index)
                    hybrid_coordinator = getattr(temp_indexer, 'hybrid_index', None)
                    if hybrid_coordinator:
                        logger.info(f"[EMAIL] Hybrid coordinator available (has_graph={bool(getattr(hybrid_coordinator, 'graph', None))}), will be set for EmailService")
            except Exception as e:
                logger.debug(f"[EMAIL] Could not get hybrid coordinator: {e}")
            
            self._email_service = EmailService(
                config=self.config,
                credentials=credentials,
                rag_engine=self._rag_engine,
                hybrid_coordinator=hybrid_coordinator  # CRITICAL: Pass it during initialization
            )
            
            if hybrid_coordinator:
                logger.info(f"[EMAIL] ✓ Hybrid coordinator set for EmailService during initialization (has_graph={bool(getattr(hybrid_coordinator, 'graph', None))})")
            
            logger.info(f"[OK] EmailService initialized (user_id={self._user_id})")
        
        return self._email_service
    
    # === MODULAR COMPONENTS (LAZY-LOADED) - For advanced features ===
    
    @property
    def indexing(self) -> EmailIndexing:
        """Get email indexing module (knowledge graph integration)"""
        if self._indexing is None:
            self._indexing = EmailIndexing(
                email_service=self.email_service,
                config=self.config,
                llm_client=self._llm_client,
                rag_engine=self.rag_engine
            )
        return self._indexing
    
    @property
    def categorization(self) -> EmailCategorization:
        """Get email categorization module (AI-powered insights)"""
        if self._categorization is None:
            self._categorization = EmailCategorization(
                llm_client=self._llm_client,  # Use LLM client if available
                classifier=None  # Will be added when needed
            )
        return self._categorization
    
    @property
    def ai_analyzer(self) -> EmailAIAnalyzer:
        """Get AI analyzer module (task extraction, meeting detection)"""
        if self._ai_analyzer is None:
            self._ai_analyzer = EmailAIAnalyzer(
                llm_client=self._llm_client
            )
        return self._ai_analyzer
    
    @property
    def parser(self) -> Any:
        """Get or create EmailParser for intelligent query understanding"""
        if self._parser is None and self.config:
            try:
                from ..agent.parsers.email_parser import EmailParser
                parser_instance = EmailParser(
                    rag_service=self._rag_engine,
                    config=self.config
                )
                self._parser = parser_instance
                logger.info("[EMAIL] EmailParser initialized for query understanding")
            except Exception as e:
                logger.warning(f"[EMAIL] EmailParser initialization failed: {e}")
                self._parser = None
        return self._parser
    
    def set_task_service(self, task_service: Any):
        """Set task service for cross-tool integration"""
        self._set_attr('_task_service', task_service)
    
    # === HELPER METHODS ===
    
    def _get_emails_for_categorization(self, folder: str, limit: int) -> List[Dict[str, Any]]:
        """Get emails from specified folder for categorization operations"""
        try:
            # Use service layer to get emails
            return self.email_service.list_recent_emails(limit=limit, folder=folder)
        except Exception as e:
            logger.error(f"Failed to get emails from folder {folder}: {e}")
            return []
    
    def _organize_emails_wrapper(self, category: Optional[str], folder: str, limit: int, dry_run: bool) -> str:
        """Wrapper for organizing emails by category"""
        try:
            # Get emails from folder using service layer
            emails = self._get_emails_for_categorization(folder, limit)
            
            if not emails:
                return f"No emails found in {folder} folder"
            
            # Categorize using categorization module
            categorized = self.categorization.categorize_emails(emails, category)
            
            # Format response
            output = f"**Email Organization** (found {len(emails)} emails)\n\n"
            for cat, email_list in categorized.items():
                output += f"**{cat.title()}** ({len(email_list)} emails):\n"
                for email in email_list[:ToolLimits.MAX_EMAILS_DISPLAY]:  # Show first MAX_EMAILS_DISPLAY
                    subject = email.get('subject', 'No Subject')
                    output += f"  - {subject}\n"
                if len(email_list) > ToolLimits.MAX_EMAILS_DISPLAY:
                    output += f"  ... and {len(email_list) - ToolLimits.MAX_EMAILS_DISPLAY} more\n"
                output += "\n"
            
            if dry_run:
                output += "\n[DRY RUN] No changes were made."
            
            return output
        except Exception as e:
            return f"[ERROR] Failed to organize emails: {str(e)}"
    
    def _categorize_emails_wrapper(self, query: Optional[str], folder: str, limit: int, dry_run: bool) -> str:
        """Wrapper for AI-powered email categorization"""
        try:
            # Get emails from folder using service layer
            emails = self._get_emails_for_categorization(folder, limit)
            
            if not emails:
                return f"No emails found in {folder} folder"
            
            # AI categorize using categorization module
            categorized = self.categorization.ai_categorize_emails(emails, query)
            
            # Format response
            output = f"**AI Email Categorization** (analyzed {len(emails)} emails)\n\n"
            for cat, email_list in categorized.items():
                output += f"**{cat}** ({len(email_list)} emails):\n"
                for email in email_list[:ToolLimits.MAX_EMAILS_DISPLAY]:  # Show first MAX_EMAILS_DISPLAY
                    subject = email.get('subject', 'No Subject')
                    sender = email.get('sender', 'Unknown')
                    output += f"  - \"{subject}\" from {sender}\n"
                if len(email_list) > ToolLimits.MAX_EMAILS_DISPLAY:
                    output += f"  ... and {len(email_list) - ToolLimits.MAX_EMAILS_DISPLAY} more\n"
                output += "\n"
            
            if dry_run:
                output += "\n[DRY RUN] No changes were made."
            
            return output
        except Exception as e:
            return f"[ERROR] Failed to categorize emails: {str(e)}"
    
    def _email_insights_wrapper(self, folder: str, limit: int) -> str:
        """Wrapper for email insights and analytics"""
        try:
            # Get emails from folder using service layer
            emails = self._get_emails_for_categorization(folder, limit)
            
            if not emails:
                return f"No emails found in {folder} folder"
            
            # Analyze patterns using categorization module
            insights = self.categorization.analyze_email_patterns(emails)
            
            # Format response
            output = f"**Email Insights** (analyzed {len(emails)} emails)\n\n"
            
            if 'top_senders' in insights:
                output += "**Top Senders:**\n"
                for sender, count in insights['top_senders'][:ToolLimits.MAX_ANALYTICS_ITEMS]:
                    output += f"  - {sender}: {count} emails\n"
                output += "\n"
            
            if 'categories' in insights:
                output += "**By Category:**\n"
                for category, count in insights['categories'].items():
                    output += f"  - {category.title()}: {count} emails\n"
                output += "\n"
            
            if 'unread_count' in insights:
                output += f"**Unread:** {insights['unread_count']} emails\n"
            
            return output
        except Exception as e:
            return f"[ERROR] Failed to generate insights: {str(e)}"
    
    def _cleanup_inbox_wrapper(self, limit: int, dry_run: bool) -> str:
        """Wrapper for inbox cleanup operations"""
        try:
            # Get emails from inbox using service layer
            emails = self._get_emails_for_categorization("inbox", limit)
            
            if not emails:
                return "Inbox is empty or no emails found"
            
            # Identify cleanup candidates
            candidates = self.categorization.identify_cleanup_candidates(emails)
            
            total_to_clean = sum(len(email_list) for email_list in candidates.values())
            
            # Format response
            output = f"**Inbox Cleanup** (scanned {len(emails)} emails)\n\n"
            output += f"Found {total_to_clean} emails to clean up:\n\n"
            
            for category, email_list in candidates.items():
                if email_list:
                    output += f"**{category}** ({len(email_list)} emails):\n"
                    for email in email_list[:ToolLimits.MAX_EMAILS_DISPLAY]:  # Show first MAX_EMAILS_DISPLAY
                        subject = email.get('subject', 'No Subject')
                        sender = email.get('sender', 'Unknown')
                        output += f"  - \"{subject}\" from {sender}\n"
                    if len(email_list) > 3:
                        output += f"  ... and {len(email_list) - 3} more\n"
                    output += "\n"
            
            if dry_run:
                output += "\n[DRY RUN] No emails were deleted. Run without dry_run to execute cleanup."
            else:
                output += f"\nCleaned up {total_to_clean} emails"
            
            return output
        except Exception as e:
            return f"[ERROR] Failed to cleanup inbox: {str(e)}"
    
    # === MAIN EXECUTION ===
    
    def _run(
        self,
        action: str,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        query: Optional[str] = None,
        message_id: Optional[str] = None,
        limit: int = LIMITS.DEFAULT_LIMIT,
        folder: str = "inbox",
        category: Optional[str] = None,
        criteria: Optional[str] = None,
        schedule_time: Optional[str] = None,
        dry_run: bool = False,
        auto_create_tasks: bool = False,
        **kwargs
    ) -> str:
        """
        Execute email operation (synchronous)
        
        Uses EmailService for core operations and modular components for
        advanced features (categorization, AI extraction, etc.).
        
        PARSER INTEGRATION: If a query is provided, the parser enhances
        parameter extraction and action classification.
        """
        logger.info(f"[EMAIL] EmailTool._run called with action='{action}', query='{query}', to='{to}', subject='{subject}', message_id='{message_id}'")
        
        # === PARSER INTEGRATION (Priority 1 Fix) ===
        # Use parser to enhance parameter extraction if query is provided
        if query and self.parser:
            try:
                parsed = self.parser.parse_query_to_params(
                    query=query,
                    user_id=self._user_id,
                    session_id=None
                )
                
                logger.info(f"[EMAIL] Parser result: action={parsed['action']}, confidence={parsed['confidence']}")
                
                # Use parsed action if confidence is high and no explicit action provided
                if parsed['confidence'] >= ParserIntegrationConfig.USE_PARSED_ACTION_THRESHOLD and (not action or action == ToolConfig.DEFAULT_ACTION_SEARCH):
                    action = parsed['action']
                    logger.info(f"[EMAIL] Using parser-detected action: {action}")
                
                # Enhance parameters with parsed entities (only if not already provided)
                entities = parsed.get('entities', {})
                if not to and 'recipient' in entities:
                    to = entities['recipient']
                    logger.info(f"[EMAIL] Using parser-extracted recipient: {to}")
                if not subject and 'subject' in entities:
                    subject = entities['subject']
                    logger.info(f"[EMAIL] Using parser-extracted subject: {subject}")
                if not query and 'search_term' in entities:
                    query = entities['search_term']
                    logger.info(f"[EMAIL] Using parser-extracted search term: {query}")
                if not schedule_time and 'schedule_time' in entities:
                    schedule_time = entities['schedule_time']
                    logger.info(f"[EMAIL] Using parser-extracted schedule time: {schedule_time}")
                
                # Log low-confidence warnings
                if parsed['confidence'] < ParserIntegrationConfig.LOW_CONFIDENCE_WARNING_THRESHOLD:
                    logger.warning(f"[EMAIL] Low confidence parse ({parsed['confidence']}). Suggestions: {parsed.get('metadata', {}).get('suggestions', [])}")
                    
            except Exception as e:
                logger.warning(f"[EMAIL] Parser enhancement failed (continuing with original params): {e}")
        
        try:
            # Check service availability
            try:
                self.email_service._ensure_available()
            except ServiceUnavailableException:
                return self._get_google_gmail_setup_message()
            
            # === ROUTE TO SERVICE LAYER ===
            
            # Core email actions (send, reply)
            if action == "send":
                return self.action_handlers.handle_send(to=to, subject=subject, body=body, **kwargs)
            
            elif action == "reply":
                return self.action_handlers.handle_reply(message_id=message_id, body=body, **kwargs)
            
            # Mark operations
            elif action == "mark_read":
                return self.action_handlers.handle_mark_read(message_id=message_id, query=query, **kwargs)
            
            elif action == "mark_unread":
                return self.action_handlers.handle_mark_unread(message_id=message_id, query=query, **kwargs)
            
            # Delete and archive operations
            elif action == "delete":
                return self.action_handlers.handle_delete(message_id=message_id, query=query, **kwargs)
            
            elif action == "archive":
                return self.action_handlers.handle_archive(message_id=message_id, query=query, **kwargs)
            
            # Search and list operations
            elif action == "list":
                return self.query_handlers.handle_list(limit=limit, folder=folder, query=query, **kwargs)
            
            elif action == "unread":
                return self.query_handlers.handle_unread(limit=limit, query=query, **kwargs)
            
            elif action == "search":
                return self.query_handlers.handle_search(query=query, folder=folder, limit=limit, **kwargs)
            
            elif action == "semantic_search":
                return self.query_handlers.handle_semantic_search(query=query, limit=limit, **kwargs)
            
            # Advanced categorization features (use modular components)
            elif action == "organize":
                return self.query_handlers.handle_organize(category=category, folder=folder, limit=limit, dry_run=dry_run, **kwargs)
            
            elif action == "categorize":
                return self.query_handlers.handle_categorize(query=query, folder=folder, limit=limit, dry_run=dry_run, **kwargs)
            
            elif action == "insights":
                return self.query_handlers.handle_insights(folder=folder, limit=limit, **kwargs)
            
            elif action == "cleanup":
                return self.query_handlers.handle_cleanup(limit=limit, dry_run=dry_run, **kwargs)
            
            # Bulk operations
            elif action == "bulk_delete":
                return self.query_handlers.handle_bulk_delete(criteria=criteria, **kwargs)
            
            elif action == "bulk_archive":
                return self.query_handlers.handle_bulk_archive(criteria=criteria, **kwargs)
            
            # Schedule email (future feature)
            elif action == "schedule":
                return self.action_handlers.handle_schedule(to=to, subject=subject, body=body, schedule_time=schedule_time, **kwargs)
            
            # AI-powered features
            elif action == "extract_tasks":
                return self.action_handlers.handle_extract_tasks(message_id=message_id, auto_create_tasks=auto_create_tasks, **kwargs)
            
            elif action == "auto_process":
                return self.action_handlers.handle_auto_process(message_id=message_id, **kwargs)
            
            else:
                return f"[ERROR] Unknown action: {action}. Use: list, unread, send, reply, mark_read, mark_unread, delete, archive, search, semantic_search, organize, bulk_delete, bulk_archive, categorize, insights, cleanup, extract_tasks, or auto_process"
        
        except EmailServiceException as e:
            return f"[ERROR] Email service error: {str(e)}"
        except Exception as e:
            return self._handle_error(e, f"email action '{action}'")
    
    async def _arun(self, **kwargs) -> str:
        """Async execution (calls sync version)"""
        return self._run(**kwargs)
    
    # === HELPER METHODS ===
    
    def _handle_follow_up_selection(self, query: str, action_type: str) -> Optional[Dict[str, Any]]:
        """
        Handle follow-up selections like "the first one", "the second one", "the one from [sender]"
        
        Uses stored context from previous email list, or uses parser/memory to understand context.
        """
        if not self._last_email_list:
            # If no stored list, try to get recent emails that might match
            query_lower = query.lower().strip() if query else ""
            has_ordinal = any(word in query_lower for word in ['first', 'second', 'third', 'one', 'two', 'three', '1', '2', '3'])
            if has_ordinal:
                try:
                    emails = self.email_service.list_recent_emails(limit=10)
                    logger.info(f"[EMAIL] No stored list, using recent emails as context ({len(emails)} emails)")
                    self._last_email_list = emails
                except:
                    return None
            else:
                return None
        
        query_lower = (query or "").lower().strip()
        emails = self._last_email_list
        
        # Handle ordinal references: "first", "second", "third", "1st", "2nd", etc.
        ordinal_patterns = {
            'first': 0, '1st': 0, 'one': 0, '1': 0,
            'second': 1, '2nd': 1, 'two': 1, '2': 1,
            'third': 2, '3rd': 2, 'three': 2, '3': 2,
            'fourth': 3, '4th': 3, 'four': 3, '4': 3,
            'fifth': 4, '5th': 4, 'five': 4, '5': 4,
        }
        
        for pattern, index in ordinal_patterns.items():
            if pattern in query_lower and index < len(emails):
                logger.info(f"[EMAIL] Resolved ordinal reference '{pattern}' to index {index}")
                return emails[index]
        
        # Handle sender-based references: "the one from [sender]", "from [sender]"
        if "from" in query_lower:
            # Extract sender name/email from query
            from_idx = query_lower.find("from")
            if from_idx != -1:
                sender_text = query[from_idx + 4:].strip()
                # Try to match by sender
                for email in emails:
                    sender = email.get('from', email.get('sender', ''))
                    if sender_text.lower() in sender.lower() or sender.lower() in sender_text.lower():
                        logger.info(f"[EMAIL] Resolved sender reference '{sender_text}' to email from {sender}")
                        return email
        
        # Handle subject-based references: "the one about [subject]", "about [subject]"
        if "about" in query_lower:
            about_idx = query_lower.find("about")
            if about_idx != -1:
                subject_text = query[about_idx + 5:].strip()
                matching = [e for e in emails if subject_text.lower() in e.get('subject', '').lower()]
                if len(matching) == 1:
                    logger.info(f"[EMAIL] Resolved subject reference '{subject_text}'")
                    return matching[0]
        
        return None
        """Format list of emails for display with conversational response"""
        if not emails:
            # Even for no emails, make it conversational
            if query:
                try:
                    from ..ai.llm_factory import LLMFactory
                    from langchain_core.messages import HumanMessage, SystemMessage
                    from ..ai.prompts import get_agent_system_prompt
                    
                    # Use self.config if available, otherwise fall back to Config.from_env()
                    config = self.config if self.config else Config.from_env()
                    llm = LLMFactory.get_llm_for_provider(config, temperature=0.7)
                    
                    if llm:
                        # Use centralized prompt with AGENT_SYSTEM_PROMPT
                        prompt = EMAIL_CONVERSATIONAL_EMPTY.format(query=query)
                        
                        messages = [
                            SystemMessage(content=get_agent_system_prompt()),
                            HumanMessage(content=prompt)
                        ]
                        response = llm.invoke(messages)
                        response_text = response.content if hasattr(response, 'content') else str(response)
                        
                        if not isinstance(response_text, str):
                            response_text = str(response_text) if response_text else ""
                        
                        if response_text and len(response_text.strip()) > 0:
                            return response_text.strip()
                except Exception as e:
                    logger.debug(f"[EMAIL] Failed to generate conversational 'no emails' response: {e}")
            
            return f"No emails found. Your inbox is clear!"
        
        # CRITICAL: Check if query is asking about email CONTENT (not just listing)
        # Use intelligent LLM-based detection from the existing architecture
        if query and len(emails) == 1:
            try:
                # Use the intelligent classification handler from the existing architecture
                from ..agent.parsers.email.classification_handlers import EmailClassificationHandlers
                from ..ai.llm_factory import LLMFactory
                
                config = self.config if self.config else Config.from_env()
                llm_client = LLMFactory.get_llm_for_provider(config, temperature=0.1)
                
                should_generate_summary = False
                
                if llm_client:
                    try:
                        # Create minimal parser wrapper for classification handler
                        class ParserWrapperForClassification:
                            def __init__(self, llm_client):
                                self.llm_client = llm_client
                        
                        temp_parser = ParserWrapperForClassification(llm_client)
                        classification_handler = EmailClassificationHandlers(temp_parser)
                        
                        # Use intelligent LLM-based detection (no hardcoded patterns)
                        what_about_detection = classification_handler.detect_what_about_query(query)
                        asks_what_about = what_about_detection.get("asks_what_about", False)
                        asks_summary = what_about_detection.get("asks_summary", False)
                        confidence = what_about_detection.get("confidence", 0.0)
                        
                        # Use LLM detection result - trust the intelligent architecture
                        should_generate_summary = asks_what_about or asks_summary
                        
                        logger.info(f"[EMAIL] Intelligent content query detection: asks_what_about={asks_what_about}, asks_summary={asks_summary}, confidence={confidence}, should_summarize={should_generate_summary}")
                    except Exception as e:
                        logger.debug(f"[EMAIL] LLM-based detection failed: {e}")
                        # If LLM detection fails, don't generate summary (let it fall through to regular formatting)
                
                # If asking about content, fetch full email body and generate summary
                if should_generate_summary:
                    email = emails[0]
                    message_id = email.get('id')
                    sender = email.get('from', email.get('sender', 'Unknown'))
                    subject = email.get('subject', '')
                    
                    if message_id:
                        try:
                            # CRITICAL: Prioritize index content - emails from index already have full body
                            email_source = email.get('_source', 'unknown')
                            body_content = email.get('body', '') or email.get('snippet', '')
                            
                            logger.info(f"[EMAIL] Initial body content check: source={email_source}, has_body={bool(email.get('body'))}, body_len={len(body_content)}, snippet_len={len(email.get('snippet', ''))}")
                            
                            # CRITICAL: If email is from index, trust the index content (it already has full body)
                            # Only fetch from Gmail API if email is NOT from index AND we don't have body content
                            is_from_index = email_source in ['index', 'hybrid_graphrag', 'neo4j_direct']
                            
                            if is_from_index:
                                # Trust index content - it already has the full body
                                logger.info(f"[EMAIL] Email is from index (source: {email_source}), using index body content (len: {len(body_content)})")
                            elif not body_content or len(body_content) < 200:
                                # Email is from Gmail API and doesn't have full body - fetch it
                                logger.info(f"[EMAIL] Email is from Gmail API (source: {email_source}), fetching full body (current_len: {len(body_content)})")
                                full_email = self.email_service.get_email(message_id)
                                if full_email:
                                    body_content = full_email.get('body', '') or full_email.get('snippet', '')
                                    logger.info(f"[EMAIL] Fetched body from Gmail API: len={len(body_content)}")
                            
                            # CRITICAL: Generate summary if we have ANY body content (even if short)
                            # The LLM can still summarize short content, and we want to provide what we have
                            if body_content and len(body_content.strip()) > 0:
                                logger.info(f"[EMAIL] Generating summary for email content query (body length: {len(body_content)}, source: {'index' if email.get('body') else 'gmail_api'})")
                                
                                # Use LLM to generate summary
                                from langchain_core.messages import HumanMessage, SystemMessage
                                from ..ai.prompts import EMAIL_SUMMARY_SINGLE
                                
                                summary_prompt = EMAIL_SUMMARY_SINGLE.format(
                                    sender=sender,
                                    subject=subject,
                                    body=body_content[:4000],  # Limit body length for LLM
                                    length_guidance="comprehensive"
                                )
                                
                                messages = [
                                    SystemMessage(content="You are a helpful personal assistant."),
                                    HumanMessage(content=summary_prompt)
                                ]
                                
                                response = llm_client.invoke(messages)
                                summary_text = response.content if hasattr(response, 'content') else str(response)
                                
                                if summary_text and len(summary_text.strip()) > 0:
                                    logger.info(f"[EMAIL] Generated email content summary ({len(summary_text)} chars)")
                                    return summary_text.strip()
                        except Exception as e:
                            logger.warning(f"[EMAIL] Failed to generate email content summary: {e}", exc_info=True)
                            # Fall through to regular formatting
            except Exception as e:
                logger.debug(f"[EMAIL] Content query detection failed: {e}")
                # Fall through to regular formatting
        
        # CRITICAL: For single email queries, check if it's a content query BEFORE generating conversational response
        # This ensures we generate summaries instead of just listing the subject
        if query and len(emails) == 1:
            try:
                # Use intelligent detection to see if this is a content query
                from ..agent.parsers.email.classification_handlers import EmailClassificationHandlers
                from ..ai.llm_factory import LLMFactory
                
                config = self.config if self.config else Config.from_env()
                llm_client = LLMFactory.get_llm_for_provider(config, temperature=0.1)
                
                if llm_client:
                    try:
                        class ParserWrapperForContentCheck:
                            def __init__(self, llm_client):
                                self.llm_client = llm_client
                        
                        temp_parser = ParserWrapperForContentCheck(llm_client)
                        classification_handler = EmailClassificationHandlers(temp_parser)
                        
                        what_about_detection = classification_handler.detect_what_about_query(query)
                        asks_what_about = what_about_detection.get("asks_what_about", False)
                        asks_summary = what_about_detection.get("asks_summary", False)
                        
                        # If it's a content query, generate summary instead of conversational response
                        if asks_what_about or asks_summary:
                            email = emails[0]
                            message_id = email.get('id')
                            sender = email.get('from', email.get('sender', 'Unknown'))
                            subject = email.get('subject', '')
                            
                            if message_id:
                                # CRITICAL: Prioritize index content - emails from index already have full body
                                email_source = email.get('_source', 'unknown')
                                body_content = email.get('body', '') or email.get('snippet', '')
                                
                                # CRITICAL: If email is from index, trust the index content (it already has full body)
                                # Only fetch from Gmail API if email is NOT from index AND we don't have body content
                                is_from_index = email_source in ['index', 'hybrid_graphrag', 'neo4j_direct']
                                
                                if is_from_index:
                                    # Trust index content - it already has the full body
                                    logger.info(f"[EMAIL] Email is from index (source: {email_source}), using index body content (len: {len(body_content)})")
                                elif not body_content or len(body_content) < 200:
                                    # Email is from Gmail API and doesn't have full body - fetch it
                                    logger.info(f"[EMAIL] Email is from Gmail API (source: {email_source}), fetching full body (current_len: {len(body_content)})")
                                    full_email = self.email_service.get_email(message_id)
                                    if full_email:
                                        body_content = full_email.get('body', '') or full_email.get('snippet', '')
                                        logger.info(f"[EMAIL] Fetched body from Gmail API: len={len(body_content)}")
                                
                                # Generate comprehensive summary
                                if body_content and len(body_content.strip()) > 0:
                                    from langchain_core.messages import HumanMessage, SystemMessage
                                    from ..ai.prompts import EMAIL_SUMMARY_SINGLE
                                    
                                    summary_prompt = EMAIL_SUMMARY_SINGLE.format(
                                        sender=sender,
                                        subject=subject,
                                        body=body_content[:4000],
                                        length_guidance="comprehensive"
                                    )
                                    
                                    messages = [
                                        SystemMessage(content="You are a helpful personal assistant."),
                                        HumanMessage(content=summary_prompt)
                                    ]
                                    
                                    response = llm_client.invoke(messages)
                                    summary_text = response.content if hasattr(response, 'content') else str(response)
                                    
                                    if summary_text and len(summary_text.strip()) > 0:
                                        logger.info(f"[EMAIL] Generated comprehensive email summary ({len(summary_text)} chars)")
                                        return summary_text.strip()
                    except Exception as e:
                        logger.debug(f"[EMAIL] Secondary content query detection failed: {e}")
            except Exception as e:
                logger.debug(f"[EMAIL] Secondary content query check failed: {e}")
        
        # Try conversational response (but only if not a content query)
        if query:
            conversational = self.formatting_handlers._generate_conversational_email_list_response(emails, query, title)
            if conversational:
                return conversational
        
        # Fallback to natural sentence format (NOT robotic, with bold subjects)
        # Create a natural sentence instead of bullet points
        # For "today" queries, include ALL emails (not just 10) to avoid truncation
        query_lower = query.lower() if query else ""
        is_today_query = "today" in query_lower or "new emails" in query_lower
        max_emails_for_fallback = len(emails) if is_today_query else min(20, len(emails))  # Increased from 10
        
        email_descriptions = []
        for email in emails[:max_emails_for_fallback]:
            subject = email.get('subject', 'No Subject')
            sender = email.get('from', email.get('sender', 'Unknown'))
            
            # Format email subject in bold
            email_desc = f"**{subject}**"
            
            # Add sender information
            if sender and sender != 'Unknown':
                # Extract name from email if it's in format "Name <email>"
                sender_name = sender.split('<')[0].strip().strip('"\'')
                if sender_name:
                    email_desc += f" from {sender_name}"
                else:
                    # Use email address if no name
                    email_addr = sender.split('<')[-1].strip('>').strip()
                    email_desc += f" from {email_addr}"
            
            email_descriptions.append(email_desc)
        
        # Create natural sentence format
        if len(email_descriptions) == 1:
            return f"You've got {email_descriptions[0]} in your inbox."
        elif len(email_descriptions) == 2:
            return f"You've got {email_descriptions[0]} and {email_descriptions[1]} in your inbox."
        else:
            first_few = ", ".join(email_descriptions[:-1])
            last_one = email_descriptions[-1]
            if len(emails) > 10:
                return f"You've got {first_few}, and {last_one} in your inbox. That's {len(emails)} emails total."
            else:
                return f"You've got {first_few}, and {last_one} in your inbox."
    
    def _get_google_gmail_setup_message(self) -> str:
        """Return setup message when Gmail is not available"""
        return (
            "[ERROR] Gmail is not available. Please make sure you're authenticated with Google.\n\n"
            "To set up Gmail:\n"
            "1. Go to Settings → Integrations\n"
            "2. Click 'Connect Gmail'\n"
            "3. Authorize access to your Gmail account"
        )
    
    def _handle_error(self, error: Exception, context: str) -> str:
        """Handle and format errors"""
        error_msg = f"[ERROR] Failed to execute {context}: {str(error)}"
        logger.error(error_msg, exc_info=True)
        return error_msg
