"""
Context Assembler

Unified context assembly for agent queries.
Combines all memory sources into a coherent context package that gives agents
the full picture needed to "take action with clarity."

Sources Combined:
- Conversation history (recent messages in session)
- Semantic facts (learned preferences and knowledge)
- Multi-hop graph context (related entities and relationships)
- Cross-app correlations (related content from other apps)
- Temporal context (what happened around this time)
- Urgent insights (conflicts, deadlines, VIP contacts)
"""
import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, TYPE_CHECKING, Tuple
from dataclasses import dataclass, field

# Attempt to import tiktoken for accurate budget management
try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

from src.utils.logger import setup_logger
from src.utils.config import Config

if TYPE_CHECKING:
    from src.ai.conversation_memory import ConversationMemory
    from src.ai.memory.semantic_memory import SemanticMemory
    from src.services.indexing.rag_graph_bridge import GraphRAGIntegrationService
    from src.services.indexing.cross_app_correlator import CrossAppCorrelator
    from src.services.insights.insight_service import InsightService
    from src.services.indexing.temporal_indexer import TemporalIndexer
    from src.ai.temporal_reasoner import TemporalReasoner

logger = setup_logger(__name__)

# Configuration
MAX_INSIGHTS = 3
GRAPH_HOPS = 3

# Intent-based weightings (Priority Scores)
DEFAULT_WEIGHTS = {
    'conversation': 1.0,
    'facts': 0.9,
    'graph': 0.8,
    'temporal': 0.7,
    'insights': 0.9,
    'cross_app': 0.6
}

INTENT_WEIGHTS = {
    'scheduling': {'temporal': 1.2, 'facts': 0.8, 'conversation': 1.0},
    'research': {'graph': 1.2, 'cross_app': 1.0, 'facts': 1.1},
    'chat': {'conversation': 1.2, 'facts': 1.0, 'temporal': 0.5}
}

DEFAULT_TOKEN_BUDGET = 2000


@dataclass
class TemporalHint:
    """Parsed temporal reference from query."""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    description: str = ""
    granularity: str = "day"  # hour, day, week, month


@dataclass
class AssembledContext:
    """
    Unified context package for agent queries.
    
    Contains all relevant context from multiple memory sources,
    ready for use in agent prompts.
    """
    # Recent conversation history
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Learned facts and preferences
    semantic_facts: List[Dict[str, Any]] = field(default_factory=list)
    
    # Multi-hop graph relationships
    graph_context: Dict[str, Any] = field(default_factory=dict)
    
    # Cross-app related content
    cross_app_content: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    
    # Time-filtered events
    temporal_context: List[Dict[str, Any]] = field(default_factory=list)
    
    # Urgent insights to surface
    urgent_insights: List[Dict[str, Any]] = field(default_factory=list)
    
    # Context metadata
    assembled_at: datetime = field(default_factory=datetime.utcnow)
    query: str = ""
    user_id: int = 0
    intent: str = "general"
    token_count: int = 0
    
    def to_prompt_context(self) -> str:
        """
        Format context for inclusion in LLM prompts using structured Markdown.
        """
        sections = []
        
        # 1. User Facts & Preferences (The "Stable" Context)
        if self.semantic_facts:
            fact_lines = [f"- {f.get('content', '')}" for f in self.semantic_facts]
            sections.append(f"### 👤 User Preferences & Facts\n" + "\n".join(fact_lines))
            
        # 2. Urgent Insights (The "Interruption" Context)
        if self.urgent_insights:
            insight_lines = [f"⚠️ **{i.get('category', 'Insight')}**: {i.get('content', '')}" for i in self.urgent_insights]
            sections.append(f"### ⚡ Urgent Insights\n" + "\n".join(insight_lines))

        # 3. Conversation History (The "Current Flow")
        if self.conversation_history:
            history_lines = []
            for msg in self.conversation_history:
                role = msg.get('role', 'unknown').upper()
                content = msg.get('content', '').strip()
                history_lines.append(f"**{role}**: {content}")
            sections.append(f"### 💬 Recent Conversation\n" + "\n".join(history_lines))
            
        # 4. Graph & Cross-App (The "Knowledge" Context)
        knowledge = []
        if self.graph_context.get('results'):
            for r in self.graph_context['results']:
                content = r.get('content', r.get('node_id', ''))
                knowledge.append(f"- [Graph] {content}")
        
        if self.cross_app_content:
            for app, items in self.cross_app_content.items():
                for item in items:
                    preview = item.get('content', '')
                    knowledge.append(f"- [{app}] {preview}")
                    
        if knowledge:
            sections.append(f"### 📚 Related Knowledge\n" + "\n".join(knowledge))
            
        # 5. Temporal context
        if self.temporal_context:
            temp_lines = [f"- {t.get('content', t.get('description', ''))}" for t in self.temporal_context]
            sections.append(f"### 📅 Temporal Context\n" + "\n".join(temp_lines))
            
        final_output = "\n\n".join(sections)
        
        # Wrap in tags for clear separation
        return f"<context>\n{final_output}\n</context>"
        
    def has_context(self) -> bool:
        """Check if any meaningful context was assembled."""
        return bool(
            self.conversation_history or
            self.semantic_facts or
            self.graph_context.get('results') or
            self.cross_app_content or
            self.urgent_insights
        )
    
    def get_token_count(self, model: str = "gpt-4") -> int:
        """Estimate token count for the assembled context."""
        if not HAS_TIKTOKEN:
            return len(self.to_prompt_context()) // 4
        
        try:
            if "gemini" in model.lower():
                encoding = tiktoken.get_encoding("cl100k_base")
            else:
                encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(self.to_prompt_context()))
        except Exception:
            # Fallback to character-based approximation if encoding fails
            return len(self.to_prompt_context()) // 4


