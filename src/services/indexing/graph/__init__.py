"""
Knowledge Graph Package

Manages the knowledge graph for structured email and document data.
Supports both ArangoDB (production) and in-memory NetworkX (fallback) backends.

New in Phase 2.5: GraphRAG Analyzer for reasoning and advice generation.
"""

from .manager import KnowledgeGraphManager
from .schema import NodeType, RelationType, GraphSchema
from .graphrag_analyzer import GraphRAGAnalyzer, AnalysisType

__all__ = [
    'KnowledgeGraphManager',
    'NodeType',
    'RelationType',
    'GraphSchema',
    'GraphRAGAnalyzer',
    'AnalysisType',
]
