"""
Knowledge Graph Constants

Centralized configuration for graph operations. All configuration in one place.
"""

# Traversal Settings
DEFAULT_MAX_DEPTH = 5
DEFAULT_TRAVERSAL_DEPTH = 2
MAX_TRAVERSAL_DEPTH = 10

# Query Limits
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_RESULTS = 1000

# Backend Settings
PRIMARY_BACKEND = "neo4j"
FALLBACK_BACKEND = "networkx"

# Validation Modes
VALIDATION_MODE_WARN = "warn"  # Log warnings but continue
VALIDATION_MODE_STRICT = "strict"  # Raise errors on validation failure

# Statistics
DEFAULT_AVG_DEGREE_PRECISION = 2  # Decimal places for average degree

# Error Messages
ERROR_NODE_NOT_FOUND = "Node '{node_id}' does not not exist in the graph"
ERROR_RELATIONSHIP_SOURCE_MISSING = "Cannot create relationship: source node '{from_node}' does not exist"
ERROR_RELATIONSHIP_TARGET_MISSING = "Cannot create relationship: target node '{to_node}' does not exist"
ERROR_INVALID_NODE_PROPERTIES = "Node validation failed for type '{node_type}'. Missing required properties: {missing}"
ERROR_BACKEND_NOT_AVAILABLE = "Backend '{backend}' is not available. Install required dependencies."

# Neo4j Connection
NEO4J_DEFAULT_URI = "bolt://localhost:7687"
NEO4J_DEFAULT_USER = "neo4j"
NEO4J_DEFAULT_PASSWORD = "password"
NEO4J_CONNECTION_TIMEOUT = 30  # seconds
NEO4J_MAX_CONNECTION_POOL_SIZE = 50

# NetworkX Settings
NETWORKX_ENABLE_QUERY_PARSER = True
NETWORKX_GRAPH_TYPE = "MultiDiGraph"  # Directed graph with multiple edges
