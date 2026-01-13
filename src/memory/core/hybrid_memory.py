"""
Hybrid Memory System

Extended memory system with semantic and conversational capabilities.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.utils.logger import setup_logger
from ..models.persistence import UnifiedContext
from .base_memory import SimplifiedMemorySystem

logger = setup_logger(__name__)

# Optional intent module integration
try:
    from src.ai.intent import classify_query_intent
    HAS_INTENT = True
except ImportError:
    classify_query_intent = None
    HAS_INTENT = False

# Optional imports for hybrid capabilities
try:
    from src.ai.rag import RAGEngine
    HAS_RAG = True
except ImportError:
    HAS_RAG = False

try:
    from src.database.models import ConversationMessage
    HAS_CONVERSATION_MODELS = True
except ImportError:
    HAS_CONVERSATION_MODELS = False

class HybridMemorySystem(SimplifiedMemorySystem):
    """
    Inherits all behavioral memory from SimplifiedMemorySystem and adds:
    - Semantic search via Qdrant (optional)
    - Conversational memory via PostgreSQL (optional)
    - Unified context generation
    """
    
    def __init__(
        self,
        db: Optional[Any] = None,
        batch_size: int = 10,
        vector_collection: str = "emails",
        enable_semantic: bool = True,
        rag_engine: Optional[Any] = None,
        config: Optional[Any] = None
    ):
        super().__init__(db, batch_size, config)
        
        self.rag_engine = rag_engine
        self.vector_collection = vector_collection
        self.has_semantic = False
        
        # Initialize semantic memory if enabled
        if enable_semantic:
            if self.rag_engine:
                self.has_semantic = True
                logger.info(f"Semantic memory enabled via provided RAGEngine (collection={vector_collection})")
            elif HAS_RAG:
                # Try to initialize RAGEngine if not provided
                try:
                    self.rag_engine = RAGEngine(config=config)
                    self.has_semantic = True
                    logger.info(f"Semantic memory enabled via new RAGEngine (collection={vector_collection})")
                except Exception as e:
                    logger.debug(f"Failed to initialize RAGEngine: {e}")
            else:
                logger.debug("Semantic memory disabled (RAGEngine not available)")
        
        logger.info(f"Hybrid memory initialized (semantic={self.has_semantic}, conversational={self.has_database})")
    
    def get_unified_context(
        self,
        query: str,
        user_id: int,
        session_id: Optional[str] = None,
        top_k: int = 5
    ) -> UnifiedContext:
        """Get unified context from all three memory layers"""
        start_time = datetime.now()
        
        # Detect intent (if available)
        intent = "general"
        if HAS_INTENT and classify_query_intent:
            intent_data = classify_query_intent(query)
            intent = intent_data.get("domain", "general")
        
        # Layer 1: Behavioral memory
        recommended_tools = self.get_tool_recommendations(query, intent, user_id)
        similar_patterns = self.get_similar_patterns(query, intent, user_id)
        user_prefs = self.get_user_preferences(user_id)
        
        # Layer 2: Semantic memory
        relevant_docs = []
        semantic_summary = ""
        if self.has_semantic:
            relevant_docs = self._query_semantic_memory(query, user_id, top_k)
            semantic_summary = self._summarize_documents(relevant_docs)
        
        # Layer 3: Conversational memory
        messages = []
        conv_summary = ""
        entities = []
        if self.has_database and HAS_CONVERSATION_MODELS:
            messages = self._query_conversational_memory(user_id, session_id, top_k)
            conv_summary = self._summarize_conversation(messages)
            entities = self._extract_entities(messages)
        
        # Calculate unified confidence
        confidence = self._calculate_unified_confidence(
            num_patterns=len(similar_patterns),
            num_docs=len(relevant_docs),
            num_messages=len(messages)
        )
        
        retrieval_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        return UnifiedContext(
            recommended_tools=recommended_tools,
            similar_patterns=similar_patterns,
            user_preferences=user_prefs,
            relevant_documents=relevant_docs,
            semantic_summary=semantic_summary,
            recent_messages=messages,
            conversation_summary=conv_summary,
            mentioned_entities=entities,
            confidence=confidence,
            retrieval_time_ms=retrieval_ms
        )
    
    def learn_from_interaction(
        self,
        query: str,
        response: str,
        user_id: int,
        session_id: str,
        tools_used: List[str],
        success: bool,
        intent: Optional[str] = None,
        entities: Optional[Dict] = None,
        execution_time: float = 0.0
    ):
        """Learn from interaction across all memory layers"""
        if not intent:
            if HAS_INTENT and classify_query_intent:
                intent_data = classify_query_intent(query)
                intent = intent_data.get("domain", "general")
            else:
                intent = "general"
        
        # 1. Learn behavioral pattern
        self.learn_query_pattern(
            query=query,
            intent=intent,
            tools_used=tools_used,
            success=success,
            execution_time=execution_time,
            user_id=user_id
        )
        
        # 2. Save conversation history
        if self.has_database and HAS_CONVERSATION_MODELS:
            self._save_conversation(
                user_id=user_id,
                session_id=session_id,
                user_message=query,
                assistant_message=response,
                intent=intent,
                entities=entities
            )
        
        # 3. Index in semantic memory (if valuable)
        if self.has_semantic and success and self._should_index_response(response):
            self._index_response(user_id, query, response)
    
    def _query_semantic_memory(self, query: str, user_id: int, k: int) -> List[Dict]:
        """Query RAGEngine for relevant documents"""
        try:
            return self.rag_engine.search(
                query=query,
                collection_name=self.vector_collection,
                limit=k,
                metadata_filter={"user_id": user_id}
            )
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []
    
    def _query_conversational_memory(
        self,
        user_id: int,
        session_id: Optional[str],
        k: int
    ) -> List[Dict]:
        """Query PostgreSQL for conversation history"""
        try:
            query = self.db.query(ConversationMessage).filter(
                ConversationMessage.user_id == user_id
            )
            
            if session_id:
                query = query.filter(ConversationMessage.session_id == session_id)
            
            messages = query.order_by(ConversationMessage.created_at.desc()).limit(k).all()
            
            return [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat()
                }
                for msg in reversed(messages)
            ]
        except Exception as e:
            logger.error(f"Conversational memory query failed: {e}")
            return []
    
    def _save_conversation(
        self,
        user_id: int,
        session_id: str,
        user_message: str,
        assistant_message: str,
        intent: Optional[str],
        entities: Optional[Dict]
    ):
        """Save conversation to PostgreSQL"""
        try:
            # Save user message
            user_msg = ConversationMessage(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=user_message,
                intent=intent,
                entities=entities
            )
            self.db.add(user_msg)
            
            # Save assistant message
            asst_msg = ConversationMessage(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=assistant_message
            )
            self.db.add(asst_msg)
            
            # Commit immediately for conversation consistency
            self.db.commit()
        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")
            self.db.rollback()
    
    def _should_index_response(self, response: str) -> bool:
        """Determine if response should be indexed in Qdrant."""
        # Index if response is substantial and informative
        return len(response.split()) > 10 and not response.lower().startswith("i'm sorry")
    
    def _index_response(self, user_id: int, query: str, response: str):
        """Index response in RAGEngine for future retrieval"""
        try:
            self.rag_engine.index_text(
                text=f"Q: {query}\nA: {response}",
                metadata={
                    "user_id": user_id,
                    "type": "interaction",
                    "timestamp": datetime.now().isoformat()
                },
                collection_name=self.vector_collection
            )
        except Exception as e:
            logger.error(f"Semantic indexing failed: {e}")
    
    def _summarize_documents(self, docs: List[Dict]) -> str:
        """Summarize top documents"""
        if not docs:
            return ""
        return " ".join([d.get("text", "")[:100] + "..." for d in docs[:2]])
    
    def _summarize_conversation(self, messages: List[Dict]) -> str:
        """Summarize conversation"""
        if not messages:
            return ""
        return f"Last {len(messages)} messages exchanged."
    
    def _extract_entities(self, messages: List[Dict]) -> List[str]:
        """Extract entities from messages"""
        # Placeholder for actual entity extraction from messages
        return []
    
    def _calculate_unified_confidence(
        self,
        num_patterns: int,
        num_docs: int,
        num_messages: int
    ) -> float:
        """Calculate unified confidence based on available data"""
        score = 0.0
        if num_patterns > 0: score += 0.4
        if num_docs > 0: score += 0.3
        if num_messages > 0: score += 0.3
        return min(1.0, max(0.1, score))
