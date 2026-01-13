"""
RAG Query Processing

Query enhancement, reranking, and search strategies:
- QueryEnhancer: Query expansion and refinement
- ResultReranker: Multi-factor result reranking
- HybridSearchEngine: Combined semantic + keyword search
- Diversity functions: MMR and deduplication
- RelevanceGrader: Self-RAG chunk relevance analysis
- QueryDecomposer: Complex query decomposition into sub-queries
- CrossEncoderReranker: High-precision semantic reranking
- HyDEGenerator: Hypothetical Document Embeddings for vague queries
"""

from .query_enhancer import QueryEnhancer
from .result_reranker import ResultReranker
from .adaptive_reranking import AdaptiveRerankingWeights, create_adaptive_reranker
from .hybrid_search import HybridSearchEngine
from .diversity import apply_diversity, maximal_marginal_relevance, remove_near_duplicates
from .relevance_grader import RelevanceGrader, RelevanceLevel, RelevanceResult
from .query_decomposer import (
    QueryDecomposer, 
    DecomposedRAGExecutor, 
    SubQuery, 
    QueryComplexity,
    DecompositionResult
)
from .cross_encoder_reranker import CrossEncoderReranker, CrossEncoderConfig, LightweightCrossEncoder
from .hyde import HyDEGenerator, HyDEConfig, hyde_search

__all__ = [
    "QueryEnhancer",
    "ResultReranker",
    "AdaptiveRerankingWeights",
    "create_adaptive_reranker",
    "HybridSearchEngine",
    "apply_diversity",
    "maximal_marginal_relevance",
    "remove_near_duplicates",
    "RelevanceGrader",
    "RelevanceLevel",
    "RelevanceResult",
    "QueryDecomposer",
    "DecomposedRAGExecutor",
    "SubQuery",
    "QueryComplexity",
    "DecompositionResult",
    "CrossEncoderReranker",
    "CrossEncoderConfig",
    "LightweightCrossEncoder",
    "HyDEGenerator",
    "HyDEConfig",
    "hyde_search",
]




