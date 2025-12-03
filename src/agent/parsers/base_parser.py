"""
Base Parser - Abstract base class for all query parsers

Provides common functionality for all parsers including:
- Semantic pattern matching (shared across all parsers)
- Common NLP utilities initialization
- Response formatting
- Context extraction
- Workflow event emission
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from langchain.tools import BaseTool
import numpy as np

from ...utils.logger import setup_logger

logger = setup_logger(__name__)

# Constants for base parser
DEFAULT_MAX_MESSAGES_CONTEXT = 5
DEFAULT_SEMANTIC_THRESHOLD = 0.7
GEMINI_THRESHOLD_MULTIPLIER = 0.95
DEFAULT_LLM_TEMPERATURE = 0.1
DEFAULT_LLM_MAX_TOKENS = 2000

# Try to import sentence transformers for semantic matching (shared across parsers)
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.debug("sentence-transformers not available - semantic matching will use Gemini only")


def safe_cosine_similarity(X, Y):
    """
    Compute cosine similarity with proper handling of edge cases.
    
    Fixes numerical overflow issues by:
    1. Normalizing vectors properly
    2. Handling zero vectors
    3. Clipping values to valid range [-1, 1]
    """
    # Convert to numpy arrays
    X = np.asarray(X, dtype=np.float64)
    Y = np.asarray(Y, dtype=np.float64)
    
    # Ensure 2D arrays
    if X.ndim == 1:
        X = X.reshape(1, -1)
    if Y.ndim == 1:
        Y = Y.reshape(1, -1)
    
    # Compute norms
    X_norm = np.linalg.norm(X, axis=1, keepdims=True)
    Y_norm = np.linalg.norm(Y, axis=1, keepdims=True)
    
    # Handle zero vectors (return 0 similarity)
    X_norm = np.where(X_norm == 0, 1, X_norm)
    Y_norm = np.where(Y_norm == 0, 1, Y_norm)
    
    # Normalize
    X_normalized = X / X_norm
    Y_normalized = Y / Y_norm
    
    # Compute dot product
    similarity = np.dot(X_normalized, Y_normalized.T)
    
    # Clip to valid range to avoid numerical errors
    similarity = np.clip(similarity, -1.0, 1.0)
    
    return similarity


class BaseParser(ABC):
    """
    Abstract base class for all query parsers
    
    Each parser handles a specific domain (email, calendar, task, notion, etc.)
    and can optionally use RAG services for enhanced understanding.
    
    Supported Domains:
    - Email: EmailParser for Gmail operations
    - Calendar: CalendarParser for Google Calendar operations
    - Task: TaskParser for Google Tasks operations
    - Notion: NotionParser for Notion pages and databases
    
    AUTONOMOUS OPERATION:
    Parsers operate autonomously to:
    - Extract entities and intents from user queries without confirmation
    - Execute actions based on confidence levels (high/medium/low)
    - Learn from feedback and adapt parsing rules automatically
    - Handle errors gracefully and recover independently
    - Use context from conversation history autonomously
    
    INTEGRATION WITH ROLES:
    Parsers are integrated with:
    - DomainSpecialistRole: Used for entity extraction and query parsing
    - AnalyzerRole: Provides domain-specific entity extraction
    - Tools: Used by EmailTool, CalendarTool, TaskTool, NotionTool for query understanding
    """
    
    def __init__(self, rag_service=None, memory=None, config=None):
        """
        Initialize parser
        
        Args:
            rag_service: Optional RAG service for enhanced parsing
            memory: Optional conversation memory for context awareness
            config: Optional configuration object (for NLP utilities, etc.)
        """
        self.rag_service = rag_service
        self.memory = memory
        self.config = config
        self.name = self.__class__.__name__.lower().replace('parser', '')
        
        # Track parser usage for analytics
        self.stats = {
            'queries_parsed': 0,
            'successful_parses': 0,
            'failed_parses': 0,
            'avg_confidence': 0.0
        }
    
    def get_supported_tools(self) -> List[str]:
        """
        Return list of tool names this parser supports
        
        Override in subclass to specify which tools are supported
        """
        return []
    
    def _is_valid_tool(self, tool: BaseTool) -> bool:
        """Check if tool is valid for this parser"""
        supported = self.get_supported_tools()
        if not supported:
            # If no tools specified, accept any tool
            return True
        return tool.name in supported
    
    def validate_tool(self, tool: BaseTool) -> bool:
        """
        Validate that the tool is compatible with this parser
        
        Args:
            tool: Tool to validate
            
        Returns:
            True if tool is valid, False otherwise
        """
        if not tool:
            logger.error("Tool is None")
            return False
        
        if not self._is_valid_tool(tool):
            logger.warning(f"Tool '{tool.name}' may not be compatible with {self.__class__.__name__}")
            # Don't fail - allow for flexibility
        
        return True
    
    @abstractmethod
    def parse_query_to_params(self, query: str, user_id: Optional[int] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Parse a query into structured parameters WITHOUT executing the tool
        
        This method replaces the old parse_query() to enable proper tool integration.
        Returns a dictionary with parsed action, entities, and metadata.
        
        Args:
            query: User query to parse
            user_id: User ID for conversation memory access
            session_id: Session ID for multi-turn conversations
            
        Returns:
            Dictionary containing:
                - action: str - The action to perform (e.g., 'send', 'search', 'list')
                - entities: Dict[str, Any] - Extracted entities (e.g., recipient, subject, date)
                - confidence: float - Confidence score (0.0-1.0)
                - metadata: Dict[str, Any] - Additional context (e.g., detected patterns, suggestions)
        """
        pass
    
    def parse_query(self, query: str, tool: BaseTool, user_id: Optional[int] = None, session_id: Optional[str] = None) -> str:
        """
        Legacy method: Parse a query and execute with the appropriate tool
        
        This method is maintained for compatibility but delegates to parse_query_to_params()
        and tool execution. New code should use parse_query_to_params() directly.
        
        Args:
            query: User query to parse
            tool: Tool to execute with parsed parameters
            user_id: User ID for conversation memory access
            session_id: Session ID for conversation memory access
            
        Returns:
            Tool execution result
        """
        # Parse query to parameters
        params = self.parse_query_to_params(query, user_id, session_id)
        
        # Execute with tool
        action = params.get('action', 'list')
        entities = params.get('entities', {})
        
        # Build tool arguments from entities
        tool_args = {**entities}
        if 'limit' in params.get('metadata', {}):
            tool_args['limit'] = params['metadata']['limit']
        
        # Execute tool action
        try:
            result = tool._run(action=action, **tool_args)
            return result
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return f"[ERROR] Failed to execute {action}: {str(e)}"
    
    def get_context(self, query: str) -> Dict[str, Any]:
        """
        Get context for the query using RAG service
        
        Args:
            query: User query
            
        Returns:
            Context dictionary
        """
        if self.rag_service:
            try:
                return self.rag_service.get_context(query)
            except Exception as e:
                logger.warning(f"Failed to get RAG context: {e}")
                return {}
        return {}
    
    def get_conversation_context(self, user_id: int, session_id: str, max_messages: int = DEFAULT_MAX_MESSAGES_CONTEXT) -> Dict[str, Any]:
        """
        Get comprehensive conversation context from memory (sync wrapper for async methods).
        
        Note: This is a synchronous wrapper. If ConversationMemory is async, it will return empty context.
        For full async support, use get_conversation_context_async() instead.
        
        Args:
            user_id: User ID
            session_id: Session ID
            max_messages: Maximum number of recent messages to retrieve
            
        Returns:
            Conversation context dictionary with entities, intents, and recent messages
        """
        if not self.memory:
            return {}
        
        # Check if memory is ConversationMemory (async) or SimplifiedMemorySystem (sync)
        memory_type = type(self.memory).__name__
        
        if memory_type == 'ConversationMemory':
            # ConversationMemory is async - return empty context for sync calls
            # Callers should use async methods or pass SimplifiedMemorySystem instead
            logger.debug("ConversationMemory requires async access - returning empty context for sync call")
            return {}
        
        try:
            # For SimplifiedMemorySystem or other sync memory systems
            if hasattr(self.memory, 'get_recent_messages'):
                recent_messages = self.memory.get_recent_messages(user_id, session_id, max_messages)
            else:
                recent_messages = []
            
            if hasattr(self.memory, 'get_recent_context'):
                recent_context = self.memory.get_recent_context(user_id, session_id)
            else:
                recent_context = {}
            
            # Extract conversation entities
            conversation_entities = self._extract_conversation_entities(recent_messages)
            
            return {
                'recent_messages': recent_messages,
                'recent_context': recent_context,
                'conversation_entities': conversation_entities,
                'last_email_mentioned': self._extract_last_email_mention(recent_messages),
                'last_person_mentioned': self._extract_last_person_mention(recent_messages),
                'last_date_mentioned': self._extract_last_date_mention(recent_messages)
            }
            
        except Exception as e:
            logger.warning(f"Failed to get conversation context: {e}")
            return {}
    
    def _extract_conversation_entities(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract entities from conversation messages"""
        entities = {
            'people': [],
            'emails': [],
            'dates': [],
            'subjects': [],
            'senders': [],
            'notion_pages': [],
            'notion_databases': [],
            'tasks': [],
            'events': []
        }
        
        for message in messages:
            content = message.get('content', '')
            if not content:
                continue
                
            # Extract email addresses
            import re
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            emails = re.findall(email_pattern, content)
            entities['emails'].extend(emails)
            
            # Extract names (simple heuristic)
            name_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
            names = re.findall(name_pattern, content)
            entities['people'].extend(names)
            
            # Extract dates
            date_pattern = r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b'
            dates = re.findall(date_pattern, content)
            entities['dates'].extend(dates)
            
            # Extract Notion page/database references
            notion_page_pattern = r'(?:Notion\s+)?page\s+(?:named|called|titled)?\s*["\']?([^"\']+)["\']?'
            notion_pages = re.findall(notion_page_pattern, content, re.IGNORECASE)
            entities['notion_pages'].extend(notion_pages)
            
            notion_db_pattern = r'(?:Notion\s+)?database\s+(?:named|called)?\s*["\']?([^"\']+)["\']?'
            notion_databases = re.findall(notion_db_pattern, content, re.IGNORECASE)
            entities['notion_databases'].extend(notion_databases)
            
            # Extract task references
            task_pattern = r'task\s+(?:named|called)?\s*["\']?([^"\']+)["\']?'
            tasks = re.findall(task_pattern, content, re.IGNORECASE)
            entities['tasks'].extend(tasks)
            
            # Extract event references
            event_pattern = r'(?:event|meeting)\s+(?:named|called|titled)?\s*["\']?([^"\']+)["\']?'
            events = re.findall(event_pattern, content, re.IGNORECASE)
            entities['events'].extend(events)
        
        # Remove duplicates
        for key in entities:
            entities[key] = list(set(entities[key]))
            
        return entities
    
    def _extract_last_email_mention(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        """Extract the last email mentioned in conversation"""
        for message in reversed(messages):  # Start from most recent
            content = message.get('content', '')
            if not content:
                continue
                
            # Look for email patterns
            import re
            
            # Pattern for "email from [sender]"
            from_pattern = r'email from\s+([a-zA-Z0-9@._-]+)'
            match = re.search(from_pattern, content, re.IGNORECASE)
            if match:
                sender = match.group(1)
                return {'sender': sender, 'context': 'from'}
            
            # Pattern for "last email from [sender]"
            last_pattern = r'last email from\s+([a-zA-Z0-9@._-]+)'
            match = re.search(last_pattern, content, re.IGNORECASE)
            if match:
                sender = match.group(1)
                return {'sender': sender, 'context': 'last_from'}
            
            # Pattern for "received an email from [sender]"
            received_pattern = r'received an email from\s+([a-zA-Z0-9@._-]+)'
            match = re.search(received_pattern, content, re.IGNORECASE)
            if match:
                sender = match.group(1)
                return {'sender': sender, 'context': 'received_from'}
        
        return None
    
    def _extract_last_person_mention(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Extract the last person mentioned in conversation"""
        for message in reversed(messages):
            content = message.get('content', '')
            if not content:
                continue
                
            # Look for name patterns
            import re
            name_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
            names = re.findall(name_pattern, content)
            if names:
                return names[-1]  # Return the last name mentioned
        
        return None
    
    def _extract_last_date_mention(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Extract the last date mentioned in conversation"""
        for message in reversed(messages):
            content = message.get('content', '')
            if not content:
                continue
                
            # Look for date patterns
            import re
            date_pattern = r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b'
            dates = re.findall(date_pattern, content)
            if dates:
                return dates[-1]  # Return the last date mentioned
        
        return None
    
    def get_email_context(self, query: str) -> Dict[str, Any]:
        """
        Get email-specific context using RAG
        Only use this for email-related queries
        
        Args:
            query: User query
            
        Returns:
            Email context dictionary
        """
        if self.rag_service:
            try:
                return self.rag_service.get_email_context(query)
            except Exception as e:
                logger.warning(f"Failed to get email context: {e}")
                return {}
        return {}
    
    def get_task_context(self, query: str) -> Dict[str, Any]:
        """
        Get task-specific context using RAG
        Only use this for task-related queries
        
        Args:
            query: User query
            
        Returns:
            Task context dictionary
        """
        # Note: Task RAG will be implemented when task indexing is added
        if self.rag_service:
            try:
                # For now, return empty but structured for future implementation
                logger.debug("Task context RAG not yet implemented")
                return {'tasks': [], 'similar_tasks': []}
            except Exception as e:
                logger.warning(f"Failed to get task context: {e}")
                return {}
        return {}
    
    def get_calendar_context(self, query: str) -> Dict[str, Any]:
        """
        Get calendar-specific context using RAG
        Only use this for calendar-related queries
        
        Args:
            query: User query
            
        Returns:
            Calendar context dictionary
        """
        # Note: Calendar RAG will be implemented when calendar event indexing is added
        if self.rag_service:
            try:
                # For now, return empty but structured for future implementation
                logger.debug("Calendar context RAG not yet implemented")
                return {'events': [], 'similar_events': []}
            except Exception as e:
                logger.warning(f"Failed to get calendar context: {e}")
                return {}
        return {}
    
    def get_notion_context(self, query: str) -> Dict[str, Any]:
        """
        Get Notion-specific context using RAG
        Only use this for Notion-related queries
        
        Args:
            query: User query
            
        Returns:
            Notion context dictionary with pages, databases, and related content
        """
        if self.rag_service:
            try:
                # Use RAG service to search for relevant Notion content
                if hasattr(self.rag_service, 'search'):
                    results = self.rag_service.search(query, top_k=5)
                    return {
                        'pages': results.get('pages', []),
                        'databases': results.get('databases', []),
                        'related_content': results.get('related_content', [])
                    }
                else:
                    logger.debug("Notion context RAG not yet fully implemented")
                    return {'pages': [], 'databases': [], 'related_content': []}
            except Exception as e:
                logger.warning(f"Failed to get Notion context: {e}")
                return {}
        return {}
    
    def extract_entities(self, query: str) -> Dict[str, Any]:
        """
        Extract entities from query (can be overridden by subclasses)
        
        Args:
            query: User query
            
        Returns:
            Dictionary of extracted entities
        """
        return {
            'original_query': query
        }
    
    def get_parser_info(self) -> Dict[str, Any]:
        """
        Get information about this parser
        
        Returns:
            Parser information dictionary with parser metadata and capabilities
        """
        supported_tools = self.get_supported_tools()
        return {
            'name': self.name,
            'has_rag': self.rag_service is not None,
            'has_memory': self.memory is not None,
            'type': self.__class__.__name__,
            'supported_tools': supported_tools,
            'domain': self._infer_domain_from_name()
        }
    
    def _infer_domain_from_name(self) -> str:
        """Infer domain from parser class name"""
        name_lower = self.name.lower()
        if 'email' in name_lower:
            return 'email'
        elif 'calendar' in name_lower:
            return 'calendar'
        elif 'task' in name_lower:
            return 'task'
        elif 'notion' in name_lower:
            return 'notion'
        return 'general'
    
    def emit_workflow_event(self, event_type: str, message: str, **kwargs):
        """
        Helper method to emit workflow events from parser handlers
        
        Args:
            event_type: Type of event ('executing', 'complete', 'error', 'progress')
            message: Human-readable message
            **kwargs: Additional data for the event
        """
        if not hasattr(self, 'workflow_emitter') or not self.workflow_emitter:
            return
        
        try:
            import asyncio
            # Try to get the running event loop
            try:
                loop = asyncio.get_running_loop()
                # If loop is running, schedule the coroutine as a task
                asyncio.create_task(self._emit_workflow_event_async(event_type, message, **kwargs))
            except RuntimeError:
                # No running loop - skip the event
                logger.debug(f"No running event loop for workflow event emission from parser")
        except Exception as e:
            logger.debug(f"Failed to emit workflow event from parser: {e}")
    
    async def _emit_workflow_event_async(self, event_type: str, message: str, **kwargs):
        """Async helper to emit workflow events"""
        try:
            from ..events.workflow_events import WorkflowEventType, WorkflowEvent
            
            # Map event_type strings to WorkflowEventType
            event_type_map = {
                'executing': WorkflowEventType.ACTION_EXECUTING,
                'complete': WorkflowEventType.ACTION_COMPLETE,
                'error': WorkflowEventType.ACTION_ERROR,
                'progress': WorkflowEventType.TOOL_CALL_PROGRESS,
                'planned': WorkflowEventType.ACTION_PLANNED
            }
            
            workflow_event_type = event_type_map.get(event_type, WorkflowEventType.ACTION_EXECUTING)
            
            event = WorkflowEvent(
                type=workflow_event_type,
                message=message,
                data={'parser': self.name, **kwargs}
            )
            
            await self.workflow_emitter.emit(event)
        except Exception as e:
            logger.debug(f"Error emitting workflow event from parser: {e}")
    
    def format_response_conversationally(self, response: str, query: Optional[str] = None) -> str:
        """
        Format tool response to be more conversational and natural
        
        This method should be called by parsers before returning results to users.
        It removes technical formatting and makes responses feel human-like.
        
        Args:
            response: Raw tool response
            query: Original user query (for context-aware formatting)
            
        Returns:
            Conversational, natural response
        """
        if not response:
            return response
        
        import re
        
        # CRITICAL: Remove technical tags and system messages (case-insensitive)
        response = re.sub(r'\[OK\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[ERROR\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[WARNING\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[INFO\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\[SEARCH\]\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'Gmail Search Results:\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'Email Search Results:\s*', '', response, flags=re.IGNORECASE)
        
        # Remove excessive markdown formatting
        response = re.sub(r'\*\*([^*]+)\*\*', r'\1', response)
        response = re.sub(r'\*([^*]+)\*', r'\1', response)
        response = re.sub(r'`([^`]+)`', r'\1', response)
        response = re.sub(r'#+\s*', '', response)  # Remove headers
        
        # Convert technical success messages to natural language
        response = re.sub(r'Successfully\s+', '', response, flags=re.IGNORECASE)
        response = re.sub(r'Created\s+task\s+in\s+Google\s+Tasks:\s*', 'I\'ve created a task: ', response, flags=re.IGNORECASE)
        response = re.sub(r'Task\s+created:\s*', 'I\'ve created a task: ', response, flags=re.IGNORECASE)
        response = re.sub(r'Scheduled\s+event:\s*', 'I\'ve scheduled: ', response, flags=re.IGNORECASE)
        response = re.sub(r'Email\s+sent\s+successfully', 'I\'ve sent that email', response, flags=re.IGNORECASE)
        response = re.sub(r'Notion\s+page\s+created:\s*', 'I\'ve created a Notion page: ', response, flags=re.IGNORECASE)
        response = re.sub(r'Page\s+created\s+in\s+Notion:\s*', 'I\'ve created a Notion page: ', response, flags=re.IGNORECASE)
        response = re.sub(r'Notion\s+page\s+updated:\s*', 'I\'ve updated the Notion page: ', response, flags=re.IGNORECASE)
        response = re.sub(r'Database\s+entry\s+created:\s*', 'I\'ve added an entry to the database: ', response, flags=re.IGNORECASE)
        
        # Handle "No results" messages more naturally
        if query:
            query_lower = query.lower()
            if "no " in response.lower() and ("email" in query_lower or "message" in query_lower):
                response = re.sub(r'No\s+emails?\s+found[\.]?', "I couldn't find any emails matching that.", response, flags=re.IGNORECASE)
            elif "no " in response.lower() and "task" in query_lower:
                response = re.sub(r'No\s+tasks?\s+found[\.]?', "I don't see any tasks matching that.", response, flags=re.IGNORECASE)
            elif "no " in response.lower() and ("meeting" in query_lower or "event" in query_lower):
                response = re.sub(r'No\s+events?\s+found[\.]?', "I couldn't find any calendar events matching that.", response, flags=re.IGNORECASE)
            elif "no " in response.lower() and ("notion" in query_lower or "page" in query_lower or "database" in query_lower):
                response = re.sub(r'No\s+(?:Notion\s+)?(?:pages?|databases?)\s+found[\.]?', "I couldn't find any Notion pages or databases matching that.", response, flags=re.IGNORECASE)
        
        # Convert numbered lists to natural sentences when there are few items
        bullet_count = response.count('\n-') + response.count('\n*') + response.count('\n1.')
        if bullet_count > 0 and bullet_count < 4:
            # Convert to natural sentences
            response = re.sub(r'\n[-*]\s+', ' ', response)
            response = re.sub(r'\n\d+\.\s+', ' ', response)
            response = re.sub(r'\s+', ' ', response)
        
        # Clean up excessive whitespace
        response = re.sub(r'\n{3,}', '\n\n', response)
        response = re.sub(r' {2,}', ' ', response)
        
        # Ensure response starts naturally (not with technical terms)
        if response.startswith(('Error:', 'Warning:', 'Failed:', 'Success:')):
            response = re.sub(r'^(Error|Warning|Failed|Success):\s*', '', response, flags=re.IGNORECASE)
        
        return response.strip()


# SHARED SEMANTIC PATTERN MATCHER USED BY ALL PARSERS
class SemanticPatternMatcher:
    """
    Shared semantic pattern matcher for all parsers.
    
    Uses Gemini embeddings when available (more accurate, 768D, cached),
    falls back to sentence-transformers for speed and reliability (384D).
    
    This eliminates code duplication - all parsers can use this shared implementation
    with their own pattern sets.
    """
    
    def __init__(self, config=None, embedding_provider=None, patterns: Optional[Dict[str, List[str]]] = None):
        """
        Initialize semantic pattern matcher.
        
        Args:
            config: Optional Config object (for Gemini embeddings)
            embedding_provider: Optional EmbeddingProvider instance (reuse existing)
            patterns: Dictionary mapping intent names to pattern lists
        """
        self.config = config
        self.embedding_provider = embedding_provider
        self.use_gemini = False
        self.model = None
        self.pattern_embeddings = {}
        self.patterns = patterns or {}
        
        # Try Gemini embeddings first (more accurate, 768D, cached)
        if config and config.ai and config.ai.api_key:
            try:
                from ...ai.rag.core.embedding_provider import create_embedding_provider
                from ...utils.config import RAGConfig as RAGConfigType
                
                rag_config = RAGConfigType(
                    embedding_provider="gemini",
                    embedding_model="models/embedding-001"  # gemini-embedding-001 (Google API format)
                )
                self.embedding_provider = create_embedding_provider(config, rag_config)
                
                from ...ai.rag.core.embedding_provider import GeminiEmbeddingProvider
                if isinstance(self.embedding_provider, GeminiEmbeddingProvider):
                    self.use_gemini = True
                    logger.debug("Using gemini-embedding-001 for semantic matching (768D, cached)")
            except Exception as e:
                logger.debug(f"Gemini embeddings not available: {e}, falling back to sentence-transformers")
        
        # Fallback to sentence-transformers (faster, local, 384D)
        if not self.use_gemini and SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.debug("Using sentence-transformers (all-MiniLM-L6-v2) for semantic matching (384D)")
            except Exception as e:
                logger.warning(f"Failed to initialize sentence-transformers: {e}")
        
        # Load pattern embeddings if patterns provided
        if self.patterns:
            self.pattern_embeddings = self._load_pattern_embeddings()
    
    def _load_pattern_embeddings(self) -> Dict[str, np.ndarray]:
        """Pre-compute embeddings for all patterns."""
        embeddings = {}
        
        if self.use_gemini and self.embedding_provider:
            try:
                for intent, pattern_list in self.patterns.items():
                    if pattern_list:
                        pattern_embeddings = self.embedding_provider.encode_batch(pattern_list)
                        embeddings[intent] = np.array(pattern_embeddings)
                        logger.debug(f"Loaded {len(pattern_list)} Gemini embeddings for '{intent}' intent")
            except Exception as e:
                logger.warning(f"Failed to load Gemini pattern embeddings: {e}")
                return {}
        elif self.model:
            try:
                for intent, pattern_list in self.patterns.items():
                    if pattern_list:
                        embeddings[intent] = self.model.encode(pattern_list)
                        logger.debug(f"Loaded {len(pattern_list)} sentence-transformer embeddings for '{intent}' intent")
            except Exception as e:
                logger.warning(f"Failed to encode patterns: {e}")
                return {}
        else:
            logger.warning("No embedding provider available for pattern matching")
            return {}
        
        return embeddings
    
    def match_semantic(self, query: str, threshold: float = DEFAULT_SEMANTIC_THRESHOLD) -> Optional[str]:
        """
        Match query to patterns using semantic similarity.
        
        Args:
            query: User query
            threshold: Minimum similarity score (0.0-1.0)
            
        Returns:
            Intent if match found above threshold, None otherwise
        """
        if not self.pattern_embeddings:
            return None
        
        try:
            # Get query embedding
            if self.use_gemini and self.embedding_provider:
                query_embedding = np.array(self.embedding_provider.encode_query(query))
                effective_threshold = threshold * GEMINI_THRESHOLD_MULTIPLIER
            elif self.model:
                query_embedding = self.model.encode([query])[0]
                effective_threshold = threshold
            else:
                return None
            
            best_match = None
            best_score = 0.0
            
            for intent, pattern_embeddings in self.pattern_embeddings.items():
                if len(pattern_embeddings) == 0:
                    continue
                
                # Use safe cosine similarity that handles edge cases
                similarities = safe_cosine_similarity(query_embedding, pattern_embeddings)[0]
                max_similarity = float(np.max(similarities))
                
                if max_similarity > best_score:
                    best_score = max_similarity
                    best_match = intent
            
            if best_score >= effective_threshold:
                provider = "Gemini" if self.use_gemini else "sentence-transformers"
                logger.debug(f"Semantic match ({provider}): '{query}' → {best_match} (score: {best_score:.2f})")
                return best_match
            
            return None
        except Exception as e:
            logger.warning(f"Semantic matching failed: {e}")
            return None


# ============================================================================
# COMMON NLP UTILITIES INITIALIZATION
# ============================================================================

def initialize_nlp_utilities(config) -> Dict[str, Any]:
    """
    Initialize common NLP utilities used by all parsers.
    
    This eliminates duplicate initialization code across parsers.
    
    Args:
        config: Configuration object
        
    Returns:
        Dictionary with 'classifier', 'date_parser', 'llm_client' keys
    """
    utilities = {
        'classifier': None,
        'date_parser': None,
        'llm_client': None
    }
    
    if not config:
        return utilities
    
    try:
        from ...ai.query_classifier import QueryClassifier
        from ...utils import FlexibleDateParser
        from ...ai.llm_factory import LLMFactory
        
        utilities['classifier'] = QueryClassifier(config)
        utilities['date_parser'] = FlexibleDateParser(config)
        
        try:
            utilities['llm_client'] = LLMFactory.get_llm_for_provider(
                config, 
                temperature=DEFAULT_LLM_TEMPERATURE, 
                max_tokens=DEFAULT_LLM_MAX_TOKENS
            )
            logger.debug("LLM client initialized for conversational responses")
        except Exception as e:
            logger.debug(f"LLM not available: {e}")
    except Exception as e:
        logger.warning(f"Failed to initialize NLP utilities: {e}")
    
    return utilities