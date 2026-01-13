"""
Graph Feedback Service

Enables the "Living" graph to learn from user feedback.
Handles positive/negative reinforcement of Insights, Connections, and Patterns.
"""
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.relationship_strength import RelationshipStrengthManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

class FeedbackType(str, Enum):
    USEFUL = "useful"
    NOT_USEFUL = "not_useful"
    WRONG = "wrong"
    CONFIRM = "confirm"
    REJECT = "reject"

class GraphFeedbackService:
    """
    Service to process user feedback on graph elements.
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager, relationship_manager: Optional[RelationshipStrengthManager] = None):
        self.config = config
        self.graph = graph_manager
        self.relationship_manager = relationship_manager
        
    async def process_feedback(
        self,
        node_id: str,
        feedback_type: FeedbackType,
        user_id: int,
        details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Process feedback for a specific node (Insight, Pattern, Hypothesis, or Relation).
        """
        try:
            # Replaced legacy node lookup with native get_node
            node = await self.graph.get_node(node_id)
            
            if not node:
                logger.warning(f"[Feedback] Node {node_id} not found")
                return False
                
            node_type = node.get("node_type")
            # node_type from get_node is the value string (e.g. "Insight")
            
            if node_type == NodeType.INSIGHT.value:
                return await self._handle_insight_feedback(node_id, feedback_type, user_id)
            elif node_type == NodeType.GRAPH_PATTERN.value:
                return await self._handle_pattern_feedback(node_id, feedback_type, user_id)
            elif node_type == NodeType.HYPOTHESIS.value:
                return await self._handle_hypothesis_feedback(node_id, feedback_type, user_id)
            else:
                # Generic node feedback (e.g. on a Connection/Person)
                return await self._handle_generic_feedback(node_id, feedback_type, user_id, node_type)
                
        except Exception as e:
            logger.error(f"[Feedback] Failed to process feedback: {e}")
            return False
            
    async def _handle_insight_feedback(self, node_id: str, feedback_type: FeedbackType, user_id: int) -> bool:
        """Handle feedback on Insights."""
        properties = {}
        now = datetime.utcnow().isoformat()
        
        if feedback_type == FeedbackType.USEFUL:
            properties = {"feedback_score": 1, "useful_count": 1, "last_feedback": now}
            # Reinforce source agent?
        elif feedback_type in [FeedbackType.NOT_USEFUL, FeedbackType.REJECT]:
             properties = {"feedback_score": -1, "dismissed": True, "dismissed_at": now}
             
        if properties:
            # We use native AQL UPDATE
            query = """
            FOR n IN Insight
                FILTER n.id == @id
                UPDATE n WITH @props IN Insight
                RETURN NEW.id
            """
            await self.graph.execute_query(query, {"id": node_id, "props": properties})
            return True
        return False

    async def _handle_pattern_feedback(self, node_id: str, feedback_type: FeedbackType, user_id: int) -> bool:
        """Handle feedback on Learned Patterns."""
        if feedback_type == FeedbackType.CONFIRM:
            # Boost confidence
            query = """
            FOR n IN GraphPattern
                FILTER n.id == @id
                UPDATE n WITH {
                    confidence: MIN([n.confidence + 0.1, 1.0]),
                    verified_by_user: true,
                    verified_at: @now
                } IN GraphPattern
            """
            await self.graph.execute_query(query, {"id": node_id, "now": datetime.utcnow().isoformat()})
            return True
            
        elif feedback_type == FeedbackType.REJECT:
            # Mark as rejected
            query = """
            FOR n IN GraphPattern
                FILTER n.id == @id
                UPDATE n WITH {
                    confidence: 0.0,
                    rejected_by_user: true,
                    rejected_at: @now
                } IN GraphPattern
            """
            await self.graph.execute_query(query, {"id": node_id, "now": datetime.utcnow().isoformat()})
            return True
        return False
        
    async def _handle_hypothesis_feedback(self, node_id: str, feedback_type: FeedbackType, user_id: int) -> bool:
        """Handle feedback on Hypotheses."""
        if feedback_type == FeedbackType.CONFIRM:
            # Convert Hypothesis to Fact/Relationship?
            # For now just mark verified
            query = """
            FOR n IN Hypothesis
                FILTER n.id == @id
                UPDATE n WITH {
                    status: 'verified',
                    confidence: 1.0,
                    verified_at: @now
                } IN Hypothesis
            """
            await self.graph.execute_query(query, {"id": node_id, "now": datetime.utcnow().isoformat()})
            return True
        elif feedback_type == FeedbackType.REJECT:
             query = """
            FOR n IN Hypothesis
                FILTER n.id == @id
                UPDATE n WITH {
                    status: 'rejected',
                    confidence: 0.0,
                    rejected_at: @now
                } IN Hypothesis
            """
             await self.graph.execute_query(query, {"id": node_id, "now": datetime.utcnow().isoformat()})
             return True
        return False
        
    async def _handle_generic_feedback(self, node_id: str, feedback_type: FeedbackType, user_id: int, node_type: str) -> bool:
        """Handle feedback on general nodes (reinforcing/decaying)."""
        # If confirm, maybe reinforce all connections?
        return True

# Global instance
_feedback_service: Optional[GraphFeedbackService] = None

def init_feedback_service(config: Config, graph_manager: KnowledgeGraphManager) -> GraphFeedbackService:
    global _feedback_service
    _feedback_service = GraphFeedbackService(config, graph_manager)
    return _feedback_service
