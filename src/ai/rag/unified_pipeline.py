"""
Unified RAG Pipeline

Combines all RAG improvements into a single, configurable search pipeline:
- Query decomposition for complex queries
- HyDE for vague/conceptual queries
- Self-RAG with relevance grading
- Cross-encoder reranking
- Feedback-based boosting
- Episode-based temporal boosting
- Contextual chunk enrichment

This is the recommended entry point for RAG search in the application.
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import asyncio

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the unified RAG pipeline."""
    # Feature toggles
    enable_decomposition: bool = True
    enable_hyde: bool = True
    enable_self_rag: bool = True
    enable_cross_encoder: bool = True
    enable_feedback: bool = True
    enable_episode_boosting: bool = True
    
    # Thresholds
    relevance_threshold: float = 0.4
    min_confidence: float = 0.3
    
    # Limits
    initial_k_multiplier: int = 3  # Fetch k * this for reranking
    max_expansion_attempts: int = 2
    
    # Weights
    cross_encoder_weight: float = 0.7
    feedback_weight: float = 0.2
    episode_boost_factor: float = 1.5


@dataclass
class PipelineResult:
    """Result from the unified pipeline."""
    results: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Pipeline execution details
    query_decomposed: bool = False
    hyde_used: bool = False
    self_rag_expanded: bool = False
    cross_encoder_applied: bool = False
    feedback_applied: bool = False
    episode_boosted: bool = False
    
    # Performance
    total_time_ms: float = 0
    stage_times: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'results': self.results,
            'metadata': self.metadata,
            'pipeline': {
                'decomposed': self.query_decomposed,
                'hyde': self.hyde_used,
                'self_rag_expanded': self.self_rag_expanded,
                'cross_encoder': self.cross_encoder_applied,
                'feedback': self.feedback_applied,
                'episode_boosted': self.episode_boosted,
                'total_time_ms': self.total_time_ms,
                'stage_times': self.stage_times
            }
        }


