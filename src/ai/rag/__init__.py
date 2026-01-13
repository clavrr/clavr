"""
RAG (Retrieval-Augmented Generation) Module

Clean, maintainable RAG architecture following industry best practices.

Architecture:
- Core: RAGEngine, EmbeddingProvider, VectorStore
- Chunking: RecursiveTextChunker, EmailChunker, ContextualChunker
- Query: QueryEnhancer, ResultReranker, HybridSearchEngine, HyDE, CrossEncoder
- Pipeline: UnifiedRAGPipeline (recommended entry point)
- Feedback: FeedbackCollector, FeedbackReranker
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
    QdrantVectorStore,
    create_vector_store
)

# Chunking strategies
from .chunking import (
    RecursiveTextChunker,
    Chunk,
    ChunkMetadata,
    EmailChunker,
    ContextualChunker,
    create_contextual_chunker
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
    remove_near_duplicates,
    # Advanced query processing
    QueryDecomposer,
    CrossEncoderReranker,
    HyDEGenerator,
    RelevanceGrader
)

# Unified Pipeline (recommended entry point)
from .unified_pipeline import (
    UnifiedRAGPipeline,
    PipelineConfig,
    PipelineResult,
    create_unified_pipeline
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
    "QdrantVectorStore",
    "create_vector_store",
    
    # Chunking
    "RecursiveTextChunker",
    "Chunk",
    "ChunkMetadata",
    "EmailChunker",
    "ContextualChunker",
    "create_contextual_chunker",
    
    # Query enhancement
    "QueryEnhancer",
    "ResultReranker",
    "HybridSearchEngine",
    "QueryDecomposer",
    "CrossEncoderReranker",
    "HyDEGenerator",
    "RelevanceGrader",
    
    # Diversity and reranking
    "apply_diversity",
    "maximal_marginal_relevance",
    "remove_near_duplicates",
    "AdaptiveRerankingWeights",
    "create_adaptive_reranker",
    
    # Unified Pipeline (recommended)
    "UnifiedRAGPipeline",
    "PipelineConfig",
    "PipelineResult",
    "create_unified_pipeline",
    
    # Monitoring
    "RAGMonitor",
    "get_monitor",
    "reset_monitor",
    
    # Document processing and integration (lazy imports - import directly to avoid circular dependency)
    # "DocumentProcessor",  # Import: from src.ai.rag.document_processor import DocumentProcessor
    # "UnifiedParserRAGBridge",  # Import: from src.ai.rag.parser_integration import UnifiedParserRAGBridge
]


