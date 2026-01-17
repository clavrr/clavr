"""
Gap Analysis Agent

Identifies missing information, potential blockers, or "holes" in the user's context.
Examples:
- "You have a meeting about Project X but no recent docs."
- "You have a deadline tomorrow but haven't worked on the task."

Outputs: Insight nodes (type=gap)
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.reasoning.interfaces import ReasoningAgent, ReasoningResult

logger = setup_logger(__name__)

class GapAnalysisAgent(ReasoningAgent):
    """
    Agent that looks for missing context.
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self.config = config
        self.graph = graph_manager
        
    @property
    def name(self) -> str:
        return "GapAnalysisAgent"
        
    async def analyze(self, user_id: int, context: Optional[Dict[str, Any]] = None) -> List[ReasoningResult]:
        """
        Run gap analysis.
        """
        results = []
        
        # Check for upcoming meetings without context/preparation
        # "Meeting in < 24h" AND "No related docs/emails in < 48h"
        
        tomorrow = (datetime.utcnow() + timedelta(days=1)).isoformat()
        now = datetime.utcnow().isoformat()
        two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
        
        query = """
        FOR e IN CalendarEvent
            FILTER e.user_id == @user_id 
               AND e.start_time > @now 
               AND e.start_time < @tomorrow
            
            LET recent_docs = (
                FOR edge IN RELATED_TO
                    FILTER edge._from == e._id OR edge._to == e._id
                    LET doc = edge._from == e._id ? DOCUMENT(edge._to) : DOCUMENT(edge._from)
                    FILTER (doc.node_type == 'Document' OR doc.node_type == 'Email')
                       AND doc.timestamp > @two_days_ago
                    RETURN doc
            )
            
            FILTER LENGTH(recent_docs) == 0
            LIMIT 3
            
            RETURN {
                title: e.title,
                time: e.start_time,
                id: e.id
            }
        """
        
        try:
            gaps = await self.graph.query(query, {
                "user_id": user_id, 
                "now": now, 
                "tomorrow": tomorrow,
                "two_days_ago": two_days_ago
            })
            
            for gap in gaps or []:
                # Handle both ArangoDB and NetworkX result formats
                title = gap.get('title') or gap.get('e.title') or 'Untitled Event'
                node_id = gap.get('id') or gap.get('node_id') or 'unknown'
                
                content = {
                    "content": f"Preparation check: You have '{title}' soon but no recent files linked.",
                    "type": "gap",
                    "actionable": True,
                    "reasoning_chain": "Event imminent but zero related artifacts found.",
                    "related_ids": [node_id]
                }
                
                results.append(ReasoningResult(
                    type="insight",
                    confidence=0.8,
                    content=content,
                    source_agent=self.name
                ))
                
        except Exception as e:
            logger.error(f"[{self.name}] Analysis failed: {e}")
            
        return results

    async def verify(self, hypothesis_id: str) -> bool:
        """
        Verify a specific gap/hypothesis.
        For gaps, 'verification' effectively means checking if the gap still exists.
        
        Args:
            hypothesis_id: The event ID or insight ID to verify
            
        Returns:
            True if the gap still exists (unresolved), False if resolved
        """
        try:
            # Check if the event still has no related documents
            two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
            
            query = """
            FOR e IN CalendarEvent
                FILTER e.id == @event_id
                
                LET recent_docs = (
                    FOR edge IN RELATED_TO
                        FILTER edge._from == e._id OR edge._to == e._id
                        LET doc = edge._from == e._id ? DOCUMENT(edge._to) : DOCUMENT(edge._from)
                        FILTER (doc.node_type == 'Document' OR doc.node_type == 'Email')
                           AND doc.timestamp > @two_days_ago
                        RETURN doc
                )
                
                RETURN { has_docs: LENGTH(recent_docs) > 0 }
            """
            
            result = await self.graph.query(query, {
                "event_id": hypothesis_id,
                "two_days_ago": two_days_ago
            })
            
            if result and len(result) > 0:
                # If has_docs is True, gap is resolved
                return not result[0].get('has_docs', False)
            
            # If event not found, consider gap resolved
            return False
            
        except Exception as e:
            logger.warning(f"[{self.name}] Verification failed for {hypothesis_id}: {e}")
            # On error, assume gap still exists
            return True
