"""
Confidence Calculator for Insights

Multi-factor confidence scoring system that provides accurate,
trustworthy confidence values for insights based on:
- Evidence strength (supporting graph nodes)
- Data recency (recent data weighted higher)
- Cross-app validation (verified across multiple apps)
- User feedback history (historical accuracy)
- Semantic coherence (logical consistency)
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import math

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

# Weight configuration for confidence factors
CONFIDENCE_WEIGHTS = {
    "evidence_count": 0.25,
    "data_recency": 0.20,
    "cross_app_validation": 0.25,
    "user_feedback": 0.15,
    "semantic_coherence": 0.15,
}

# Thresholds
MIN_EVIDENCE_FOR_FULL_SCORE = 5  # 5+ supporting nodes = max evidence score
RECENCY_HALF_LIFE_DAYS = 7  # Data loses half its recency score after 7 days
MIN_FEEDBACK_COUNT = 3  # Need at least 3 feedback entries for reliable scoring


class ConfidenceCalculator:
    """
    Multi-factor confidence scoring for insights.
    
    Produces confidence scores between 0.0 and 1.0 based on
    multiple weighted factors.
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        
        # Cache for feedback statistics to avoid repeated queries
        self._feedback_cache: Dict[str, Dict[str, float]] = {}
        self._cache_expiry = timedelta(hours=1)
        self._cache_time: Optional[datetime] = None
        
    async def calculate(
        self,
        insight: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        Calculate comprehensive confidence score for an insight.
        
        Args:
            insight: Insight dict with id, content, type, related_ids, etc.
            context: Optional additional context (current query, etc.)
            
        Returns:
            Confidence score between 0.0 and 1.0
        """
        context = context or {}
        
        insight_id = insight.get("id", "")
        insight_type = insight.get("type", "suggestion")
        content = insight.get("content", "")
        related_ids = insight.get("related_ids", [])
        created_at = insight.get("created_at", datetime.utcnow().isoformat())
        user_id = insight.get("user_id", 0)
        
        # Calculate individual factor scores
        scores = {
            "evidence_count": await self._score_evidence(insight_id, related_ids),
            "data_recency": self._score_recency(created_at),
            "cross_app_validation": await self._score_cross_app(related_ids),
            "user_feedback": await self._score_feedback(insight_type, user_id),
            "semantic_coherence": await self._score_coherence(content, related_ids),
        }
        
        # Calculate weighted sum
        total_score = sum(
            scores[factor] * CONFIDENCE_WEIGHTS[factor]
            for factor in scores
        )
        
        # Clamp to [0, 1]
        final_score = max(0.0, min(1.0, total_score))
        
        logger.debug(
            f"[ConfidenceCalculator] Insight {insight_id}: "
            f"evidence={scores['evidence_count']:.2f}, "
            f"recency={scores['data_recency']:.2f}, "
            f"cross_app={scores['cross_app_validation']:.2f}, "
            f"feedback={scores['user_feedback']:.2f}, "
            f"coherence={scores['semantic_coherence']:.2f} "
            f"-> final={final_score:.2f}"
        )
        
        return final_score
    
    async def _score_evidence(
        self,
        insight_id: str,
        related_ids: List[str]
    ) -> float:
        """
        Score based on the number of supporting graph nodes.
        
        More evidence = higher confidence.
        Uses logarithmic scaling to prevent runaway scores.
        """
        if not related_ids:
            # Try to fetch from graph
            if insight_id and self.graph:
                try:
                    # Native AQL for evidence scoring
                    # Query connected nodes via specific relationships
                    query = """
                    FOR i IN Insight
                        FILTER i.id == @id
                        LET evidence_count = LENGTH(
                            FOR n IN 1..1 OUTBOUND i ABOUT, SUPPORTS, DERIVED_FROM
                            RETURN n
                        )
                        RETURN { evidence_count: evidence_count }
                    """
                    result = await self.graph.execute_query(query, {"id": insight_id})
                    if result:
                        evidence_count = result[0].get("evidence_count", 0)
                    else:
                        evidence_count = 0
                except Exception as e:
                    logger.debug(f"[ConfidenceCalculator] Evidence query failed: {e}")
                    evidence_count = 0
            else:
                evidence_count = 0
        else:
            evidence_count = len(related_ids)
        
        if evidence_count == 0:
            return 0.3  # Base score for insights without explicit evidence
        
        # Logarithmic scaling: 1 node = 0.5, 5+ nodes = 1.0
        score = 0.5 + 0.5 * min(1.0, math.log(evidence_count + 1) / math.log(MIN_EVIDENCE_FOR_FULL_SCORE + 1))
        
        return score
    
    def _score_recency(self, created_at: str) -> float:
        """
        Score based on how recent the data is.
        
        Uses exponential decay with configurable half-life.
        Recent data = higher confidence.
        """
        try:
            if isinstance(created_at, str):
                created_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                created_time = created_at
        except (ValueError, TypeError):
            # If we can't parse, assume recent
            return 0.8
        
        now = datetime.utcnow()
        if created_time.tzinfo:
            now = now.replace(tzinfo=created_time.tzinfo)
            
        age_days = (now - created_time).total_seconds() / 86400
        
        # Exponential decay: score = 2^(-age / half_life)
        decay_factor = math.pow(2, -age_days / RECENCY_HALF_LIFE_DAYS)
        
        # Scale to [0.3, 1.0] - even old data gets some score
        score = 0.3 + 0.7 * decay_factor
        
        return score
    
    async def _score_cross_app(self, related_ids: List[str]) -> float:
        """
        Score based on whether the insight is validated across multiple apps.
        
        Cross-app validation = higher confidence.
        """
        if not related_ids or not self.graph:
            return 0.5  # Neutral score
        
        try:
            # Query the sources of related nodes
            sources: set = set()
            
            # Use explicit node lookup via AQL for better performance/reliability
            for node_id in related_ids[:10]:
                query = """
                FOR n IN UNION(
                    (FOR x IN Email FILTER x.id == @id RETURN x),
                    (FOR x IN Message FILTER x.id == @id RETURN x),
                    (FOR x IN CalendarEvent FILTER x.id == @id RETURN x),
                    (FOR x IN ActionItem FILTER x.id == @id RETURN x),
                    (FOR x IN Document FILTER x.id == @id RETURN x),
                    (FOR x IN Person FILTER x.id == @id RETURN x)
                )
                    RETURN { source: n.source, type: n.node_type }
                """
                result = await self.graph.execute_query(query, {"id": node_id})
                if result:
                    source = result[0].get("source")
                    node_type = result[0].get("type")
                    
                    if source:
                        sources.add(source.lower())
                    elif node_type:
                        # Infer source from node type
                        if node_type == "Email":
                            sources.add("gmail")
                        elif node_type == "Message":
                            sources.add("slack")
                        elif node_type == "CalendarEvent":
                            sources.add("gcalendar")
                        elif node_type == "ActionItem" or node_type == "Task":
                            sources.add("tasks")
            
            unique_apps = len(sources)
            
            if unique_apps >= 3:
                return 1.0  # Maximum score for 3+ apps
            elif unique_apps == 2:
                return 0.85  # Good score for 2 apps
            elif unique_apps == 1:
                return 0.6  # Decent score for single app
            else:
                return 0.5  # Neutral
                
        except Exception as e:
            logger.debug(f"[ConfidenceCalculator] Cross-app scoring failed: {e}")
            return 0.5
    
    async def _score_feedback(self, insight_type: str, user_id: int) -> float:
        """
        Score based on historical user feedback for similar insights.
        
        If users frequently find similar insights helpful, score higher.
        """
        if not self.graph or not user_id:
            return 0.6  # Neutral default
        
        # Check cache
        cache_key = f"{user_id}:{insight_type}"
        if self._cache_time and datetime.utcnow() - self._cache_time < self._cache_expiry:
            if cache_key in self._feedback_cache:
                return self._feedback_cache[cache_key].get("score", 0.6)
        
        try:
            query = """
            FOR f IN InsightFeedback
                FILTER f.user_id == @user_id AND f.insight_type == @insight_type
                COLLECT feedback_type = f.feedback_type WITH COUNT INTO count
                RETURN { feedback: feedback_type, count: count }
            """
            result = await self.graph.execute_query(query, {
                "user_id": user_id,
                "insight_type": insight_type
            })
            
            if not result:
                return 0.6  # No feedback history
            
            total = 0
            helpful = 0
            not_helpful = 0
            
            for record in result:
                count = record.get("count", 0)
                feedback = record.get("feedback", "")
                total += count
                
                if feedback == "helpful":
                    helpful += count
                elif feedback in ("not_helpful", "wrong"):
                    not_helpful += count
            
            if total < MIN_FEEDBACK_COUNT:
                return 0.6  # Not enough feedback for reliable scoring
            
            # Calculate ratio of helpful feedback
            helpful_ratio = helpful / total if total > 0 else 0.5
            
            # Scale to [0.2, 1.0]
            score = 0.2 + 0.8 * helpful_ratio
            
            # Cache result
            self._feedback_cache[cache_key] = {"score": score, "total": total}
            self._cache_time = datetime.utcnow()
            
            return score
            
        except Exception as e:
            logger.debug(f"[ConfidenceCalculator] Feedback scoring failed: {e}")
            return 0.6
    
    async def _score_coherence(
        self,
        content: str,
        related_ids: List[str]
    ) -> float:
        """
        Score based on semantic coherence of the insight.
        
        Checks if the insight content makes sense given the related nodes.
        Uses simple heuristics (not full LLM for performance).
        """
        if not content:
            return 0.5
        
        # Basic coherence checks
        score = 0.7  # Start with decent score
        
        # Check 1: Content length - very short or very long is suspicious
        content_length = len(content)
        if content_length < 10:
            score -= 0.2
        elif content_length > 500:
            score -= 0.1
        
        # Check 2: Contains specific entities (names, dates, etc.)
        # More specific = more likely to be accurate
        import re
        
        # Look for names (capitalized words)
        name_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
        names = re.findall(name_pattern, content)
        if names:
            score += 0.1
        
        # Look for dates
        date_pattern = r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b'
        dates = re.findall(date_pattern, content, re.IGNORECASE)
        if dates:
            score += 0.1
        
        # Check 3: Has related evidence
        if related_ids and len(related_ids) > 0:
            score += 0.1
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))
    
    def clear_cache(self):
        """Clear the feedback cache."""
        self._feedback_cache.clear()
        self._cache_time = None


# Global instance management
_confidence_calculator: Optional[ConfidenceCalculator] = None


def get_confidence_calculator() -> Optional[ConfidenceCalculator]:
    """Get the global confidence calculator instance."""
    return _confidence_calculator


def init_confidence_calculator(
    config: Config,
    graph_manager: KnowledgeGraphManager
) -> ConfidenceCalculator:
    """Initialize and return the global confidence calculator."""
    global _confidence_calculator
    _confidence_calculator = ConfidenceCalculator(config, graph_manager)
    logger.info("[ConfidenceCalculator] Initialized")
    return _confidence_calculator
