"""
Email Semantic Pattern Matcher - Handles semantic matching for email intents

Extracted from email_parser.py to improve maintainability.
"""
import numpy as np
from typing import Dict, Any, Optional
from ....utils.logger import setup_logger
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for semantic matching
DEFAULT_SEMANTIC_THRESHOLD = EmailParserConfig.HYBRID_SEARCH_CONFIDENCE_THRESHOLD
GEMINI_THRESHOLD_MULTIPLIER = 0.95

# Try to import sentence transformers for semantic matching
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers not available - semantic matching will be disabled")


def safe_cosine_similarity(X, Y):
    """
    Compute cosine similarity with proper handling of edge cases.
    
    Fixes numerical overflow issues by:
    1. Normalizing vectors properly
    2. Handling zero vectors
    3. Clipping values to valid range [-1, 1]
    """
    # Convert to numpy arrays
    X = np.asarray(X, dtype=np.float64)
    Y = np.asarray(Y, dtype=np.float64)
    
    # Ensure 2D arrays
    if X.ndim == 1:
        X = X.reshape(1, -1)
    if Y.ndim == 1:
        Y = Y.reshape(1, -1)
    
    # Compute norms
    X_norm = np.linalg.norm(X, axis=1, keepdims=True)
    Y_norm = np.linalg.norm(Y, axis=1, keepdims=True)
    
    # Handle zero vectors (return 0 similarity)
    X_norm = np.where(X_norm == 0, 1, X_norm)
    Y_norm = np.where(Y_norm == 0, 1, Y_norm)
    
    # Normalize
    X_normalized = X / X_norm
    Y_normalized = Y / Y_norm
    
    # Compute dot product
    similarity = np.dot(X_normalized, Y_normalized.T)
    
    # Clip to valid range to avoid numerical errors
    similarity = np.clip(similarity, -1.0, 1.0)
    
    return similarity


