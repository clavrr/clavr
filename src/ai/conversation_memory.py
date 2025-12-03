"""
Conversation Memory Management

Async conversation memory for use with FastAPI and async workflows.
Stores and retrieves conversation history for context-aware responses without blocking.

Features:
- Async/await-based API for non-blocking I/O
- Message storage with metadata (intent, entities, confidence)
- Context retrieval for conversation continuity
- Entity extraction for reference resolution
- Automatic cleanup of old messages
- RAG-powered semantic search over conversation history
- Cross-session context retrieval
- Optimized for FastAPI async route handlers
- SQLAlchemy 2.0 async query patterns (select() instead of query())
- RAG calls wrapped in asyncio.to_thread() (RAG engine is sync)
"""
import asyncio
import json
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, func

from ..database.models import ConversationMessage
from ..utils.logger import setup_logger
from .memory_constants import (
    LOG_OK, LOG_ERROR, LOG_INFO, LOG_WARNING,
    ROLE_USER, ROLE_ASSISTANT, VALID_ROLES,
    DEFAULT_MESSAGE_LIMIT, DEFAULT_MAX_AGE_MINUTES, DEFAULT_CLEANUP_DAYS,
    DEFAULT_CONTEXT_LIMIT, SESSION_ID_DISPLAY_LENGTH, ENTITY_TYPES
)

# Type checking import to avoid circular dependencies
if TYPE_CHECKING:
    from .rag import RAGEngine

logger = setup_logger(__name__)


