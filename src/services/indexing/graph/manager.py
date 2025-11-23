"""
Knowledge Graph Manager

Manages the knowledge graph with support for both Neo4j (production) and NetworkX (fallback) backends.
Provides a unified interface for graph operations.

Backend Strategy:
- Neo4j: Primary backend for production (requires Neo4j server)
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
    NEO4J_DEFAULT_URI,
    NEO4J_DEFAULT_USER,
    NEO4J_DEFAULT_PASSWORD,
    PRIMARY_BACKEND,
    FALLBACK_BACKEND,
)
from ....utils.logger import setup_logger
from ....utils.config import Config

logger = setup_logger(__name__)


class GraphBackend(str, Enum):
    """Supported graph database backends"""
    NEO4J = "neo4j"  # Production backend (primary)
    NETWORKX = "networkx"  # Development/testing backend (fallback)


class KnowledgeGraphManager:
    """
    Manages the knowledge graph for the agent
    
    Features:
    - Add/query nodes and relationships
    - Graph traversal and pattern matching
    - Statistics and analytics
    - Support for Neo4j (production) and NetworkX (development) backends
    - Strict validation with no placeholders

    
    Usage:
        # Neo4j backend (production)
        graph = KnowledgeGraphManager(
            backend="neo4j",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="password"
        )
        
        # NetworkX backend (development/testing)
        graph = KnowledgeGraphManager(backend="networkx")
    """
    
    def __init__(
        self,
        backend: str = PRIMARY_BACKEND,
        neo4j_uri: Optional[str] = None,
        neo4j_user: Optional[str] = None,
        neo4j_password: Optional[str] = None,
        validation_mode: str = VALIDATION_MODE_STRICT,
        config: Optional[Config] = None
    ):
        """
        Initialize knowledge graph manager
        
        Args:
            backend: Graph backend to use (neo4j or networkx)
            neo4j_uri: Neo4j connection URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            validation_mode: 'strict' (raise errors) or 'warn' (log warnings)
            config: Optional configuration object
        """
        self.backend_type = GraphBackend(backend)
        self.validation_mode = validation_mode
        self.config = config
        
        # Get Neo4j credentials - Priority: parameters > environment variables > config > defaults
        # This allows Neo4j Aura (cloud) to work via environment variables
        import os
        
        neo4j_uri = neo4j_uri or os.getenv('NEO4J_URI') or (getattr(config, 'neo4j_uri', None) if config else None) or NEO4J_DEFAULT_URI
        neo4j_user = neo4j_user or os.getenv('NEO4J_USER') or (getattr(config, 'neo4j_user', None) if config else None) or NEO4J_DEFAULT_USER
        neo4j_password = neo4j_password or os.getenv('NEO4J_PASSWORD') or (getattr(config, 'neo4j_password', None) if config else None) or NEO4J_DEFAULT_PASSWORD
        
        # Initialize backend
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
                f"(validation_mode={validation_mode}, in-memory)"
            )
        
        elif self.backend_type == GraphBackend.NEO4J:
            try:
                from neo4j import GraphDatabase
                self.driver = GraphDatabase.driver(
                    neo4j_uri,
                    auth=(neo4j_user, neo4j_password)
                )
                logger.info(
                    f"Connected to Neo4j at {neo4j_uri} "
                    f"(validation_mode={validation_mode})"
                )
            except ImportError:
                raise ImportError(
                    ERROR_BACKEND_NOT_AVAILABLE.format(backend='Neo4j') +
                    " Install with: pip install neo4j"
                )
    
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
            return True
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._add_node_neo4j(node_id, node_type, properties_with_meta)
    
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
            return True
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._add_relationship_neo4j(
                from_node, to_node, rel_type, properties_with_meta
            )
    
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
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._get_node_neo4j(node_id)
    
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
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._get_nodes_batch_neo4j(node_ids, node_type)
    
    async def query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a graph query
        
        Args:
            query: Query string (Cypher for Neo4j, custom for NetworkX)
            params: Query parameters
            
        Returns:
            List of result records
        """
        params = params or {}
        
        if self.backend_type == GraphBackend.NETWORKX:
            # For NetworkX, we'll support simple pattern queries
            return await self._query_networkx(query, params)
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._query_neo4j(query, params)
    
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
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._traverse_neo4j(start_node, rel_types, depth, direction)
    
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
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._find_path_neo4j(from_node, to_node, max_depth)
    
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
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._get_neighbors_neo4j(node_id, rel_type, direction)
    
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
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._get_neighbors_batch_neo4j(node_ids, rel_types, direction, target_node_types)
    
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
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._get_stats_neo4j()
    
    async def delete_node(self, node_id: str) -> bool:
        """Delete a node and its relationships"""
        if self.backend_type == GraphBackend.NETWORKX:
            if self.graph.has_node(node_id):
                self.graph.remove_node(node_id)
                logger.debug(f"Deleted node: {node_id}")
                return True
            return False
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._delete_node_neo4j(node_id)
    
    async def clear(self) -> bool:
        """Clear all nodes and relationships"""
        if self.backend_type == GraphBackend.NETWORKX:
            self.graph.clear()
            logger.info("Cleared graph")
            return True
        
        elif self.backend_type == GraphBackend.NEO4J:
            return await self._clear_neo4j()
    
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
    
    # ==================== Neo4j-specific methods ====================
    
    def _sanitize_properties(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize properties to ensure all values are Neo4j-serializable.
        
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
    
    async def _add_node_neo4j(
        self,
        node_id: str,
        node_type: NodeType,
        properties: Dict[str, Any]
    ) -> bool:
        """
        Add node to Neo4j (IMPROVED: Priority 4 - adds uuid property for alignment)
        """
        def _execute():
            try:
                with self.driver.session() as session:
                    # Sanitize properties to remove non-serializable values
                    sanitized_properties = self._sanitize_properties(properties)
                    
                    # Add uuid property alongside id for better alignment with architecture (Priority 4)
                    properties_with_uuid = {
                        **sanitized_properties,
                        'uuid': node_id,  # Add uuid as alias to id
                        'id': node_id    # Keep id as primary
                    }
                    
                    query = f"""
                    MERGE (n:{node_type.value} {{id: $node_id}})
                    SET n += $properties
                    RETURN n
                    """
                    session.run(query, node_id=node_id, properties=properties_with_uuid)
                    return True
            except Exception as e:
                # Re-raise to be caught by caller
                raise
        
        try:
            return await asyncio.to_thread(_execute)
        except Exception as e:
            # Check if it's a connection error (including BrokenPipeError)
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
                # Log the error but don't raise - allow graceful fallback
                logger.warning(
                    f"Neo4j connection error for node {node_id}: {error_type}: {error_str}. "
                    f"This is likely a transient network issue. Will retry on next operation."
                )
                # Return False to indicate failure, but don't raise exception
                # This allows the caller to handle gracefully (e.g., fallback to vector-only)
                return False
            raise
    
    async def _add_relationship_neo4j(
        self,
        from_node: str,
        to_node: str,
        rel_type: RelationType,
        properties: Dict[str, Any]
    ) -> bool:
        """Add relationship to Neo4j"""
        # Get node types for explicit labels 
        from_node_data = await self._get_node_neo4j(from_node)
        to_node_data = await self._get_node_neo4j(to_node)
        
        from_label = ""
        to_label = ""
        if from_node_data and isinstance(from_node_data, dict):
            from_type = from_node_data.get('node_type')
            if from_type:
                from_label = f":{from_type}"
        if to_node_data and isinstance(to_node_data, dict):
            to_type = to_node_data.get('node_type')
            if to_type:
                to_label = f":{to_type}"
        
        def _execute():
            try:
                with self.driver.session() as session:
                    # Sanitize relationship properties
                    sanitized_properties = self._sanitize_properties(properties) if properties else {}
                    
                    # Use separate MATCH statements to avoid cartesian product warning
                    # MERGE ensures idempotency (won't create duplicate relationships)
                    query = f"""
                    MATCH (a{from_label} {{id: $from_node}})
                    MATCH (b{to_label} {{id: $to_node}})
                    MERGE (a)-[r:{rel_type.value}]->(b)
                    SET r += $properties
                    RETURN r
                    """
                    session.run(query, from_node=from_node, to_node=to_node, properties=sanitized_properties)
                    return True
            except Exception as e:
                # Re-raise to be caught by caller
                raise
        
        try:
            return await asyncio.to_thread(_execute)
        except Exception as e:
            # Check if it's a connection error (including BrokenPipeError)
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
                # Log the error but don't raise - allow graceful fallback
                logger.warning(
                    f"Neo4j connection error for relationship {from_node}->{to_node}: {error_type}: {error_str}. "
                    f"This is likely a transient network issue. Will retry on next operation."
                )
                # Return False to indicate failure, but don't raise exception
                return False
            raise
    
    async def _get_node_neo4j(self, node_id: str, node_type: Optional[NodeType] = None) -> Optional[Dict[str, Any]]:
        """
        Get node from Neo4j (IMPROVED: Priority 2 - uses explicit label)
        
        Args:
            node_id: Node identifier
            node_type: Optional node type for explicit label (better performance)
        """
        def _execute():
            try:
                with self.driver.session() as session:
                    # Use explicit label if provided (Priority 2 improvement)
                    if node_type:
                        query = f"MATCH (n:{node_type.value} {{id: $node_id}}) RETURN n"
                    else:
                        query = "MATCH (n {id: $node_id}) RETURN n"
                    result = session.run(query, node_id=node_id)
                    record = result.single()
                    if record:
                        node_data = dict(record["n"])
                        # Extract properties correctly
                        if isinstance(node_data, dict) and 'properties' in node_data:
                            return node_data['properties']
                        return node_data
                    return None
            except Exception as e:
                # Re-raise to be caught by caller
                raise
        
        try:
            return await asyncio.to_thread(_execute)
        except Exception as e:
            # Check if it's a connection error - return None gracefully
            error_str = str(e)
            if "Connection refused" in error_str or "ServiceUnavailable" in error_str or "Couldn't connect" in error_str:
                # Neo4j is not running - return None (node doesn't exist)
                logger.debug(f"Neo4j connection failed for node {node_id}: {e}")
                return None
            raise
    
    async def _get_nodes_batch_neo4j(
        self,
        node_ids: List[str],
        node_type: Optional[NodeType] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get multiple nodes from Neo4j in batch (IMPROVED: Priority 1)
        
        Matches architecture: MATCH (e:Email) WHERE e.id IN $node_ids
        """
        if not node_ids:
            return {}
        
        def _execute():
            with self.driver.session() as session:
                # Use explicit label if provided (Priority 2 improvement)
                if node_type:
                    query = f"""
                    MATCH (n:{node_type.value})
                    WHERE n.id IN $node_ids
                    RETURN n.id as id, n
                    """
                else:
                    query = """
                    MATCH (n)
                    WHERE n.id IN $node_ids
                    RETURN n.id as id, n
                    """
                result = session.run(query, node_ids=node_ids)
                nodes_dict = {}
                for record in result:
                    node_id = record["id"]
                    node_data = record["n"]
                    if isinstance(node_data, dict):
                        # Extract properties correctly
                        if 'properties' in node_data:
                            nodes_dict[node_id] = node_data['properties']
                        else:
                            nodes_dict[node_id] = dict(node_data)
                    else:
                        # Handle node object
                        nodes_dict[node_id] = dict(node_data) if hasattr(node_data, '__dict__') else {}
                return nodes_dict
        
        return await asyncio.to_thread(_execute)
    
    async def _query_neo4j(
        self,
        query: str,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Execute Cypher query on Neo4j"""
        def _execute():
            with self.driver.session() as session:
                result = session.run(query, **params)
                return [dict(record) for record in result]
        
        return await asyncio.to_thread(_execute)
    
    async def _traverse_neo4j(
        self,
        start_node: str,
        rel_types: List[RelationType],
        depth: int,
        direction: str
    ) -> List[Dict[str, Any]]:
        """Traverse Neo4j graph"""
        rel_pattern = "|".join([rt.value for rt in rel_types])
        
        if direction == "outgoing":
            rel_direction = f"-[:{rel_pattern}]->"
        elif direction == "incoming":
            rel_direction = f"<-[:{rel_pattern}]-"
        else:  # both
            rel_direction = f"-[:{rel_pattern}]-"
        
        def _execute():
            with self.driver.session() as session:
                query = f"""
                MATCH path = (start {{id: $start_node}}){rel_direction}*(..{depth})(end)
                RETURN DISTINCT end
                """
                result = session.run(query, start_node=start_node)
                return [dict(record["end"]) for record in result]
        
        return await asyncio.to_thread(_execute)
    
    async def _find_path_neo4j(
        self,
        from_node: str,
        to_node: str,
        max_depth: int
    ) -> Optional[List[str]]:
        """Find shortest path in Neo4j"""
        def _execute():
            with self.driver.session() as session:
                query = f"""
                MATCH path = shortestPath((start {{id: $from_node}})-[*..{max_depth}]-(end {{id: $to_node}}))
                RETURN [node in nodes(path) | node.id] as path
                """
                result = session.run(query, from_node=from_node, to_node=to_node)
                record = result.single()
                if record:
                    return record["path"]
                return None
        
        return await asyncio.to_thread(_execute)
    
    async def _get_neighbors_neo4j(
        self,
        node_id: str,
        rel_type: Optional[RelationType] = None,
        direction: str = "both"
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Get neighbors from Neo4j (IMPROVED: Priority 2 - uses explicit label when possible)
        """
        # Get node type first (async call outside thread)
        node = await self._get_node_neo4j(node_id)
        node_type_str = ""
        if node and isinstance(node, dict):
            node_type = node.get('node_type')
            if node_type:
                node_type_str = f":{node_type}"
        
        # Build query parameters
                if rel_type:
                    rel_pattern = rel_type.value
                else:
                    rel_pattern = "*"
                
                if direction == "outgoing":
                    rel_direction = f"-[:{rel_pattern}]->"
                elif direction == "incoming":
                    rel_direction = f"<-[:{rel_pattern}]-"
                else:  # both
                    rel_direction = f"-[:{rel_pattern}]-"
                
        def _execute():
            with self.driver.session() as session:
                query = f"""
                MATCH (start{node_type_str} {{id: $node_id}}){rel_direction}(neighbor)
                RETURN neighbor.id as neighbor_id, neighbor, type(r) as rel_type, r as rel_props
                """
                result = session.run(query, node_id=node_id)
                neighbors = []
                for record in result:
                    neighbor_id = record["neighbor_id"]
                    neighbor_data = dict(record["neighbor"])
                    rel_props = dict(record["rel_props"]) if record["rel_props"] else {}
                    neighbors.append((neighbor_id, rel_props))
                return neighbors
        
        return await asyncio.to_thread(_execute)
    
    async def _get_neighbors_batch_neo4j(
        self,
        node_ids: List[str],
        rel_types: Optional[List[RelationType]] = None,
        direction: str = "both",
        target_node_types: Optional[List[NodeType]] = None
    ) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
        """
        Get neighbors for multiple nodes in batch from Neo4j (IMPROVED: Priority 1 & 3)
        
        Matches architecture pattern:
        MATCH (e:Email) WHERE e.id IN $node_ids
        MATCH (e)-[:CONTAINS]->(a:ActionItem)
        RETURN e.id, a
        """
        if not node_ids:
            return {}
        
        def _execute():
            with self.driver.session() as session:
                # Build relationship pattern
                if rel_types and len(rel_types) > 0:
                    rel_pattern = "|".join([rt.value for rt in rel_types])
                else:
                    rel_pattern = "*"
                
                if direction == "outgoing":
                    rel_direction = f"-[:{rel_pattern}]->"
                elif direction == "incoming":
                    rel_direction = f"<-[:{rel_pattern}]-"
                else:  # both
                    rel_direction = f"-[:{rel_pattern}]-"
                
                # Build target node type filter (Priority 3 improvement)
                target_type_filter = ""
                if target_node_types and len(target_node_types) > 0:
                    target_labels = ":".join([nt.value for nt in target_node_types])
                    target_type_filter = f"(neighbor:{target_labels})"
                else:
                    target_type_filter = "(neighbor)"
                
                # Batch query (Priority 1 improvement)
                query = f"""
                MATCH (start){rel_direction}{target_type_filter}
                WHERE start.id IN $node_ids
                RETURN start.id as start_id, neighbor.id as neighbor_id, neighbor, 
                       type(r) as rel_type, r as rel_props
                """
                result = session.run(query, node_ids=node_ids)
                
                # Group neighbors by start node
                neighbors_map: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {node_id: [] for node_id in node_ids}
                for record in result:
                    start_id = record["start_id"]
                    neighbor_id = record["neighbor_id"]
                    neighbor_data = dict(record["neighbor"])
                    rel_props = dict(record["rel_props"]) if record["rel_props"] else {}
                    
                    if start_id in neighbors_map:
                        neighbors_map[start_id].append((neighbor_id, rel_props))
                
                return neighbors_map
        
        return await asyncio.to_thread(_execute)
    
    async def _get_stats_neo4j(self) -> GraphStats:
        """Get statistics from Neo4j"""
        def _execute():
            with self.driver.session() as session:
                # Count nodes
                node_result = session.run("MATCH (n) RETURN count(n) as count").single()
                node_count = node_result["count"] if node_result else 0
                
                # Count relationships
                rel_result = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()
                rel_count = rel_result["count"] if rel_result else 0
                
                return GraphStats(
                    total_nodes=node_count,
                    total_relationships=rel_count,
                    nodes_by_type={},
                    relationships_by_type={},
                    avg_degree=0.0,
                    max_depth=0
                )
        
        return await asyncio.to_thread(_execute)
    
    async def _delete_node_neo4j(self, node_id: str) -> bool:
        """Delete node from Neo4j"""
        def _execute():
            with self.driver.session() as session:
                query = "MATCH (n {id: $node_id}) DETACH DELETE n"
                session.run(query, node_id=node_id)
                return True
        
        return await asyncio.to_thread(_execute)
    
    async def _clear_neo4j(self) -> bool:
        """Clear Neo4j database"""
        def _execute():
            with self.driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
                return True
        
        return await asyncio.to_thread(_execute)
    
    def __del__(self):
        """Cleanup on deletion"""
        if self.backend_type == GraphBackend.NEO4J and hasattr(self, 'driver'):
            self.driver.close()
