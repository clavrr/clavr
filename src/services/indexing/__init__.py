"""
Indexing Package - Production Email Indexing with Knowledge Graph

Main Components:
- IntelligentEmailIndexer: Production email indexer with graph + vector support
- HybridIndexCoordinator: Coordinates graph and vector stores
- Parsers: EmailParser, ReceiptParser, AttachmentParser
- Graph: KnowledgeGraphManager, schema definitions
"""

# Phase 1: Parsers
from .parsers import (
    BaseParser,
    ParsedNode,
    Relationship,
    Entity,
    ExtractedIntents,
    EmailParser,
    ReceiptParser,
    AttachmentParser
)

# Phase 2: Knowledge Graph
from .graph import (
    KnowledgeGraphManager,
    NodeType,
    RelationType,
    GraphSchema,
    GraphRAGAnalyzer,
    AnalysisType
)

# Phase 2: Hybrid Index
from .hybrid_index import HybridIndexCoordinator

# Phase 2.5: RAG-Graph Integration Bridge
from .rag_graph_bridge import (
    RAGVectorAdapter,
    GraphRAGIntegrationService
)

# Phase 3: Main Indexer + Helper Functions
from .indexer import (
    IntelligentEmailIndexer,
    get_background_indexer,
    start_background_indexing,
    start_user_background_indexing,
    stop_background_indexing,
    get_user_background_indexer
)

__all__ = [
    # Parsers
    'BaseParser',
    'ParsedNode',
    'Relationship',
    'Entity',
    'ExtractedIntents',
    'EmailParser',
    'ReceiptParser',
    'AttachmentParser',
    
    # Graph
    'KnowledgeGraphManager',
    'NodeType',
    'RelationType',
    'GraphSchema',
    'GraphRAGAnalyzer',
    'AnalysisType',
    
    # Hybrid Index
    'HybridIndexCoordinator',
    
    # RAG-Graph Integration
    'RAGVectorAdapter',
    'GraphRAGIntegrationService',
    
    # Main Indexer
    'IntelligentEmailIndexer',
    'get_background_indexer',
    'start_background_indexing',
    'start_user_background_indexing',
    'stop_background_indexing',
    'get_user_background_indexer',
]
