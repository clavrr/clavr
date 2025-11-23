"""
Hybrid Index Coordinator

Coordinates between Knowledge Graph (structured reasoning) and Vector Store (semantic search).
Provides a unified indexing and querying interface.

Vector Store: RAGEngine ONLY (Pinecone primary, PostgreSQL fallback)
Graph Store: Neo4j or NetworkX

"""
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from .graph.manager import KnowledgeGraphManager
from .graph.schema import NodeType, RelationType
from .parsers.base import ParsedNode, Relationship
from .rag_graph_bridge import RAGVectorAdapter, GraphRAGIntegrationService
from .graph_rag_constants import (
    DEFAULT_GRAPH_DEPTH,
    DEFAULT_MAX_RESULTS,
    DEFAULT_VECTOR_LIMIT,
    VECTOR_SCORE_WEIGHT,
    GRAPH_SCORE_WEIGHT,
    GRAPH_SCORE_NORMALIZATION_FACTOR,
    MAX_NEIGHBORS_FOR_CONTEXT,
)
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class HybridIndexCoordinator:
    """
    Coordinates hybrid indexing between Knowledge Graph and Vector Store
    
    Architecture:
    - Knowledge Graph: Primary storage for structured data and relationships
    - Vector Store: Secondary storage for semantic search (entry points)
    
    Query Strategy:
    1. Start with vector search for semantic entry points
    2. Use graph traversal for structured reasoning
    3. Combine results for comprehensive answers
    
    Usage:
        coordinator = HybridIndexCoordinator(graph_manager, vector_store)
        
        # Index a parsed email
        await coordinator.index_node(email_node)
        
        # Hybrid query
        results = await coordinator.query(
            text_query="meeting with John",
            use_graph=True
        )
    """
    
    def __init__(
        self,
        graph_manager: KnowledgeGraphManager,
        rag_engine,  # Must be RAGEngine instance
        enable_graph: bool = True,
        enable_vector: bool = True
    ):
        """
        Initialize hybrid index coordinator
        
        Args:
            graph_manager: Knowledge graph manager instance
            rag_engine: RAGEngine instance (Pinecone/PostgreSQL)
            enable_graph: Whether to use graph indexing
            enable_vector: Whether to use vector indexing
        """
        from ...ai.rag import RAGEngine
        
        if not isinstance(rag_engine, RAGEngine):
            raise TypeError(
                f"HybridIndexCoordinator requires RAGEngine, got {type(rag_engine).__name__}. "
                "Only Pinecone and PostgreSQL vector stores are supported."
            )
        
        self.graph = graph_manager
        self.rag_engine = rag_engine
        self.vector = RAGVectorAdapter(rag_engine)
        self.enable_graph = enable_graph
        self.enable_vector = enable_vector
        
        # Initialize integration service for advanced features
        self.integration = GraphRAGIntegrationService(
            rag_engine,
            graph_manager
        )
        
        logger.info(
            f"Initialized HybridIndexCoordinator "
            f"(graph={'enabled' if enable_graph else 'disabled'}, "
            f"vector={'enabled' if enable_vector else 'disabled'}, "
            f"backend={rag_engine.vector_store.__class__.__name__})"
        )
    
    async def index_node(self, node: ParsedNode) -> bool:
        """
        Index a parsed node in both graph and vector store
        
        Args:
            node: Parsed node to index
            
        Returns:
            True if successful
        """
        # Use integration service (optimized for RAGEngine)
        return await self.integration.index_parsed_node(
            node,
            index_in_graph=self.enable_graph,
            index_in_vector=self.enable_vector
        )
    
    async def index_batch(self, nodes: List[ParsedNode]) -> Tuple[int, int]:
        """
        Index multiple nodes in batch
        
        Args:
            nodes: List of parsed nodes
            
        Returns:
            Tuple of (successful_count, failed_count)
        """
        successful = 0
        failed = 0
        
        for node in nodes:
            if await self.index_node(node):
                successful += 1
            else:
                failed += 1
        
        logger.info(f"Batch indexed: {successful} successful, {failed} failed")
        return successful, failed
    
    async def query(
        self,
        text_query: str,
        use_graph: bool = True,
        use_vector: bool = True,
        graph_depth: int = DEFAULT_GRAPH_DEPTH,
        vector_limit: int = DEFAULT_VECTOR_LIMIT,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute hybrid query across graph and vector store
        
        Args:
            text_query: Natural language query
            use_graph: Whether to use graph traversal
            use_vector: Whether to use vector search
            graph_depth: Maximum graph traversal depth
            vector_limit: Maximum vector search results
            filters: Optional metadata filters
            
        Returns:
            Combined results from both stores
        """
        # Use integration service (provides better context enrichment)
        if use_graph:
            return await self.integration.search_with_context(
                query=text_query,
                max_results=vector_limit,
                graph_depth=graph_depth,
                include_graph_context=use_graph,
                filters=filters
            )
        
        # Vector-only search
        vector_results = await asyncio.to_thread(
            self.rag_engine.search,
            text_query,
            k=vector_limit,
            filters=filters
        )
        
        return {
            "results": [
                {
                    'content': r.get('content', ''),
                    'metadata': r.get('metadata', {}),
                    'confidence': r.get('confidence', 0.5),
                    'graph_context': None
                }
                for r in vector_results
            ],
            "total": len(vector_results),
            "query": text_query,
            "has_graph_context": False,
            "metadata": {
                "timestamp": datetime.now().isoformat()
            }
        }
    
    async def get_node_with_context(
        self,
        node_id: str,
        depth: int = DEFAULT_GRAPH_DEPTH,
        include_relationships: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get a node with its surrounding context from the graph
        
        Args:
            node_id: Node identifier
            depth: How many hops to traverse
            include_relationships: Whether to include relationship details
            
        Returns:
            Node data with context
        """
        if not self.enable_graph:
            return None
        
        node_data = await self.graph.get_node(node_id)
        if not node_data:
            return None
        
        context = {
            "node": node_data,
            "neighbors": [],
            "paths": []
        }
        
        # Get neighbors
        if include_relationships:
            neighbors = await self.graph.get_neighbors(node_id, direction="both")
            context["neighbors"] = [
                {"node_id": neighbor_id, "relationship": rel_data}
                for neighbor_id, rel_data in neighbors
            ]
        
        # Traverse for additional context
        if depth > 1:
            traversal_results = await self.graph.traverse(
                start_node=node_id,
                rel_types=list(RelationType),
                depth=depth,
                direction="both"
            )
            context["connected_nodes"] = traversal_results
        
        return context
    
    async def find_related_nodes(
        self,
        node_id: str,
        rel_type: RelationType,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[Dict[str, Any]]:
        """
        Find nodes related to a given node by a specific relationship type
        
        Args:
            node_id: Source node ID
            rel_type: Relationship type to follow
            max_results: Maximum number of results
            
        Returns:
            List of related nodes
        """
        if not self.enable_graph:
            return []
        
        neighbors = await self.graph.get_neighbors(node_id, rel_type=rel_type, direction="outgoing")
        
        results = []
        for neighbor_id, rel_data in neighbors[:max_results]:
            node_data = await self.graph.get_node(neighbor_id)
            if node_data:
                results.append({
                    "node_id": neighbor_id,
                    "node_data": node_data,
                    "relationship": rel_data
                })
        
        return results
    
    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics from both graph and vector store
        
        Returns:
            Combined statistics
        """
        stats = {
            "graph": None,
            "vector": None,
            "timestamp": datetime.now().isoformat()
        }
        
        # Graph stats
        if self.enable_graph:
            graph_stats = await self.graph.get_stats()
            stats["graph"] = graph_stats.dict()
        
        # Vector stats from RAGEngine
        if self.enable_vector:
            try:
                vector_stats = await asyncio.to_thread(self.rag_engine.get_stats)
                stats["vector"] = vector_stats
            except Exception as e:
                logger.debug(f"Could not get vector stats: {e}")
        
        return stats
  
