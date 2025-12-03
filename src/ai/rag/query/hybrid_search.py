"""
Hybrid Search Module - Semantic + Keyword Search with RRF Fusion

Supports:
1. Pinecone native hybrid search (sparse-dense vectors) - PRIMARY
2. BM25 + semantic fusion for PostgreSQL backend - FALLBACK

ChromaDB is not supported.
"""
from typing import List, Dict, Any, Optional
import re

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class HybridSearchEngine:
    """
    Hybrid search combining semantic (dense) and keyword (sparse) search.
    
    For Pinecone: Uses native sparse-dense vector support
    For other backends: Uses BM25 + RRF fusion
    """
    
    def __init__(self, backend_type: str = "pinecone"):
        """
        Initialize hybrid search engine.
        
        Args:
            backend_type: "pinecone" or "postgres" 
        """
        self.backend_type = backend_type.lower()
        
        if self.backend_type not in ["pinecone", "postgres"]:
            raise ValueError(
                f"Unsupported backend: {backend_type}. "
                "Only 'pinecone' and 'postgres' are supported."
            )
        
        self.bm25_index = None
        self.indexed_docs = []
        self.doc_id_map = {}
        
        logger.info(f"Hybrid search initialized for backend: {self.backend_type}")
    
    def supports_native_hybrid(self) -> bool:
        """Check if backend supports native hybrid search."""
        return self.backend_type == "pinecone"
    
    def build_bm25_index(self, documents: List[Dict[str, Any]]):
        """
        Build BM25 index for non-Pinecone backends.
        
        Args:
            documents: List of dicts with 'id' and 'content' keys
        """
        if self.supports_native_hybrid():
            logger.debug("Pinecone uses native hybrid search, skipping BM25 index")
            return
        
        if not documents:
            logger.warning("No documents provided for BM25 indexing")
            return
        
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.error("rank-bm25 not installed. Run: pip install rank-bm25")
            return
        
        # Tokenize documents
        tokenized_docs = []
        self.doc_id_map = {}
        
        for idx, doc in enumerate(documents):
            content = doc.get('content', '')
            tokens = self._tokenize(content)
            tokenized_docs.append(tokens)
            
            # Map index to doc_id for later lookup
            doc_id = doc.get('id', f"doc_{idx}")
            self.doc_id_map[idx] = doc_id
            self.indexed_docs.append(doc)
        
        # Build BM25 index
        self.bm25_index = BM25Okapi(tokenized_docs)
        logger.info(f"Built BM25 index with {len(documents)} documents")
    
    def search_bm25(self, query: str, k: int = 10) -> List[Dict[str, Any]]:
        """
        Keyword search using BM25 (for non-Pinecone backends).
        
        Args:
            query: Search query
            k: Number of results
            
        Returns:
            Top-k results by BM25 score
        """
        if self.supports_native_hybrid():
            logger.debug("Pinecone uses native hybrid search")
            return []
        
        if not self.bm25_index:
            logger.warning("BM25 index not built, returning empty results")
            return []
        
        # Tokenize query
        query_tokens = self._tokenize(query)
        
        # Get BM25 scores
        scores = self.bm25_index.get_scores(query_tokens)
        
        # Get top-k indices
        top_k_indices = sorted(
            range(len(scores)), 
            key=lambda i: scores[i], 
            reverse=True
        )[:k]
        
        # Format results
        results = []
        for idx in top_k_indices:
            if scores[idx] > 0:  # Only include non-zero scores
                doc = self.indexed_docs[idx]
                results.append({
                    'id': self.doc_id_map[idx],
                    'content': doc.get('content', ''),
                    'metadata': doc.get('metadata', {}),
                    'bm25_score': float(scores[idx]),
                    'source': 'bm25'
                })
        
        return results
    
    def fusion_search(
        self,
        semantic_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        semantic_weight: float = 0.7,
        bm25_weight: float = 0.3,
        k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fuse semantic and BM25 results using Reciprocal Rank Fusion (RRF).
        
        RRF Formula: score = sum(weight / (rank + k))
        where k=60 is the standard RRF constant
        
        Args:
            semantic_results: Results from vector search
            bm25_results: Results from BM25 search
            semantic_weight: Weight for semantic results (0-1)
            bm25_weight: Weight for BM25 results (0-1)
            k: Number of results to return
            
        Returns:
            Fused and reranked results
        """
        RRF_K = 60  # Standard RRF constant
        
        # Calculate RRF scores
        rrf_scores = {}
        result_map = {}  # Store full result objects
        
        # Process semantic results
        for rank, result in enumerate(semantic_results, start=1):
            doc_id = result.get('id')
            if doc_id:
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + semantic_weight / (rank + RRF_K)
                if doc_id not in result_map:
                    result_map[doc_id] = result
        
        # Process BM25 results
        for rank, result in enumerate(bm25_results, start=1):
            doc_id = result.get('id')
            if doc_id:
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + bm25_weight / (rank + RRF_K)
                if doc_id not in result_map:
                    result_map[doc_id] = result
        
        # Sort by RRF score
        sorted_doc_ids = sorted(
            rrf_scores.keys(),
            key=lambda doc_id: rrf_scores[doc_id],
            reverse=True
        )[:k]
        
        # Build final results
        fused_results = []
        for doc_id in sorted_doc_ids:
            result = result_map[doc_id].copy()
            result['rrf_score'] = rrf_scores[doc_id]
            result['fusion_method'] = 'rrf'
            fused_results.append(result)
        
        logger.debug(
            f"Fused {len(semantic_results)} semantic + {len(bm25_results)} BM25 "
            f"results → {len(fused_results)} final results"
        )
        
        return fused_results
    
    def extract_keywords_for_sparse(self, text: str, max_keywords: int = 10) -> Dict[str, float]:
        """
        Extract keywords with TF-IDF-like scores for Pinecone sparse vectors.
        
        Args:
            text: Text to extract keywords from
            max_keywords: Maximum number of keywords
            
        Returns:
            Dict mapping keywords to scores
        """
        tokens = self._tokenize(text)
        
        # Calculate term frequencies
        tf = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        
        # Simple scoring based on frequency
        max_freq = max(tf.values()) if tf else 1
        keyword_scores = {
            token: freq / max_freq 
            for token, freq in tf.items()
        }
        
        # Return top keywords
        sorted_keywords = sorted(
            keyword_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:max_keywords]
        
        return dict(sorted_keywords)
    
    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text for BM25 indexing or keyword extraction.
        
        Simple tokenization:
        - Lowercase
        - Split on non-alphanumeric
        - Remove stopwords
        """
        # Lowercase and split
        tokens = re.findall(r'\b\w+\b', text.lower())
        
        # Remove stopwords (basic list)
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
            'could', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those'
        }
        tokens = [t for t in tokens if t not in stopwords and len(t) > 2]
        
        return tokens
