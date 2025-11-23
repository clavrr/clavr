"""
RAG-Graph Integration Bridge

Provides seamless integration between the RAG architecture (ai/rag) and the 
Knowledge Graph system (services/indexing/graph).

This bridge:
1. Adapts RAGEngine API to work with HybridIndexCoordinator
2. Ensures proper data flow between vector (Pinecone/PostgreSQL) and graph stores
3. Provides unified search interface combining both systems
4. Maintains consistency between structured (graph) and unstructured (vector) data

Vector Store: RAGEngine 
Graph Store: Neo4j or NetworkX
"""
from typing import Dict, Any, List, Optional
import asyncio

from ...ai.rag import RAGEngine
from ...utils.logger import setup_logger
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
    
    This adapter only supports RAGEngine (Pinecone/PostgreSQL backends).
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
            # Ensure neo4j_node_id exists (THE BRIDGE)
            node_id = metadata.get('neo4j_node_id') or metadata.get('node_id', f"doc_{i}")
            if 'neo4j_node_id' not in metadata and 'node_id' in metadata:
                metadata['neo4j_node_id'] = metadata['node_id']  # Add bridge field if missing
            
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
                # Check if it's a Neo4j connection error (including BrokenPipeError)
                error_str = str(e)
                error_type = type(e).__name__
                
                # Handle various connection errors
                is_connection_error = (
                    "Connection refused" in error_str or 
                    "ServiceUnavailable" in error_str or 
                    "Couldn't connect" in error_str or
                    "Broken pipe" in error_str.lower() or
                    "BrokenPipeError" in error_type or
                    "defunct connection" in error_str.lower() or
                    "Failed to write" in error_str or
                    "Failed to read" in error_str
                )
                
                if is_connection_error:
                    # Neo4j connection issue - gracefully fall back to vector-only
                    logger.warning(
                        f"Neo4j connection error for {node.node_id}: {error_type}: {error_str}. "
                        f"This is likely a transient network issue. Continuing with vector-only indexing."
                    )
                else:
                    # Other graph errors - log but continue to vector indexing
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
        Matches architecture pattern: WHERE e.id IN $list_of_pinecone_ids
        
        Args:
            query: Natural language query
            max_results: Maximum results to return
            graph_depth: Depth for graph context traversal
            include_graph_context: Whether to enrich with graph data
            filters: Optional metadata filters
            
        Returns:
            Search results with optional graph context
        """
        # Step 1: Vector search for semantic matches (Pinecone)
        vector_results = await asyncio.to_thread(
            self.rag.search,
            query,
            k=max_results,
            filters=filters
        )
        
        # Step 2: Extract node_ids from Pinecone results (architecture pattern)
        # Architecture: Extract neo4j_node_id from Pinecone metadata (THE BRIDGE)
        node_ids = []
        for result in vector_results:
            metadata = result.get('metadata', {})
            # Extract neo4j_node_id (THE BRIDGE) or fallback to node_id
            node_id = metadata.get('neo4j_node_id') or metadata.get('node_id')
            if node_id:
                node_ids.append(node_id)
        
        # Step 3: Batch query Neo4j for nodes and neighbors (IMPROVED: Priority 1)
        nodes_map = {}
        neighbors_map = {}
        
        if include_graph_context and node_ids:
            try:
                # Extract node types from metadata for explicit labels (Priority 2)
                node_types_map = {}
                for result in vector_results:
                    metadata = result.get('metadata', {})
                    # Extract neo4j_node_id (THE BRIDGE) or fallback to node_id
                    node_id = metadata.get('neo4j_node_id') or metadata.get('node_id')
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
            # Architecture: Extract neo4j_node_id from Pinecone metadata (THE BRIDGE)
            metadata = result.get('metadata', {})
            node_id = metadata.get('neo4j_node_id') or metadata.get('node_id')
            
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
                        'neo4j_node_id': node_id,  # ← THE BRIDGE : Links to graph 
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
        
        This PRECISELY matches the Pinecone GraphRAG architecture pattern:
        Step 1: Create node in Neo4j → Get unique Node ID (node.node_id)
        Step 2: Store in Pinecone → Include neo4j_node_id in metadata (THE BRIDGE)
        
        Architecture Pattern:
        - Raw Data → Chunking → Embedding → Pinecone
        - Each chunk gets the neo4j_node_id (Neo4j Node ID) in metadata for linking back to Neo4j
        """
        # CRITICAL: Include both node_id and neo4j_node_id for clarity and architecture alignment
        # The architecture document shows 'neo4j_node_id' as the bridge field
        metadata = {
            'neo4j_node_id': node.node_id,  # ← THE BRIDGE: Neo4j Node ID (matches architecture exactly)
            'node_id': node.node_id,  # ← Also keep node_id for backward compatibility
            'node_type': node.node_type,
            'doc_type': node.node_type.lower(),
            'indexed_at': node.properties.get('indexed_at', ''),
            **self._extract_searchable_metadata(node)
        }
        
        # Use chunked indexing 
        # Each chunk will have the neo4j_node_id for Neo4j graph traversal
        # Vector IDs are created as: {node_id}_chunk_{i} (matches pattern: vec-{node_id})
        await asyncio.to_thread(
            self.rag.index_document_chunked,  # WITH chunking
            node.node_id,  # Base doc_id (used to create chunk IDs: {node_id}_chunk_0, etc.)
            node.searchable_text,
            metadata  # Propagated to ALL chunks - includes neo4j_node_id (THE BRIDGE)
        )
    
    def _extract_searchable_metadata(self, node: ParsedNode) -> Dict[str, Any]:
        """Extract relevant metadata for vector search."""
        metadata = {}
        
        # Common fields
        for field in ['subject', 'sender', 'date', 'filename', 'merchant', 'total']:
            if field in node.properties:
                metadata[field] = node.properties[field]
        
        # User ID for filtering
        if 'user_id' in node.properties:
            metadata['user_id'] = str(node.properties['user_id'])
        
        return metadata
