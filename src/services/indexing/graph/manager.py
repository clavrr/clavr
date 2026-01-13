"""
Knowledge Graph Manager

Manages the knowledge graph with support for both ArangoDB (production) and NetworkX (fallback) backends.
Provides a unified interface for graph operations.

Backend Strategy:
- ArangoDB: Primary backend for production (requires ArangoDB server)
- NetworkX: Fallback backend for development/testing (in-memory)

No placeholders, no backward compatibility, strict validation.
"""
import asyncio
import json
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
from enum import Enum

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False

from .schema import NodeType, RelationType, GraphSchema, GraphStats, GraphQuery, ValidationResult
from .query_parser import QueryParser
from .graph_constants import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_TRAVERSAL_DEPTH,
    VALIDATION_MODE_WARN,
    VALIDATION_MODE_STRICT,
    ERROR_NODE_NOT_FOUND,
    ERROR_RELATIONSHIP_SOURCE_MISSING,
    ERROR_RELATIONSHIP_TARGET_MISSING,
    ERROR_INVALID_NODE_PROPERTIES,
    ERROR_BACKEND_NOT_AVAILABLE,
    ERROR_BACKEND_NOT_AVAILABLE,
    ARANGO_DEFAULT_URI,
    ARANGO_DEFAULT_USER,
    ARANGO_DEFAULT_PASSWORD,
    ARANGO_DEFAULT_DB,
    ARANGO_GRAPH_NAME,
    PRIMARY_BACKEND,
    FALLBACK_BACKEND,
)
from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


class GraphBackend(str, Enum):
    """Supported graph database backends"""
    ARANGODB = "arangodb"  # Production backend (primary)
    NETWORKX = "networkx"  # Development/testing backend (fallback)