class ContextPruner:
    """
    Intelligent filter that deduplicates and prunes context to fit a token budget.
    """
    
    def __init__(self, model: str = "gpt-4"):
        self.model = model
        self.encoding = None
        if HAS_TIKTOKEN:
            try:
                if "gemini" in model.lower():
                    self.encoding = tiktoken.get_encoding("cl100k_base")
                else:
                    self.encoding = tiktoken.encoding_for_model(model)
            except Exception:
                # Model not recognized, use no encoding (will fallback to char count)
                pass

    def prune(
        self, 
        context: AssembledContext, 
        budget: int = DEFAULT_TOKEN_BUDGET,
        intent: str = "general"
    ) -> AssembledContext:
        """
        Prunes context items based on relevance scores and token budget.
        """
        # 1. Calculate Weights
        weights = DEFAULT_WEIGHTS.copy()
        if intent in INTENT_WEIGHTS:
            weights.update(INTENT_WEIGHTS[intent])
        
        # 2. Deduplicate cross-source
        self._deduplicate(context)
        
        # 3. Score all items
        scored_items = self._collect_and_score(context, weights)
        
        # 4. Filter by budget
        # We start with a conservative approach: most recent conversation is always high priority,
        # then we fill with high-scored facts and knowledge.
        self._pack_to_budget(context, scored_items, budget)
        
        return context

    def _deduplicate(self, context: AssembledContext):
        """
        Removes overlapping info across sources using fuzzy string matching.
        """
        seen_items = [] # List of word sets for fuzzy matching
        
        # 1. Process Conversation History (The "Anchor" of context)
        # We don't remove conversation history, but we use it to prune other sources.
        for msg in context.conversation_history:
            content = msg.get('content', '').lower()
            seen_items.append(set(re.findall(r'\w+', content)))
            
        # 2. Prune Facts against Conversation
        unique_facts = []
        for fact in context.semantic_facts:
            content = fact.get('content', '').lower()
            fact_words = set(re.findall(r'\w+', content))
            
            if not self._is_redundant(fact_words, seen_items):
                unique_facts.append(fact)
                seen_items.append(fact_words)
        context.semantic_facts = unique_facts
        
        # 3. Prune Graph against Conversation and Facts
        if context.graph_context.get('results'):
            unique_graph = []
            for res in context.graph_context['results']:
                content = res.get('content', '').lower()
                res_words = set(re.findall(r'\w+', content))
                
                if not self._is_redundant(res_words, seen_items):
                    unique_graph.append(res)
                    seen_items.append(res_words)
            context.graph_context['results'] = unique_graph

    def _is_redundant(self, target_words: set, reference_sets: List[set], threshold: float = 0.5) -> bool:
        """
        Checks if a set of words significantly overlaps with any reference set.
        Filtered by common stop words to focus on meaningful content.
        """
        STOPWORDS = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been', 'has', 'have', 'had', 'do', 'does', 'did', 'to', 'for', 'of', 'she', 'he', 'they', 'it'}
        
        filtered_target = target_words - STOPWORDS
        if not filtered_target:
            return False
            
        for ref_set in reference_sets:
            filtered_ref = ref_set - STOPWORDS
            if not filtered_ref:
                continue
                
            intersection = len(filtered_target.intersection(filtered_ref))
            # Use 'overlap coefficient' (intersection / min_size) for better partial match
            min_size = min(len(filtered_target), len(filtered_ref))
            if min_size == 0: continue
            
            similarity = intersection / min_size
            
            if similarity >= threshold:
                return True
        return False

    def _collect_and_score(self, context: AssembledContext, weights: Dict[str, float]) -> List[Dict[str, Any]]:
        """Consolidates items into a rankable list."""
        all_items = []
        
        # We don't score conversation history here as it's usually treated as a block
        # Scoring Facts
        for i, f in enumerate(context.semantic_facts):
            all_items.append({
                'type': 'facts',
                'data': f,
                'score': weights['facts'] * (1.0 - (i * 0.05)), # Slight decay for position
                'tokens': self._count_tokens(f.get('content', ''))
            })
            
        # Scoring Graph
        if context.graph_context.get('results'):
            for i, r in enumerate(context.graph_context['results']):
                content = r.get('content', '')
                all_items.append({
                    'type': 'graph',
                    'data': r,
                    'score': weights['graph'] * (1.0 - (i * 0.1)),
                    'tokens': self._count_tokens(content)
                })
        
        # Sort by score descending
        all_items.sort(key=lambda x: x['score'], reverse=True)
        return all_items

    def _pack_to_budget(self, context: AssembledContext, items: List[Dict[str, Any]], budget: int):
        """Selects items until budget is full."""
        current_tokens = self._count_tokens(context.to_prompt_context())
        
        # Base context (Conversation and Insights) usually stays
        # We prune the rest:
        final_facts = []
        final_graph = []
        final_cross: Dict[str, List[Dict[str, Any]]] = {}
        
        for item in items:
            if current_tokens + item['tokens'] > budget:
                continue
                
            if item['type'] == 'facts':
                final_facts.append(item['data'])
            elif item['type'] == 'graph':
                final_graph.append(item['data'])
            elif item['type'] == 'cross_app':
                # Cross-app items have app_name in data
                app_name = item['data'].get('source_app', 'unknown')
                if app_name not in final_cross:
                    final_cross[app_name] = []
                final_cross[app_name].append(item['data'])
            
            current_tokens += item['tokens']
            
        context.semantic_facts = final_facts
        if context.graph_context.get('results'):
            context.graph_context['results'] = final_graph
        if final_cross:
            context.cross_app_content = final_cross

    def _count_tokens(self, text: str) -> int:
        if self.encoding:
            return len(self.encoding.encode(text))
        return len(text) // 4


