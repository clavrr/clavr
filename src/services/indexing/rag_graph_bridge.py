"""
RAG-Graph Integration Bridge

Provides seamless integration between the RAG architecture (ai/rag) and the 
Knowledge Graph system (services/indexing/graph).

This bridge:
1. Adapts RAGEngine API to work with HybridIndexCoordinator
2. Ensures proper data flow between vector (Qdrant/PostgreSQL) and graph stores
3. Provides unified search interface combining both systems
4. Maintains consistency between structured (graph) and unstructured (vector) data

Vector Store: RAGEngine (Qdrant/PostgreSQL)
Graph Store: ArangoDB or NetworkX
"""
from typing import Dict, Any, List, Optional
import asyncio

from src.ai.rag import RAGEngine
from src.utils.logger import setup_logger
from .graph.manager import KnowledgeGraphManager
from .graph.schema import NodeType, RelationType
from .parsers.base import ParsedNode
from .graph_rag_constants import (
    DEFAULT_GRAPH_DEPTH,
    MAX_NEIGHBORS_FOR_CONTEXT,
    DEFAULT_MAX_RESULTS,
)

logger = setup_logger(__name__)


class RAGVectorAdapter:
    """
    Adapter to make RAGEngine compatible with HybridIndexCoordinator's async interface.
    
    This adapter only supports RAGEngine (Qdrant/PostgreSQL backends).
    No ChromaDB, no other vector stores.
    """
    
    def __init__(self, rag_engine: RAGEngine):
        """
        Initialize adapter with RAG engine.
        
        Args:
            rag_engine: RAGEngine instance (must be RAGEngine, no other types supported)
        """
        if not isinstance(rag_engine, RAGEngine):
            raise TypeError(f"Expected RAGEngine, got {type(rag_engine).__name__}")
        
        self.rag = rag_engine
        logger.info(f"RAGVectorAdapter initialized with {self.rag.__class__.__name__}")
    
    async def add(
        self,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str]
    ) -> None:
        """
        Add documents to vector store.
        
        Args:
            documents: List of document texts
            metadatas: List of metadata dicts
            ids: List of document IDs
        """
        docs = [
            {
                'id': doc_id,
                'content': content,
                'metadata': metadata
            }
            for doc_id, content, metadata in zip(ids, documents, metadatas)
        ]
        
        await asyncio.to_thread(self.rag.index_bulk_documents, docs)
        logger.debug(f"Indexed {len(docs)} documents via adapter")
    
    async def query(
        self,
        query: str,
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Query vector store.
        
        Args:
            query: Query text
            n_results: Number of results
            where: Optional metadata filters
            
        Returns:
            List of results with content, metadata, and score
        """
        results = await asyncio.to_thread(
            self.rag.search,
            query,
            k=n_results,
            filters=where
        )
        return results
    
    async def similarity_search(
        self,
        query: str,
        k: int = 10,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Similarity search.
        
        Args:
            query: Query text
            k: Number of results
            filter: Optional metadata filters
            
        Returns:
            List of results
        """
        return await asyncio.to_thread(
            self.rag.search,
            query,
            k=k,
            filters=filter
        )
    
    async def index_documents(self, documents: List[Dict[str, Any]]) -> None:
        """
        Index documents.
        
        Args:
            documents: List of document dicts with 'text' and 'metadata'
        """
        docs = []
        for i, doc in enumerate(documents):
            metadata = doc.get('metadata', {})
            # Ensure graph_node_id exists (THE BRIDGE)
            node_id = metadata.get('graph_node_id') or metadata.get('node_id', f"doc_{i}")
            if 'graph_node_id' not in metadata and 'node_id' in metadata:
                metadata['graph_node_id'] = metadata['node_id']  # Add bridge field if missing
            
            docs.append({
                'id': node_id,  # Use node_id as vector ID (or generate if missing)
                'content': doc['text'],
                'metadata': metadata
            })
        
        await asyncio.to_thread(self.rag.index_bulk_documents, docs)
        logger.debug(f"Indexed {len(docs)} documents")
    
    async def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Alias for index_documents."""
        await self.index_documents(documents)


class GraphRAGIntegrationService:
    """
    High-level service for integrating Graph and RAG systems.
    
    Provides:
    - Unified indexing that updates both graph and vector stores
    - Intelligent search combining graph traversal and vector similarity
    - Context enrichment using both systems
    - Consistency management between systems
    """
    
    def __init__(
        self,
        rag_engine: RAGEngine,
        graph_manager: KnowledgeGraphManager
    ):
        """
        Initialize integration service.
        
        Args:
            rag_engine: RAG engine instance
            graph_manager: Knowledge graph manager instance
        """
        self.rag = rag_engine
        self.graph = graph_manager
        self.adapter = RAGVectorAdapter(rag_engine)
        logger.info("GraphRAGIntegrationService initialized")
    
    async def index_parsed_node(
        self,
        node: ParsedNode,
        index_in_graph: bool = True,
        index_in_vector: bool = True
    ) -> bool:
        """
        Index a parsed node in both graph and vector stores.
        
        Args:
            node: Parsed node to index
            index_in_graph: Whether to index in graph
            index_in_vector: Whether to index in vector store
            
        Returns:
            True if successful
        """
        graph_indexed = False
        vector_indexed = False
        
        # Try to index in graph first (primary store)
        if index_in_graph:
            try:
                await self._index_node_in_graph(node)
                graph_indexed = True
            except ValueError as e:
                # Validation error - log but continue to vector indexing
                if "Property 'body'" in str(e) or "exceeds maximum length" in str(e) or "is empty" in str(e):
                    logger.warning(f"Skipping graph indexing for {node.node_id} due to validation: {e}")
                    logger.info(f"Will still index in vector store for semantic search")
                else:
                    # Other validation errors - re-raise
                    raise
            except Exception as e:
                # Log general graph error but continue to vector indexing
                logger.error(f"Failed to index node {node.node_id} in graph: {e}")
                graph_indexed = False
        
        # Index in vector store (for semantic search) - always try even if graph failed
        if index_in_vector:
            if node.searchable_text:
                try:
                    await self._index_node_in_vector(node)
                    vector_indexed = True
                except Exception as e:
                    logger.error(f"Failed to index node {node.node_id} in vector store: {e}", exc_info=True)
            else:
                # No searchable_text - skip vector indexing (this is normal for some node types)
                logger.debug(f"Skipping vector indexing for {node.node_id} (no searchable_text)")
        
        if graph_indexed and vector_indexed:
            logger.info(f"Successfully indexed node {node.node_id} in both systems")
        elif vector_indexed:
            logger.info(f"Indexed node {node.node_id} in vector store only (graph validation failed)")
        elif graph_indexed:
            if node.searchable_text:
                logger.warning(f"Indexed node {node.node_id} in graph only (vector indexing failed)")
            else:
                logger.debug(f"Indexed node {node.node_id} in graph only (no searchable_text for vector indexing)")
        
        return graph_indexed or vector_indexed
    
    async def search_with_context(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        graph_depth: int = DEFAULT_GRAPH_DEPTH,
        include_graph_context: bool = True,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Search with automatic context enrichment from graph.
        
        IMPROVED: Uses batch querying for better performance (Priority 1)
        Matches architecture pattern: WHERE e.id IN $list_of_qdrant_ids
        
        Args:
            query: Natural language query
            max_results: Maximum results to return
            graph_depth: Depth for graph context traversal
            include_graph_context: Whether to enrich with graph data
            filters: Optional metadata filters
            
        Returns:
            Search results with optional graph context
        """
        # Step 1: Vector search for semantic matches (Qdrant)
        vector_results = await asyncio.to_thread(
            self.rag.search,
            query,
            k=max_results,
            filters=filters
        )
        
        # Step 2: Extract node_ids from Vector results (architecture pattern)
        # Architecture: Extract graph_node_id from Vector metadata (THE BRIDGE)
        node_ids = []
        for result in vector_results:
            metadata = result.get('metadata', {})
            # Extract graph_node_id (THE BRIDGE) or fallback to node_id
            node_id = metadata.get('graph_node_id') or metadata.get('node_id')
            if node_id:
                node_ids.append(node_id)
        
        # Step 3: Batch query Graph for nodes and neighbors (IMPROVED: Priority 1)
        nodes_map = {}
        neighbors_map = {}
        
        if include_graph_context and node_ids:
            try:
                # Extract node types from metadata for explicit labels (Priority 2)
                node_types_map = {}
                for result in vector_results:
                    metadata = result.get('metadata', {})
                    # Extract graph_node_id (THE BRIDGE) or fallback to node_id
                    node_id = metadata.get('graph_node_id') or metadata.get('node_id')
                    node_type_str = metadata.get('node_type')
                    if node_id and node_type_str:
                        try:
                            from .graph.schema import NodeType
                            node_types_map[node_id] = NodeType(node_type_str)
                        except (ValueError, KeyError):
                            pass
                
                # Batch get nodes (Priority 1 improvement)
                # Try to use node types for explicit labels when available
                if node_types_map:
                    # Group by node type for optimal batch queries
                    nodes_by_type: Dict[NodeType, List[str]] = {}
                    nodes_without_type = []
                    
                    for node_id in node_ids:
                        if node_id in node_types_map:
                            node_type = node_types_map[node_id]
                            if node_type not in nodes_by_type:
                                nodes_by_type[node_type] = []
                            nodes_by_type[node_type].append(node_id)
                        else:
                            nodes_without_type.append(node_id)
                    
                    # Batch query by type (uses explicit labels)
                    for node_type, type_node_ids in nodes_by_type.items():
                        type_nodes = await self.graph.get_nodes_batch(type_node_ids, node_type=node_type)
                        nodes_map.update(type_nodes)
                    
                    # Query nodes without type
                    if nodes_without_type:
                        no_type_nodes = await self.graph.get_nodes_batch(nodes_without_type)
                        nodes_map.update(no_type_nodes)
                else:
                    # Fallback: batch query without type filter
                    nodes_map = await self.graph.get_nodes_batch(node_ids)
                
                # Batch get neighbors (Priority 1 & 3 improvement)
                # Get common relationship types for context enrichment
                from .graph.schema import RelationType, NodeType
                rel_types = [
                    RelationType.CONTAINS,  # For ActionItems
                    RelationType.FROM,      # For Contacts
                    RelationType.HAS_ATTACHMENT,  # For Documents
                ]
                target_node_types = [
                    NodeType.ACTION_ITEM,
                    NodeType.CONTACT,
                    NodeType.DOCUMENT,
                ]
                
                neighbors_map = await self.graph.get_neighbors_batch(
                    node_ids,
                    rel_types=rel_types,
                    direction='both',
                    target_node_types=target_node_types
                )
                
            except Exception as e:
                logger.warning(f"Failed to batch query graph context: {e}", exc_info=True)
                # Fallback to individual queries if batch fails
                nodes_map = {}
                neighbors_map = {}
        
        # Step 4: Enrich results with graph context
        enriched_results = []
        
        for result in vector_results:
            enriched = {
                'content': result.get('content', ''),
                'metadata': result.get('metadata', {}),
                'confidence': result.get('confidence', 0.5),
                'graph_context': None
            }
            
            # Get graph node ID from metadata (architecture pattern)
            # Architecture: Extract graph_node_id from Qdrant metadata (THE BRIDGE)
            metadata = result.get('metadata', {})
            node_id = metadata.get('graph_node_id') or metadata.get('node_id')
            
            if include_graph_context and node_id:
                # Use batch-queried data (Priority 1 improvement)
                node = nodes_map.get(node_id)
                neighbors = neighbors_map.get(node_id, [])
                
                if node:
                    enriched['graph_context'] = {
                        'node': node,
                        'neighbors': neighbors[:MAX_NEIGHBORS_FOR_CONTEXT],
                        'node_type': node.get('node_type') or node.get('type'),
                        'properties': node
                    }
            
            enriched_results.append(enriched)
        
        return {
            'results': enriched_results,
            'total': len(enriched_results),
            'query': query,
            'has_graph_context': include_graph_context,
            'batch_query_used': len(node_ids) > 0  # Indicate batch querying was used
        }
    
    async def get_related_content(
        self,
        node_id: str,
        relationship_type: Optional[str] = None,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[Dict[str, Any]]:
        """
        Get content related to a graph node via relationships.
        
        Args:
            node_id: Graph node ID
            relationship_type: Optional relationship type filter
            max_results: Maximum results
            
        Returns:
            List of related content with metadata
        """
        # Get related nodes from graph
        if relationship_type:
            from .graph.schema import RelationType
            neighbors = await self.graph.get_neighbors(
                node_id,
                rel_type=RelationType[relationship_type],
                direction='both'
            )
        else:
            neighbors = await self.graph.get_neighbors(
                node_id,
                direction='both'
            )
        
        # For each neighbor, get the full node data
        related_content = []
        
        for neighbor_id, rel_data in neighbors[:max_results]:
            node = await self.graph.get_node(neighbor_id)
            
            if node:
                related_content.append({
                    'node_id': neighbor_id,
                    'node_data': node,
                    'relationship': rel_data,
                    'properties': node.get('properties', {})
                })
        
        return related_content
    
    async def search_with_multi_hop_context(
        self,
        query: str,
        max_hops: int = 2,
        max_results: int = DEFAULT_MAX_RESULTS,
        filters: Optional[Dict[str, Any]] = None,
        relationship_weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Multi-hop context retrieval combining vector search with graph traversal.
        
        Process:
        1. Perform initial vector search for semantic matches
        2. For each match, traverse graph relationships up to N hops
        3. Collect context from related nodes
        4. Re-rank results combining semantic similarity + graph proximity
        
        This enables queries like:
        - "What were we discussing about Project X with Sarah?"
        - "Show me all documents related to the budget meeting"
        - "What action items came from conversations with the marketing team?"
        
        Args:
            query: Natural language query
            max_hops: Maximum graph traversal depth (default: 2)
            max_results: Maximum final results
            filters: Optional metadata filters for vector search
            relationship_weights: Custom weights for relationship types in scoring
            
        Returns:
            Enhanced results with multi-hop context and combined scoring
        """
        from .graph.schema import RelationType, NodeType
        
        # Default relationship weights for scoring (higher = more relevant)
        default_weights = {
            RelationType.SAME_AS.value: 1.0,  # Identity relations are strongest
            RelationType.ABOUT.value: 0.9,
            RelationType.CONTAINS.value: 0.8,
            RelationType.PART_OF.value: 0.8,
            RelationType.ASSIGNED_TO.value: 0.7,
            RelationType.OCCURRED_DURING.value: 0.7,
            RelationType.MENTIONS.value: 0.6,
            RelationType.FROM.value: 0.5,
            RelationType.TO.value: 0.5,
        }
        weights = relationship_weights or default_weights
        
        # Step 1: Initial vector search
        vector_results = await asyncio.to_thread(
            self.rag.search,
            query,
            k=max_results * 2,  # Get more initially for re-ranking
            filters=filters
        )
        
        # Step 2: Extract seed node IDs
        seed_nodes = []
        for result in vector_results:
            metadata = result.get('metadata', {})
            node_id = metadata.get('graph_node_id') or metadata.get('node_id')
            if node_id:
                seed_nodes.append({
                    'id': node_id,
                    'score': result.get('confidence', result.get('score', 0.5)),
                    'content': result.get('content', ''),
                    'metadata': metadata,
                    'hop': 0  # Direct match
                })
        
        # Step 3: Multi-hop graph expansion
        discovered_nodes = {}  # node_id -> best path info
        for seed in seed_nodes:
            discovered_nodes[seed['id']] = {
                **seed,
                'path': [],
                'graph_score': 1.0  # Direct matches get full score
            }
        
        # BFS expansion for additional hops
        current_frontier = [s['id'] for s in seed_nodes]
        for hop in range(1, max_hops + 1):
            next_frontier = []
            
            for node_id in current_frontier:
                if node_id not in discovered_nodes:
                    continue
                    
                parent_info = discovered_nodes[node_id]
                
                try:
                    neighbors = await self.graph.get_neighbors(
                        node_id,
                        direction='both'
                    )
                    
                    for neighbor_id, rel_data in neighbors:
                        rel_type = rel_data.get('type', rel_data.get('rel_type', ''))
                        rel_weight = weights.get(rel_type, 0.4)
                        
                        # Calculate graph proximity score (decays with hops)
                        hop_decay = 0.7 ** hop  # 0.7^1 = 0.7, 0.7^2 = 0.49, etc.
                        graph_score = rel_weight * hop_decay
                        
                        if neighbor_id not in discovered_nodes:
                            # Get neighbor node data
                            neighbor_node = await self.graph.get_node(neighbor_id)
                            
                            if neighbor_node:
                                discovered_nodes[neighbor_id] = {
                                    'id': neighbor_id,
                                    'score': 0,  # No direct vector match
                                    'content': self._extract_node_content(neighbor_node),
                                    'metadata': neighbor_node,
                                    'hop': hop,
                                    'path': parent_info.get('path', []) + [{
                                        'from': node_id,
                                        'rel': rel_type,
                                        'to': neighbor_id
                                    }],
                                    'graph_score': graph_score
                                }
                                next_frontier.append(neighbor_id)
                        else:
                            # Update if this path is better
                            existing = discovered_nodes[neighbor_id]
                            if graph_score > existing.get('graph_score', 0) and hop < existing.get('hop', max_hops):
                                existing['graph_score'] = graph_score
                                existing['hop'] = hop
                                existing['path'] = parent_info.get('path', []) + [{
                                    'from': node_id,
                                    'rel': rel_type,
                                    'to': neighbor_id
                                }]
                                
                except Exception as e:
                    logger.debug(f"Error getting neighbors for {node_id}: {e}")
            
            current_frontier = next_frontier
        
        # Step 4: Re-rank by combined score
        all_results = list(discovered_nodes.values())
        
        for result in all_results:
            # Combined score: semantic similarity + graph proximity
            semantic_score = result.get('score', 0) * 0.6  # 60% weight to semantic
            graph_score = result.get('graph_score', 0) * 0.4  # 40% weight to graph
            result['combined_score'] = semantic_score + graph_score
        
        # Sort by combined score
        all_results.sort(key=lambda x: x.get('combined_score', 0), reverse=True)
        
        # Step 5: Format final results
        final_results = []
        for result in all_results[:max_results]:
            final_results.append({
                'node_id': result['id'],
                'content': result.get('content', ''),
                'metadata': result.get('metadata', {}),
                'scores': {
                    'semantic': result.get('score', 0),
                    'graph': result.get('graph_score', 0),
                    'combined': result.get('combined_score', 0),
                },
                'hop_distance': result.get('hop', 0),
                'path': result.get('path', []),
            })
        
        return {
            'results': final_results,
            'total': len(final_results),
            'query': query,
            'max_hops': max_hops,
            'seed_count': len(seed_nodes),
            'expanded_count': len(discovered_nodes),
        }
    
    async def search_for_agent(
        self,
        query: str,
        task_type: str = "general",
        user_id: Optional[int] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Optimized search interface for agents.
        
        Automatically tunes parameters based on task type:
        - 'research': High depth (3 hops), explores CONNECTED concepts
        - 'fact_check': Low depth (1 hop), focuses on EXACT matches
        - 'planning': Med depth (2 hops), prioritizes TEMPORAL links
        - 'general': Default (2 hops)
        
        Args:
            query: The agent's query
            task_type: The type of task (research, fact_check, planning, general)
            user_id: User context
            limit: Max results
            
        Returns:
            Search results formatted for agent consumption
        """
        # Tune parameters based on task
        if task_type == 'research':
            max_hops = 3
            # Boost topic/related links
            rel_weights = {'RELATED_TO': 0.8, 'DISCUSSES': 0.9, 'MENTIONS': 0.6}
            
        elif task_type == 'fact_check':
            max_hops = 1
            # Focus on precision
            rel_weights = {'SAME_AS': 1.0, 'HAS_ATTACHMENT': 0.9}
            
        elif task_type == 'planning':
            max_hops = 2
            # Boost temporal/dependency links
            rel_weights = {
                'PRECEDED': 0.9, 'FOLLOWS': 0.9, 'BLOCKED_BY': 0.9, 
                'OCCURRED_DURING': 0.8, 'SCHEDULED_FOR': 0.8
            }
        else:
            max_hops = 2
            rel_weights = None
            
        filters = {'user_id': str(user_id)} if user_id else None
        
        return await self.search_with_multi_hop_context(
            query=query,
            max_hops=max_hops,
            max_results=limit,
            filters=filters,
            relationship_weights=rel_weights
        )
    
    def _extract_node_content(self, node: Dict[str, Any]) -> str:
        """Extract human-readable content from a node for display."""
        props = node.get('properties', node)
        
        # Try common content fields in order of preference
        for field in ['content', 'body', 'text', 'description', 'subject', 'name', 'title']:
            if field in props and props[field]:
                content = str(props[field])
                return content[:500] if len(content) > 500 else content
        
        return str(props.get('id', 'Unknown'))
    
    async def ensure_consistency(self, node_id: str) -> bool:
        """
        Ensure a node is consistent between graph and vector stores.
        
        Args:
            node_id: Node ID to check
            
        Returns:
            True if consistent or successfully synchronized
        """
        graph_node = await self.graph.get_node(node_id)
        
        if not graph_node:
            logger.warning(f"Node {node_id} not found in graph")
            return False
        
        # Check if exists in vector store
        exists = await asyncio.to_thread(self.rag.document_exists, node_id)
        
        if not exists:
            logger.info(f"Syncing node {node_id} to vector store")
            searchable_text = graph_node.get('properties', {}).get('searchable_text', '')
            
            if searchable_text:
                await asyncio.to_thread(
                    self.rag.index_document,
                    node_id,
                    searchable_text,
                    {
                        'graph_node_id': node_id,  # ← THE BRIDGE : Links to graph 
                        'node_id': node_id,  # Also keep for backward compatibility
                        'node_type': graph_node.get('type'),
                        **graph_node.get('properties', {})
                    }
                )
        
        return True
    
    async def _index_node_in_graph(self, node: ParsedNode) -> None:
        """Index node in knowledge graph."""
        from .graph.schema import NodeType, RelationType
        
        # Add the main node
        await self.graph.add_node(
            node_id=node.node_id,
            node_type=NodeType(node.node_type),
            properties=node.properties
        )
        
        # Add relationships - fail if target doesn't exist (no placeholders)
        for relationship in node.relationships:
            # Handle both Relationship objects and dicts
            if isinstance(relationship, dict):
                to_node = relationship.get('to_node')
            else:
                to_node = relationship.to_node
            
            if not to_node:
                continue
                
            target_exists = await self.graph.get_node(to_node)
            if not target_exists:
                # Extract from_node for error message
                if isinstance(relationship, dict):
                    from_node = relationship.get('from_node')
                else:
                    from_node = relationship.from_node
                
                # This is expected when indexing emails before their related nodes (Contacts, Documents)
                # The related nodes will be indexed separately, and relationships can be created later
                logger.debug(
                    f"Skipping relationship from {from_node} to {to_node}: "
                    f"target node not yet indexed (will be created when target node is indexed)"
                )
                continue
            
            # Extract relationship details
            if isinstance(relationship, dict):
                from_node = relationship.get('from_node')
                rel_type = relationship.get('rel_type')
                rel_properties = relationship.get('properties', {})
            else:
                from_node = relationship.from_node
                rel_type = relationship.rel_type
                rel_properties = relationship.properties
            
            # Add relationship
            await self.graph.add_relationship(
                from_node=from_node,
                to_node=to_node,
                rel_type=RelationType(rel_type),
                properties=rel_properties
            )
    
    async def _index_node_in_vector(self, node: ParsedNode) -> None:
        """
        Index node's searchable text in vector store with chunking.
        
        This PRECISELY matches the Qdrant GraphRAG architecture pattern:
        Step 1: Create node in Graph → Get unique Node ID (node.node_id)
        Step 2: Store in Qdrant → Include graph_node_id in metadata (THE BRIDGE)
        
        Architecture Pattern:
        - Raw Data → Chunking → Embedding → Qdrant
        - Each chunk gets the graph_node_id (Graph Node ID) in metadata for linking back to Graph
        
        OPTIMIZATION: Skips indexing if document already exists in vector store.
        This prevents duplicate writes and saves Qdrant write units.
        """
        # Check if already indexed (skip if first chunk exists)
        first_chunk_id = f"{node.node_id}_chunk_0"
        try:
            already_exists = await asyncio.to_thread(
                self.rag.vector_store.document_exists,
                first_chunk_id
            )
            if already_exists:
                logger.debug(f"Skipping vector indexing for {node.node_id} (already indexed)")
                return
        except Exception as e:
            # If check fails, proceed with indexing (safer to index than miss)
            logger.debug(f"Could not check if {node.node_id} exists, proceeding with indexing: {e}")
        
        # CRITICAL: Include both node_id and graph_node_id for clarity and architecture alignment
        # The architecture document shows 'graph_node_id' as the bridge field
        metadata = {
            'graph_node_id': node.node_id,  # ← THE BRIDGE: Graph Node ID (matches architecture exactly)
            'node_id': node.node_id,  # ← Also keep node_id for backward compatibility
            'node_type': node.node_type,
            'doc_type': node.node_type.lower(),
            'indexed_at': node.properties.get('indexed_at', ''),
            **self._extract_searchable_metadata(node)
        }
        
        # Use chunked indexing 
        # Each chunk will have the graph_node_id for Graph traversal
        # Vector IDs are created as: {node_id}_chunk_{i} (matches pattern: vec-{node_id})
        await asyncio.to_thread(
            self.rag.index_document_chunked,  # WITH chunking
            node.node_id,  # Base doc_id (used to create chunk IDs: {node_id}_chunk_0, etc.)
            node.searchable_text,
            metadata  # Propagated to ALL chunks - includes graph_node_id (THE BRIDGE)
        )
        logger.info(f"Added {len(node.searchable_text.split()) // 100 + 1} documents to Qdrant")
    
    def _extract_searchable_metadata(self, node: ParsedNode) -> Dict[str, Any]:
        """Extract relevant metadata for vector search.
        
        CRITICAL: This metadata is used by EmailService.search_emails() to filter
        index results. Missing fields cause filtering to fail, leading to fallback
        to Gmail API (slower).
        
        Email-critical fields:
        - email_id: Required for deduplication and lookup
        - sender/from: Required for sender filtering
        - subject: Required for subject filtering
        - timestamp/date: Required for date range filtering
        - is_unread: Required for unread filtering (most common issue!)
        - labels: Required for folder/label filtering
        - thread_id: Required for threading
        - has_attachments: Required for attachment filtering
        - folder: Required for folder filtering
        """
        metadata = {}
        
        # Email-specific fields (CRITICAL for filtering in EmailService)
        email_fields = [
            'subject', 'sender', 'from', 'sender_email', 'sender_name',
            'date', 'timestamp', 'email_id', 'thread_id',
            'is_unread', 'is_important', 'is_starred',
            'has_attachments', 'folder', 'labels'
        ]
        
        for field in email_fields:
            if field in node.properties:
                value = node.properties[field]
                # Handle special cases
                if field == 'labels' and isinstance(value, list):
                    # Store as comma-separated for easier filtering
                    metadata[field] = value  # Keep as list for proper filtering
                elif value is not None:  # Include False values (e.g., is_unread=False)
                    metadata[field] = value
        
        # Document/receipt fields (kept for backward compatibility)
        document_fields = ['filename', 'merchant', 'total', 'amount', 'receipt_date']
        for field in document_fields:
            if field in node.properties:
                metadata[field] = node.properties[field]
        
        # User ID for filtering (always include)
        if 'user_id' in node.properties:
            metadata['user_id'] = node.properties['user_id']
        else:
            logger.warning(f"Node {node.node_id} MISSING user_id in properties! Keys: {list(node.properties.keys())}")
        
        return metadata
