"""
Insight Feedback Service

Collects and processes user feedback on insights to improve
future confidence scoring and insight relevance.

Feedback types:
- helpful: User found the insight useful
- not_helpful: User didn't find value in the insight
- wrong: The insight was factually incorrect
- obvious: User already knew this information
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)


class FeedbackType(str, Enum):
    """Valid feedback types for insights."""
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    WRONG = "wrong"
    OBVIOUS = "obvious"
    ACTED_ON = "acted_on"  # User took action based on insight


@dataclass
class FeedbackStats:
    """Statistics about feedback for an insight type."""
    total_count: int
    helpful_count: int
    not_helpful_count: int
    wrong_count: int
    obvious_count: int
    acted_on_count: int
    helpful_ratio: float
    average_confidence_of_helpful: float


class InsightFeedbackService:
    """
    Records user feedback on insights and adjusts future scoring.
    
    Features:
    - Store feedback with context
    - Calculate aggregate statistics per insight type
    - Adjust pattern weights based on feedback
    - Track which insights led to user actions
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        
        # In-memory cache for pattern weights
        self._pattern_weights: Dict[str, float] = {}
        self._weight_cache_time: Optional[datetime] = None
        self._weight_cache_ttl = timedelta(hours=1)
    
    async def record_feedback(
        self,
        user_id: int,
        insight_id: str,
        feedback_type: str,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Record user feedback on an insight.
        
        Args:
            user_id: User providing feedback
            insight_id: ID of the insight
            feedback_type: One of: helpful, not_helpful, wrong, obvious, acted_on
            context: Optional additional context
            
        Returns:
            True if feedback recorded successfully
        """
        if feedback_type not in [ft.value for ft in FeedbackType]:
            logger.warning(f"[FeedbackService] Invalid feedback type: {feedback_type}")
            return False
        
        context = context or {}
        
        try:
            # Get insight details for pattern learning - AQL version
            insight_query = """
            FOR i IN Insight
                FILTER i.id == @insight_id
                RETURN {
                    type: i.type,
                    confidence: i.confidence,
                    content: i.content
                }
            """
            insight_result = await self.graph.execute_query(
                insight_query, {"insight_id": insight_id}
            )
            
            insight_type = "unknown"
            original_confidence = 0.5
            if insight_result:
                insight_type = insight_result[0].get("type", "unknown")
                original_confidence = insight_result[0].get("confidence", 0.5)
            
            # Create feedback node
            feedback_id = f"feedback:{user_id}:{insight_id}:{datetime.utcnow().timestamp()}"
            properties = {
                "id": feedback_id,
                "user_id": user_id,
                "insight_id": insight_id,
                "insight_type": insight_type,
                "feedback_type": feedback_type,
                "original_confidence": original_confidence,
                "created_at": datetime.utcnow().isoformat(),
                "context": str(context) if context else None
            }
            
            await self.graph.add_node(
                feedback_id,
                NodeType.INSIGHT,  # Using INSIGHT node type for feedback (could add specific type)
                properties
            )
            
            # Create relationship to original insight
            await self.graph.add_relationship(
                feedback_id,
                insight_id,
                RelationType.ABOUT,
                {"feedback_type": feedback_type}
            )
            
            # Adjust insight confidence based on feedback
            await self._adjust_insight_confidence(insight_id, feedback_type)
            
            # Update pattern weights for future insights
            await self._update_pattern_weights(insight_type, feedback_type)
            
            logger.info(
                f"[FeedbackService] Recorded {feedback_type} feedback "
                f"for insight {insight_id} from user {user_id}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"[FeedbackService] Failed to record feedback: {e}")
            return False
    
    async def get_feedback_stats(
        self,
        user_id: int,
        insight_type: Optional[str] = None
    ) -> FeedbackStats:
        """
        Get aggregate feedback statistics for a user.
        
        Args:
            user_id: User ID
            insight_type: Optional filter by insight type
            
        Returns:
            FeedbackStats with counts and ratios
        """
        try:
            type_filter = ""
            params = {"user_id": user_id}
            
            if insight_type:
                type_filter = "AND f.insight_type == @insight_type"
                params["insight_type"] = insight_type
            
            query = f"""
            FOR f IN InsightFeedback
                FILTER f.user_id == @user_id 
                   AND f.feedback_type != null
                   {type_filter}
                COLLECT feedback = f.feedback_type
                AGGREGATE count = LENGTH(1), avg_confidence = AVG(f.original_confidence)
                RETURN {{
                    feedback: feedback,
                    count: count,
                    avg_confidence: avg_confidence
                }}
            """
            
            result = await self.graph.execute_query(query, params)
            
            stats = {
                "helpful": 0,
                "not_helpful": 0,
                "wrong": 0,
                "obvious": 0,
                "acted_on": 0,
                "avg_helpful_confidence": 0.0
            }
            
            total = 0
            for record in result or []:
                feedback = record.get("feedback", "")
                count = record.get("count", 0)
                total += count
                
                if feedback in stats:
                    stats[feedback] = count
                    
                if feedback == "helpful":
                    stats["avg_helpful_confidence"] = record.get("avg_confidence", 0.5)
            
            helpful_ratio = stats["helpful"] / total if total > 0 else 0.0
            
            return FeedbackStats(
                total_count=total,
                helpful_count=stats["helpful"],
                not_helpful_count=stats["not_helpful"],
                wrong_count=stats["wrong"],
                obvious_count=stats["obvious"],
                acted_on_count=stats["acted_on"],
                helpful_ratio=helpful_ratio,
                average_confidence_of_helpful=stats["avg_helpful_confidence"]
            )
            
        except Exception as e:
            logger.error(f"[FeedbackService] Failed to get stats: {e}")
            return FeedbackStats(0, 0, 0, 0, 0, 0, 0.0, 0.0)
    
    async def get_pattern_weight(self, insight_type: str) -> float:
        """
        Get the learned weight for an insight type based on feedback.
        
        Higher weight = historically more helpful insights of this type.
        """
        # Check cache
        now = datetime.utcnow()
        if (
            self._weight_cache_time and 
            now - self._weight_cache_time < self._weight_cache_ttl and
            insight_type in self._pattern_weights
        ):
            return self._pattern_weights[insight_type]
        
        # Calculate from database
        try:
            query = """
            FOR f IN InsightFeedback
                FILTER f.insight_type == @insight_type 
                   AND f.feedback_type != null
                COLLECT feedback = f.feedback_type
                AGGREGATE count = LENGTH(1)
                RETURN {
                    feedback: feedback,
                    count: count
                }
            """
            result = await self.graph.execute_query(query, {"insight_type": insight_type})
            
            helpful = 0
            total = 0
            
            for record in result or []:
                feedback = record.get("feedback", "")
                count = record.get("count", 0)
                total += count
                
                if feedback == "helpful" or feedback == "acted_on":
                    helpful += count
            
            if total < 3:  # Not enough data
                weight = 1.0  # Neutral weight
            else:
                # Weight is the helpful ratio, ranging from 0.5 to 1.5
                ratio = helpful / total
                weight = 0.5 + ratio  # Maps 0-1 to 0.5-1.5
            
            self._pattern_weights[insight_type] = weight
            self._weight_cache_time = now
            
            return weight
            
        except Exception as e:
            logger.debug(f"[FeedbackService] Pattern weight lookup failed: {e}")
            return 1.0
    
    async def _adjust_insight_confidence(
        self,
        insight_id: str,
        feedback_type: str
    ) -> None:
        """
        Adjust an insight's confidence based on feedback.
        
        - helpful/acted_on: Small positive adjustment
        - not_helpful/obvious: Small negative adjustment
        - wrong: Larger negative adjustment
        """
        adjustment = 0.0
        
        if feedback_type in ("helpful", "acted_on"):
            adjustment = 0.05  # Small boost
        elif feedback_type in ("not_helpful", "obvious"):
            adjustment = -0.03  # Small decrease
        elif feedback_type == "wrong":
            adjustment = -0.15  # Significant decrease
        
        if adjustment == 0:
            return
        
        try:
            query = """
            FOR i IN Insight
                FILTER i.id == @id
                LET new_conf = (
                    i.confidence + @adj > 1.0 ? 1.0 :
                    (i.confidence + @adj < 0.0 ? 0.0 : i.confidence + @adj)
                )
                UPDATE i WITH {
                    confidence: new_conf,
                    feedback_adjusted: true,
                    last_feedback: @now
                } IN Insight
                RETURN { new_confidence: NEW.confidence }
            """
            await self.graph.execute_query(query, {
                "id": insight_id,
                "adj": adjustment,
                "now": datetime.utcnow().isoformat()
            })
            
        except Exception as e:
            logger.debug(f"[FeedbackService] Confidence adjustment failed: {e}")
    
    async def _update_pattern_weights(
        self,
        insight_type: str,
        feedback_type: str
    ) -> None:
        """
        Update the pattern weight for an insight type.
        
        This affects future confidence calculations for similar insights.
        """
        # Invalidate cache for this type
        self._pattern_weights.pop(insight_type, None)
        
        # The actual weight will be recalculated on next request
        # using the updated feedback data
        logger.debug(
            f"[FeedbackService] Pattern weight invalidated for type: {insight_type}"
        )
    
    async def get_recent_feedback(
        self,
        user_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent feedback entries for a user."""
        try:
            query = """
            FOR f IN InsightFeedback
                FILTER f.user_id == @user_id 
                   AND f.feedback_type != null
                SORT f.created_at DESC
                LIMIT @limit
                RETURN {
                    insight_id: f.insight_id,
                    feedback: f.feedback_type,
                    type: f.insight_type,
                    created_at: f.created_at
                }
            """
            result = await self.graph.execute_query(query, {
                "user_id": user_id,
                "limit": limit
            })
            
            return result or []
            
        except Exception as e:
            logger.error(f"[FeedbackService] Failed to get recent feedback: {e}")
            return []


# Global instance management
_feedback_service: Optional[InsightFeedbackService] = None


def get_feedback_service() -> Optional[InsightFeedbackService]:
    """Get the global feedback service instance."""
    return _feedback_service


def init_feedback_service(
    config: Config,
    graph_manager: KnowledgeGraphManager
) -> InsightFeedbackService:
    """Initialize and return the global feedback service."""
    global _feedback_service
    _feedback_service = InsightFeedbackService(config, graph_manager)
    logger.info("[InsightFeedbackService] Initialized")
    return _feedback_service
