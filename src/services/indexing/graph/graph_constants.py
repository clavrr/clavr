"""
Knowledge Graph Constants

Centralized configuration for graph operations. All configuration in one place.
"""

from src.utils.urls import URLs

# Traversal Settings
DEFAULT_MAX_DEPTH = 5
DEFAULT_TRAVERSAL_DEPTH = 2
MAX_TRAVERSAL_DEPTH = 10

# Query Limits
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_RESULTS = 1000

# Backend Settings
PRIMARY_BACKEND = "arangodb"
FALLBACK_BACKEND = "networkx"

# Validation Modes
VALIDATION_MODE_WARN = "warn"  # Log warnings but continue
VALIDATION_MODE_STRICT = "strict"  # Raise errors on validation failure

# Statistics
DEFAULT_AVG_DEGREE_PRECISION = 2  # Decimal places for average degree

# Error Messages
ERROR_NODE_NOT_FOUND = "Node '{node_id}' does not exist in the graph"
ERROR_RELATIONSHIP_SOURCE_MISSING = "Cannot create relationship: source node '{from_node}' does not exist"
ERROR_RELATIONSHIP_TARGET_MISSING = "Cannot create relationship: target node '{to_node}' does not exist"
ERROR_INVALID_NODE_PROPERTIES = "Node validation failed for type '{node_type}'. Missing required properties: {missing}"
ERROR_BACKEND_NOT_AVAILABLE = "Backend '{backend}' is not available. Install required dependencies."

# ArangoDB Connection
ARANGO_DEFAULT_URI = URLs.ARANGODB
ARANGO_DEFAULT_USER = URLs.ARANGODB_USER
ARANGO_DEFAULT_PASSWORD = URLs.ARANGODB_PASSWORD
ARANGO_DEFAULT_DB = URLs.ARANGODB_DB
ARANGO_GRAPH_NAME = "clavr_graph"



# NetworkX Settings
NETWORKX_ENABLE_QUERY_PARSER = True
NETWORKX_GRAPH_TYPE = "MultiDiGraph"  # Directed graph with multiple edges