class ConversationMemory:
    """
    Manages conversation history with context-aware retrieval (async).
    
    Provides:
    - Short-term memory (recent messages in session)
    - Context tracking (entities, intents)
    - Easy retrieval for query routing and context building
    - Semantic search over conversation history (RAG-powered)
    - Cross-session context retrieval
    - **Non-blocking async operations** for high concurrency
    
    Example:
        # Basic usage (without RAG)
        from src.database import get_async_db
        
        async def my_handler(db: AsyncSession = Depends(get_async_db)):
            memory = ConversationMemory(db)
            await memory.add_message(user_id=1, session_id="session_123", role="user", content="Hello")
            messages = await memory.get_recent_messages(user_id=1, session_id="session_123")
        
        # With RAG for semantic search (auto-initialized)
        from api.dependencies import AppState
        
        async def my_handler(db: AsyncSession = Depends(get_async_db)):
            # RAG engine is auto-initialized from AppState if available
            memory = ConversationMemory(db)
            
            # Find similar conversations
            results = await memory.search_similar_conversations("project deadlines", user_id=1)
            
            # Get formatted context for LLM
            context = await memory.format_context_for_llm(user_id=1, session_id="session_123")
            
            # Get conversation summary
            summary = await memory.get_conversation_summary(user_id=1, session_id="session_123")
    """
    
    def __init__(self, db: AsyncSession, rag_engine: Optional['RAGEngine'] = None, auto_init_rag: bool = True):
        """
        Initialize async conversation memory manager.
        
        Args:
            db: SQLAlchemy async database session
            rag_engine: Optional RAG engine for semantic search capabilities
            auto_init_rag: If True and rag_engine is None, try to get RAGEngine from AppState
        """
        self.db = db
        
        # Auto-initialize RAG if not provided and auto_init_rag is True
        if rag_engine is None and auto_init_rag:
            try:
                from api.dependencies import AppState
                rag_engine = AppState.get_rag_engine()
                logger.debug(f"{LOG_OK} Auto-initialized RAG engine from AppState")
            except Exception as e:
                logger.debug(f"{LOG_INFO} Could not auto-initialize RAG engine: {e}")
        
        self.rag = rag_engine
        self._rag_enabled = rag_engine is not None
        
        if self._rag_enabled:
            logger.info(f"{LOG_OK} ConversationMemory initialized with RAG support (semantic search enabled)")
        else:
            logger.info(f"{LOG_INFO} ConversationMemory initialized without RAG (semantic search disabled)")
    
    async def add_message(
        self,
        user_id: int,
        session_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        entities: Optional[Dict[str, Any]] = None,
        confidence: Optional[float] = None
    ) -> Optional[int]:
        """
        Add a message to conversation history (async).
        
        **Automatically indexes user messages in RAG if enabled.**
        
        Args:
            user_id: User ID
            session_id: Session ID (for grouping conversations)
            role: 'user' or 'assistant'
            content: Message content
            intent: Detected intent (for assistant messages)
            entities: Extracted entities (for user messages)
            confidence: Confidence score (0.0-1.0) for routing
            
        Returns:
            Message ID if successful, None on error
            
        Raises:
            ValueError: If role is invalid or content is empty
            Exception: If database operation fails
        """
        self._validate_message_inputs(role, content)
        
        try:
            message = ConversationMessage(
                user_id=user_id,
                session_id=session_id,
                role=role,
                content=content.strip(),
                intent=intent,
                entities=entities or {},
                confidence=self._format_confidence(confidence)
            )
            
            self.db.add(message)
            await self.db.commit()
            await self.db.refresh(message)
            
            session_display = self._format_session_id(session_id)
            logger.info(
                f"{LOG_OK} Saved {role} message (id={message.id}) for user {user_id} "
                f"in session {session_display} (intent={intent})"
            )
            
            # Index in RAG if enabled (both user and assistant messages for better context)
            if self._rag_enabled:
                await self._index_message_in_rag(message)
            
            return message.id
            
        except Exception as e:
            await self.db.rollback()
            logger.error(
                f"{LOG_ERROR} Failed to save message: {e}",
                exc_info=True,
                extra={
                    'user_id': user_id,
                    'session_id': session_id,
                    'role': role,
                    'intent': intent,
                    'content_length': len(content) if content else 0
                }
            )
            raise
    
    async def get_recent_messages(
        self,
        user_id: int,
        session_id: str,
        limit: int = DEFAULT_MESSAGE_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        Get recent messages for context (chronological order, oldest first) - async.
        
        Args:
            user_id: User ID
            session_id: Session ID
            limit: Maximum number of messages to return (default: 10)
            
        Returns:
            List of message dictionaries with keys: role, content, intent, entities, timestamp
            Returns empty list on error
        """
        try:
            messages = await self._query_messages(user_id, session_id, limit=limit)
            return [self._format_message(msg) for msg in reversed(messages)]
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Failed to retrieve messages: {e}",
                exc_info=True,
                extra={'user_id': user_id, 'session_id': session_id, 'limit': limit}
            )
            return []
    
    async def get_recent_context(
        self,
        user_id: int,
        session_id: str,
        max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES
    ) -> Dict[str, Any]:
        """
        Get recent context (entities, intents) for reference resolution - async.
        
        Useful for resolving pronouns ("it", "that") and maintaining conversation continuity.
        
        Args:
            user_id: User ID
            session_id: Session ID
            max_age_minutes: Only consider messages from last N minutes (default: 30)
            
        Returns:
            Dictionary with keys:
            - recent_entities: Dict[str, List] grouped by entity type
            - recent_intents: List[str] of recent intents
            - message_count: int number of messages considered
            Returns empty structure on error
        """
        try:
            since = datetime.utcnow() - timedelta(minutes=max_age_minutes)
            messages = await self._query_messages(user_id, session_id, limit=DEFAULT_CONTEXT_LIMIT, since=since)
            return self._extract_context_from_messages(messages)
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Failed to get context: {e}",
                exc_info=True,
                extra={'user_id': user_id, 'session_id': session_id, 'max_age_minutes': max_age_minutes}
            )
            return self._empty_context()
    
    async def clear_old_messages(
        self,
        days: int = DEFAULT_CLEANUP_DAYS
    ) -> int:
        """
        Clean up old messages (for privacy/storage management) - async.
        
        Args:
            days: Delete messages older than N days (default: 30)
            
        Returns:
            Number of messages deleted (0 on error)
        """
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            stmt = delete(ConversationMessage).where(
                ConversationMessage.timestamp < cutoff
            )
            
            result = await self.db.execute(stmt)
            await self.db.commit()
            
            deleted = result.rowcount
            
            logger.info(f"{LOG_INFO} Deleted {deleted} old conversation messages (older than {days} days)")
            return deleted
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Failed to clean up messages: {e}",
                exc_info=True,
                extra={'days': days}
            )
            await self.db.rollback()
            return 0
    
    async def get_message_count(
        self,
        user_id: int,
        session_id: Optional[str] = None
    ) -> int:
        """
        Get count of messages for a user (optionally filtered by session) - async.
        
        Args:
            user_id: User ID
            session_id: Optional session ID to filter by
            
        Returns:
            Number of messages (0 on error)
        """
        try:
            conditions = [ConversationMessage.user_id == user_id]
            
            if session_id:
                conditions.append(ConversationMessage.session_id == session_id)
            
            stmt = select(func.count()).select_from(ConversationMessage).where(and_(*conditions))
            
            result = await self.db.execute(stmt)
            return result.scalar_one()
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Failed to get message count: {e}",
                exc_info=True,
                extra={'user_id': user_id, 'session_id': session_id}
            )
            return 0
    
    # RAG-Powered Semantic Search Methods 
    
    async def search_similar_conversations(
        self,
        query: str,
        user_id: int,
        k: int = 5,
        min_score: float = 0.7,
        session_id_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Find past conversation messages semantically similar to query - async.
        
        **Requires RAG engine** - Use semantic similarity instead of keyword matching.
        
        Use Cases:
        - "What did we discuss about X?"
        - "Find all conversations about project Y"
        - Reference resolution: "Continue our chat about..."
        
        Args:
            query: Search query
            user_id: User ID to filter by
            k: Number of results to return
            min_score: Minimum relevance score (0-1)
            session_id_filter: Optional session ID to filter by
            
        Returns:
            List of messages with relevance scores, sorted by relevance
            Returns empty list if RAG not enabled
            
        Raises:
            ValueError: If RAG is not enabled
            
        Example:
            results = await memory.search_similar_conversations(
                query="project deadlines",
                user_id=1,
                k=5,
                min_score=0.7
            )
            for r in results:
                print(f"Session {r['session_id']}: {r['content']} (score: {r['relevance_score']})")
        """
        if not self._rag_enabled:
            raise ValueError(
                "Semantic search requires RAG engine. "
                "Initialize ConversationMemory with rag_engine parameter."
            )
        
        try:
            # Build metadata filters
            filters = {
                "type": "conversation_message",
                "user_id": user_id
            }
            
            if session_id_filter:
                filters["session_id"] = session_id_filter
            
            # Search in RAG (wrap sync call in thread to avoid blocking)
            results = await asyncio.to_thread(
                self.rag.search,
                query=query,
                k=k * 2,  # Get 2x results for min_score filtering
                rerank=True,
                filters=filters
            )
            
            # Filter by min_score and format
            formatted_results = []
            for result in results:
                score = result.get('rerank_score', result.get('score', 0))
                if score >= min_score:
                    metadata = result.get('metadata', {})
                    formatted_results.append({
                        'message_id': metadata.get('message_id'),
                        'content': result.get('content', ''),
                        'session_id': metadata.get('session_id'),
                        'intent': metadata.get('intent'),
                        'timestamp': metadata.get('timestamp'),
                        'relevance_score': score
                    })
            
            # Limit to k results
            formatted_results = formatted_results[:k]
            
            logger.info(
                f"{LOG_OK} Semantic search found {len(formatted_results)} relevant conversations "
                f"(query: '{query[:50]}...', min_score: {min_score})"
            )
            
            return formatted_results
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Semantic search failed: {e}",
                exc_info=True,
                extra={'query': query, 'user_id': user_id, 'k': k}
            )
            return []
    
    async def get_relevant_context_from_history(
        self,
        current_query: str,
        user_id: int,
        exclude_session_id: Optional[str] = None,
        k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Find relevant messages from user's conversation history (all sessions) - async.
        
        **Cross-session context retrieval** - Continues conversations across devices/sessions.
        
        Use Case:
            User on mobile: "Continue our discussion about Q4"
            Agent searches desktop session history and finds context
        
        Args:
            current_query: Current user query
            user_id: User ID
            exclude_session_id: Don't include messages from this session
            k: Number of relevant messages to return
        
        Returns:
            List of messages with relevance scores from OTHER sessions
            Returns empty list if RAG not enabled (with warning)
            
        Example:
            context = await memory.get_relevant_context_from_history(
                current_query="When is the Q4 report due?",
                user_id=1,
                exclude_session_id="mobile_session",
                k=3
            )
            for msg in context:
                print(f"From {msg['session_id']}: {msg['content']}")
        """
        if not self._rag_enabled:
            logger.warning(
                f"{LOG_WARNING} Cross-session context requires RAG engine - returning empty list"
            )
            return []
        
        try:
            # Search all user's conversations
            all_results = await self.search_similar_conversations(
                query=current_query,
                user_id=user_id,
                k=k * 3,  # Get more to filter by session
                min_score=0.6  # Lower threshold for cross-session
            )
            
            # Filter out current session
            other_session_results = []
            for result in all_results:
                if result['session_id'] != exclude_session_id:
                    result['from_other_session'] = True
                    other_session_results.append(result)
            
            # Limit to k results
            other_session_results = other_session_results[:k]
            
            if other_session_results:
                logger.info(
                    f"{LOG_OK} Found {len(other_session_results)} relevant messages "
                    f"from other sessions (excluded: {exclude_session_id})"
                )
            else:
                logger.debug(
                    f"{LOG_INFO} No relevant cross-session context found "
                    f"for query: '{current_query[:50]}...'"
                )
            
            return other_session_results
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Cross-session context retrieval failed: {e}",
                exc_info=True,
                extra={'query': current_query, 'user_id': user_id, 'exclude_session': exclude_session_id}
            )
            return []
    
    async def get_conversation_summary(
        self,
        user_id: int,
        session_id: str,
        max_messages: int = 20
    ) -> Dict[str, Any]:
        """
        Get a summary of the conversation for context building - async.
        
        Provides structured summary with:
        - Key topics discussed
        - Entities mentioned
        - Intents detected
        - Message count and time span
        
        Args:
            user_id: User ID
            session_id: Session ID
            max_messages: Maximum messages to analyze for summary
            
        Returns:
            Dictionary with summary information:
            - topics: List[str] of key topics
            - entities: Dict[str, List] of entities by type
            - intents: List[str] of detected intents
            - message_count: int
            - time_span: Dict with 'start' and 'end' timestamps
        """
        try:
            messages = await self._query_messages(user_id, session_id, limit=max_messages)
            
            if not messages:
                return {
                    'topics': [],
                    'entities': {entity_type: [] for entity_type in ENTITY_TYPES},
                    'intents': [],
                    'message_count': 0,
                    'time_span': None
                }
            
            # Extract information
            all_entities = {entity_type: [] for entity_type in ENTITY_TYPES}
            intents = []
            timestamps = []
            
            for msg in messages:
                if msg.intent:
                    intents.append(msg.intent)
                if msg.entities:
                    self._extract_entities_from_message(msg.entities, all_entities)
                if msg.timestamp:
                    timestamps.append(msg.timestamp)
            
            # Extract topics from message content (simple keyword extraction)
            topics = self._extract_topics([msg.content for msg in messages])
            
            time_span = None
            if timestamps:
                time_span = {
                    'start': min(timestamps).isoformat(),
                    'end': max(timestamps).isoformat()
                }
            
            return {
                'topics': topics,
                'entities': all_entities,
                'intents': list(set(intents)),  # Unique intents
                'message_count': len(messages),
                'time_span': time_span
            }
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Failed to get conversation summary: {e}",
                exc_info=True,
                extra={'user_id': user_id, 'session_id': session_id}
            )
            return {
                'topics': [],
                'entities': {entity_type: [] for entity_type in ENTITY_TYPES},
                'intents': [],
                'message_count': 0,
                'time_span': None
            }
    
    async def format_context_for_llm(
        self,
        user_id: int,
        session_id: str,
        include_summary: bool = True,
        include_recent_messages: bool = True,
        max_messages: int = 10
    ) -> str:
        """
        Format conversation context as a string for LLM consumption - async.
        
        Creates a formatted string that can be included in LLM prompts
        to provide conversation context.
        
        Args:
            user_id: User ID
            session_id: Session ID
            include_summary: Whether to include conversation summary
            include_recent_messages: Whether to include recent messages
            max_messages: Maximum number of recent messages to include
            
        Returns:
            Formatted context string
        """
        try:
            context_parts = []
            
            if include_summary:
                summary = await self.get_conversation_summary(user_id, session_id, max_messages=max_messages)
                if summary['message_count'] > 0:
                    context_parts.append("=== Conversation Summary ===")
                    if summary['topics']:
                        context_parts.append(f"Topics: {', '.join(summary['topics'][:5])}")
                    if summary['intents']:
                        context_parts.append(f"Intents: {', '.join(summary['intents'])}")
                    context_parts.append(f"Messages: {summary['message_count']}")
                    context_parts.append("")
            
            if include_recent_messages:
                messages = await self.get_recent_messages(user_id, session_id, limit=max_messages)
                if messages:
                    context_parts.append("=== Recent Messages ===")
                    for msg in messages[-max_messages:]:  # Get last N messages
                        role_label = "User" if msg['role'] == ROLE_USER else "Assistant"
                        content_preview = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
                        context_parts.append(f"{role_label}: {content_preview}")
                    context_parts.append("")
            
            return "\n".join(context_parts) if context_parts else ""
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Failed to format context for LLM: {e}",
                exc_info=True,
                extra={'user_id': user_id, 'session_id': session_id}
            )
            return ""
    
    async def add_messages_batch(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Optional[int]]:
        """
        Add multiple messages in a batch operation - async.
        
        More efficient than calling add_message() multiple times.
        
        Args:
            messages: List of message dictionaries with keys:
                - user_id: int
                - session_id: str
                - role: str
                - content: str
                - intent: Optional[str]
                - entities: Optional[Dict]
                - confidence: Optional[float]
                
        Returns:
            List of message IDs (None for failed messages)
        """
        message_ids = []
        
        try:
            for msg_data in messages:
                try:
                    msg_id = await self.add_message(
                        user_id=msg_data['user_id'],
                        session_id=msg_data['session_id'],
                        role=msg_data['role'],
                        content=msg_data['content'],
                        intent=msg_data.get('intent'),
                        entities=msg_data.get('entities'),
                        confidence=msg_data.get('confidence')
                    )
                    message_ids.append(msg_id)
                except Exception as e:
                    logger.warning(f"Failed to add message in batch: {e}")
                    message_ids.append(None)
            
            logger.info(f"{LOG_OK} Added {len([m for m in message_ids if m is not None])} messages in batch")
            return message_ids
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Batch message addition failed: {e}",
                exc_info=True
            )
            return message_ids
    
    # Helper methods (private)
    
    def _validate_message_inputs(self, role: str, content: str) -> None:
        """Validate message inputs before storage."""
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {VALID_ROLES}")
        
        if not content or not content.strip():
            raise ValueError("Message content cannot be empty")
    
    def _format_confidence(self, confidence: Optional[float]) -> Optional[str]:
        """Format confidence score for storage (as string)."""
        return str(confidence) if confidence is not None else None
    
    def _format_session_id(self, session_id: str) -> str:
        """Format session ID for display (truncate if too long)."""
        if session_id and len(session_id) > SESSION_ID_DISPLAY_LENGTH:
            return session_id[:SESSION_ID_DISPLAY_LENGTH] + "..."
        return session_id
    
    async def _query_messages(
        self,
        user_id: int,
        session_id: str,
        limit: int = DEFAULT_MESSAGE_LIMIT,
        since: Optional[datetime] = None
    ) -> List[ConversationMessage]:
        """
        Query messages from database (internal helper) - async.
        
        Args:
            user_id: User ID
            session_id: Session ID
            limit: Maximum number of messages
            since: Optional timestamp filter (only messages after this time)
            
        Returns:
            List of ConversationMessage objects (newest first)
        """
        conditions = [
            ConversationMessage.user_id == user_id,
            ConversationMessage.session_id == session_id
        ]
        
        if since:
            conditions.append(ConversationMessage.timestamp >= since)
        
        stmt = select(ConversationMessage).where(
            and_(*conditions)
        ).order_by(ConversationMessage.timestamp.desc()).limit(limit)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    def _format_message(self, msg: ConversationMessage) -> Dict[str, Any]:
        """Format a ConversationMessage object into a dictionary."""
        return {
            'role': msg.role,
            'content': msg.content,
            'intent': msg.intent,
            'entities': msg.entities or {},
            'timestamp': msg.timestamp.isoformat() if msg.timestamp else None
        }
    
    def _extract_context_from_messages(self, messages: List[ConversationMessage]) -> Dict[str, Any]:
        """
        Extract context (entities and intents) from a list of messages.
        
        Args:
            messages: List of ConversationMessage objects
            
        Returns:
            Dictionary with recent_entities, recent_intents, and message_count
        """
        all_entities = {entity_type: [] for entity_type in ENTITY_TYPES}
        recent_intents = []
        
        for msg in messages:
            if msg.intent:
                recent_intents.append(msg.intent)
            
            if msg.entities:
                self._extract_entities_from_message(msg.entities, all_entities)
        
        return {
            'recent_entities': all_entities,
            'recent_intents': recent_intents,
            'message_count': len(messages)
        }
    
    def _extract_entities_from_message(
        self,
        entities: Dict[str, Any],
        all_entities: Dict[str, List[Any]]
    ) -> None:
        """
        Extract entities from a message's entity dictionary.
        
        Args:
            entities: Entity dictionary from message
            all_entities: Dictionary to accumulate entities into (modified in place)
        """
        for entity_type in ENTITY_TYPES:
            if entity_type in entities:
                entity_value = entities[entity_type]
                if isinstance(entity_value, list):
                    all_entities[entity_type].extend(entity_value)
                elif entity_value:  # Handle single values
                    all_entities[entity_type].append(entity_value)
    
    def _empty_context(self) -> Dict[str, Any]:
        """Return empty context structure."""
        return {
            'recent_entities': {entity_type: [] for entity_type in ENTITY_TYPES},
            'recent_intents': [],
            'message_count': 0
        }
    
    def _extract_topics(self, messages: List[str], max_topics: int = 5) -> List[str]:
        """
        Extract key topics from message content.
        
        Simple keyword-based topic extraction. Could be enhanced with LLM.
        
        Args:
            messages: List of message content strings
            max_topics: Maximum number of topics to return
            
        Returns:
            List of topic strings
        """
        import re
        from collections import Counter
        
        # Common stopwords to ignore
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have',
            'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could',
            'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those',
            'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them'
        }
        
        # Extract words (3+ characters, not stopwords)
        words = []
        for msg in messages:
            msg_words = re.findall(r'\b[a-z]{3,}\b', msg.lower())
            words.extend([w for w in msg_words if w not in stopwords])
        
        # Count and return most common
        word_counts = Counter(words)
        topics = [word for word, count in word_counts.most_common(max_topics)]
        
        return topics
    
    async def _index_message_in_rag(self, message: ConversationMessage) -> None:
        """
        Index a message in RAG vector store for semantic search - async.
        
        Wraps the synchronous RAG.index_document() call in asyncio.to_thread()
        to avoid blocking the async event loop.
        
        Args:
            message: ConversationMessage object to index
        """
        try:
            doc_id = f"conv_msg_{message.id}"
            
            # Build metadata, excluding None values (Pinecone doesn't accept None)
            metadata = {
                "type": "conversation_message",
                "user_id": message.user_id,
                "session_id": message.session_id,
                "message_id": message.id,
                "role": message.role,
            }
            
            # Add optional fields only if they have values
            if message.intent:
                metadata["intent"] = message.intent
            if message.timestamp:
                metadata["timestamp"] = message.timestamp.isoformat()
            
            # Pinecone metadata must be string, number, boolean, or list of strings
            # Convert dict to JSON string, exclude if None/empty dict
            if message.entities and isinstance(message.entities, (str, int, float, bool, list, dict)):
                if isinstance(message.entities, dict) and message.entities:
                    metadata["entities"] = json.dumps(message.entities)
                elif isinstance(message.entities, (str, int, float, bool, list)):
                    metadata["entities"] = message.entities
            
            # Wrap sync RAG call in thread to avoid blocking
            await asyncio.to_thread(
                self.rag.index_document,
                doc_id=doc_id,
                content=message.content,
                metadata=metadata
            )
            
            logger.debug(
                f"{LOG_OK} Indexed message {message.id} in RAG (doc_id={doc_id}, "
                f"user={message.user_id}, session={message.session_id[:20]}...)"
            )
            
        except Exception as e:
            # Don't fail the whole operation if RAG indexing fails
            logger.warning(
                f"{LOG_WARNING} Failed to index message {message.id} in RAG: {e}. "
                "Message saved to database but not searchable via semantic search."
            )
