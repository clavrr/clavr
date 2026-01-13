"""
Graph-RAG Integration Constants

Centralized configuration for graph and RAG integration settings.
No hardcoded values - all configuration in one place.
"""

# Graph Traversal Settings
DEFAULT_GRAPH_DEPTH = 2
MAX_GRAPH_DEPTH = 5
DEFAULT_NEIGHBOR_LIMIT = 10
MAX_NEIGHBORS_FOR_CONTEXT = 20

# Scoring Weights
VECTOR_SCORE_WEIGHT = 0.6
GRAPH_SCORE_WEIGHT = 0.4
GRAPH_SCORE_NORMALIZATION_FACTOR = 10.0  # Divide neighbor count by this

# Search Limits
DEFAULT_MAX_RESULTS = 10
DEFAULT_VECTOR_LIMIT = 10
MAX_RELATED_CONTENT = 20

# Node Type Inference
# When creating relationships to unknown nodes, try to infer type from context
# If inference fails, relationships will fail rather than create invalid placeholders
ENABLE_NODE_TYPE_INFERENCE = True

# Cache Settings
ENABLE_CONSISTENCY_CHECKING = True
CONSISTENCY_CHECK_INTERVAL_SECONDS = 3600  # 1 hour

# Vector Store Requirements
# System only supports RAGEngine (which uses Qdrant or PostgreSQL)
SUPPORTED_VECTOR_BACKEND = "RAGEngine" 
PRIMARY_VECTOR_STORE = "qdrant"
FALLBACK_VECTOR_STORE = "postgres"