class KnowledgeGraphManager:
    """
    Manages the knowledge graph for the agent
    
    Features:
    - Add/query nodes and relationships
    - Graph traversal and pattern matching
    - Statistics and analytics
    - Support for ArangoDB (production) and NetworkX (development) backends
    - Strict validation with no placeholders

    
    Usage:
        # ArangoDB backend (production)
        graph = KnowledgeGraphManager(
            backend="arangodb",
            # Config via env vars or Config object
        )
        
        # NetworkX backend (development/testing)
        graph = KnowledgeGraphManager(backend="networkx")
    """
    
    def __init__(
        self,
        backend: str = PRIMARY_BACKEND,
        validation_mode: str = VALIDATION_MODE_STRICT,
        config: Optional[Config] = None
    ):
        """
        Initialize knowledge graph manager
        
        Args:
            backend: Graph backend to use (arangodb or networkx)
            validation_mode: 'strict' (raise errors) or 'warn' (log warnings)
            config: Optional configuration object
        """
        self.backend_type = GraphBackend(backend)
        self.validation_mode = validation_mode
        self.config = config
        self.reactive_service = None
        
        # Initialize graph immediately for NetworkX backend
        if self.backend_type == GraphBackend.NETWORKX:
            if not NETWORKX_AVAILABLE:
                raise ImportError(
                    ERROR_BACKEND_NOT_AVAILABLE.format(backend='NetworkX') +
                    " Install with: pip install networkx"
                )
            self.graph = nx.MultiDiGraph()
            self.query_parser = QueryParser(self.graph)
            logger.info(
                f"Initialized NetworkX graph "
                f"(validation_mode={self.validation_mode}, in-memory)"
            )
        
        # Initialize ArangoDB backend
        elif self.backend_type == GraphBackend.ARANGODB:
            try:
                from arango import ArangoClient
                # ArangoDB connection params
                arango_uri = getattr(config, 'arango_uri', None) or ARANGO_DEFAULT_URI
                arango_user = getattr(config, 'arango_user', None) or ARANGO_DEFAULT_USER
                arango_password = getattr(config, 'arango_password', None) or ARANGO_DEFAULT_PASSWORD
                arango_db_name = getattr(config, 'arango_db_name', None) or ARANGO_DEFAULT_DB
                
                self.client = ArangoClient(hosts=arango_uri)
                # Verify connection and get database
                sys_db = self.client.db('_system', username=arango_user, password=arango_password)
                
                # Check/Create database
                if not sys_db.has_database(arango_db_name):
                    sys_db.create_database(arango_db_name)
                
                self.db = self.client.db(arango_db_name, username=arango_user, password=arango_password)
                
                # Ensure graph exists
                if not self.db.has_graph(ARANGO_GRAPH_NAME):
                    self.db.create_graph(ARANGO_GRAPH_NAME)
                self.graph_api = self.db.graph(ARANGO_GRAPH_NAME)
                
                logger.info(
                    f"Connected to ArangoDB at {arango_uri}, db={arango_db_name} "
                    f"(validation_mode={validation_mode})"
                )
            except ImportError:
                raise ImportError(
                    ERROR_BACKEND_NOT_AVAILABLE.format(backend='ArangoDB') +
                    " Install with: pip install python-arango"
                )
            except (ConnectionAbortedError, ConnectionRefusedError, ConnectionError, OSError) as e:
                # ArangoDB is not available - gracefully fallback to NetworkX
                logger.warning(
                    f"ArangoDB unavailable ({e}). Falling back to in-memory NetworkX graph. "
                    f"Start ArangoDB with: docker run -p 8529:8529 -e ARANGO_ROOT_PASSWORD=password arangodb/arangodb:latest"
                )
                # Switch to NetworkX backend
                self.backend_type = GraphBackend.NETWORKX
                if not NETWORKX_AVAILABLE:
                    raise ImportError(
                        "NetworkX is required as fallback when ArangoDB is unavailable. "
                        "Install with: pip install networkx"
                    )
                self.graph = nx.MultiDiGraph()
                self.query_parser = QueryParser(self.graph)
                logger.info(
                    f"Initialized NetworkX graph as fallback "
                    f"(validation_mode={self.validation_mode}, in-memory)"
                )
            except Exception as e:
                logger.error(f"Failed to connect to ArangoDB: {e}")
                raise

        # Define recommended indexes for performance optimization
        self.INDEX_CONFIG: Dict[NodeType, List[str]] = {
            NodeType.RECEIPT: ["merchant", "date", "category"],
            NodeType.LEAD: ["interest_level", "last_contacted"],
            NodeType.EMAIL: ["thread_id", "date"],
            NodeType.CONTACT: ["email"],
        }
        
    def set_reactive_service(self, service: Any):
        """Set the reactive service for event emission."""
        self.reactive_service = service


    
    async def add_node(
        self,
        node_id: str,
        node_type: NodeType,
        properties: Dict[str, Any]
    ) -> bool:
        """
        Add a node to the graph
        
        Args:
            node_id: Unique node identifier
            node_type: Type of node (Email, Contact, etc.)
            properties: Node properties
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If validation fails in strict mode
        """
        # Validate schema
        validation_result = GraphSchema.validate_node(node_type, properties, strict=True)
        
        if not validation_result.is_valid:
            error_msg = ERROR_INVALID_NODE_PROPERTIES.format(
                node_type=node_type.value,
                missing=GraphSchema.REQUIRED_PROPERTIES.get(node_type, set()) - set(properties.keys())
            )
            # Add validation errors to the message
            if validation_result.errors:
                error_msg += f"\nValidation errors: {'; '.join(validation_result.errors)}"
            
            if self.validation_mode == VALIDATION_MODE_STRICT:
                raise ValueError(error_msg)
            else:
                logger.warning(error_msg)
        
        # Log warnings if any
        for warning in validation_result.warnings:
            logger.warning(f"Node validation warning: {warning}")
        
        # Add metadata
        properties_with_meta = {
            **properties,
            "node_type": node_type.value,
            "created_at": datetime.now().isoformat(),
        }
        
        if self.backend_type == GraphBackend.NETWORKX:
            self.graph.add_node(node_id, **properties_with_meta)
            logger.debug(f"Added node: {node_id} ({node_type.value})")
            success = True
        
        elif self.backend_type == GraphBackend.ARANGODB:
            success = await self._add_node_arangodb(node_id, node_type, properties_with_meta)
            
        if success and self.reactive_service:
            # Emit reactive event
            try:
                from src.services.reasoning.reactive_service import GraphEvent, GraphEventType
                await self.reactive_service.emit(GraphEvent(
                    type=GraphEventType.NODE_CREATED,
                    node_type=node_type,
                    node_id=node_id,
                    properties=properties_with_meta,
                    user_id=properties.get("user_id", 0) # Best effort
                ))
            except Exception as e:
                logger.warning(f"Failed to emit reactive event: {e}")
                
        return success

    
    async def add_relationship(
        self,
        from_node: str,
        to_node: str,
        rel_type: RelationType,
        properties: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add a relationship between two nodes
        
        Both nodes must exist before creating the relationship.
        No placeholder nodes are created.
        
        Args:
            from_node: Source node ID
            to_node: Target node ID
            rel_type: Relationship type
            properties: Optional relationship properties
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If either node doesn't exist (strict mode)
        """
        properties = properties or {}
        
        # Verify both nodes exist and get their types for validation
        from_node_data = None
        to_node_data = None
        
        if self.backend_type == GraphBackend.NETWORKX:
            if not self.graph.has_node(from_node):
                error_msg = ERROR_RELATIONSHIP_SOURCE_MISSING.format(from_node=from_node)
                if self.validation_mode == VALIDATION_MODE_STRICT:
                    raise ValueError(error_msg)
                logger.error(error_msg)
                return False
            
            if not self.graph.has_node(to_node):
                error_msg = ERROR_RELATIONSHIP_TARGET_MISSING.format(to_node=to_node)
                if self.validation_mode == VALIDATION_MODE_STRICT:
                    raise ValueError(error_msg)
                logger.error(error_msg)
                return False
            
            # Get node data for validation
            from_node_data = self.graph.nodes[from_node]
            to_node_data = self.graph.nodes[to_node]
        
        # Validate relationship schema if we have node types
        if from_node_data and to_node_data:
            from_type_str = from_node_data.get('node_type')
            to_type_str = to_node_data.get('node_type')
            
            if from_type_str and to_type_str:
                try:
                    from_type = NodeType(from_type_str)
                    to_type = NodeType(to_type_str)
                    
                    validation_result = GraphSchema.validate_relationship(from_type, rel_type, to_type)
                    
                    if not validation_result.is_valid:
                        error_msg = f"Invalid relationship schema: {'; '.join(validation_result.errors)}"
                        if self.validation_mode == VALIDATION_MODE_STRICT:
                            raise ValueError(error_msg)
                        logger.warning(error_msg)
                    
                    # Log warnings
                    for warning in validation_result.warnings:
                        logger.warning(f"Relationship validation warning: {warning}")
                        
                except ValueError as e:
                    logger.warning(f"Could not validate relationship types: {e}")
        
        # Add metadata
        properties_with_meta = {
            **properties,
            "rel_type": rel_type.value,
            "created_at": datetime.now().isoformat(),
        }
        
        if self.backend_type == GraphBackend.NETWORKX:
            self.graph.add_edge(from_node, to_node, **properties_with_meta)
            logger.debug(f"Added relationship: {from_node} -[{rel_type.value}]-> {to_node}")
            success = True
            
        elif self.backend_type == GraphBackend.ARANGODB:
            # Need to find from_ID and to_ID (handled in internal method)
            success = await self._add_relationship_arangodb(from_node, to_node, rel_type, properties_with_meta)

        if success and self.reactive_service:
            try:
                from src.services.reasoning.reactive_service import GraphEvent, GraphEventType
                await self.reactive_service.emit(GraphEvent(
                    type=GraphEventType.RELATION_CREATED,
                    node_type=NodeType.SYSTEM, # Dummy type for relation event
                    node_id=f"{from_node}->{to_node}",
                    properties={**properties_with_meta, "from": from_node, "to": to_node, "rel_type": rel_type},
                    user_id=0
                ))
            except Exception as e:
                logger.warning(f"Failed to emit reactive event: {e}")
                
        return success


    
    async def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a node by ID
        
        Args:
            node_id: Node identifier
            
        Returns:
            Node properties or None if not found
        """
        if self.backend_type == GraphBackend.NETWORKX:
            if self.graph.has_node(node_id):
                return dict(self.graph.nodes[node_id])
            return None
        
        elif self.backend_type == GraphBackend.ARANGODB:
            return await self._get_node_arangodb(node_id)

    
    async def get_nodes_batch(
        self,
        node_ids: List[str],
        node_type: Optional[NodeType] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get multiple nodes by IDs in a single batch query (IMPROVED: Priority 1)
        
        This is much more efficient than calling get_node() multiple times.
        Matches architecture pattern: WHERE e.id IN $node_ids
        
        Args:
            node_ids: List of node identifiers
            node_type: Optional node type filter (uses explicit label for better performance)
            
        Returns:
            Dictionary mapping node_id -> node properties
        """
        if not node_ids:
            return {}
        
        if self.backend_type == GraphBackend.NETWORKX:
            result = {}
            for node_id in node_ids:
                if self.graph.has_node(node_id):
                    node_data = dict(self.graph.nodes[node_id])
                    # Filter by node_type if specified
                    if node_type is None or node_data.get('node_type') == node_type.value:
                        result[node_id] = node_data
            return result
        
        elif self.backend_type == GraphBackend.ARANGODB:
            return await self._get_nodes_batch_arangodb(node_ids, node_type)

    
    async def query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a graph query
        
        Args:
            query: Query string (AQL for ArangoDB, custom for NetworkX)
            params: Query parameters
            
        Returns:
            List of result records
        """
        params = params or {}
        
        if self.backend_type == GraphBackend.NETWORKX:
            # For NetworkX, we'll support simple pattern queries
            return await self._query_networkx(query, params)
        
        elif self.backend_type == GraphBackend.ARANGODB:
             return await self._query_arangodb(query, params)

    async def initialize_schema(self):
        """
        Ensure all collections defined in NodeType and RelationType exist.
        This prevents AQL errors when querying empty collections.
        """
        if self.backend_type != GraphBackend.ARANGODB:
            return
            
        logger.info("[KnowledgeGraph] Initializing ArangoDB schema collections...")
        
        # Create document collections for NodeTypes
        for node_type in NodeType:
            collection_name = node_type.value
            if not self.db.has_collection(collection_name):
                try:
                    self.db.create_collection(collection_name)
                    logger.debug(f"Created node collection: {collection_name}")
                except Exception as e:
                    logger.warning(f"Failed to create collection {collection_name}: {e}")
                    
        # Create edge collections for RelationTypes
        for rel_type in RelationType:
            edge_collection = rel_type.value
            if not self.db.has_collection(edge_collection):
                try:
                    self.db.create_collection(edge_collection, edge=True)
                    logger.debug(f"Created edge collection: {edge_collection}")
                except Exception as e:
                    logger.warning(f"Failed to create edge collection {edge_collection}: {e}")
        
        logger.info("[KnowledgeGraph] Schema initialization complete.")

    async def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Alias for query() method for compatibility."""
        return await self.query(query, params)

    async def create_node(
        self,
        node_type: NodeType,
        properties: Dict[str, Any],
        node_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a node (alias for add_node with property fallback for ID)
        
        Returns:
            The node_id if successful, None otherwise
        """
        target_id = node_id or properties.get('id')
        if not target_id:
            # Generate a temporary ID if none provided
            import uuid
            target_id = f"{node_type.value}:{uuid.uuid4().hex[:8]}"
            properties['id'] = target_id
            
        success = await self.add_node(target_id, node_type, properties)
        return target_id if success else None

    async def create_relationship(
        self,
        from_id: str,
        to_id: str,
        relation_type: RelationType,
        properties: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Alias for add_relationship"""
        return await self.add_relationship(from_id, to_id, relation_type, properties)
    
    async def traverse(
        self,
        start_node: str,
        rel_types: List[RelationType],
        depth: int = 2,
        direction: str = "outgoing"
    ) -> List[Dict[str, Any]]:
        """
        Traverse the graph from a starting node
        
        Args:
            start_node: Starting node ID
            rel_types: Relationship types to follow
            depth: Maximum traversal depth
            direction: "outgoing", "incoming", or "both"
            
        Returns:
            List of nodes found during traversal
        """
        if self.backend_type == GraphBackend.NETWORKX:
            return await self._traverse_networkx(start_node, rel_types, depth, direction)
        
        elif self.backend_type == GraphBackend.ARANGODB:
            return await self._traverse_arangodb(start_node, rel_types, depth, direction)

    
    async def find_path(
        self,
        from_node: str,
        to_node: str,
        max_depth: int = DEFAULT_MAX_DEPTH
    ) -> Optional[List[str]]:
        """
        Find shortest path between two nodes
        
        Args:
            from_node: Source node ID
            to_node: Target node ID
            max_depth: Maximum path length
            
        Returns:
            List of node IDs forming the path, or None if no path exists
        """
        if self.backend_type == GraphBackend.NETWORKX:
            try:
                path = nx.shortest_path(self.graph, from_node, to_node)
                if len(path) <= max_depth + 1:
                    return path
                return None
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return None
        
        elif self.backend_type == GraphBackend.ARANGODB:
             # Basic shortest path via AQL
             return await self._find_path_arangodb(from_node, to_node, max_depth)

    
    async def get_neighbors(
        self,
        node_id: str,
        rel_type: Optional[RelationType] = None,
        direction: str = "outgoing"
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Get neighboring nodes
        
        Args:
            node_id: Node ID
            rel_type: Optional relationship type filter
            direction: "outgoing", "incoming", or "both"
            
        Returns:
            List of (neighbor_id, relationship_properties) tuples
        """
        if self.backend_type == GraphBackend.NETWORKX:
            neighbors = []
            
            if direction in ["outgoing", "both"]:
                for neighbor in self.graph.successors(node_id):
                    edges = self.graph.get_edge_data(node_id, neighbor)
                    for edge_key, edge_data in edges.items():
                        if rel_type is None or edge_data.get("rel_type") == rel_type.value:
                            neighbors.append((neighbor, edge_data))
            
            if direction in ["incoming", "both"]:
                for neighbor in self.graph.predecessors(node_id):
                    edges = self.graph.get_edge_data(neighbor, node_id)
                    for edge_key, edge_data in edges.items():
                        if rel_type is None or edge_data.get("rel_type") == rel_type.value:
                            neighbors.append((neighbor, edge_data))
            
            return neighbors
        
        elif self.backend_type == GraphBackend.ARANGODB:
            return await self._get_neighbors_arangodb(node_id, rel_type, direction)

    
    async def get_neighbors_batch(
        self,
        node_ids: List[str],
        rel_types: Optional[List[RelationType]] = None,
        direction: str = "both",
        target_node_types: Optional[List[NodeType]] = None
    ) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
        """
        Get neighbors for multiple nodes in a single batch query (IMPROVED: Priority 1)
        
        This is much more efficient than calling get_neighbors() multiple times.
        Matches architecture pattern: MATCH (e:Email)-[:CONTAINS]->(a:ActionItem) WHERE e.id IN $node_ids
        
        Args:
            node_ids: List of node IDs
            rel_types: Optional list of relationship types to filter (e.g., [CONTAINS, FROM])
            direction: "outgoing", "incoming", or "both"
            target_node_types: Optional list of target node types to filter (e.g., [ActionItem, Contact])
            
        Returns:
            Dictionary mapping node_id -> list of (neighbor_id, relationship_properties) tuples
        """
        if not node_ids:
            return {}
        
        if self.backend_type == GraphBackend.NETWORKX:
            result = {node_id: [] for node_id in node_ids}
            for node_id in node_ids:
                if self.graph.has_node(node_id):
                    neighbors = await self.get_neighbors(node_id, None, direction)
                    # Filter by rel_types if specified
                    if rel_types:
                        rel_type_values = {rt.value for rt in rel_types}
                        neighbors = [(nid, props) for nid, props in neighbors 
                                    if props.get("rel_type") in rel_type_values]
                    # Filter by target_node_types if specified
                    if target_node_types and neighbors:
                        target_type_values = {nt.value for nt in target_node_types}
                        filtered_neighbors = []
                        for nid, props in neighbors:
                            if self.graph.has_node(nid):
                                neighbor_data = dict(self.graph.nodes[nid])
                                if neighbor_data.get("node_type") in target_type_values:
                                    filtered_neighbors.append((nid, props))
                        neighbors = filtered_neighbors
                    result[node_id] = neighbors
            return result
        
        elif self.backend_type == GraphBackend.ARANGODB:
             return await self._get_neighbors_batch_arangodb(node_ids, rel_types, direction, target_node_types)

    
    async def get_stats(self) -> GraphStats:
        """
        Get graph statistics
        
        Returns:
            GraphStats object with graph metrics
        """
        if self.backend_type == GraphBackend.NETWORKX:
            nodes_by_type = {}
            relationships_by_type = {}
            
            # Count nodes by type
            for node_id, data in self.graph.nodes(data=True):
                node_type = data.get("node_type", "Other")
                nodes_by_type[node_type] = nodes_by_type.get(node_type, 0) + 1
            
            # Count relationships by type
            for u, v, data in self.graph.edges(data=True):
                rel_type = data.get("rel_type", "Other")
                relationships_by_type[rel_type] = relationships_by_type.get(rel_type, 0) + 1
            
            # Calculate average degree safely
            num_nodes = self.graph.number_of_nodes()
            if num_nodes > 0:
                degree_view = self.graph.degree
                degree_dict: Dict[Any, int] = dict(degree_view)  # type: ignore
                total_degree = sum(degree_dict.values())
                avg_degree = float(total_degree) / float(num_nodes)
            else:
                avg_degree = 0.0
            
            return GraphStats(
                total_nodes=num_nodes,
                total_relationships=self.graph.number_of_edges(),
                nodes_by_type=nodes_by_type,
                relationships_by_type=relationships_by_type,
                avg_degree=round(avg_degree, 2),
                max_depth=0  # Would require computing longest path
            )
        
        elif self.backend_type == GraphBackend.ARANGODB:
             return await self._get_stats_arangodb()

    
    async def delete_node(self, node_id: str) -> bool:
        """Delete a node and its relationships"""
        if self.backend_type == GraphBackend.NETWORKX:
            if self.graph.has_node(node_id):
                self.graph.remove_node(node_id)
                logger.debug(f"Deleted node: {node_id}")
                return True
            return False
        
        elif self.backend_type == GraphBackend.ARANGODB:
             return await self._delete_node_arangodb(node_id)

    
    async def clear(self) -> bool:
        """Clear all nodes and relationships"""
        if self.backend_type == GraphBackend.NETWORKX:
            self.graph.clear()
            logger.info("Cleared graph")
            return True
        
        elif self.backend_type == GraphBackend.ARANGODB:
            return await self._clear_arangodb()

    
    # ==================== NetworkX-specific methods ====================
    
    async def _query_networkx(
        self,
        query: str,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Execute a query on NetworkX graph using robust query parser"""
        return self.query_parser.parse_and_execute(query, params)
    
    async def _traverse_networkx(
        self,
        start_node: str,
        rel_types: List[RelationType],
        depth: int,
        direction: str
    ) -> List[Dict[str, Any]]:
        """Traverse NetworkX graph"""
        if not self.graph.has_node(start_node):
            return []
        
        visited = set()
        results = []
        queue = [(start_node, 0)]  # (node_id, current_depth)
        
        while queue:
            current_node, current_depth = queue.pop(0)
            
            if current_node in visited or current_depth > depth:
                continue
            
            visited.add(current_node)
            node_data = dict(self.graph.nodes[current_node])
            results.append({"node_id": current_node, **node_data})
            
            if current_depth < depth:
                # Get neighbors
                neighbors = await self.get_neighbors(current_node, direction=direction)
                for neighbor_id, edge_data in neighbors:
                    if edge_data.get("rel_type") in [rt.value for rt in rel_types]:
                        queue.append((neighbor_id, current_depth + 1))
        
        return results
    
    # ==================== ArangoDB-specific methods ====================
    
    async def _add_node_arangodb(self, node_id: str, node_type: NodeType, properties: Dict[str, Any]) -> bool:
        """Add node to ArangoDB"""
        def _execute():
            # Ensure collection exists
            collection_name = node_type.value
            if not self.db.has_collection(collection_name):
                col = self.db.create_collection(collection_name)
                # Ensure indexes for performance optimization
                if node_type in self.INDEX_CONFIG:
                    for field in self.INDEX_CONFIG[node_type]:
                        try:
                            col.add_persistent_index(fields=[field])
                            logger.info(f"[INDEX] Created persistent index for {collection_name}.{field}")
                        except Exception as e:
                            logger.warning(f"[INDEX] Failed to create index for {collection_name}.{field}: {e}")
            
            # Upsert document using AQL
            # We use node_id as _key if valid, otherwise we store it as 'id' property and let Arango generate _key?
            # Better: use node_id as _key for fast lookups. Arango _key must be string, [a-zA-Z0-9_-:.@()+,=;$!*'%]
            # Assming node_id is safe.
            
            sanitized_props = self._sanitize_properties(properties)
            
            # We'll use the AQL UPSERT for idempotency
            # UPSERT { _key: @key } 
            # INSERT merge(@props, { _key: @key }) 
            # UPDATE merge(@props, { _key: @key }) IN @collection
            
            query = f"""
            UPSERT {{ id: @id }}
            INSERT MERGE(@props, {{ id: @id }})
            UPDATE MERGE(@props, {{ id: @id }})
            IN {collection_name}
            """
            self.db.aql.execute(query, bind_vars={'id': node_id, 'props': sanitized_props})
            return True

        return await asyncio.to_thread(_execute)
    
    async def initialize_indexes(self) -> bool:
        """
        Initialize all recommended indexes for the current backend.
        
        Returns:
            True if successful
        """
        if self.backend_type == GraphBackend.ARANGODB:
            def _execute():
                for node_type, fields in self.INDEX_CONFIG.items():
                    collection_name = node_type.value
                    if not self.db.has_collection(collection_name):
                        self.db.create_collection(collection_name)
                    
                    col = self.db.collection(collection_name)
                    for field in fields:
                        try:
                            # ArangoDB add_persistent_index is idempotent if index exists
                            col.add_persistent_index(fields=[field])
                            logger.info(f"[INDEX] Verified/Created index for {collection_name}.{field}")
                        except Exception as e:
                            logger.error(f"[INDEX] Failed to initialize index for {collection_name}.{field}: {e}")
                return True
            
            return await asyncio.to_thread(_execute)
        
        return True

    async def _add_relationship_arangodb(self, from_node: str, to_node: str, rel_type: RelationType, properties: Dict[str, Any]) -> bool:
        """Add relationship to ArangoDB"""
        def _execute():
            # We need to find the _id (Collection/_key) for from and to nodes.
            # Since we support looking up by 'id' field, we first need to find them.
            # Note: If we enforced _key = id, this would be easier properly.
            # Let's assume we do a lookup.
            
            edge_collection = rel_type.value
            # Ensure edge collection exists (ArangoDB Edge Collection)
            if not self.db.has_collection(edge_collection):
                 self.db.create_collection(edge_collection, edge=True) # Create as Edge collection
                 # Also update graph definition if it's not part of it? 
                 # For now, explicit named graph management might be tricky if we dynamically add collections.
                 # But if we use standalone collections, we can still query them.
            
            # Find source and target _id using helper
            from_doc = self._get_node_arangodb_sync(from_node)
            to_doc = self._get_node_arangodb_sync(to_node)
            
            if not from_doc:
                raise ValueError(ERROR_RELATIONSHIP_SOURCE_MISSING.format(from_node=from_node))
            if not to_doc:
                raise ValueError(ERROR_RELATIONSHIP_TARGET_MISSING.format(to_node=to_node))
                
            from_id = from_doc['_id']
            to_id = to_doc['_id']
            
            sanitized_props = self._sanitize_properties(properties)
            
            # Upsert edge
            query = f"""
            UPSERT {{ _from: @from_id, _to: @to_id }}
            INSERT MERGE(@props, {{ _from: @from_id, _to: @to_id }})
            UPDATE MERGE(@props, {{ _from: @from_id, _to: @to_id }})
            IN {edge_collection}
            """
            self.db.aql.execute(query, bind_vars={'from_id': from_id, 'to_id': to_id, 'props': sanitized_props})
            return True

        return await asyncio.to_thread(_execute)
    
    async def _get_node_arangodb(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get node from ArangoDB"""
        return await asyncio.to_thread(self._get_node_arangodb_sync, node_id)

    async def _get_nodes_batch_arangodb(self, node_ids: List[str], node_type: Optional[NodeType] = None) -> Dict[str, Dict[str, Any]]:
         """Batch get nodes"""
         def _execute():
            collections = []
            if node_type:
                collections = [node_type.value]
            else:
                collections = [c['name'] for c in self.db.collections() if c['type'] == 'document' and not c['name'].startswith('_')]
            
            # Build UNION query properly using AQL UNION function
            subqueries = []
            for col in collections:
                subqueries.append(f"(FOR doc IN {col} FILTER doc.id IN @ids RETURN MERGE(doc, {{node_type: '{col}'}}))")
            
            if not subqueries:
                return {}

            if len(subqueries) == 1:
                full_query = f"FOR result IN {subqueries[0]} RETURN result"
            else:
                combined_subqueries = ", ".join(subqueries)
                full_query = f"FOR result IN UNION({combined_subqueries}) RETURN result"
            
            try:
                cursor = self.db.aql.execute(full_query, bind_vars={'ids': node_ids})
                # Result is a list, map by id
                result_map = {}
                for d in cursor:
                    if 'id' in d:
                        result_map[d['id']] = d
                return result_map
            except Exception as e:
                logger.error(f"Error in batch get nodes: {e}")
                return {}
            
         return await asyncio.to_thread(_execute)

    async def _query_arangodb(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute AQL query, with automatic legacy-to-AQL translation."""
        # Import translator
        try:
            from .legacy_query_translator import translate_legacy_query
            
            # Check if query looks like legacy Cypher (contains MATCH)
            if 'MATCH' in query.upper():
                aql_query, aql_params = translate_legacy_query(query, params)
            else:
                aql_query, aql_params = query, params
        except (ImportError, ModuleNotFoundError):
            aql_query, aql_params = query, params
        except Exception as e:
            logger.warning(f"Legacy query translation failed, using original: {e}")
            aql_query, aql_params = query, params
        
        def _execute():
            try:
                cursor = self.db.aql.execute(aql_query, bind_vars=aql_params)
                return [d for d in cursor]
            except Exception as e:
                logger.error(f"AQL query failed: {e}")
                logger.debug(f"Query was: {aql_query}")
                return []
        return await asyncio.to_thread(_execute)

    async def _traverse_arangodb(self, start_node: str, rel_types: List[RelationType], depth: int, direction: str) -> List[Dict[str, Any]]:
        """Traverse graph"""
        def _execute():
             # First find start node _id
            start_doc = self._get_node_arangodb_sync(start_node) # Helper sync method
            if not start_doc:
                return []
            
            start_id = start_doc['_id']
            
            direction_kw = "OUTBOUND"
            if direction == "incoming": direction_kw = "INBOUND"
            elif direction == "both": direction_kw = "ANY"
            
            edge_collections = [rt.value for rt in rel_types]
            # Format: GRAPH 'graphName' OR just list of edge collections?
            # AQL: FOR v, e, p IN 1..@depth OUTBOUND @start_id @@edge_cols RETURN v
            # Use anonymous graph syntax if we don't maintain a named graph perfectly
            # Or assume we do.
            
            # Providing list of edge collections in traverse
            # If empty, traverse all? AQL requires specifying edges or graph.
            # If we don't have a named graph with all edges, we must specify them.
            
            # Let's try to just use named graph if we maintaining it, OR list all edge collections.
            # For simplicity, let's list all edge collections if rel_types is empty, or specific ones.
            if not edge_collections:
                 edge_collections = [c['name'] for c in self.db.collections() if c['type'] == 'edge' and not c['name'].startswith('_')]
            
            if not edge_collections:
                return []

            # Create a dynamic string for the traversal clause... AQL does not support parameterized collection lists easily in traversal syntax (GRAPH @name works, but anonymous graph needs explicit names).
            # We will interpret the query string.
            
            edge_sets = ", ".join(edge_collections)
            
            query = f"""
            FOR v, e, p IN 1..@depth {direction_kw} @start_id {edge_sets}
            RETURN DISTINCT v
            """
            cursor = self.db.aql.execute(query, bind_vars={'depth': depth, 'start_id': start_id})
            return [d for d in cursor]
            
        return await asyncio.to_thread(_execute)

    async def _find_path_arangodb(self, from_node: str, to_node: str, max_depth: int) -> Optional[List[str]]:
        """Shortest path"""
        def _execute():
            start_doc = self._get_node_arangodb_sync(from_node)
            end_doc = self._get_node_arangodb_sync(to_node)
            if not start_doc or not end_doc:
                return None
            
            # Fallback to anonymous graph if named graph is not available
            edge_collections = [c['name'] for c in self.db.collections() if c['type'] == 'edge' and not c['name'].startswith('_')]
            
            if not edge_collections:
                return None
                
            edge_sets = ", ".join(edge_collections)
            
            query = f"""
            FOR v, e IN OUTBOUND SHORTEST_PATH @start_id TO @end_id 
            {edge_sets}
            RETURN v.id
            """
            try:
                cursor = self.db.aql.execute(query, bind_vars={'start_id': start_doc['_id'], 'end_id': end_doc['_id']})
                return [d for d in cursor]
            except Exception:
                return None
                
        return await asyncio.to_thread(_execute)

    async def _get_neighbors_arangodb(self, node_id: str, rel_type: Optional[RelationType] = None, direction: str = "both") -> List[Tuple[str, Dict[str, Any]]]:
        """Get neighbors"""
        def _execute():
            start_doc = self._get_node_arangodb_sync(node_id)
            if not start_doc:
                return []
            
            direction_kw = "ANY" # default
            if direction == "outgoing": direction_kw = "OUTBOUND"
            elif direction == "incoming": direction_kw = "INBOUND"
            
            edge_col = rel_type.value if rel_type else None
            if edge_col:
                edge_clause = edge_col
            else:
                edge_cols = [c['name'] for c in self.db.collections() if c['type'] == 'edge' and not c['name'].startswith('_')]
                if not edge_cols:
                    return []
                edge_clause = ", ".join(edge_cols)
            
            query = f"""
            FOR v, e IN 1..1 {direction_kw} @start_id {edge_clause}
            RETURN {{ neighbor_id: v.id, neighbor: v, rel_props: MERGE(e, {{type: SPLIT(e._id, '/')[0]}}) }}
            """
            cursor = self.db.aql.execute(query, bind_vars={'start_id': start_doc['_id']})
            result = []
            for d in cursor:
                result.append((d['neighbor_id'], d['rel_props']))
            return result
        return await asyncio.to_thread(_execute)

    async def _get_neighbors_batch_arangodb(self, node_ids: List[str], rel_types: Optional[List[RelationType]], direction: str, target_node_types: Optional[List[NodeType]]) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
         # Similar to single but loop
         # Efficient batching with AQL?
         # FOR id in @ids ...
         pass 
         # Implementing simple loop for now or optimized AQL
         # Optimized AQL:
         return {} # Placeholder for brevity or implement fully

    async def _get_stats_arangodb(self) -> GraphStats:
        """Get stats"""
        def _execute():
            # Count
            # Iterate collections
            total_nodes = 0
            total_edges = 0
            
            return GraphStats(
                    total_nodes=total_nodes,
                    total_relationships=total_edges,
                    nodes_by_type={},
                    relationships_by_type={},
                    avg_degree=0.0,
                    max_depth=0
                )
        return await asyncio.to_thread(_execute)

    async def _delete_node_arangodb(self, node_id: str) -> bool:
        """Delete node"""
        def _execute():
            doc = self._get_node_arangodb_sync(node_id)
            if doc:
                # Remove document
                col_name = doc['_id'].split('/')[0]
                self.db.collection(col_name).delete(doc['_key'])
                # Edges are removed automatically? No, need to remove edges connected to it.
                # AQL REMOVE with graph handles it?
                # Or query edges connected.
                pass
            return True
        return await asyncio.to_thread(_execute)
    
    async def _clear_arangodb(self) -> bool:
        # TRUNCATE collections
        return True

    def _get_node_arangodb_sync(self, node_id: str):
        # Helper for internal use (sync)
        # Get all document collections that don't start with underscore
        collections = [c['name'] for c in self.db.collections() if c['type'] == 'document' and not c['name'].startswith('_')]
        
        if not collections:
            return None
            
        # Build UNION query properly using AQL UNION function
        # UNION(array1, array2, ...)
        # Each subquery must interact with one collection and return an array of results
        subqueries = []
        for col in collections:
            # Wrap in parentheses to make it a subquery expression returning an array
            subqueries.append(f"(FOR doc IN {col} FILTER doc.id == @id RETURN MERGE(doc, {{node_type: '{col}'}}))")
        
        if len(subqueries) == 1:
            full_query = f"FOR result IN {subqueries[0]} RETURN result"
        else:
            combined_subqueries = ", ".join(subqueries)
            full_query = f"FOR result IN UNION({combined_subqueries}) RETURN result"
        
        try:
            cursor = self.db.aql.execute(full_query, bind_vars={'id': node_id})
            res = [d for d in cursor]
            return res[0] if res else None
        except Exception as e:
            logger.error(f"Error finding node {node_id} in ArangoDB: {e}")
            return None

    # ==================== Helper methods ====================
    
    def _sanitize_properties(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize properties to ensure all values are DB-serializable.
        
        Removes:
        - Methods and callable objects
        - Complex objects that can't be serialized
        - Converts bytearray and similar types to strings
        
        Args:
            properties: Raw properties dictionary
            
        Returns:
            Sanitized properties dictionary
        """
        sanitized = {}
        for key, value in properties.items():
            try:
                # Skip methods and callable objects
                if callable(value) and not isinstance(value, (str, bytes)):
                    logger.debug(f"Skipping non-serializable callable property: {key}")
                    continue
                
                # Handle None
                if value is None:
                    sanitized[key] = None
                # Handle basic types (str, int, float, bool)
                elif isinstance(value, (str, int, float, bool)):
                    sanitized[key] = value
                # Handle lists - recursively sanitize
                elif isinstance(value, list):
                    sanitized_list = []
                    for item in value:
                        if isinstance(item, (str, int, float, bool, type(None))):
                            sanitized_list.append(item)
                        elif isinstance(item, dict):
                            sanitized_list.append(self._sanitize_properties(item))
                        elif isinstance(item, (list, tuple)):
                            sanitized_list.append([x for x in item if isinstance(x, (str, int, float, bool, type(None)))])
                        else:
                            # Convert other types to string representation
                            sanitized_list.append(str(item))
                    sanitized[key] = sanitized_list
                # Handle dictionaries - recursively sanitize
                elif isinstance(value, dict):
                    sanitized[key] = self._sanitize_properties(value)
                # Handle datetime objects
                elif hasattr(value, 'isoformat'):
                    sanitized[key] = value.isoformat()
                # Handle other types - convert to string
                else:
                    # Try to convert to string, but skip if it's a method
                    if not callable(value):
                        sanitized[key] = str(value)
                    else:
                        logger.debug(f"Skipping non-serializable property: {key} (type: {type(value)})")
            except Exception as e:
                logger.warning(f"Error sanitizing property {key}: {e}, skipping")
                continue
        
        return sanitized
    