class ContextAssembler:
    """
    Unified context assembly for agent queries.
    
    Combines all memory sources into a coherent context package:
    - Conversation history
    - Semantic facts/preferences
    - Multi-hop graph relationships
    - Cross-app correlations
    - Temporal context
    - Urgent insights
    
    Usage:
        assembler = ContextAssembler(
            config=config,
            conversation_memory=conv_mem,
            semantic_memory=sem_mem,
            graph_rag=graph_service,
            ...
        )
        
        context = await assembler.assemble_context(
            query="What did Sarah say about the project?",
            user_id=123,
            session_id="session-abc"
        )
        
        # Use in agent prompt
        prompt += context.to_prompt_context()
    """
    
    def __init__(
        self,
        config: Config,
        conversation_memory: Optional['ConversationMemory'] = None,
        semantic_memory: Optional['SemanticMemory'] = None,
        graph_rag: Optional['GraphRAGIntegrationService'] = None,
        cross_app_correlator: Optional['CrossAppCorrelator'] = None,
        insight_service: Optional['InsightService'] = None,
        temporal_indexer: Optional['TemporalIndexer'] = None,
        temporal_reasoner: Optional['TemporalReasoner'] = None
    ):
        self.config = config
        self.conversation_memory = conversation_memory
        self.semantic_memory = semantic_memory
        self.graph_rag = graph_rag
        self.cross_app_correlator = cross_app_correlator
        self.insight_service = insight_service
        self.temporal_indexer = temporal_indexer
        self.temporal_reasoner = temporal_reasoner
        
    async def assemble_context(
        self,
        query: str,
        user_id: int,
        session_id: str,
        intent: str = "general",
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        include_conversation: bool = True,
        include_facts: bool = True,
        include_graph: bool = True,
        include_cross_app: bool = True,
        include_temporal: bool = True,
        include_insights: bool = True
    ) -> AssembledContext:
        """
        Assemble comprehensive context for an agent query.
        
        Fetches from multiple sources in parallel for performance.
        Includes a pruning step to ensure token budgets are respected.
        """
        context = AssembledContext(query=query, user_id=user_id, intent=intent)
        
        # Build list of coroutines to run in parallel
        tasks = []
        task_keys = []
        
        if include_conversation and self.conversation_memory:
            tasks.append(self._fetch_conversation(user_id, session_id))
            task_keys.append('conversation')
            
        if include_facts and self.semantic_memory:
            tasks.append(self._fetch_facts(query, user_id))
            task_keys.append('facts')
            
        if include_graph and self.graph_rag:
            tasks.append(self._fetch_graph_context(query, user_id))
            task_keys.append('graph')
            
        if include_cross_app and self.cross_app_correlator:
            tasks.append(self._fetch_cross_app(query, user_id))
            task_keys.append('cross_app')
            
        if include_temporal and self.temporal_indexer:
            temporal_hint = self._parse_temporal_hint(query)
            if temporal_hint.start_date or (self.temporal_reasoner and "when" in query.lower()):
                tasks.append(self._fetch_temporal(temporal_hint, user_id, query))
                task_keys.append('temporal')
                
        if include_insights and self.insight_service:
            tasks.append(self._fetch_insights(user_id, query))
            task_keys.append('insights')
            
        # Execute all in parallel
        if tasks:
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Map results back to context
                for key, result in zip(task_keys, results):
                    if isinstance(result, Exception):
                        logger.debug(f"[ContextAssembler] {key} fetch failed: {result}")
                        continue
                        
                    if key == 'conversation':
                        context.conversation_history = result or []
                    elif key == 'facts':
                        context.semantic_facts = result or []
                    elif key == 'graph':
                        context.graph_context = result or {}
                    elif key == 'cross_app':
                        context.cross_app_content = result or {}
                    elif key == 'temporal':
                        context.temporal_context = result or []
                    elif key == 'insights':
                        context.urgent_insights = result or []
                        
            except Exception as e:
                logger.warning(f"[ContextAssembler] Parallel fetch failed: {e}")
                
        # --- NEW: Pruning & Reranking Stage ---
        try:
            # use_approx=True ensures we use fast local counting (cl100k_base) for the intensive loop
            pruner = ContextPruner(model=self.config.ai.model)
            context = pruner.prune(context, budget=token_budget, intent=intent)
            
            # --- HYBRID APPROACH ---
            # Use SDK for precise final count if it's a Gemini model
            # This follows the "once or twice per query" rule for SDK usage
            if "gemini" in self.config.ai.model.lower() and self.config.ai.api_key:
                context.token_count = await self._count_tokens_exact(context.to_prompt_context())
            else:
                context.token_count = context.get_token_count(model=self.config.ai.model)
                
        except Exception as prune_err:
            logger.error(f"[ContextAssembler] Pruning/Counting failed: {prune_err}")
            
        return context
    
    async def _count_tokens_exact(self, text: str) -> int:
        """
        Get exact token count using Google GenAI SDK.
        This involves a network call, so use sparingly (e.g. final prompt check).
        """
        if not text:
            return 0
            
        try:
            import google.generativeai as genai
            
            # Ensure configured (idempotent-ish check)
            if not getattr(genai, 'configure', None):
                 return len(text) // 4 # Fallback
            
            # We assume configure was called in LLMFactory or EmbeddingProvider, 
            # but to be safe/independent:
            if not genai._client: # Rough check if configured
                 genai.configure(api_key=self.config.ai.api_key)
            
            model = genai.GenerativeModel(self.config.ai.model)
            response = await model.count_tokens_async(text)
            return response.total_tokens
        except Exception as e:
            logger.warning(f"Failed to get exact token count from SDK: {e}. Falling back to approximation.")
            # Fallback to local approximation logic
            if HAS_TIKTOKEN:
                try:
                    enc = tiktoken.get_encoding("cl100k_base")
                    return len(enc.encode(text))
                except Exception:
                    # Encoding failed, use character approximation
                    pass
            return len(text) // 4
        
    async def _fetch_conversation(
        self,
        user_id: int,
        session_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch recent conversation messages."""
        try:
            # Check for enhanced conversation memory features
            if hasattr(self.conversation_memory, 'get_extended_semantic_context'):
                # This bundled result includes both history and facts
                # We'll use just the history part here for consistency
                history_data = await self.conversation_memory.get_relevant_context_from_history(
                    current_query="context_assembly", # Placeholder for broad context
                    user_id=user_id,
                    k=10
                )
                if history_data:
                    return history_data
            
            messages = await self.conversation_memory.get_recent_messages(
                user_id=user_id,
                session_id=session_id,
                limit=10 # Use internal limit, pruner will trim later
            )
            return messages or []
        except Exception as e:
            logger.debug(f"[ContextAssembler] Conversation fetch failed: {e}")
            return []
            
    async def _fetch_facts(
        self,
        query: str,
        user_id: int
    ) -> List[Dict[str, Any]]:
        """Fetch relevant semantic facts."""
        try:
            facts = await self.semantic_memory.search_facts(
                query=query,
                user_id=user_id,
                limit=10 # Higher limit, pruner will trim
            )
            return facts or []
        except Exception as e:
            logger.debug(f"[ContextAssembler] Facts fetch failed: {e}")
            return []
            
    async def _fetch_graph_context(
        self,
        query: str,
        user_id: int
    ) -> Dict[str, Any]:
        """Fetch multi-hop graph context."""
        try:
            # Use specific agent search if available for better relevance
            if hasattr(self.graph_rag, 'search_for_agent'):
                results = await self.graph_rag.search_for_agent(
                    query=query,
                    task_type="general",
                    user_id=user_id,
                    limit=10
                )
                return results or {}
                
            results = await self.graph_rag.search_with_multi_hop_context(
                query=query,
                max_hops=GRAPH_HOPS,
                max_results=10,
                filters={'user_id': str(user_id)}
            )
            return results or {}
        except Exception as e:
            logger.debug(f"[ContextAssembler] Graph fetch failed: {e}")
            return {}
            
    async def _fetch_cross_app(
        self,
        query: str,
        user_id: int
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch cross-app related content."""
        try:
            results = await self.cross_app_correlator.get_cross_app_context(
                query=query,
                user_id=user_id,
                primary_source='agent',  # Will be deprioritized
                max_per_app=3
            )
            return results or {}
        except Exception as e:
            logger.debug(f"[ContextAssembler] Cross-app fetch failed: {e}")
            return {}
            
    async def _fetch_temporal(
        self,
        hint: TemporalHint,
        user_id: int,
        query: str = ""
    ) -> List[Dict[str, Any]]:
        """Fetch events in time range, using TemporalReasoner if available."""
        try:
            # Prefer advanced reasoner if available
            if self.temporal_reasoner and query:
                context = await self.temporal_reasoner.reason_about_time(query, user_id)
                if context and context.activities:
                    # Convert to consistent format
                    return context.activities
            
            # Fallback to simple indexer lookup
            if not hint.start_date:
                return []
                
            end_date = hint.end_date or datetime.utcnow()
            
            events = await self.temporal_indexer.get_events_in_timeblock(
                start_time=hint.start_date,
                end_time=end_date,
                granularity=hint.granularity,
                user_id=user_id
            )
            return events or []
        except Exception as e:
            logger.debug(f"[ContextAssembler] Temporal fetch failed: {e}")
            return []
            
    async def _fetch_insights(
        self,
        user_id: int,
        current_context: str
    ) -> List[Dict[str, Any]]:
        """Fetch urgent insights."""
        try:
            insights = await self.insight_service.get_contextual_insights(
                user_id=user_id,
                current_context=current_context,
                max_insights=MAX_INSIGHTS
            )
            return insights or []
        except Exception as e:
            logger.debug(f"[ContextAssembler] Insights fetch failed: {e}")
            return []
            
    def _parse_temporal_hint(self, query: str) -> TemporalHint:
        """
        Parse temporal references from a query.
        
        Examples:
        - "last week" -> 7 days ago to now
        - "yesterday" -> yesterday start to end
        - "this morning" -> today 00:00 to 12:00
        """
        query_lower = query.lower()
        now = datetime.utcnow()
        hint = TemporalHint()
        
        # Check for common temporal patterns
        if 'yesterday' in query_lower:
            yesterday = now - timedelta(days=1)
            hint.start_date = yesterday.replace(hour=0, minute=0, second=0)
            hint.end_date = yesterday.replace(hour=23, minute=59, second=59)
            hint.description = "yesterday"
            hint.granularity = "day"
            
        elif 'last week' in query_lower:
            hint.start_date = now - timedelta(weeks=1)
            hint.end_date = now
            hint.description = "last week"
            hint.granularity = "week"
            
        elif 'this week' in query_lower:
            # Start of current week (Monday)
            start_of_week = now - timedelta(days=now.weekday())
            hint.start_date = start_of_week.replace(hour=0, minute=0, second=0)
            hint.end_date = now
            hint.description = "this week"
            hint.granularity = "week"
            
        elif 'last month' in query_lower:
            hint.start_date = now - timedelta(days=30)
            hint.end_date = now
            hint.description = "last month"
            hint.granularity = "month"
            
        elif 'today' in query_lower or 'this morning' in query_lower:
            hint.start_date = now.replace(hour=0, minute=0, second=0)
            hint.end_date = now
            hint.description = "today"
            hint.granularity = "day"
            
        return hint


# Global instance management
_assembler: Optional[ContextAssembler] = None


def get_context_assembler() -> Optional[ContextAssembler]:
    """Get the global ContextAssembler instance."""
    return _assembler


def init_context_assembler(
    config: Config,
    conversation_memory: Optional['ConversationMemory'] = None,
    semantic_memory: Optional['SemanticMemory'] = None,
    graph_rag: Optional['GraphRAGIntegrationService'] = None,
    cross_app_correlator: Optional['CrossAppCorrelator'] = None,
    insight_service: Optional['InsightService'] = None,
    temporal_indexer: Optional['TemporalIndexer'] = None,
    temporal_reasoner: Optional['TemporalReasoner'] = None
) -> ContextAssembler:
    """Initialize and return the global ContextAssembler instance."""
    global _assembler
    _assembler = ContextAssembler(
        config=config,
        conversation_memory=conversation_memory,
        semantic_memory=semantic_memory,
        graph_rag=graph_rag,
        cross_app_correlator=cross_app_correlator,
        insight_service=insight_service,
        temporal_indexer=temporal_indexer,
        temporal_reasoner=temporal_reasoner
    )
    return _assembler
