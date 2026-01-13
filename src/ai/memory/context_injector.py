"""
Dynamic Prompt Injection - LTM to STM Context Transfer

Systematically retrieves and injects long-term memory (semantic facts,
preferences, active episodes) into the LLM's short-term context.

Part of the Advanced RAG architecture for personalized responses.
"""
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import asyncio

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class ContextPriority(Enum):
    """Priority levels for context injection."""
    CRITICAL = 1    # Always include (e.g., active intent, current task)
    HIGH = 2        # Include if relevant (e.g., user preferences for current topic)
    MEDIUM = 3      # Include if space allows (e.g., related people)
    LOW = 4         # Include as padding (e.g., general facts)


@dataclass
class ContextChunk:
    """A chunk of context to inject."""
    content: str
    source: str              # "fact_graph", "semantic_memory", "episode", "graph"
    priority: ContextPriority
    relevance_score: float   # 0-1 relevance to current query
    category: Optional[str] = None
    token_estimate: int = 0  # Estimated token count
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InjectionResult:
    """Result of context injection."""
    system_context: str      # Context to inject into system prompt
    user_context: str        # Context to inject before user message
    chunks_used: List[ContextChunk]
    total_tokens: int
    sources_used: List[str]
    injection_summary: str   # Brief description of what was injected


