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
import re
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, func, or_

from ..database.models import ConversationMessage
from ..utils.logger import setup_logger
from .rag.query.rules import SEARCH_STOPWORDS
from .memory.semantic_memory import SemanticMemory
from .memory.extractor import FactExtractor
from .memory_constants import (
    LOG_OK, LOG_ERROR, LOG_INFO, LOG_WARNING,
    ROLE_USER, ROLE_ASSISTANT, VALID_ROLES,
    DEFAULT_MESSAGE_LIMIT, DEFAULT_MAX_AGE_MINUTES, DEFAULT_CLEANUP_DAYS,
    DEFAULT_CONTEXT_LIMIT, SESSION_ID_DISPLAY_LENGTH, ENTITY_TYPES,
    DEFAULT_CONVERSATION_LIST_LIMIT, DEFAULT_CONVERSATION_MESSAGES_LIMIT,
    PREVIEW_MESSAGE_LENGTH, DEFAULT_PREVIEW_TEXT
)



# Type checking import to avoid circular dependencies
if TYPE_CHECKING:
    from .rag import RAGEngine

from ..database import get_async_db_context
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
                # CRITICAL: Use dedicated conversation RAG engine to prevent polluting email-knowledge
                rag_engine = AppState.get_conversation_rag_engine()
                logger.debug(f"{LOG_OK} Auto-initialized Conversation RAG engine from AppState")
            except Exception as e:
                logger.debug(f"{LOG_INFO} Could not auto-initialize RAG engine: {e}")
        
        self.rag = rag_engine
        self._rag_enabled = rag_engine is not None
        
        if self._rag_enabled:
            logger.info(f"{LOG_OK} ConversationMemory initialized with RAG support (semantic search enabled)")
        else:
            logger.info(f"{LOG_INFO} ConversationMemory initialized without RAG (semantic search disabled)")

        # Initialize Semantic Memory (Fact Store)
        self.semantic = SemanticMemory(db, rag_engine)
        self.extractor = FactExtractor()
    
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
            # Ensure clean transaction state before proceeding
            # Rollback any existing transaction to handle cases where a previous 
            # operation failed and left the session in an aborted/failed state.
            # This is safe because:
            # 1. If there's no active transaction, rollback is a no-op
            # 2. If there's a failed transaction, this clears it
            # 3. Each add_message should be its own atomic transaction anyway
            try:
                await self.db.rollback()
            except Exception as e:
                logger.debug(f"{LOG_INFO} Database rollback before message add failed: {e}")
                pass  # Ignore errors - rollback is best-effort cleanup
            
            # --- DEDUPLICATION GUARD (in-memory, session-scoped) ---
            # Prevents the same message from being saved multiple times within
            # the SAME session (e.g. ChatService + MemoryOrchestrator both saving).
            # Content is Fernet-encrypted (non-deterministic), so SQL equality
            # won't work — we use an in-memory hash instead.
            # NOTE: session_id IS included so cross-session saves are NOT blocked.
            # Cross-session duplicates (frontend vs backend creating separate sessions)
            # are handled at the list_conversations level instead.
            import hashlib, re as _re
            now = datetime.utcnow()
            
            # Normalize: strip trailing separators, whitespace, and "---" blocks
            normalized = _re.sub(r'[\s\-]+$', '', content.strip())
            content_hash = hashlib.sha256(
                f"{user_id}:{session_id}:{role}:{normalized}".encode()
            ).hexdigest()
            
            # Role+session proximity key
            role_key = f"{user_id}:{session_id}:{role}"
            
            # Lazy-init class-level dedup caches
            if not hasattr(ConversationMemory, '_dedup_cache'):
                ConversationMemory._dedup_cache = {}       # content hash → timestamp
                ConversationMemory._role_dedup_cache = {}   # role key → timestamp
            
            # Check content hash (same content in same session within 60s)
            last_seen = ConversationMemory._dedup_cache.get(content_hash)
            if last_seen and (now - last_seen).total_seconds() < 60:
                logger.info(
                    f"{LOG_INFO} Dedup: skipping duplicate {role} message (content hash match)"
                )
                return None
            
            # Check role+session proximity (same role in same session within 15s)
            role_last_seen = ConversationMemory._role_dedup_cache.get(role_key)
            if role_last_seen and (now - role_last_seen).total_seconds() < 15:
                logger.info(
                    f"{LOG_INFO} Dedup: skipping duplicate {role} message (same role in session within 15s)"
                )
                return None
            
            # Record in both caches
            ConversationMemory._dedup_cache[content_hash] = now
            ConversationMemory._role_dedup_cache[role_key] = now
            
            # Periodic cleanup
            if len(ConversationMemory._dedup_cache) > 200:
                cutoff = now - timedelta(seconds=120)
                ConversationMemory._dedup_cache = {
                    k: v for k, v in ConversationMemory._dedup_cache.items() if v > cutoff
                }
                ConversationMemory._role_dedup_cache = {
                    k: v for k, v in ConversationMemory._role_dedup_cache.items() if v > cutoff
                }
            
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

            # Background task: Fact Extraction (Observer)
            # Only analyze if user message, to capture user statements
            if role == ROLE_USER:
                 # Pass recent context + this message
                 # We construct a mini-history list for the extractor
                 # Ideally we should fetch recent history, but for efficiency we just pass this one 
                 # and maybe the previous assistant message if possible.
                 # Actually, let's just trigger it. The extractor can fetch what it needs or accept a list.
                 # Our extractor accepts 'messages'. Let's build a small list.
                 # WARNING: fetching history here might block? No, it's async.
                 # Better: Fire and forget.
                 asyncio.create_task(self._run_extraction(user_id, role, content))
            
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
        Tiered conversation retention: summarize → then delete raw messages.
        
        Tier architecture:
        - Hot (0-30 days): Full messages in ConversationMessage
        - Warm (30-180 days): Summarized into ConversationSummary (1 row per session)
        - Cold (180+ days): Only Qdrant vectors survive for semantic recall
        
        Args:
            days: Summarize and delete messages older than N days (default: 30)
            
        Returns:
            Number of messages deleted (0 on error)
        """
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            # 1. Find sessions with messages about to be deleted
            from sqlalchemy import func, distinct
            
            session_query = (
                select(
                    ConversationMessage.session_id,
                    ConversationMessage.user_id,
                    func.count(ConversationMessage.id).label('msg_count'),
                    func.min(ConversationMessage.timestamp).label('first_msg'),
                    func.max(ConversationMessage.timestamp).label('last_msg'),
                )
                .where(ConversationMessage.timestamp < cutoff)
                .group_by(ConversationMessage.session_id, ConversationMessage.user_id)
            )
            
            result = await self.db.execute(session_query)
            sessions_to_summarize = result.fetchall()
            
            # 2. For each session, create a warm-tier summary
            from src.database.models import ConversationSummary
            
            for row in sessions_to_summarize:
                session_id = row.session_id
                user_id = row.user_id
                
                # Check if summary already exists
                existing = await self.db.execute(
                    select(ConversationSummary).where(
                        ConversationSummary.user_id == user_id,
                        ConversationSummary.session_id == session_id
                    )
                )
                if existing.scalar_one_or_none():
                    continue  # Already summarized
                
                # Fetch messages for this session to build summary
                msgs_result = await self.db.execute(
                    select(ConversationMessage)
                    .where(
                        ConversationMessage.session_id == session_id,
                        ConversationMessage.user_id == user_id,
                        ConversationMessage.timestamp < cutoff
                    )
                    .order_by(ConversationMessage.timestamp)
                    .limit(50)
                )
                messages = msgs_result.scalars().all()
                
                if not messages:
                    continue
                
                # Build text summary (lightweight — no LLM needed for the basic version)
                conversation_lines = []
                key_facts = []
                agents_used = {}
                
                for msg in messages:
                    role_label = "User" if msg.role == "user" else "Assistant"
                    content_preview = (msg.content or "")[:150]
                    conversation_lines.append(f"{role_label}: {content_preview}")
                    
                    # Track agents used
                    if msg.active_agent:
                        agents_used[msg.active_agent] = agents_used.get(msg.active_agent, 0) + 1
                    
                    # Extract intents as key facts
                    if msg.intent and msg.intent not in key_facts:
                        key_facts.append(f"Intent: {msg.intent}")
                
                # Determine primary agent
                primary_agent = max(agents_used, key=agents_used.get) if agents_used else None
                
                # Build summary text
                summary_text = f"Conversation with {len(messages)} messages. "
                if key_facts:
                    summary_text += f"Topics: {', '.join(key_facts[:5])}. "
                summary_text += "Excerpt: " + " | ".join(conversation_lines[:5])
                
                # Create warm-tier summary
                summary = ConversationSummary(
                    user_id=user_id,
                    session_id=session_id,
                    summary=summary_text[:2000],
                    key_facts=key_facts[:20],
                    message_count=row.msg_count,
                    primary_agent=primary_agent,
                    first_message_at=row.first_msg,
                    last_message_at=row.last_msg,
                    expires_at=datetime.utcnow() + timedelta(days=180),
                )
                self.db.add(summary)
            
            # 3. Now delete the raw messages (they're preserved in summaries)
            stmt = delete(ConversationMessage).where(
                ConversationMessage.timestamp < cutoff
            )
            
            result = await self.db.execute(stmt)
            await self.db.commit()
            
            deleted = result.rowcount
            
            logger.info(
                f"{LOG_INFO} Tiered cleanup: summarized {len(sessions_to_summarize)} sessions, "
                f"deleted {deleted} old messages (older than {days} days)"
            )
            return deleted
            
        except Exception as e:
            logger.error(
                f"{LOG_ERROR} Failed to clean up messages: {e}",
                exc_info=True,
                extra={'days': days}
            )
            await self.db.rollback()
            return 0
    
    async def clear_warm_tier(self, max_age_days: int = 180) -> int:
        """
        Cold-tier transition: delete warm summaries older than max_age_days.
        After this, only Qdrant vectors survive for semantic recall.
        """
        try:
            from src.database.models import ConversationSummary
            
            cutoff = datetime.utcnow() - timedelta(days=max_age_days)
            
            stmt = delete(ConversationSummary).where(
                ConversationSummary.expires_at < cutoff
            )
            result = await self.db.execute(stmt)
            await self.db.commit()
            
            deleted = result.rowcount
            if deleted > 0:
                logger.info(f"{LOG_INFO} Cold-tier cleanup: removed {deleted} expired conversation summaries")
            return deleted
            
        except Exception as e:
            logger.error(f"{LOG_ERROR} Warm-tier cleanup failed: {e}")
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
            await self.db.rollback()
            logger.error(
                f"{LOG_ERROR} Failed to get message count: {e}",
                exc_info=True,
                extra={'user_id': user_id, 'session_id': session_id}
            )
            return 0
    
    async def list_conversations(
        self,
        user_id: int,
        limit: int = DEFAULT_CONVERSATION_LIST_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        List all conversations (sessions) for a user - async.
        
        Returns conversations sorted by most recent activity, with preview of first message.
        Used for sidebar "Your Actions" list.
        
        Args:
            user_id: User ID
            limit: Maximum number of conversations to return (default: DEFAULT_CONVERSATION_LIST_LIMIT)
            
        Returns:
            List of conversation dictionaries with keys:
            - session_id: Session identifier
            - preview: First user message (truncated to PREVIEW_MESSAGE_LENGTH chars)
            - last_activity: Timestamp of most recent message
            - message_count: Number of messages in conversation
            Returns empty list on error
        """
        try:
            # Get distinct sessions with their latest message timestamp
            stmt = (
                select(
                    ConversationMessage.session_id,
                    func.max(ConversationMessage.timestamp).label('last_activity'),
                    func.count(ConversationMessage.id).label('message_count'),
                    func.min(ConversationMessage.id).label('first_message_id')
                )
                .where(ConversationMessage.user_id == user_id)
                .group_by(ConversationMessage.session_id)
                .order_by(func.max(ConversationMessage.timestamp).desc())
                .limit(limit)
            )
            
            result = await self.db.execute(stmt)
            sessions = result.all()
            
            # Get preview (first user message) for each session
            conversations = []
            for session in sessions:
                # Get first user message as preview
                preview_stmt = (
                    select(ConversationMessage.content)
                    .where(
                        and_(
                            ConversationMessage.user_id == user_id,
                            ConversationMessage.session_id == session.session_id,
                            ConversationMessage.role == 'user'
                        )
                    )
                    .order_by(ConversationMessage.timestamp.asc())
                    .limit(1)
                )
                
                preview_result = await self.db.execute(preview_stmt)
                preview_msg = preview_result.scalar_one_or_none()
                
                if preview_msg and len(preview_msg) > PREVIEW_MESSAGE_LENGTH:
                    preview = preview_msg[:PREVIEW_MESSAGE_LENGTH] + "..."
                else:
                    preview = preview_msg or DEFAULT_PREVIEW_TEXT
                
                conversations.append({
                    'session_id': session.session_id,
                    'preview': preview,
                    'last_activity': session.last_activity.isoformat() if session.last_activity else None,
                    'message_count': session.message_count
                })
            
            # --- CROSS-SESSION DEDUP ---
            # The frontend and backend may create separate sessions for the same
            # query. Deduplicate by preview text: if multiple conversations share
            # the same first user message, keep only the one with the most messages
            # (or most recent activity as tiebreaker).
            seen_previews = {}  # preview → index in deduped list
            deduped = []
            for conv in conversations:
                preview_text = conv.get('preview', '')
                if preview_text and preview_text != DEFAULT_PREVIEW_TEXT:
                    if preview_text in seen_previews:
                        # Keep the one with more messages
                        existing_idx = seen_previews[preview_text]
                        if conv['message_count'] > deduped[existing_idx]['message_count']:
                            deduped[existing_idx] = conv
                        continue
                    seen_previews[preview_text] = len(deduped)
                deduped.append(conv)
            
            logger.info(f"{LOG_OK} Listed {len(deduped)} conversations for user {user_id} (deduped from {len(conversations)})")
            return deduped
            
        except Exception as e:
            await self.db.rollback()
            logger.error(
                f"{LOG_ERROR} Failed to list conversations: {e}",
                exc_info=True,
                extra={'user_id': user_id, 'limit': limit}
            )
            return []
    
    async def get_conversation_messages(
        self,
        user_id: int,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all messages for a specific conversation (session) - async.
        
        Used when user clicks on a conversation in the sidebar to view full history.
        
        Args:
            user_id: User ID
            session_id: Session ID
            limit: Optional limit on number of messages (None = all messages)
            
        Returns:
            List of message dictionaries with keys: role, content, timestamp, intent, entities
            Returns empty list on error
        """
        try:
            messages = await self._query_messages(
                user_id=user_id,
                session_id=session_id,
                limit=limit or DEFAULT_CONVERSATION_MESSAGES_LIMIT
            )
            
            # Reverse to chronological order (oldest first) since _query_messages returns newest first
            formatted = [self._format_message(msg) for msg in reversed(messages)]
            
            session_display = self._format_session_id(session_id)
            logger.info(f"{LOG_OK} Retrieved {len(formatted)} messages for session {session_display}")
            return formatted
            
        except Exception as e:
            logger.error(f"Failed to get recent messages: {e}")
            return []

    async def generate_conversation_title(
        self,
        user_id: int,
        session_id: str
    ) -> str:
        """
        Generate a concise title for a conversation based on its content - async.
        
        Args:
            user_id: User ID
            session_id: Session ID
            
        Returns:
            A short (3-6 words) title for the conversation
        """
        try:
            # Get first few messages
            messages = await self.get_recent_messages(user_id, session_id, limit=5)
            if not messages:
                return "New Conversation"
            
            # Use LLM to summarize if available, otherwise use first message preview
            if self._rag_enabled and hasattr(self.rag, 'llm'):
                # Simple prompt for title generation
                history_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
                prompt = (
                    "Based on the following conversation start, generate a very concise title "
                    "(max 5 words) that captures the main topic. Return ONLY the title.\n\n"
                    f"{history_text}"
                )
                
                try:
                    title = await self.rag.llm.agenerate(prompt)
                    return title.strip().replace('"', '')
                except Exception as llm_err:
                    logger.debug(f"LLM title generation failed: {llm_err}")
            
            # Fallback to preview
            first_user_msg = next((m['content'] for m in messages if m['role'] == ROLE_USER), "New Chat")
            title = first_user_msg[:40] + "..." if len(first_user_msg) > 40 else first_user_msg
            return title
            
        except Exception as e:
            logger.error(f"Failed to generate title: {e}")
            return "Conversation"
    
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
            logger.warning(f"Semantic search failed, falling back to keyword search: {e}")
            return await self.search_conversations_keyword(query, user_id, k=k, session_id_filter=session_id_filter)

    async def search_conversations_keyword(
        self,
        query: str,
        user_id: int,
        k: int = 5,
        session_id_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fallback keyword-based search for conversation messages - async.
        Used when RAG is unavailable or fails.
        """
        try:
            # Simple keyword matching using SQL LIKE
            # 1. Clean query
            clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', query).strip()
            if not clean_query:
                return []
            
            # 2. Build search terms
            terms = [t for t in clean_query.split() if t.lower() not in SEARCH_STOPWORDS]
            if not terms:
                # If all stopwords, use original query minus special chars
                terms = [clean_query]
            
            # 3. Build conditions
            conditions = [
                ConversationMessage.user_id == user_id,
                ConversationMessage.role == ROLE_USER
            ]
            
            if session_id_filter:
                conditions.append(ConversationMessage.session_id == session_id_filter)
                
            # Use OR for multiple terms
            term_conditions = []
            for term in terms:
                term_conditions.append(ConversationMessage.content.ilike(f"%{term}%"))
            
            if term_conditions:
                conditions.append(or_(*term_conditions))
            
            # 4. Execute query
            stmt = select(ConversationMessage).where(
                and_(*conditions)
            ).order_by(ConversationMessage.timestamp.desc()).limit(k)
            
            result = await self.db.execute(stmt)
            messages = result.scalars().all()
            
            # 5. Format results (Score is static 0.5 for keyword hits)
            return [{
                'message_id': msg.id,
                'content': msg.content,
                'session_id': msg.session_id,
                'intent': msg.intent,
                'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
                'relevance_score': 0.5,
                'search_method': 'keyword'
            } for msg in messages]
            
        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
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

    async def get_extended_semantic_context(
        self,
        user_id: int,
        query: str,
        k_messages: int = 3,
        k_facts: int = 5
    ) -> Dict[str, Any]:
        """
        Get comprehensive context combining recent messages, cross-session history, and facts.
        
        Args:
            user_id: User ID
            query: Current user query
            k_messages: Number of historical messages to retrieve
            k_facts: Number of facts to retrieve
            
        Returns:
            Combined context dictionary
        """
        # 1. Get facts from SemanticMemory
        facts = await self.semantic.search_facts(user_id, query, k=k_facts)
        
        # 2. Get cross-session history
        history = await self.get_relevant_context_from_history(query, user_id, k=k_messages)
        
        return {
            "facts": facts,
            "related_history": history
        }
    
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

    async def get_user_preferences(self, user_id: int) -> str:
        """
        Get explicit user preferences from semantic memory.
        
        Args:
            user_id: User ID
            
        Returns:
            Formatted string of preferences
        """
        try:
            facts = await self.semantic.get_facts(user_id, category="preference")
            if not facts:
                return ""
            
            return "EXPLICIT USER PREFERENCES:\n" + "\n".join([f"- {f['content']}" for f in facts])
        except Exception as e:
            logger.error(f"Failed to get user preferences: {e}")
            return ""

    async def learn_fact(self, user_id: int, content: str, category: str = "general") -> Optional[int]:
        """
        Learn a new fact about the user.
        
        Args:
            user_id: User ID
            content: Fact content
            category: Fact category
            
        Returns:
            Fact ID or None
        """
        return await self.semantic.learn_fact(user_id, content, category)

    async def _run_extraction(self, user_id: int, role: str, content: str):
        """
        Helper to run fact extraction in background with its own DB session.
        Uses get_async_db_context to ensure session lifetime safely.
        """
        try:
             # Use a fresh context manager session for background task
             async with get_async_db_context() as db:
                 # Re-initialize SemanticMemory with the fresh session
                 # This avoids 'Session is closed' errors in background tasks
                 bg_semantic = SemanticMemory(db, self.rag)
                 
                 msgs = [{"role": role, "content": content}]
                 await self.extractor.extract_and_learn(msgs, user_id, bg_semantic)
                 
                 logger.debug(f"Background extraction successful for user {user_id}")
             
        except Exception as e:
            logger.debug(f"Background extraction failed: {e}")

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
        try:
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
        except Exception as e:
            await self.db.rollback()
            logger.error(f"{LOG_ERROR} _query_messages failed: {e}")
            return []
    
    def _format_message(self, msg: ConversationMessage) -> Dict[str, Any]:
        """Format a ConversationMessage object into a dictionary."""
        content = msg.content
        # Defense-in-depth: strip any encrypted tokens that may have been
        # persisted before the saving-side fix was applied.
        if content and 'gAAAAAB' in content:
            import re
            _fernet_re = re.compile(r'gAAAAAB[A-Za-z0-9_\-+=/.]{40,}')
            content = _fernet_re.sub('', content)
            # Remove leftover "Suggestion:" labels that held tokens
            lines = content.split('\n')
            lines = [
                ln for ln in lines
                if not ln.strip().startswith('💡 Suggestion:')
                and not ln.strip().startswith('Suggestion:')
                and ln.strip() not in ('💡 Suggestion:', 'Suggestion:', '💡', '---')
            ]
            content = '\n'.join(lines).strip()
        return {
            'role': msg.role,
            'content': content,
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
        
        Simple keyword-based topic extraction using centralized stopwords.
        
        Args:
            messages: List of message content strings
            max_topics: Maximum number of topics to return
            
        Returns:
            List of topic strings
        """
        import re
        from collections import Counter
        
        # Extract words (3+ characters, not in centralized stopword list)
        words = []
        for msg in messages:
            # Use simple regex for tokenization
            msg_words = re.findall(r'\b[a-z]{3,}\b', msg.lower())
            words.extend([w for w in msg_words if w not in SEARCH_STOPWORDS])
        
        # Count and return most common
        word_counts = Counter(words)
        topics = [word for word, count in word_counts.most_common(max_topics)]
        
        return topics
    
    async def _index_message_in_rag(self, message: ConversationMessage) -> None:
        """
        Index a message in RAG vector store for semantic search - async.
        
        Wraps the synchronous RAG.index_document() call in asyncio.to_thread()
        Internal method to index a single message in RAG asynchronously.
        
        OPTIMIZATION: Skips indexing if message already exists to save Qdrant write units.
        
        Args:
            message: ConversationMessage object to index
        """
        try:
            doc_id = f"conv_msg_{message.id}"
            
            # Check if already indexed to prevent duplicate writes (save Qdrant quota)
            try:
                already_exists = await asyncio.to_thread(
                    self.rag.document_exists,
                    doc_id
                )
                if already_exists:
                    logger.debug(
                        f"{LOG_INFO} Message {message.id} already indexed, skipping (doc_id={doc_id})"
                    )
                    return
            except Exception as check_error:
                # If check fails, proceed with indexing (safer to index than miss)
                logger.debug(f"Could not check if message {message.id} exists, proceeding: {check_error}")
            
            # 1. Build Base Metadata
            metadata = {
                "type": "conversation_message",
                "user_id": message.user_id,
                "session_id": message.session_id,
                "message_id": message.id,
                "role": message.role,
            }
            
            # 2. Add Conditional Fields
            if message.intent:
                metadata["intent"] = message.intent
            if message.timestamp:
                metadata["timestamp"] = message.timestamp.isoformat()
                
            # 3. Handle Entities (robust serialization)
            # Qdrant accepts str, int, float, bool, or list[str]
            # It does NOT accept dicts or nested lists. We must JSON serialize them.
            if message.entities:
                 metadata["entities"] = json.dumps(message.entities)
            
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
    

