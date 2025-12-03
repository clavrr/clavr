"""
RAG (Retrieval-Augmented Generation) Module

Clean, maintainable RAG architecture following industry best practices.

Architecture:
- Core: RAGEngine, EmbeddingProvider, VectorStore
- Chunking: RecursiveTextChunker, EmailChunker
- Query: QueryEnhancer, ResultReranker, HybridSearchEngine
- Processing: DocumentProcessor, UnifiedParserRAGBridge
- Utils: Monitoring, Performance, Utilities
"""

# Core components
from .core import (
    RAGEngine,
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    create_embedding_provider,
    VectorStore,
    PostgresVectorStore,
    PineconeVectorStore,
    create_vector_store
)

# Chunking strategies
from .chunking import (
    RecursiveTextChunker,
    Chunk,
    ChunkMetadata,
    EmailChunker
)

# Query processing
from .query import (
    QueryEnhancer,
    ResultReranker,
    HybridSearchEngine,
    AdaptiveRerankingWeights,
    create_adaptive_reranker,
    apply_diversity,
    maximal_marginal_relevance,
    remove_near_duplicates
)

# Monitoring
from .utils import (
    RAGMonitor,
    get_monitor,
    reset_monitor
)

# DocumentProcessor and UnifiedParserRAGBridge - lazy imports to avoid circular dependency
# These are used by services/indexing/indexer.py but importing them here creates
# a circular dependency (rag -> services.indexing.parsers -> services.indexing.indexer -> rag)
# Import directly: from src.ai.rag.processing.document_processor import DocumentProcessor
# Import directly: from src.ai.rag.processing.parser_integration import UnifiedParserRAGBridge

# Utilities are internal - not exported to avoid namespace pollution
# Import directly: from src.ai.rag.utils.utils import extract_keywords
# Performance modules are internal - not exported

__all__ = [
    # Core interfaces
    "EmbeddingProvider",
    "VectorStore",
    "RAGEngine",
    
    # Embedding providers
    "GeminiEmbeddingProvider", 
    "SentenceTransformerEmbeddingProvider",
    "create_embedding_provider",
    
    # Vector stores
    "PostgresVectorStore",
    "PineconeVectorStore",
    "create_vector_store",
    
    # Chunking
    "RecursiveTextChunker",
    "Chunk",
    "ChunkMetadata",
    "EmailChunker",
    
    # Query enhancement
    "QueryEnhancer",
    "ResultReranker",
    "HybridSearchEngine",
    
    # Diversity and reranking
    "apply_diversity",
    "maximal_marginal_relevance",
    "remove_near_duplicates",
    "AdaptiveRerankingWeights",
    "create_adaptive_reranker",
    
    # Monitoring
    "RAGMonitor",
    "get_monitor",
    "reset_monitor",
    
    # Document processing and integration (lazy imports - import directly to avoid circular dependency)
    # "DocumentProcessor",  # Import: from src.ai.rag.document_processor import DocumentProcessor
    # "UnifiedParserRAGBridge",  # Import: from src.ai.rag.parser_integration import UnifiedParserRAGBridge
]

