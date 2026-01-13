"""
Enhanced Semantic Memory

Builds on the existing SemanticMemory to add:
- Rich fact model with provenance tracking
- Hierarchical organization via FactGraph
- Automatic inference via FactInferenceEngine
- Temporal intelligence
- Active learning with clarification questions

This is the "Powerful" version of semantic memory.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Set
from enum import Enum

from src.ai.memory.semantic_memory import SemanticMemory, FactValidationResult
from src.ai.memory.fact_inference import (
    FactInferenceEngine, 
    InferredFact,
    get_inference_engine,
    init_inference_engine
)
from src.ai.memory.fact_graph import (
    FactGraph,
    FactGraphManager,
    FactNode,
    FactCategory,
    get_fact_graph_manager,
    init_fact_graph_manager
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class FactProvenance:
    """Tracks the source and history of a fact."""
    source_type: str  # user_explicit, user_confirmed, behavior_observed, single_observation, inferred, imported
    source_chain: List[Dict[str, Any]] = field(default_factory=list)
    
    # Trust score based on source type
    trust_score: float = 0.5
    
    # Corroboration
    corroboration_count: int = 0
    corroborating_sources: List[str] = field(default_factory=list)
    
    # History
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_verified: Optional[datetime] = None
    modification_history: List[Dict] = field(default_factory=list)
    
    def add_corroboration(self, source: str, evidence: str):
        """Add corroborating evidence."""
        self.corroboration_count += 1
        self.corroborating_sources.append(source)
        self.trust_score = min(1.0, self.trust_score + 0.05)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "trust_score": self.trust_score,
            "corroboration_count": self.corroboration_count,
            "corroborating_sources": self.corroborating_sources,
            "created_at": self.created_at.isoformat()
        }
    
    @classmethod
    def from_source_type(cls, source_type: str) -> "FactProvenance":
        """Create provenance with trust score based on source type."""
        trust_map = {
            "user_explicit": 1.0,
            "user_confirmed": 0.95,
            "behavior_observed": 0.8,
            "single_observation": 0.6,
            "inferred": 0.5,
            "imported": 0.4
        }
        return cls(
            source_type=source_type,
            trust_score=trust_map.get(source_type, 0.5)
        )


@dataclass
class ClarificationQuestion:
    """A question to clarify uncertain or conflicting facts."""
    question: str
    priority: str  # high, medium, low
    reason: str
    fact_ids: List[int] = field(default_factory=list)
    conflict_type: str = "uncertainty"  # uncertainty, contradiction, outdated
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EnhancedFactResult:
    """Result from enhanced fact operations."""
    fact_id: Optional[int]
    content: str
    category: str
    confidence: float
    provenance: FactProvenance
    entities: List[str]
    validation_result: str
    inferences_generated: List[InferredFact] = field(default_factory=list)


class EnhancedSemanticMemory:
    """
    Enhanced semantic memory with inference and organization.
    
    Capabilities:
    - All base SemanticMemory features (contradiction detection, etc.)
    - Rich fact model with provenance
    - Hierarchical organization
    - Automatic inference
    - Temporal intelligence
    - Active learning
    """
    
    # Source type trust hierarchy
    SOURCE_TRUST = {
        "user_explicit": 1.0,
        "user_confirmed": 0.95,
        "behavior_observed": 0.8,
        "single_observation": 0.6,
        "inferred": 0.5,
        "imported": 0.4
    }
    
    def __init__(
        self,
        base_memory: SemanticMemory,
        inference_engine: Optional[FactInferenceEngine] = None,
        graph_manager: Optional[FactGraphManager] = None,
        llm: Optional[Any] = None
    ):
        """
        Initialize enhanced semantic memory.
        
        Args:
            base_memory: The underlying SemanticMemory instance
            inference_engine: Optional FactInferenceEngine
            graph_manager: Optional FactGraphManager
            llm: Optional LLM for clarification generation
        """
        self.base = base_memory
        self.inference_engine = inference_engine or get_inference_engine()
        self.graph_manager = graph_manager or get_fact_graph_manager()
        self.llm = llm
        
        # Pending clarifications per user
        self._clarifications: Dict[int, List[ClarificationQuestion]] = {}
        
        # Access tracking
        self._access_log: Dict[int, List[Tuple[int, datetime]]] = {}  # user_id -> [(fact_id, timestamp)]
        
        logger.info("[EnhancedSemanticMemory] Initialized")
    
    async def learn_fact_enhanced(
        self,
        user_id: int,
        content: str,
        category: str = "general",
        source: str = "agent",
        source_type: str = "single_observation",
        confidence: Optional[float] = None,
        entities: Optional[List[str]] = None,
        provenance_data: Optional[Dict] = None,
        valid_until: Optional[datetime] = None,
        run_inference: bool = True
    ) -> EnhancedFactResult:
        """
        Learn a fact with full enhanced processing.
        
        Args:
            user_id: User ID
            content: Fact content
            category: Fact category
            source: Source of the fact
            source_type: Type of source for trust scoring
            confidence: Override confidence (auto-calculated if None)
            entities: Entities mentioned (auto-extracted if None)
            provenance_data: Additional provenance info
            valid_until: Expiration date for temporal facts
            run_inference: Whether to run inference after learning
            
        Returns:
            EnhancedFactResult with all details
        """
        # Calculate confidence from source type if not provided
        if confidence is None:
            confidence = self.SOURCE_TRUST.get(source_type, 0.5)
        
        # Create provenance
        provenance = FactProvenance.from_source_type(source_type)
        if provenance_data:
            provenance.source_chain.append(provenance_data)
        
        # Auto-extract entities if not provided
        if entities is None:
            entities = self._extract_entities(content)
        
        # Learn via base memory (with validation)
        fact_id, validation_result = await self.base.learn_fact(
            user_id=user_id,
            content=content,
            category=category,
            source=source,
            confidence=confidence,
            validate=True
        )
        
        # Add to fact graph if available
        if self.graph_manager and fact_id:
            graph = self.graph_manager.get_or_create(user_id)
            
            # Map category string to FactCategory enum
            cat_map = {
                "preference": FactCategory.PREFERENCE,
                "relationship": FactCategory.RELATIONSHIP,
                "expertise": FactCategory.EXPERTISE,
                "goal": FactCategory.GOAL,
                "context": FactCategory.CONTEXT,
                "inferred": FactCategory.INFERRED,
            }
            fact_category = cat_map.get(category.lower(), FactCategory.DOMAIN)
            
            graph.add_fact(
                content=content,
                category=fact_category,
                confidence=confidence,
                entities=entities,
                source=source,
                source_type=source_type,
                provenance=[provenance.to_dict()],
                valid_until=valid_until,
                fact_id=fact_id
            )
        
        # Run inference on new fact if enabled
        inferences = []
        if run_inference and self.inference_engine and fact_id:
            try:
                # Get recent facts for inference context
                recent_facts = await self.base.get_facts(
                    user_id=user_id,
                    limit=30,
                    min_confidence=0.4
                )
                
                # Add the new fact
                recent_facts.append({
                    "id": fact_id,
                    "content": content,
                    "category": category,
                    "confidence": confidence
                })
                
                # Run inference
                inferences = await self.inference_engine.infer_from_facts(
                    facts=recent_facts,
                    user_id=user_id,
                    max_inferences=3
                )
                
                # Store high-confidence inferences
                for inf in inferences:
                    if inf.confidence >= 0.6:
                        await self.base.learn_fact(
                            user_id=user_id,
                            content=inf.content,
                            category=inf.suggested_category,
                            source="inference_engine",
                            confidence=inf.confidence,
                            validate=True
                        )
                        logger.info(
                            f"[EnhancedSemanticMemory] Inferred: "
                            f"'{inf.content[:50]}...' (conf: {inf.confidence:.2f})"
                        )
                        
            except Exception as e:
                logger.debug(f"[EnhancedSemanticMemory] Inference failed: {e}")
        
        # Check for potential clarifications needed
        if validation_result == FactValidationResult.CONTRADICTION:
            self._add_clarification(
                user_id=user_id,
                question=f"There's a conflict: '{content[:50]}...' vs existing knowledge. Which is correct?",
                priority="high",
                reason="Detected contradiction",
                fact_ids=[fact_id] if fact_id else [],
                conflict_type="contradiction"
            )
        
        return EnhancedFactResult(
            fact_id=fact_id,
            content=content,
            category=category,
            confidence=confidence,
            provenance=provenance,
            entities=entities,
            validation_result=validation_result.value if isinstance(validation_result, FactValidationResult) else validation_result,
            inferences_generated=inferences
        )
    
    async def search_enhanced(
        self,
        query: str,
        user_id: int,
        limit: int = 10,
        min_confidence: float = 0.3,
        categories: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        include_inferred: bool = True,
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Enhanced search with multiple filters.
        
        Args:
            query: Search query
            user_id: User ID
            limit: Max results
            min_confidence: Minimum confidence threshold
            categories: Optional category filter
            entities: Optional entity filter
            include_inferred: Include inferred facts
            include_expired: Include expired temporal facts
        """
        results = []
        
        # Search base memory
        base_results = await self.base.search_facts(
            query=query,
            user_id=user_id,
            limit=limit * 2  # Get more to filter
        )
        
        # Search graph if available for entity-based results
        graph_results = []
        if self.graph_manager and entities:
            graph = self.graph_manager.get(user_id)
            if graph:
                for entity in entities[:3]:
                    entity_facts = graph.get_facts_by_entity(entity, min_confidence)
                    graph_results.extend([f.to_dict() for f in entity_facts])
        
        # Combine results
        all_results = base_results + graph_results
        
        # Deduplicate
        seen_ids = set()
        for result in all_results:
            rid = result.get("id")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                
                # Apply filters
                conf = result.get("confidence", 0.5)
                if conf < min_confidence:
                    continue
                
                cat = result.get("category", "")
                if categories and cat not in categories:
                    continue
                
                if not include_inferred and result.get("source") == "inference_engine":
                    continue
                
                results.append(result)
        
        # Record access
        self._record_access(user_id, [r.get("id") for r in results if r.get("id")])
        
        # Sort by confidence and relevance
        results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return results[:limit]
    
    async def get_context_bundle(
        self,
        user_id: int,
        query: Optional[str] = None,
        entities: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        max_facts: int = 10
    ) -> Dict[str, Any]:
        """
        Get a comprehensive context bundle for LLM injection.
        
        Returns organized facts by category with relevance to query.
        """
        bundle = {
            "preferences": [],
            "relationships": [],
            "expertise": [],
            "inferred": [],
            "context_string": ""
        }
        
        # Get from graph for organized retrieval
        if self.graph_manager:
            graph = self.graph_manager.get(user_id)
            if graph:
                # Get preferences
                prefs = graph.get_facts_by_category(
                    FactCategory.PREFERENCE, 
                    min_confidence=0.5
                )[:4]
                bundle["preferences"] = [f.content for f in prefs]
                
                # Get relationships
                rels = graph.get_facts_by_category(
                    FactCategory.RELATIONSHIP, 
                    min_confidence=0.5
                )[:3]
                bundle["relationships"] = [f.content for f in rels]
                
                # Get expertise
                exp = graph.get_facts_by_category(
                    FactCategory.EXPERTISE, 
                    min_confidence=0.5
                )[:2]
                bundle["expertise"] = [f.content for f in exp]
                
                # Entity-specific facts
                if entities:
                    for entity in entities[:2]:
                        entity_facts = graph.get_facts_by_entity(entity)[:2]
                        bundle["inferred"].extend([f.content for f in entity_facts])
                
                # Generate context string
                bundle["context_string"] = graph.format_for_context(
                    categories=[FactCategory.PREFERENCE, FactCategory.RELATIONSHIP],
                    max_per_category=3
                )
        
        # Add query-relevant facts
        if query:
            relevant = await self.search_enhanced(
                query=query,
                user_id=user_id,
                limit=5,
                min_confidence=0.5
            )
            bundle["query_relevant"] = [r.get("content") for r in relevant]
        
        return bundle
    
    async def generate_inferences(
        self,
        user_id: int,
        max_inferences: int = 5
    ) -> List[InferredFact]:
        """
        Generate new inferences from all user facts.
        
        Useful for periodic batch inference.
        """
        if not self.inference_engine:
            return []
        
        # Get all high-quality facts
        facts = await self.base.get_facts(
            user_id=user_id,
            limit=50,
            min_confidence=0.5
        )
        
        if len(facts) < 3:
            return []
        
        inferences = await self.inference_engine.infer_from_facts(
            facts=facts,
            user_id=user_id,
            max_inferences=max_inferences
        )
        
        return inferences
    
    def get_clarifications(
        self, 
        user_id: int,
        limit: int = 5
    ) -> List[ClarificationQuestion]:
        """Get pending clarification questions for a user."""
        questions = self._clarifications.get(user_id, [])
        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        sorted_q = sorted(questions, key=lambda x: priority_order.get(x.priority, 2))
        return sorted_q[:limit]
    
    async def apply_clarification(
        self,
        user_id: int,
        question_index: int,
        resolution: str,
        new_content: Optional[str] = None
    ):
        """
        Apply user's answer to a clarification question.
        
        Args:
            user_id: User ID
            question_index: Index of the question
            resolution: User's resolution ('keep_new', 'keep_old', 'update')
            new_content: New content if resolution is 'update'
        """
        questions = self._clarifications.get(user_id, [])
        if question_index >= len(questions):
            return
        
        question = questions[question_index]
        
        for fact_id in question.fact_ids:
            if resolution == "keep_new":
                # Boost confidence of new fact
                await self.base.resolve_contradiction(
                    fact_id=fact_id,
                    resolution="keep",
                    new_confidence=0.9
                )
            elif resolution == "keep_old":
                # Delete new conflicting fact
                await self.base.resolve_contradiction(
                    fact_id=fact_id,
                    resolution="delete"
                )
        
        # Remove the question
        questions.pop(question_index)
    
    def _add_clarification(
        self,
        user_id: int,
        question: str,
        priority: str,
        reason: str,
        fact_ids: List[int],
        conflict_type: str
    ):
        """Add a clarification question."""
        if user_id not in self._clarifications:
            self._clarifications[user_id] = []
        
        self._clarifications[user_id].append(ClarificationQuestion(
            question=question,
            priority=priority,
            reason=reason,
            fact_ids=fact_ids,
            conflict_type=conflict_type
        ))
    
    def _extract_entities(self, content: str) -> List[str]:
        """Extract entities from content using shared utility."""
        from .memory_utils import extract_entities
        return extract_entities(content)
    
    def _record_access(self, user_id: int, fact_ids: List[int]):
        """Record fact access for analytics."""
        if user_id not in self._access_log:
            self._access_log[user_id] = []
        
        now = datetime.utcnow()
        for fid in fact_ids:
            if fid:
                self._access_log[user_id].append((fid, now))
        
        # Trim old access logs (keep last 1000)
        if len(self._access_log[user_id]) > 1000:
            self._access_log[user_id] = self._access_log[user_id][-1000:]
    
    def get_most_accessed_facts(
        self, 
        user_id: int, 
        days: int = 7,
        limit: int = 10
    ) -> List[Tuple[int, int]]:
        """Get most frequently accessed facts."""
        if user_id not in self._access_log:
            return []
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        # Count accesses
        counts = {}
        for fid, ts in self._access_log[user_id]:
            if ts >= cutoff:
                counts[fid] = counts.get(fid, 0) + 1
        
        # Sort by count
        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_counts[:limit]
    
    def get_stats(self, user_id: int) -> Dict[str, Any]:
        """Get enhanced memory stats for a user."""
        stats = {
            "pending_clarifications": len(self._clarifications.get(user_id, [])),
            "access_log_size": len(self._access_log.get(user_id, [])),
        }
        
        if self.graph_manager:
            graph = self.graph_manager.get(user_id)
            if graph:
                stats["graph_stats"] = graph.get_stats()
        
        return stats


# Factory function
def create_enhanced_semantic_memory(
    base_memory: SemanticMemory,
    llm: Optional[Any] = None
) -> EnhancedSemanticMemory:
    """
    Create an enhanced semantic memory instance.
    
    This initializes the inference engine and graph manager if not already done.
    """
    # Initialize global components if needed
    if not get_inference_engine():
        init_inference_engine(llm=llm)
    
    if not get_fact_graph_manager():
        init_fact_graph_manager()
    
    return EnhancedSemanticMemory(
        base_memory=base_memory,
        inference_engine=get_inference_engine(),
        graph_manager=get_fact_graph_manager(),
        llm=llm
    )
