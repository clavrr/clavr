"""
Indexing Package - Production Email Indexing with Knowledge Graph

Main Components:
- UnifiedIndexerService: Central orchestration for all indexers
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

# Knowledge Graph
from .graph import (
    KnowledgeGraphManager,
    NodeType,
    RelationType,
    GraphSchema,
    GraphRAGAnalyzer,
    AnalysisType
)

# Hybrid Index
from .hybrid_index import HybridIndexCoordinator

# RAG-Graph Integration Bridge
from .rag_graph_bridge import (
    RAGVectorAdapter,
    GraphRAGIntegrationService
)

# Unified Indexer (replaces legacy indexer)
from .unified_indexer import (
    UnifiedIndexerService,
    get_unified_indexer,
    start_unified_indexing,
    stop_unified_indexing
)

# Phase 4: Cross-App Intelligence
from .cross_app_correlator import (
    CrossAppCorrelator,
    get_cross_app_correlator,
    init_cross_app_correlator
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
    
    # Unified Indexer
    'UnifiedIndexerService',
    'get_unified_indexer',
    'start_unified_indexing',
    'stop_unified_indexing',
    
    # Cross-App Intelligence
    'CrossAppCorrelator',
    'get_cross_app_correlator',
    'init_cross_app_correlator',
]
