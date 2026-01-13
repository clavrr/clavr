"""
Semantic Cache - Vector-based caching for RAG queries.

Stores results for conceptually similar queries using embedding similarity.
This allows Clavr to return results in <50ms for repetitive or slightly 
rephrased questions without re-running the full RAG pipeline.
"""
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from src.utils.logger import setup_logger
from .cache import TTLCache
from ..utils.utils import calculate_semantic_score

logger = setup_logger(__name__)


class SemanticCache:
    """
    Vector-based cache for RAG search results.
    
    Uses query embeddings to find conceptually identical previous queries.
    """
    
    def __init__(
        self, 
        embedding_provider: Any,
        threshold: float = 0.96,
        max_size: int = 1000,
        ttl_seconds: int = 3600
    ):
        """
        Initialize semantic cache.
        
        Args:
            embedding_provider: Provider to generate query embeddings
            threshold: Cosine similarity threshold for a "hit"
            max_size: Maximum number of entries in cache
            ttl_seconds: Time-to-live for cache entries
        """
        self.embedding_provider = embedding_provider
        self.threshold = threshold
        self.ttl_seconds = ttl_seconds
        
        # Internal storage: List of (query_text, embedding, results, timestamp)
        # For a high-performance production system, this could be a small 
        # in-memory vector index (like Faiss or HNSWLib). 
        # For now, we use a simple linear search for precision and simplicity.
        self.cache: List[Dict[str, Any]] = []
        self.max_size = max_size
        
        logger.info(f"SemanticCache initialized (threshold={threshold}, max_size={max_size})")

    def get(self, query: str, query_embedding: Optional[List[float]] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Try to retrieve results from semantic cache.
        
        Args:
            query: The raw query string
            query_embedding: Pre-computed embedding (optional)
            
        Returns:
            Cached results or None if miss
        """
        if not self.cache:
            return None
            
        # 1. Clean up expired entries
        self._cleanup()
        
        # 2. Get embedding if not provided
        if query_embedding is None:
            query_embedding = self.embedding_provider.encode_query(query)
            
        # 3. Find best match
        best_match = None
        best_score = -1.0
        
        # Vectorized similarity would be faster, but linear is fine for ~1000 entries
        for entry in self.cache:
            score = self._cosine_similarity(query_embedding, entry['embedding'])
            if score > best_score:
                best_score = score
                best_match = entry
        
        # 4. Check against threshold
        if best_match and best_score >= self.threshold:
            logger.debug(f"Semantic Cache HIT: '{query}' matches '{best_match['query']}' (score={best_score:.4f})")
            # Update last accessed for LRU-like behavior later if needed
            best_match['hits'] += 1
            return best_match['results']
            
        return None

    def set(self, query: str, results: List[Dict[str, Any]], query_embedding: Optional[List[float]] = None):
        """Store results in semantic cache."""
        # 1. Get embedding if not provided
        if query_embedding is None:
            query_embedding = self.embedding_provider.encode_query(query)
            
        # 2. Check for overflow
        if len(self.cache) >= self.max_size:
            # Simple eviction: oldest first
            self.cache.pop(0)
            
        # 3. Store
        self.cache.append({
            'query': query,
            'embedding': query_embedding,
            'results': results,
            'timestamp': time.time(),
            'hits': 0
        })
        
        logger.debug(f"Cached semantic results for: '{query}'")

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import math
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
            
        return dot_product / (magnitude1 * magnitude2)

    def _cleanup(self):
        """Remove expired entries from cache."""
        now = time.time()
        self.cache = [
            entry for entry in self.cache 
            if now - entry['timestamp'] < self.ttl_seconds
        ]

    def clear(self):
        """Clear all cache entries."""
        self.cache = []
        logger.info("Semantic cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'threshold': self.threshold,
            'total_hits': sum(e['hits'] for e in self.cache)
        }
