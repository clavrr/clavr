"""
Notion Semantic Pattern Matcher - Semantic pattern matching for Notion queries

Uses embeddings for semantic similarity matching when available.
"""
from typing import Dict, Any, Optional, List
import numpy as np

from ....utils.logger import setup_logger
from .constants import NotionParserConfig

logger = setup_logger(__name__)

# Try to import sentence transformers for semantic matching
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers not available - semantic matching will be disabled")

class NotionSemanticPatternMatcher:
    """Semantic pattern matcher for Notion queries"""
    
    def __init__(self, config=None):
        self.config = config
        self.model = None
        self.embedding_provider = None
        self.use_gemini = False
        
        # Try Gemini embeddings first (more accurate, 768D, cached)
        if config and config.ai and config.ai.api_key:
            try:
                from ....ai.rag.core.embedding_provider import create_embedding_provider
                from ....utils.config import RAGConfig
                
                rag_config = RAGConfig(
                    embedding_provider="gemini",
                    embedding_model="models/embedding-001"  # gemini-embedding-001 (Google API format)
                )
                self.embedding_provider = create_embedding_provider(config, rag_config)
                
                # Check if it's actually Gemini (not fallback)
                from ....ai.rag.core.embedding_provider import GeminiEmbeddingProvider
                if isinstance(self.embedding_provider, GeminiEmbeddingProvider):
                    self.use_gemini = True
                    logger.info("[NOTION] Using gemini-embedding-001 for semantic matching (more accurate, 768D, cached)")
                else:
                    logger.info("[NOTION] Gemini embeddings unavailable, falling back to sentence-transformers")
            except Exception as e:
                logger.debug(f"[NOTION] Gemini embeddings not available: {e}, falling back to sentence-transformers")
        
        # Fallback to sentence-transformers (faster, local, 384D)
        if not self.use_gemini and SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("[NOTION] Using sentence-transformers (all-MiniLM-L6-v2) for semantic matching (384D)")
            except Exception as e:
                logger.warning(f"[NOTION] Failed to load sentence transformer: {e}")
    
    def calculate_similarity(self, query: str, pattern: str) -> float:
        """
        Calculate semantic similarity between query and pattern
        
        Args:
            query: User query
            pattern: Pattern to match against
            
        Returns:
            Similarity score (0.0-1.0)
        """
        # Use Gemini embedding provider if available (better quality)
        if self.use_gemini and self.embedding_provider:
            try:
                query_embedding = np.array(self.embedding_provider.encode(query))
                pattern_embedding = np.array(self.embedding_provider.encode(pattern))
                
                # Calculate cosine similarity
                similarity = np.dot(query_embedding, pattern_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(pattern_embedding)
                )
                
                # Apply threshold multiplier for Gemini (tends to be more confident)
                similarity *= NotionParserConfig.GEMINI_THRESHOLD_MULTIPLIER
                
                return float(similarity)
            except Exception as e:
                logger.debug(f"[NOTION] Gemini similarity calculation failed: {e}")
        
        # Fallback to sentence transformer
        if self.model:
            try:
                query_embedding = self.model.encode(query)
                pattern_embedding = self.model.encode(pattern)
                
                # Calculate cosine similarity
                similarity = np.dot(query_embedding, pattern_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(pattern_embedding)
                )
                
                return float(similarity)
            except Exception as e:
                logger.debug(f"[NOTION] Sentence transformer similarity calculation failed: {e}")
        
        # Fallback: simple keyword matching
        query_words = set(query.lower().split())
        pattern_words = set(pattern.lower().split())
        
        if not query_words or not pattern_words:
            return 0.0
        
        intersection = query_words & pattern_words
        union = query_words | pattern_words
        
        return len(intersection) / len(union) if union else 0.0
    
    def find_best_match(self, query: str, patterns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Find best matching pattern for query
        
        Args:
            query: User query
            patterns: List of pattern dictionaries with 'pattern' and 'action' keys
            
        Returns:
            Best matching pattern dictionary or None
        """
        best_match = None
        best_score = 0.0
        
        for pattern_info in patterns:
            pattern = pattern_info.get('pattern', '')
            score = self.calculate_similarity(query, pattern)
            
            if score > best_score and score >= NotionParserConfig.DEFAULT_SEMANTIC_THRESHOLD:
                best_score = score
                best_match = pattern_info
                best_match['similarity_score'] = score
        
        return best_match