class DynamicContextInjector:
    """
    Injects long-term memory into LLM prompts dynamically.
    
    Combines multiple memory sources:
    - FactGraph: Hierarchical user preferences and knowledge
    - SemanticMemory: Learned facts from conversations
    - EpisodeDetector: Active project/thread context
    - Knowledge Graph: Related entities and relationships
    
    Features:
    - Query-aware relevance filtering
    - Token budget management
    - Priority-based selection
    - Source attribution for debuggability
    """
    
    # Default token budgets
    DEFAULT_SYSTEM_BUDGET = 1000   # Tokens for system context
    DEFAULT_USER_BUDGET = 500     # Tokens for user-side context
    
    # Approximate tokens per character
    TOKENS_PER_CHAR = 0.25
    
    def __init__(
        self,
        fact_graph_manager: Optional[Any] = None,
        semantic_memory: Optional[Any] = None,
        episode_detector: Optional[Any] = None,
        knowledge_graph: Optional[Any] = None,
        system_token_budget: int = 1000,
        user_token_budget: int = 500
    ):
        """
        Initialize context injector.
        
        Args:
            fact_graph_manager: FactGraphManager for user facts
            semantic_memory: SemanticMemory for learned facts
            episode_detector: EpisodeDetector for active context
            knowledge_graph: KnowledgeGraphManager for entity lookup
            system_token_budget: Max tokens for system context
            user_token_budget: Max tokens for user context
        """
        self.fact_graph_manager = fact_graph_manager
        self.semantic_memory = semantic_memory
        self.episode_detector = episode_detector
        self.knowledge_graph = knowledge_graph
        self.system_token_budget = system_token_budget
        self.user_token_budget = user_token_budget
        
        logger.info("DynamicContextInjector initialized")
    
    async def build_context(
        self,
        user_id: int,
        query: str,
        intent: Optional[str] = None,
        entities: Optional[List[str]] = None,
        include_episodes: bool = True,
        include_preferences: bool = True,
        include_relationships: bool = True
    ) -> InjectionResult:
        """
        Build context to inject into LLM prompt.
        
        Args:
            user_id: The user's ID
            query: Current query/message
            intent: Detected intent (e.g., "scheduling", "email")
            entities: Entities mentioned in query
            include_episodes: Include active episode context
            include_preferences: Include user preferences
            include_relationships: Include relationship context
            
        Returns:
            InjectionResult with formatted context
        """
        chunks: List[ContextChunk] = []
        
        # Gather context from all sources in parallel
        tasks = []
        
        if include_preferences and self.fact_graph_manager:
            tasks.append(self._gather_preferences(user_id, query, intent))
        
        if include_relationships and self.fact_graph_manager:
            tasks.append(self._gather_relationships(user_id, entities))
        
        if include_episodes and self.episode_detector:
            tasks.append(self._gather_episodes(user_id, query))
        
        if self.semantic_memory:
            tasks.append(self._gather_semantic_facts(user_id, query))
        
        if entities and self.knowledge_graph:
            tasks.append(self._gather_entity_context(user_id, entities))
        
        # Execute all gathering tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                chunks.extend(result)
            elif isinstance(result, Exception):
                logger.debug(f"Context gathering failed: {result}")
        
        # Sort by priority and relevance
        chunks.sort(key=lambda c: (c.priority.value, -c.relevance_score))
        
        # Build context within token budgets
        system_context, user_context, used_chunks = self._build_within_budget(chunks)
        
        # Calculate summary
        sources = list(set(c.source for c in used_chunks))
        total_tokens = sum(c.token_estimate for c in used_chunks)
        
        summary = self._build_summary(used_chunks)
        
        # Track fact usage for feedback loop (reinforcement)
        await self._track_fact_usage(user_id, used_chunks)
        
        return InjectionResult(
            system_context=system_context,
            user_context=user_context,
            chunks_used=used_chunks,
            total_tokens=total_tokens,
            sources_used=sources,
            injection_summary=summary
        )
    
    async def _gather_preferences(
        self,
        user_id: int,
        query: str,
        intent: Optional[str]
    ) -> List[ContextChunk]:
        """Gather relevant preferences from FactGraph."""
        chunks = []
        
        try:
            from .fact_graph import FactCategory, PreferenceSubcategory
            
            graph = self.fact_graph_manager.get_or_create(user_id)
            
            # Determine relevant subcategories based on intent
            subcategories = []
            if intent:
                intent_mapping = {
                    "scheduling": [PreferenceSubcategory.SCHEDULING],
                    "calendar": [PreferenceSubcategory.SCHEDULING],
                    "email": [PreferenceSubcategory.COMMUNICATION],
                    "communication": [PreferenceSubcategory.COMMUNICATION],
                    "work": [PreferenceSubcategory.WORK_STYLE],
                    "task": [PreferenceSubcategory.WORK_STYLE],
                }
                subcategories = intent_mapping.get(intent.lower(), [])
            
            # Get preference facts
            for subcat in subcategories or [None]:
                subcat_val = subcat.value if subcat else None
                facts = graph.get_facts_by_category(
                    FactCategory.PREFERENCE,
                    subcategory=subcat_val,
                    min_confidence=0.5
                )[:5]
                
                for fact in facts:
                    # Calculate relevance to query
                    relevance = self._calculate_relevance(query, fact.content)
                    
                    chunks.append(ContextChunk(
                        content=fact.content,
                        source="fact_graph",
                        priority=ContextPriority.HIGH if relevance > 0.3 else ContextPriority.MEDIUM,
                        relevance_score=relevance,
                        category="preference",
                        token_estimate=self._estimate_tokens(fact.content),
                        metadata={"fact_id": fact.id, "confidence": fact.confidence}
                    ))
                    
        except Exception as e:
            logger.debug(f"Preference gathering failed: {e}")
        
        return chunks
    
    async def _gather_relationships(
        self,
        user_id: int,
        entities: Optional[List[str]]
    ) -> List[ContextChunk]:
        """Gather relationship context for mentioned entities."""
        chunks = []
        
        if not entities:
            return chunks
        
        try:
            from .fact_graph import FactCategory
            
            graph = self.fact_graph_manager.get_or_create(user_id)
            
            for entity in entities:
                # Find facts mentioning this entity
                facts = graph.get_facts_by_entity(entity, min_confidence=0.5)[:3]
                
                for fact in facts:
                    chunks.append(ContextChunk(
                        content=fact.content,
                        source="fact_graph",
                        priority=ContextPriority.HIGH,  # Entity-specific is high priority
                        relevance_score=0.8,
                        category="relationship",
                        token_estimate=self._estimate_tokens(fact.content),
                        metadata={"entity": entity, "fact_id": fact.id}
                    ))
                    
        except Exception as e:
            logger.debug(f"Relationship gathering failed: {e}")
        
        return chunks
    
    async def _gather_episodes(
        self,
        user_id: int,
        query: str
    ) -> List[ContextChunk]:
        """Gather active episode context."""
        chunks = []
        
        try:
            context = await self.episode_detector.get_retrieval_context(
                user_id, query, max_episodes=3
            )
            
            if context.context_summary:
                chunks.append(ContextChunk(
                    content=f"Currently active: {context.context_summary}",
                    source="episode",
                    priority=ContextPriority.CRITICAL,
                    relevance_score=1.0,
                    category="active_context",
                    token_estimate=self._estimate_tokens(context.context_summary)
                ))
            
            # Add episode details
            for ep in context.active_episodes[:2]:
                detail = f"{ep.title} (activity: {ep.activity_score:.1%})"
                chunks.append(ContextChunk(
                    content=detail,
                    source="episode",
                    priority=ContextPriority.HIGH,
                    relevance_score=ep.activity_score * ep.recency_score,
                    category="episode",
                    token_estimate=self._estimate_tokens(detail),
                    metadata={"episode_id": ep.episode_id, "type": ep.type.value}
                ))
                
        except Exception as e:
            logger.debug(f"Episode gathering failed: {e}")
        
        return chunks
    
    async def _gather_semantic_facts(
        self,
        user_id: int,
        query: str
    ) -> List[ContextChunk]:
        """Gather relevant facts from SemanticMemory."""
        chunks = []
        
        try:
            facts = await self.semantic_memory.search_facts(
                query=query,
                user_id=user_id,
                limit=5,
                use_semantic=True
            )
            
            for fact in facts:
                content = fact.content if hasattr(fact, 'content') else str(fact)
                confidence = getattr(fact, 'confidence', 1.0)
                
                chunks.append(ContextChunk(
                    content=content,
                    source="semantic_memory",
                    priority=ContextPriority.MEDIUM,
                    relevance_score=confidence,
                    category=getattr(fact, 'category', 'general'),
                    token_estimate=self._estimate_tokens(content),
                    metadata={"fact_id": getattr(fact, 'id', None)}
                ))
                
        except Exception as e:
            logger.debug(f"Semantic fact gathering failed: {e}")
        
        return chunks
    
    async def _gather_entity_context(
        self,
        user_id: int,
        entities: List[str]
    ) -> List[ContextChunk]:
        """Gather context about entities from knowledge graph."""
        chunks = []
        
        try:
            for entity in entities[:3]:  # Limit entities
                # Search for entity in graph
                nodes = await self.knowledge_graph.find_nodes_by_property(
                    'name', entity,
                    fuzzy=True,
                    limit=1
                )
                
                if nodes:
                    node = nodes[0]
                    # Get connected nodes for context
                    connected = await self.knowledge_graph.get_neighbors(
                        node.get('_id'),
                        limit=3
                    )
                    
                    if connected:
                        connections = [n.get('name', n.get('_id', ''))[:30] for n in connected]
                        context = f"{entity}: related to {', '.join(connections)}"
                        chunks.append(ContextChunk(
                            content=context,
                            source="graph",
                            priority=ContextPriority.MEDIUM,
                            relevance_score=0.6,
                            category="entity_context",
                            token_estimate=self._estimate_tokens(context),
                            metadata={"entity": entity, "node_id": node.get('_id')}
                        ))
                        
        except Exception as e:
            logger.debug(f"Entity context gathering failed: {e}")
        
        return chunks
    
    def _build_within_budget(
        self,
        chunks: List[ContextChunk]
    ) -> Tuple[str, str, List[ContextChunk]]:
        """Build context strings within token budgets."""
        system_parts = []
        user_parts = []
        used_chunks = []
        
        system_tokens = 0
        user_tokens = 0
        
        for chunk in chunks:
            # Decide where to place based on priority
            if chunk.priority in [ContextPriority.CRITICAL, ContextPriority.HIGH]:
                # High priority goes to system context
                if system_tokens + chunk.token_estimate <= self.system_token_budget:
                    system_parts.append(chunk.content)
                    system_tokens += chunk.token_estimate
                    used_chunks.append(chunk)
            else:
                # Lower priority goes to user context
                if user_tokens + chunk.token_estimate <= self.user_token_budget:
                    user_parts.append(chunk.content)
                    user_tokens += chunk.token_estimate
                    used_chunks.append(chunk)
        
        # Format system context
        if system_parts:
            system_context = self._format_system_context(system_parts)
        else:
            system_context = ""
        
        # Format user context
        if user_parts:
            user_context = self._format_user_context(user_parts)
        else:
            user_context = ""
        
        return system_context, user_context, used_chunks
    
    def _format_system_context(self, parts: List[str]) -> str:
        """Format parts into system context block."""
        if not parts:
            return ""
        
        lines = ["[User Context - Use this to personalize responses]"]
        for part in parts:
            lines.append(f"• {part}")
        
        return "\n".join(lines)
    
    def _format_user_context(self, parts: List[str]) -> str:
        """Format parts into user context block."""
        if not parts:
            return ""
        
        return f"[Background: {'; '.join(parts[:5])}]"
    
    def _calculate_relevance(self, query: str, content: str) -> float:
        """Calculate relevance score between query and content."""
        if not query or not content:
            return 0.0
        
        query_words = set(query.lower().split())
        content_words = set(content.lower().split())
        
        if not query_words:
            return 0.0
        
        overlap = len(query_words & content_words)
        return min(1.0, overlap / len(query_words))
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        return int(len(text) * self.TOKENS_PER_CHAR)
    
    def _build_summary(self, chunks: List[ContextChunk]) -> str:
        """Build a summary of what was injected."""
        if not chunks:
            return "No context injected"
        
        source_counts = {}
        for chunk in chunks:
            source_counts[chunk.source] = source_counts.get(chunk.source, 0) + 1
        
        parts = [f"{count} from {source}" for source, count in source_counts.items()]
        return f"Injected: {', '.join(parts)}"

    async def _track_fact_usage(self, user_id: int, chunks: List[ContextChunk]) -> None:
        """
        Track which facts were used in context injection.
        
        This enables the feedback loop:
        - Facts that are used get reinforced (confidence boost)
        - Facts that are never used may decay over time
        
        Args:
            user_id: User ID
            chunks: Chunks that were actually included in context
        """
        if not self.semantic_memory:
            return
        
        # Collect fact IDs from chunks with fact_id metadata
        fact_ids = []
        for chunk in chunks:
            fact_id = chunk.metadata.get("fact_id")
            if fact_id is not None:
                fact_ids.append(fact_id)
        
        if not fact_ids:
            return
        
        # Use a small reinforcement boost for usage (not explicit confirmation)
        USAGE_BOOST = 0.02  # Small boost - explicit feedback gives more
        
        try:
            for fact_id in fact_ids:
                # Check if semantic_memory has reinforce_fact method
                if hasattr(self.semantic_memory, 'reinforce_fact'):
                    await self.semantic_memory.reinforce_fact(
                        user_id=user_id,
                        fact_id=fact_id,
                        boost=USAGE_BOOST
                    )
            
            logger.debug(f"[ContextInjector] Tracked usage of {len(fact_ids)} facts for user {user_id}")
        except Exception as e:
            # Non-critical - don't break context injection if tracking fails
            logger.debug(f"[ContextInjector] Fact usage tracking failed: {e}")


def format_injection_for_prompt(result: InjectionResult) -> Dict[str, str]:
    """
    Format injection result for easy prompt construction.
    
    Returns:
        Dict with 'system' and 'user' keys for insertion
    """
    return {
        'system': result.system_context,
        'user': result.user_context,
        'summary': result.injection_summary
    }


async def inject_context_into_messages(
    messages: List[Dict[str, str]],
    injector: DynamicContextInjector,
    user_id: int,
    query: str,
    intent: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Helper to inject context into a message list.
    
    Modifies the system message and prepends context to user message.
    """
    result = await injector.build_context(user_id, query, intent)
    
    modified = []
    for msg in messages:
        if msg.get('role') == 'system' and result.system_context:
            # Append context to system message
            modified.append({
                'role': 'system',
                'content': f"{msg['content']}\n\n{result.system_context}"
            })
        elif msg.get('role') == 'user' and result.user_context:
            # Prepend context to first user message
            if not any(m.get('role') == 'user' for m in modified):
                modified.append({
                    'role': 'user',
                    'content': f"{result.user_context}\n\n{msg['content']}"
                })
            else:
                modified.append(msg)
        else:
            modified.append(msg)
    
    return modified
