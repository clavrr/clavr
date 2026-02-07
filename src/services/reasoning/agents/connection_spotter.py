"""
Connection Spotter Agent

A reasoning agent that identifies non-obvious connections between disparate
data sources (e.g., Slack messages and Notion pages) using semantic similarity
and temporal proximity.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio

from src.services.reasoning.interfaces import ReasoningAgent, ReasoningResult
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.ai.rag import RAGEngine
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class ConnectionSpotterAgent(ReasoningAgent):
    """
    Agent that spots connections between unconnected nodes.
    
    Strategies:
    1. Cross-App Keyword Matching: "Project X" in Slack <-> "Project X" in Notion
    2. Semantic Similarity: Uses RAG embeddings to find related content
    3. Temporal Co-occurrence: Things happening at the same time might be related
    """
    
    def __init__(self, config: Any, graph_manager: KnowledgeGraphManager, rag_engine: RAGEngine):
        super().__init__(config, graph_manager)
        self.rag_engine = rag_engine
        
    @property
    def name(self) -> str:
        return "ConnectionSpotter"
        
    async def analyze(self, user_id: int, context: Optional[Dict[str, Any]] = None) -> List[ReasoningResult]:
        """Analyze for missing connections."""
        results = []
        
        # 1. Get recent "Orphan" content (content without many links)
        # We look for content created in the last 24h
        time_window = datetime.utcnow() - timedelta(hours=24)
        
        # Native AQL to union across content types and check for Project connections
        # We search specifically in Message, Document, CalendarEvent
        query = """
        FOR n IN UNION(
            (FOR x IN Message FILTER x.user_id == @user_id AND x.created_at > @time_window RETURN x),
            (FOR x IN Document FILTER x.user_id == @user_id AND x.created_at > @time_window RETURN x),
            (FOR x IN CalendarEvent FILTER x.user_id == @user_id AND x.created_at > @time_window RETURN x)
        )
            # Check if linked to any Project (assuming PART_OF or RELATED_TO or CONTAINS edges)
            # We traverse 1 hop in any direction
            LET linked_project_count = LENGTH(
                FOR v, e IN 1..1 ANY n 
                FILTER v.node_type == 'Project'
                LIMIT 1
                RETURN 1
            )
            
            FILTER linked_project_count == 0
            
            LIMIT 20
            RETURN {
                id: n.id,
                content: n.content,
                title: n.title,
                type: n.node_type,
                source: n.source
            }
        """
        
        try:
            orphans = await self.graph.execute_query(query, {
                "user_id": user_id,
                "time_window": time_window.isoformat()
            })
            
            for orphan in orphans or []:
                node_id = orphan['id']
                text = orphan.get('content') or orphan.get('title') or ""
                
                if len(text) < 20:
                    continue
                    
                # Find potentially related nodes using Vector Search
                # We assume the RAG engine can search for us
                similar_nodes = await self.rag_engine.search(
                    query=text, 
                    user_id=user_id, 
                    limit=5,
                    threshold=0.8
                )
                
                for similar in similar_nodes:
                    target_id = similar.metadata.get('node_id')
                    
                    # specific check: don't link to self
                    if target_id == node_id:
                        continue
                        
                    # Check if connection already exists
                    if await self.graph.check_connection(node_id, target_id):
                        continue
                        
                    # If different source, it's an interesting cross-app connection
                    if similar.metadata.get('source') != orphan['source']:
                        # Create Hypothesis
                        results.append(ReasoningResult(
                            type='hypothesis',
                            confidence=similar.score,
                            source_agent=self.name,
                            content={
                                "statement": f"'{orphan.get('title', 'Item')}' from {orphan['source']} is related to '{similar.content[:30]}...' from {similar.metadata.get('source')}",
                                "reasoning": f"High semantic similarity ({similar.score:.2f}) across different apps.",
                                "evidence_ids": [node_id, target_id],
                                "status": "pending"
                            }
                        ))
                        
                        # If very high confidence, also suggest a Topic/Project link
                        if similar.score > 0.85:
                             # MATERIALIZE the connection in the graph
                             try:
                                 await self.graph.add_relationship(
                                     from_node=node_id,
                                     to_node=target_id,
                                     rel_type=RelationType.RELATED_TO,
                                     properties={
                                         "discovered_by": "ConnectionSpotter",
                                         "confidence": similar.score,
                                         "created_at": datetime.utcnow().isoformat()
                                     }
                                 )
                                 logger.info(f"[ConnectionSpotter] Created RELATED_TO link: {node_id} -> {target_id}")
                             except Exception as e:
                                 logger.warning(f"[ConnectionSpotter] Failed to create relationship: {e}")
                             
                             results.append(ReasoningResult(
                                type='insight',
                                confidence=similar.score,
                                source_agent=self.name,
                                content={
                                    "content": f"Found a link between your {orphan['source']} and {similar.metadata.get('source')}.",
                                    "type": "connection",
                                    "actionable": True,
                                    "related_ids": [node_id, target_id],
                                    "reasoning_chain": "Semantic similarity > 0.85"
                                }
                            ))
                            
        except Exception as e:
            logger.error(f"[ConnectionSpotter] Analysis failed: {e}")
            
        return results
        
    async def verify(self, hypothesis_id: str) -> bool:
        """
        Verify a hypothesis (placeholder).
        In a real system, this might ask the user or run a deeper check.
        """
        return True
