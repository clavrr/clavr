"""
Calendar Semantic Pattern Matcher - Enhanced NLU for calendar queries

This module provides semantic pattern matching using embeddings:
- Gemini embeddings (preferred) - more accurate, 768D, cached
- Sentence-transformers (fallback) - fast, local, 384D

Handles paraphrases, synonyms, and variations better than exact string matching.
"""

from typing import Dict, Optional, List
import numpy as np

from ....utils.logger import setup_logger
from ..base_parser import safe_cosine_similarity

logger = setup_logger(__name__)

# Constants for semantic matching
DEFAULT_SEMANTIC_THRESHOLD = 0.7
GEMINI_THRESHOLD_MULTIPLIER = 0.95  # Slightly lower threshold for Gemini (more accurate embeddings)

# Try to import sentence transformers for semantic matching
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers not available - semantic matching will be disabled")


class CalendarSemanticPatternMatcher:
    """
    Semantic pattern matcher using embeddings (Gemini preferred, sentence-transformers fallback).
    """
    
    def __init__(self, config=None, embedding_provider=None):
        """
        Initialize semantic pattern matcher.
        
        Args:
            config: Optional Config object (for Gemini embeddings)
            embedding_provider: Optional EmbeddingProvider instance (reuse existing)
        """
        self.config = config
        self.embedding_provider = embedding_provider
        self.use_gemini = False
        self.model = None
        self.pattern_embeddings = {}
        
        # Try Gemini embeddings first
        if config and config.ai and config.ai.api_key:
            try:
                from ....ai.rag.core.embedding_provider import create_embedding_provider
                from ....utils.config import RAGConfig
                
                rag_config = RAGConfig(
                    embedding_provider="gemini",
                    embedding_model="models/embedding-001"
                )
                self.embedding_provider = create_embedding_provider(config, rag_config)
                
                from ....ai.rag.core.embedding_provider import GeminiEmbeddingProvider
                if isinstance(self.embedding_provider, GeminiEmbeddingProvider):
                    self.use_gemini = True
                    logger.info("[ENHANCED] Using gemini-embedding-001 for calendar semantic matching (768D, cached)")
                else:
                    logger.info("[ENHANCED] Gemini unavailable, falling back to sentence-transformers")
            except Exception as e:
                logger.debug(f"Gemini embeddings not available: {e}, falling back to sentence-transformers")
        
        # Fallback to sentence-transformers
        if not self.use_gemini:
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                logger.warning("SemanticPatternMatcher: No embedding provider available")
                return
            
            try:
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("[ENHANCED] Using sentence-transformers (all-MiniLM-L6-v2) for calendar semantic matching (384D)")
            except Exception as e:
                logger.warning(f"Failed to initialize sentence-transformers: {e}")
                return
        
        # Load pattern embeddings
        self.pattern_embeddings = self._load_pattern_embeddings()
        if self.pattern_embeddings:
            logger.info("[ENHANCED] CalendarSemanticPatternMatcher initialized successfully")
    
    def _get_calendar_patterns(self) -> Dict[str, List[str]]:
        """
        Get calendar patterns from centralized action classifiers.
        
        Returns:
            Dictionary mapping intent names to pattern lists
        """
        try:
            from .action_classifiers import CalendarActionPatterns
            
            patterns = CalendarActionPatterns()
            return {
                'list': patterns.LIST_PATTERNS,
                'create': patterns.CREATE_PATTERNS,
                'search': patterns.SEARCH_PATTERNS,
                'update': patterns.UPDATE_PATTERNS,
                'delete': patterns.DELETE_PATTERNS,
                'count': patterns.COUNT_PATTERNS,
            }
        except ImportError:
            # Fallback to basic patterns if action_classifiers not available
            logger.warning("CalendarActionPatterns not available, using fallback patterns")
            return {
                'list': [
                    "what do i have", "what's on", "show me", "my calendar",
                    "upcoming events", "what meetings", "what events"
                ],
                'create': [
                    "schedule meeting", "create event", "book meeting", "add to calendar",
                    "new event", "new meeting", "schedule a", "create a"
                ],
            }
    
    def _load_pattern_embeddings(self) -> Dict[str, np.ndarray]:
        """
        Pre-compute embeddings for all patterns.
        
        Uses centralized patterns from CalendarActionPatterns for consistency.
        
        Returns:
            Dictionary mapping intent names to numpy arrays of embeddings
        """
        patterns = self._get_calendar_patterns()
        embeddings = {}
        
        if self.use_gemini and self.embedding_provider:
            try:
                for intent, pattern_list in patterns.items():
                    if pattern_list:
                        pattern_embeddings = self.embedding_provider.encode_batch(pattern_list)
                        embeddings[intent] = np.array(pattern_embeddings)
                        logger.debug(f"[ENHANCED] Loaded {len(pattern_list)} Gemini embeddings for '{intent}' (768D)")
            except Exception as e:
                logger.warning(f"Failed to load Gemini pattern embeddings: {e}")
                return {}
        
        elif self.model:
            try:
                for intent, pattern_list in patterns.items():
                    if pattern_list:
                        embeddings[intent] = self.model.encode(pattern_list)
                        logger.debug(f"[ENHANCED] Loaded {len(pattern_list)} sentence-transformer embeddings for '{intent}' (384D)")
            except Exception as e:
                logger.warning(f"Failed to encode patterns: {e}")
                return {}
        else:
            logger.warning("No embedding provider available for pattern matching")
            return {}
        
        return embeddings
    
    def match_semantic(self, query: str, threshold: float = DEFAULT_SEMANTIC_THRESHOLD) -> Optional[str]:
        """
        Match query to patterns using semantic similarity.
        
        Args:
            query: User query
            threshold: Minimum similarity score (0.0-1.0). Defaults to DEFAULT_SEMANTIC_THRESHOLD.
            
        Returns:
            Intent if match found above threshold, None otherwise
        """
        if not self.pattern_embeddings:
            return None
        
        try:
            # Get query embedding
            if self.use_gemini and self.embedding_provider:
                query_embedding = np.array(self.embedding_provider.encode_query(query))
                effective_threshold = threshold * GEMINI_THRESHOLD_MULTIPLIER
            elif self.model:
                query_embedding = self.model.encode([query])[0]
                effective_threshold = threshold
            else:
                return None
            
            best_match = None
            best_score = 0.0
            
            for intent, pattern_embeddings in self.pattern_embeddings.items():
                if len(pattern_embeddings) == 0:
                    continue
                
                # Use safe cosine similarity that handles edge cases
                similarities = safe_cosine_similarity(query_embedding, pattern_embeddings)[0]
                max_similarity = float(np.max(similarities))
                
                if max_similarity > best_score:
                    best_score = max_similarity
                    best_match = intent
            
            if best_score >= effective_threshold:
                provider = "Gemini" if self.use_gemini else "sentence-transformers"
                logger.debug(f"[ENHANCED] Semantic match ({provider}): '{query}' → {best_match} (score: {best_score:.2f})")
                return best_match
            
            return None
        except Exception as e:
            logger.warning(f"Semantic matching failed: {e}")
            return None
