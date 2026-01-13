"""
Salience Scorer

Scores memories by importance/relevance for prioritized retrieval.

Not all memories are equal. This scorer helps determine which memories
should be surfaced to agents based on multiple factors:
- Recency (exponential decay)
- Frequency (how often accessed)
- Relevance (semantic similarity to current query)
- Importance (explicit importance markers)
- Goal alignment (relation to active goals)
- Entity overlap (shared entities with current context)
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import math
import re

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class ScoredMemory:
    """A memory with its computed salience score."""
    content: str
    score: float
    source: str  # 'semantic', 'graph', 'conversation', 'working'
    metadata: Dict[str, Any]
    
    # Score breakdown for explainability
    recency_score: float = 0.0
    frequency_score: float = 0.0
    relevance_score: float = 0.0
    importance_score: float = 0.0
    goal_alignment_score: float = 0.0
    entity_overlap_score: float = 0.0
    
    def explain_score(self) -> str:
        """Explain why this memory scored as it did."""
        parts = []
        if self.recency_score > 0.1:
            parts.append(f"recent({self.recency_score:.2f})")
        if self.frequency_score > 0.1:
            parts.append(f"frequent({self.frequency_score:.2f})")
        if self.relevance_score > 0.1:
            parts.append(f"relevant({self.relevance_score:.2f})")
        if self.importance_score > 0.1:
            parts.append(f"important({self.importance_score:.2f})")
        if self.goal_alignment_score > 0.1:
            parts.append(f"goal-aligned({self.goal_alignment_score:.2f})")
        if self.entity_overlap_score > 0.1:
            parts.append(f"entity-match({self.entity_overlap_score:.2f})")
        return " + ".join(parts) if parts else "base"


class SalienceScorer:
    """
    Scores memories by importance/relevance for prioritized retrieval.
    
    Factors:
    - Recency (exponential decay) - recent memories score higher
    - Frequency (access count bonus) - frequently accessed memories score higher
    - Relevance (semantic similarity) - memories related to query score higher
    - Importance (explicit markers) - explicitly important memories score higher
    - Goal alignment (goal matching) - memories related to active goals score higher
    - Entity overlap (shared entities) - memories sharing entities with context score higher
    """
    
    # Default weights for each factor (can be overridden)
    DEFAULT_WEIGHTS = {
        "recency": 0.20,
        "frequency": 0.10,
        "relevance": 0.30,
        "importance": 0.15,
        "goal_alignment": 0.15,
        "entity_overlap": 0.10
    }
    
    # Decay parameters
    RECENCY_HALF_LIFE_HOURS = 24  # Memory "importance" halves every 24 hours
    FREQUENCY_LOG_BASE = 2  # Logarithmic frequency bonus
    
    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        embedder: Optional[Any] = None
    ):
        """
        Initialize the salience scorer.
        
        Args:
            weights: Custom weights for each factor (must sum to ~1.0)
            embedder: Optional embedding model for semantic similarity
        """
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self.embedder = embedder
        
        # Normalize weights to sum to 1.0
        weight_sum = sum(self.weights.values())
        if abs(weight_sum - 1.0) > 0.01:
            for k in self.weights:
                self.weights[k] /= weight_sum
    
    def score(
        self,
        memory: Dict[str, Any],
        query: str,
        active_goals: Optional[List[str]] = None,
        current_entities: Optional[List[str]] = None,
        now: Optional[datetime] = None
    ) -> ScoredMemory:
        """
        Calculate salience score for a memory.
        
        Args:
            memory: Dictionary with 'content', 'timestamp', 'access_count', 
                   'importance', 'entities', etc.
            query: The current user query
            active_goals: List of active user goals
            current_entities: Entities in current context
            now: Current time (for testing)
            
        Returns:
            ScoredMemory with score from 0.0 to 1.0 (1.0 = highest salience)
        """
        now = now or datetime.utcnow()
        active_goals = active_goals or []
        current_entities = current_entities or []
        
        content = memory.get("content", "")
        metadata = memory.get("metadata", {})
        source = memory.get("source", "unknown")
        
        # Calculate individual scores
        recency = self._recency_decay(memory.get("timestamp"), now)
        frequency = self._frequency_bonus(memory.get("access_count", 1))
        relevance = self._semantic_similarity(content, query)
        importance = memory.get("importance", 0.5)
        goal_align = self._goal_alignment(content, active_goals)
        entity_overlap = self._entity_overlap(
            memory.get("entities", []), 
            current_entities
        )
        
        # Weighted combination
        total_score = (
            self.weights["recency"] * recency +
            self.weights["frequency"] * frequency +
            self.weights["relevance"] * relevance +
            self.weights["importance"] * importance +
            self.weights["goal_alignment"] * goal_align +
            self.weights["entity_overlap"] * entity_overlap
        )
        
        return ScoredMemory(
            content=content,
            score=min(1.0, max(0.0, total_score)),
            source=source,
            metadata=metadata,
            recency_score=recency,
            frequency_score=frequency,
            relevance_score=relevance,
            importance_score=importance,
            goal_alignment_score=goal_align,
            entity_overlap_score=entity_overlap
        )
    
    def score_batch(
        self,
        memories: List[Dict[str, Any]],
        query: str,
        active_goals: Optional[List[str]] = None,
        current_entities: Optional[List[str]] = None,
        top_k: Optional[int] = None
    ) -> List[ScoredMemory]:
        """
        Score a batch of memories and return sorted by salience.
        
        Args:
            memories: List of memory dictionaries
            query: Current user query
            active_goals: Active user goals
            current_entities: Entities in current context
            top_k: Only return top K highest scoring memories
            
        Returns:
            List of ScoredMemory sorted by score (highest first)
        """
        now = datetime.utcnow()
        
        scored = [
            self.score(m, query, active_goals, current_entities, now)
            for m in memories
        ]
        
        # Sort by score descending
        scored.sort(key=lambda x: x.score, reverse=True)
        
        if top_k is not None:
            scored = scored[:top_k]
        
        return scored
    
    def _recency_decay(
        self, 
        timestamp: Any, 
        now: datetime
    ) -> float:
        """
        Calculate recency score using exponential decay.
        
        Recent memories get higher scores, with decay over time.
        Half-life: RECENCY_HALF_LIFE_HOURS
        """
        if timestamp is None:
            return 0.5  # Default for unknown timestamps
        
        # Parse timestamp if string
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                return 0.5
        
        # Handle timezone-naive comparison
        if timestamp.tzinfo and not now.tzinfo:
            now = now.replace(tzinfo=timestamp.tzinfo)
        elif now.tzinfo and not timestamp.tzinfo:
            timestamp = timestamp.replace(tzinfo=now.tzinfo)
        
        try:
            age_hours = (now - timestamp).total_seconds() / 3600
        except TypeError:
            # Fallback if datetime comparison fails
            return 0.5
        
        if age_hours < 0:
            return 1.0  # Future timestamps get max score
        
        # Exponential decay: score = 2^(-age/half_life)
        decay = math.pow(2, -age_hours / self.RECENCY_HALF_LIFE_HOURS)
        return decay
    
    def _frequency_bonus(self, access_count: int) -> float:
        """
        Calculate frequency bonus using logarithmic scaling.
        
        More frequently accessed memories get higher scores,
        but with diminishing returns (log scale).
        """
        if access_count <= 0:
            return 0.0
        
        # Log scaling: log2(access_count + 1) / log2(max_expected + 1)
        # Assuming max expected is ~100 accesses for normalization
        max_expected = 100
        normalized = math.log(access_count + 1, self.FREQUENCY_LOG_BASE)
        max_normalized = math.log(max_expected + 1, self.FREQUENCY_LOG_BASE)
        
        return min(1.0, normalized / max_normalized)
    
    def _semantic_similarity(self, content: str, query: str) -> float:
        """
        Calculate semantic similarity between content and query.
        
        Uses embeddings if available, otherwise falls back to
        keyword matching.
        """
        if not content or not query:
            return 0.0
        
        # Use embeddings if available
        if self.embedder:
            try:
                # Assuming embedder has encode() method returning vectors
                content_vec = self.embedder.encode(content)
                query_vec = self.embedder.encode(query)
                
                # Cosine similarity
                dot_product = sum(a * b for a, b in zip(content_vec, query_vec))
                norm_content = math.sqrt(sum(a * a for a in content_vec))
                norm_query = math.sqrt(sum(b * b for b in query_vec))
                
                if norm_content > 0 and norm_query > 0:
                    return (dot_product / (norm_content * norm_query) + 1) / 2
            except Exception as e:
                logger.debug(f"Embedding similarity failed: {e}")
        
        # Fallback: Keyword-based similarity
        return self._keyword_similarity(content, query)
    
    def _keyword_similarity(self, content: str, query: str) -> float:
        """
        Calculate keyword-based similarity (Jaccard-like).
        
        Simple but effective fallback when embeddings unavailable.
        """
        # Tokenize
        content_words = set(self._tokenize(content.lower()))
        query_words = set(self._tokenize(query.lower()))
        
        if not content_words or not query_words:
            return 0.0
        
        # Jaccard similarity with length normalization
        intersection = len(content_words & query_words)
        union = len(content_words | query_words)
        
        if union == 0:
            return 0.0
        
        jaccard = intersection / union
        
        # Boost if query words appear in content
        query_coverage = intersection / len(query_words) if query_words else 0
        
        # Weighted combination
        return 0.4 * jaccard + 0.6 * query_coverage
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for keyword matching."""
        # Remove punctuation and split
        words = re.findall(r'\b\w+\b', text)
        # Filter stopwords
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'must', 'can',
            'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'as', 'into', 'through', 'during', 'before', 'after',
            'above', 'below', 'between', 'under', 'again', 'further',
            'then', 'once', 'here', 'there', 'when', 'where', 'why',
            'how', 'all', 'each', 'few', 'more', 'most', 'other',
            'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same',
            'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if',
            'or', 'because', 'until', 'while', 'about', 'against',
            'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'you',
            'your', 'he', 'him', 'his', 'she', 'her', 'it', 'its',
            'they', 'them', 'their', 'what', 'which', 'who', 'whom'
        }
        return [w for w in words if w not in stopwords and len(w) > 1]
    
    def _goal_alignment(self, content: str, goals: List[str]) -> float:
        """
        Calculate alignment with active user goals.
        
        Higher score if content relates to any active goal.
        """
        if not goals or not content:
            return 0.0
        
        content_lower = content.lower()
        max_alignment = 0.0
        
        for goal in goals:
            goal_lower = goal.lower()
            
            # Check direct substring match
            if goal_lower in content_lower:
                return 1.0
            
            # Check keyword overlap
            goal_words = set(self._tokenize(goal_lower))
            content_words = set(self._tokenize(content_lower))
            
            if goal_words:
                overlap = len(goal_words & content_words) / len(goal_words)
                max_alignment = max(max_alignment, overlap)
        
        return max_alignment
    
    def _entity_overlap(
        self, 
        memory_entities: List[str], 
        current_entities: List[str]
    ) -> float:
        """
        Calculate entity overlap between memory and current context.
        
        Higher score if memory mentions entities from current context.
        """
        if not memory_entities or not current_entities:
            return 0.0
        
        # Normalize entity names for comparison
        memory_set = {e.lower().strip() for e in memory_entities}
        current_set = {e.lower().strip() for e in current_entities}
        
        overlap = len(memory_set & current_set)
        
        # Normalize by size of current context (what we're looking for)
        if current_set:
            return overlap / len(current_set)
        
        return 0.0
    
    def adjust_weights_for_task(self, task_type: str) -> Dict[str, float]:
        """
        Adjust weights based on task type for optimized retrieval.
        
        Args:
            task_type: 'research', 'fact_check', 'planning', 'general'
            
        Returns:
            Adjusted weights dictionary
        """
        task_weights = {
            "research": {
                "recency": 0.10,
                "frequency": 0.05,
                "relevance": 0.45,  # Prioritize relevance
                "importance": 0.15,
                "goal_alignment": 0.15,
                "entity_overlap": 0.10
            },
            "fact_check": {
                "recency": 0.05,
                "frequency": 0.10,
                "relevance": 0.40,
                "importance": 0.25,  # Prioritize importance
                "goal_alignment": 0.10,
                "entity_overlap": 0.10
            },
            "planning": {
                "recency": 0.15,
                "frequency": 0.10,
                "relevance": 0.25,
                "importance": 0.15,
                "goal_alignment": 0.25,  # Prioritize goal alignment
                "entity_overlap": 0.10
            },
            "general": self.DEFAULT_WEIGHTS.copy()
        }
        
        return task_weights.get(task_type, self.DEFAULT_WEIGHTS.copy())


# Global instance
_salience_scorer: Optional[SalienceScorer] = None


def get_salience_scorer() -> SalienceScorer:
    """Get the global SalienceScorer instance."""
    global _salience_scorer
    if _salience_scorer is None:
        _salience_scorer = SalienceScorer()
    return _salience_scorer


def init_salience_scorer(
    weights: Optional[Dict[str, float]] = None,
    embedder: Optional[Any] = None
) -> SalienceScorer:
    """Initialize the global SalienceScorer with custom settings."""
    global _salience_scorer
    _salience_scorer = SalienceScorer(weights=weights, embedder=embedder)
    return _salience_scorer