class UnifiedRAGPipeline:
    """
    Unified RAG Pipeline combining all improvements.
    
    Pipeline stages:
    1. Query Analysis → Decomposition + HyDE decision
    2. Initial Retrieval → Hybrid search with adaptive RRF
    3. Relevance Grading → Self-RAG check, expand if needed
    4. Reranking → Cross-encoder + feedback + episode boosting
    5. Final Selection → Top-k with diversity
    
    Usage:
        pipeline = UnifiedRAGPipeline(
            rag_engine=rag_engine,
            llm_client=llm_client,
            episode_detector=episode_detector
        )
        
        result = await pipeline.search(
            query="Compare emails from Carol with meeting notes about Q4",
            user_id=123,
            k=5
        )
    """
    
    def __init__(
        self,
        rag_engine: Any,
        llm_client: Optional[Any] = None,
        episode_detector: Optional[Any] = None,
        feedback_collector: Optional[Any] = None,
        fact_graph: Optional[Any] = None,
        config: Optional[PipelineConfig] = None
    ):
        """
        Initialize unified pipeline.
        
        Args:
            rag_engine: RAGEngine instance
            llm_client: LLM client for HyDE/expansion
            episode_detector: EpisodeDetector for temporal boosting
            feedback_collector: FeedbackCollector for learned preferences
            fact_graph: FactGraph for entity resolution and context
            config: Pipeline configuration
        """
        self.rag_engine = rag_engine
        self.llm_client = llm_client
        self.episode_detector = episode_detector
        self.feedback_collector = feedback_collector
        self.fact_graph = fact_graph
        self.config = config or PipelineConfig()
        
        # Lazy-load components
        self._decomposer = None
        self._hyde = None
        self._grader = None
        self._cross_encoder = None
        self._feedback_reranker = None
        self._episode_booster = None
        
        logger.info("UnifiedRAGPipeline initialized")
    
    def _get_decomposer(self):
        """Lazy load query decomposer."""
        if self._decomposer is None:
            from .query.query_decomposer import QueryDecomposer
            self._decomposer = QueryDecomposer()
        return self._decomposer
    
    def _get_hyde(self):
        """Lazy load HyDE generator."""
        if self._hyde is None:
            from .query.hyde import HyDEGenerator
            self._hyde = HyDEGenerator(self.llm_client)
        return self._hyde
    
    def _get_grader(self):
        """Lazy load relevance grader."""
        if self._grader is None:
            from .query.relevance_grader import RelevanceGrader
            self._grader = RelevanceGrader(
                expansion_threshold=self.config.relevance_threshold
            )
        return self._grader
    
    def _get_cross_encoder(self):
        """Lazy load cross-encoder reranker."""
        if self._cross_encoder is None:
            from .query.cross_encoder_reranker import CrossEncoderReranker
            self._cross_encoder = CrossEncoderReranker()
        return self._cross_encoder
    
    def _get_feedback_reranker(self):
        """Lazy load feedback reranker."""
        if self._feedback_reranker is None and self.feedback_collector:
            from .feedback import FeedbackReranker
            self._feedback_reranker = FeedbackReranker(
                self.feedback_collector,
                feedback_weight=self.config.feedback_weight
            )
        return self._feedback_reranker
    
    def _get_episode_booster(self):
        """Lazy load episode booster."""
        if self._episode_booster is None and self.episode_detector:
            from .reranking.episode_boosting import EpisodeBoostingReranker
            self._episode_booster = EpisodeBoostingReranker(
                self.episode_detector
            )
        return self._episode_booster
    
    async def search(
        self,
        query: str,
        user_id: Optional[int] = None,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> PipelineResult:
        """
        Execute the full RAG pipeline with adaptive routing.
        """
        start_time = datetime.utcnow()
        result = PipelineResult(results=[])
        
        try:
            # Stage 0: Adaptive Routing
            stage_start = datetime.utcnow()
            route = self._route_query(query)
            result.stage_times['routing'] = (datetime.utcnow() - stage_start).total_seconds() * 1000
            
            if route == 'FAST':
                logger.debug(f"Routing to FAST path for query: {query[:50]}")
                fast_results = self.rag_engine.fast_search(query, k=k, filters=filters)
                result.results = fast_results
                result.metadata['route'] = 'FAST'
                result.total_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                return result

            # FULL Path continues...
            fetch_k = k * self.config.initial_k_multiplier
            
            # Stage 1: Query Analysis & Graph Augmentation
            stage_start = datetime.utcnow()
            # Run query analysis and graph lookup in parallel
            analysis_task = asyncio.create_task(self._analyze_query(query))
            graph_task = asyncio.create_task(self._graph_augmentation(query, user_id))
            
            query_info, graph_context = await asyncio.gather(analysis_task, graph_task)
            result.metadata['graph_context'] = graph_context is not None
            result.stage_times['query_analysis'] = (datetime.utcnow() - stage_start).total_seconds() * 1000
            
            # Stage 2: Initial Retrieval
            stage_start = datetime.utcnow()
            
            # Augment query with graph context if available
            search_query = query
            if graph_context:
                search_query = f"{query} (Context: {graph_context})"
                logger.debug(f"Augmented query with graph context: {search_query[:100]}...")
            
            all_results = await self._initial_retrieval(
                search_query, query_info, fetch_k, filters
            )
            result.query_decomposed = query_info.get('decomposed', False)
            result.hyde_used = query_info.get('hyde_used', False)
            result.stage_times['initial_retrieval'] = (datetime.utcnow() - stage_start).total_seconds() * 1000
            
            # Stage 3: Self-RAG Relevance Check
            if self.config.enable_self_rag and all_results:
                stage_start = datetime.utcnow()
                all_results, expanded = await self._self_rag_check(
                    query, all_results, fetch_k, filters
                )
                result.self_rag_expanded = expanded
                result.stage_times['self_rag'] = (datetime.utcnow() - stage_start).total_seconds() * 1000
            
            # Stage 4: Cross-Encoder Reranking
            if self.config.enable_cross_encoder and all_results:
                stage_start = datetime.utcnow()
                all_results = await self._cross_encoder_rerank(query, all_results, fetch_k)
                result.cross_encoder_applied = True
                result.stage_times['cross_encoder'] = (datetime.utcnow() - stage_start).total_seconds() * 1000
            
            # Stage 5: Feedback-Based Boosting
            if self.config.enable_feedback and self._get_feedback_reranker() and all_results:
                stage_start = datetime.utcnow()
                all_results = await self._get_feedback_reranker().rerank(
                    query, all_results, k=fetch_k
                )
                result.feedback_applied = True
                result.stage_times['feedback'] = (datetime.utcnow() - stage_start).total_seconds() * 1000
            
            # Stage 6: Episode-Based Boosting
            if self.config.enable_episode_boosting and user_id and self._get_episode_booster():
                stage_start = datetime.utcnow()
                all_results = await self._get_episode_booster().rerank_with_episodes(
                    query, all_results, user_id, k=fetch_k
                )
                result.episode_boosted = True
                result.stage_times['episode_boost'] = (datetime.utcnow() - stage_start).total_seconds() * 1000
            
            # Final selection
            result.results = all_results[:k]
            result.metadata = {
                'query': query,
                'total_candidates': len(all_results),
                'returned': len(result.results)
            }
            
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            result.metadata['error'] = str(e)
            
            # Fallback to basic search
            try:
                fallback = await self.rag_engine.asearch(query, k=k, filters=filters)
                result.results = fallback
                result.metadata['fallback'] = True
            except Exception as fallback_err:
                logger.debug(f"Fallback search also failed: {fallback_err}")
        
        result.total_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        logger.info(
            f"Pipeline complete: {len(result.results)} results in {result.total_time_ms:.0f}ms "
            f"(decomposed={result.query_decomposed}, hyde={result.hyde_used}, "
            f"self_rag={result.self_rag_expanded}, cross_encoder={result.cross_encoder_applied})"
        )
        
        return result
    
    async def _analyze_query(self, query: str) -> Dict[str, Any]:
        """Analyze query for decomposition and HyDE applicability."""
        info = {'original': query, 'decomposed': False, 'hyde_used': False}
        
        # Check for decomposition
        if self.config.enable_decomposition:
            decomposer = self._get_decomposer()
            from .query.query_decomposer import QueryComplexity
            decomposition = decomposer.decompose(query)
            
            if decomposition.complexity != QueryComplexity.SIMPLE:
                info['decomposed'] = True
                info['sub_queries'] = [sq.query for sq in decomposition.sub_queries]
                info['complexity'] = decomposition.complexity.value
        
        # Check for HyDE applicability
        if self.config.enable_hyde and self.llm_client:
            hyde = self._get_hyde()
            info['hyde_recommended'] = hyde.should_use_hyde(query)
        
        return info
    
    async def _initial_retrieval(
        self,
        query: str,
        query_info: Dict[str, Any],
        k: int,
        filters: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Perform initial retrieval with decomposition/HyDE if applicable."""
        
        # Case 1: Decomposed query
        if query_info.get('decomposed') and self.config.enable_decomposition:
            from .query.query_decomposer import DecomposedRAGExecutor
            decomposer = self._get_decomposer()
            executor = DecomposedRAGExecutor(self.rag_engine, decomposer)
            
            result = await executor.execute(query, k, filters)
            return result.get('aggregated_results', [])
        
        # Case 2: HyDE applicable
        if query_info.get('hyde_recommended') and self.config.enable_hyde and self.llm_client:
            hyde = self._get_hyde()
            result = await hyde.search_with_hyde(query, self.rag_engine, k, filters)
            query_info['hyde_used'] = result['metadata'].get('hyde_used', False)
            return result['results']
        
        # Case 3: Standard search
        return await self.rag_engine.asearch(query, k=k, filters=filters)
    
    async def _self_rag_check(
        self,
        query: str,
        results: List[Dict[str, Any]],
        k: int,
        filters: Optional[Dict[str, Any]]
    ) -> tuple:
        """Check relevance and expand query if needed."""
        grader = self._get_grader()
        enhanced = await self.rag_engine.query_enhancer.enhance(query)
        
        relevance = grader.grade_chunks(results[:min(k, len(results))], enhanced)
        
        if not relevance.should_expand_query:
            return results, False
        
        # Expand query
        logger.debug(f"Self-RAG: Low relevance ({relevance.score:.2f}), expanding")
        
        for reform in enhanced.get('reformulated', [])[:2]:
            if reform.lower() != query.lower():
                extra = await self.rag_engine.asearch(reform, k=k, filters=filters)
                results = self._merge_results(results, extra)
                break
        
        return results, True
    
    async def _cross_encoder_rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        k: int
    ) -> List[Dict[str, Any]]:
        """Apply cross-encoder reranking."""
        try:
            cross_encoder = self._get_cross_encoder()
            return await cross_encoder.arerank(query, results, k=k)
        except Exception as e:
            logger.debug(f"Cross-encoder skipped: {e}")
            return results
    
    def _merge_results(
        self,
        primary: List[Dict[str, Any]],
        secondary: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge and deduplicate results."""
        seen = set()
        merged = []
        
        for result in primary + secondary:
            result_id = result.get('id') or result.get('doc_id')
            if result_id and result_id not in seen:
                seen.add(result_id)
                merged.append(result)
            elif not result_id:
                merged.append(result)
        
        merged.sort(key=lambda x: x.get('score', 0), reverse=True)
        return merged


    def _route_query(self, query: str) -> str:
        """
        Determine if query should take the FAST or FULL path.
        
        FAST: Direct vector search for specific entities or simple keywords.
        FULL: Multi-step decomposition, HyDE, and intensive reranking.
        """
        words = query.lower().split()
        
        # 1. Very short queries are likely entity/keyword searches
        if len(words) <= 3:
            return 'FAST'
            
        # 2. Check for complex markers
        complex_markers = ['compare', 'difference', 'versus', 'vs', 'both', 'analyze', 'summarize', 'total']
        if any(m in query.lower() for m in complex_markers):
            return 'FULL'
            
        # 3. Check for sequential markers
        if any(m in query.lower() for m in ['then', 'after', 'following']):
            return 'FULL'
            
        # 4. Default to FULL for medium/long queries for accuracy
        return 'FULL'

    async def _graph_augmentation(self, query: str, user_id: Optional[int]) -> Optional[str]:
        """
        Resolve entities in query using FactGraph.
        """
        if not self.fact_graph or not user_id:
            return None
            
        try:
            # Simple entity extraction from query (can be improved)
            from src.ai.memory.memory_utils import extract_entities
            entities = extract_entities(query)
            
            if not entities:
                return None
                
            graph_facts = []
            for entity in entities:
                facts = self.fact_graph.get_facts_by_entity(entity)
                if facts:
                    # Take top 2 facts per entity
                    graph_facts.extend([f.content for f in facts[:2]])
            
            if graph_facts:
                return "Known Context: " + " | ".join(graph_facts)
        except Exception as e:
            logger.debug(f"Graph augmentation failed: {e}")
            
        return None


def create_unified_pipeline(
    rag_engine: Any,
    llm_client: Optional[Any] = None,
    episode_detector: Optional[Any] = None,
    feedback_collector: Optional[Any] = None,
    fact_graph: Optional[Any] = None,
    **config_kwargs
) -> UnifiedRAGPipeline:
    """
    Factory function to create a configured pipeline.
    """
    config = PipelineConfig(**config_kwargs)
    
    return UnifiedRAGPipeline(
        rag_engine=rag_engine,
        llm_client=llm_client,
        episode_detector=episode_detector,
        feedback_collector=feedback_collector,
        fact_graph=fact_graph,
        config=config
    )