class EmailSemanticPatternMatcher:
    """
    Semantic pattern matcher for email intents using embeddings (Gemini preferred, sentence-transformers fallback).
    Handles paraphrases, synonyms, and variations better than exact string matching.
    
    Uses Gemini embeddings when available for better accuracy, falls back to sentence-transformers
    for speed and reliability.
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
        
        # Try Gemini embeddings first (gemini-embedding-001 via models/embedding-001 API format)
        # This is more accurate (768D) and uses caching for fast repeated queries
        if config and config.ai and config.ai.api_key:
            try:
                from ....ai.rag.core.embedding_provider import create_embedding_provider
                from ....utils.config import RAGConfig
                
                # Create Gemini embedding provider with gemini-embedding-001 model
                # Note: Google API uses "models/embedding-001" format, which corresponds to gemini-embedding-001
                rag_config = RAGConfig(
                    embedding_provider="gemini",
                    embedding_model="models/embedding-001"  # gemini-embedding-001 (Google API format)
                )
                self.embedding_provider = create_embedding_provider(config, rag_config)
                
                # Check if it's actually Gemini (not fallback)
                from ....ai.rag.core.embedding_provider import GeminiEmbeddingProvider
                if isinstance(self.embedding_provider, GeminiEmbeddingProvider):
                    self.use_gemini = True
                    logger.info("[ENHANCED] Using gemini-embedding-001 for email semantic matching (more accurate, 768D, cached)")
                else:
                    logger.info("[ENHANCED] Gemini embeddings unavailable, falling back to sentence-transformers")
            except Exception as e:
                logger.debug(f"Gemini embeddings (gemini-embedding-001) not available: {e}, falling back to sentence-transformers")
        
        # Fallback to sentence-transformers (faster, local, no API dependency)
        if not self.use_gemini:
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                logger.warning("EmailSemanticPatternMatcher: No embedding provider available")
                return
            
            try:
                # Use lightweight sentence-transformer model for speed (384 dimensions)
                # This is the fallback when Gemini embeddings are not available
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("[ENHANCED] Using sentence-transformers (all-MiniLM-L6-v2) for email semantic matching (fast, local, 384D)")
            except Exception as e:
                logger.warning(f"Failed to initialize sentence-transformers fallback: {e}")
                return
        
        # Load pattern embeddings
        self.pattern_embeddings = self._load_pattern_embeddings()
        if self.pattern_embeddings:
            logger.info("[ENHANCED] EmailSemanticPatternMatcher initialized successfully")
    
    def _load_pattern_embeddings(self) -> Dict[str, np.ndarray]:
        """Pre-compute embeddings for all email patterns"""
        patterns = {
            'list': [
                'show emails', 'list emails', 'my emails', 'recent emails',
                'check emails', 'read emails', 'what emails', 'which emails',
                'emails do i have', 'emails have i', 'do i have emails',
                'any emails', 'any new emails', 'new emails', 'emails today'
            ],
            'search': [
                'find emails', 'search emails', 'emails from', 'emails about',
                'emails containing', 'emails with', 'look for emails',
                'find email', 'search for email', 'email from', 'email about'
            ],
            'send': [
                'send email', 'send an email', 'compose email', 'write email',
                'draft email', 'create email', 'email to', 'send to'
            ],
            'reply': [
                'reply to', 'reply email', 'respond to', 'answer email',
                'reply to email', 'respond to email'
            ],
            'summarize': [
                'summarize email', 'email summary', 'key points',
                'brief summary', 'summarize emails', 'email summaries'
            ],
            'unread': [
                'unread emails', 'unread', 'unread messages', 'left unread',
                'oldest unread', 'longest unread', 'haven\'t read'
            ]
        }
        
        embeddings = {}
        
        if self.use_gemini and self.embedding_provider:
            # Use Gemini embeddings (more accurate, 768D)
            try:
                for intent, pattern_list in patterns.items():
                    if pattern_list:
                        # Batch encode for efficiency
                        pattern_embeddings = self.embedding_provider.encode_batch(pattern_list)
                        # Convert to numpy array
                        embeddings[intent] = np.array(pattern_embeddings)
                        logger.debug(f"[ENHANCED] Loaded {len(pattern_list)} Gemini embeddings for '{intent}' intent (768D)")
            except Exception as e:
                logger.warning(f"Failed to load Gemini pattern embeddings: {e}")
                return {}
        
        elif self.model:
            # Use sentence-transformers (faster, 384D)
            try:
                for intent, pattern_list in patterns.items():
                    if pattern_list:
                        embeddings[intent] = self.model.encode(pattern_list)
                        logger.debug(f"[ENHANCED] Loaded {len(pattern_list)} sentence-transformer embeddings for '{intent}' intent (384D)")
            except Exception as e:
                logger.warning(f"Failed to encode patterns: {e}")
                return {}
        else:
            logger.warning("No embedding provider available for email pattern matching")
            return {}
        
        return embeddings
    
    def match_semantic(self, query: str, threshold: float = DEFAULT_SEMANTIC_THRESHOLD) -> Optional[str]:
        """
        Match query to patterns using semantic similarity.
        
        Uses Gemini embeddings if available (more accurate), otherwise sentence-transformers.
        Gemini embeddings are cached, so repeated queries are fast.
        
        Args:
            query: User query
            threshold: Minimum similarity score (0.0-1.0)
                       Note: Gemini embeddings may need slightly lower threshold (0.65) 
                       due to different embedding space
            
        Returns:
            Intent if match found above threshold, None otherwise
        """
        if not self.pattern_embeddings:
            return None
        
        try:
            # Get query embedding
            if self.use_gemini and self.embedding_provider:
                # Use Gemini (cached, more accurate)
                query_embedding = np.array(self.embedding_provider.encode_query(query))
                # Adjust threshold slightly for Gemini (different embedding space)
                effective_threshold = threshold * GEMINI_THRESHOLD_MULTIPLIER
            elif self.model:
                # Use sentence-transformers
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
                logger.debug(f"[ENHANCED] Email semantic match ({provider}): '{query}' → {best_match} (score: {best_score:.2f})")
                return best_match
            
            return None
        except Exception as e:
            logger.warning(f"Email semantic matching failed: {e}")
            return None
