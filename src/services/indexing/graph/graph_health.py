"""
Graph Health Monitor Service

Responsibility: Monitor and maintain the quality of the Knowledge Graph.
- Detects orphan nodes (no relationships)
- Identifies potential duplicates
- Flags stale data
- Reports overall graph health stats
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager

logger = setup_logger(__name__)

@dataclass
class HealthReport:
    timestamp: datetime
    orphan_count: int
    duplicate_candidates: int
    stale_node_count: int
    node_count: int
    relationship_count: int
    issues: List[str] = field(default_factory=list)

class GraphHealthMonitor:
    """
    Monitors graph health and integrity.
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self.is_running = False
        
    async def run_health_check(self, user_id: Optional[int] = None) -> HealthReport:
        """
        Run a comprehensive health check on the graph.
        If user_id is provided, checks are scoped to that user.
        """
        logger.info(f"[GraphHealth] Running health check{' for user ' + str(user_id) if user_id else ''}")
        
        # Parallel execution of checks
        results = await asyncio.gather(
            self._count_nodes(user_id),
            self._count_relationships(user_id),
            self._find_orphan_nodes(user_id),
            self._find_potential_duplicates(user_id),
            self._find_stale_nodes(user_id)
        )
        
        node_count, rel_count, orphans, duplicates, stale = results
        
        issues = []
        if orphans > 0:
            issues.append(f"Found {orphans} orphan nodes")
        if duplicates > 0:
            issues.append(f"Found {duplicates} potential duplicates")
        if stale > 0:
            issues.append(f"Found {stale} stale nodes (older than 6 months)")
            
        return HealthReport(
            timestamp=datetime.utcnow(),
            orphan_count=orphans,
            duplicate_candidates=duplicates,
            stale_node_count=stale,
            node_count=node_count,
            relationship_count=rel_count,
            issues=issues
        )

    async def _count_nodes(self, user_id: Optional[int]) -> int:
        collections = [t.value for t in NodeType]
        subqueries = [f"(FOR n IN {c} FILTER @user_id == null OR n.user_id == @user_id RETURN 1)" for c in collections]
        query = f"RETURN LENGTH(UNION({', '.join(subqueries)}))"
        result = await self.graph.execute_query(query, {'user_id': user_id})
        return result[0] if result else 0

    async def _count_relationships(self, user_id: Optional[int]) -> int:
        # Note: Relationships might not have user_id, so this filter might be strict
        collections = [t.value for t in RelationType]
        subqueries = [f"(FOR r IN {c} FILTER @user_id == null OR r.user_id == @user_id RETURN 1)" for c in collections]
        query = f"RETURN LENGTH(UNION({', '.join(subqueries)}))"
        result = await self.graph.execute_query(query, {'user_id': user_id})
        return result[0] if result else 0

    async def _find_orphan_nodes(self, user_id: Optional[int]) -> int:
        """Nodes with no relationships (isolated)."""
        # Limiting to main entity types to avoid massive queries on tiny nodes
        # Checks if node has 0 edges connected
        collections = [
            NodeType.PERSON.value, NodeType.CONTACT.value, NodeType.EMAIL.value, 
            NodeType.DOCUMENT.value, NodeType.ACTION_ITEM.value
        ]
        
        # We check each collection
        total_orphans = 0
        
        # We can't easily UNION diverse checks, so we run per collection (safer for timeouts too)
        for col in collections:
            query = f"""
            FOR n IN {col}
                FILTER (@user_id == null OR n.user_id == @user_id)
                LET edge_count = LENGTH(
                    FOR v, e IN 1..1 ANY n 
                    OPTIONS {{ bfs: true, uniqueVertices: 'global' }}
                    LIMIT 1 
                    RETURN 1
                )
                FILTER edge_count == 0
                COLLECT WITH COUNT INTO c
                RETURN c
            """
            try:
                res = await self.graph.execute_query(query, {'user_id': user_id})
                if res:
                    total_orphans += res[0]
            except Exception as e:
                logger.warning(f"Error checking orphans in {col}: {e}")
                
        return total_orphans

    async def _find_potential_duplicates(self, user_id: Optional[int]) -> int:
        """
        Find nodes with same name/title/subject created recently.
        """
        # Only check duplicate-prone types
        collections = [NodeType.PERSON.value, NodeType.TOPIC.value, NodeType.CONTACT.value]
        total_dups = 0
        
        for col in collections:
            query = f"""
            FOR n IN {col}
                FILTER (@user_id == null OR n.user_id == @user_id)
                AND (n.name != null OR n.title != null)
                COLLECT label = NOT_NULL(n.name, n.title) WITH COUNT INTO c
                FILTER c > 1
                RETURN c
            """
            try:
                # Returns list of counts > 1. Each entry is a duplicate set.
                # Actually we want "count of potential duplicates". Sum of (c-1)? Or just number of sets?
                # "duplicate_candidates" usually means how many nodes are involved.
                res = await self.graph.execute_query(query, {'user_id': user_id})
                if res:
                    total_dups += sum(res) # Sum of all counts
            except Exception as e:
                logger.warning(f"Error checking duplicates in {col}: {e}")
                
        return total_dups

    async def _find_stale_nodes(self, user_id: Optional[int]) -> int:
        """Nodes not updated in a long time."""
        from src.services.service_constants import ServiceConstants
        cutoff = (datetime.utcnow() - timedelta(days=ServiceConstants.STALE_NODE_THRESHOLD_DAYS)).isoformat()
        
        collections = [NodeType.PERSON.value, NodeType.PROJECT.value, NodeType.GOAL.value]
        subqueries = [f"(FOR n IN {c} FILTER (@user_id == null OR n.user_id == @user_id) AND n.updated_at != null AND n.updated_at < @cutoff RETURN 1)" for c in collections]
        
        query = f"RETURN LENGTH(UNION({', '.join(subqueries)}))"
        
        result = await self.graph.execute_query(query, {'user_id': user_id, 'cutoff': cutoff})
        return result[0] if result else 0
