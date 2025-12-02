"""
Task Semantic Pattern Matcher

Matches task queries to intents using semantic similarity instead of exact string matching.
This handles paraphrases way better - like "show me my tasks" vs "what tasks do I have" 
will both match the "list" intent.

Prefers Gemini embeddings when available (more accurate, 768D, cached),
falls back to sentence-transformers (fast, local, 384D) if Gemini isn't set up.
"""
import numpy as np
from typing import Dict, Optional

from ....utils.logger import setup_logger
from ...intent import (
    TASK_QUESTION_PATTERNS, TASK_CREATE_PATTERNS, TASK_LIST_PATTERNS,
    TASK_ANALYSIS_PATTERNS, TASK_COMPLETION_PATTERNS
)
from .constants import TaskParserConfig

logger = setup_logger(__name__)

# Lazy imports for sentence transformers (heavy dependencies)
# These will only be imported when actually instantiating the matcher
SENTENCE_TRANSFORMERS_AVAILABLE = None  # Will be checked on first use

def _check_sentence_transformers_available():
    """Check if sentence-transformers is available (lazy check)"""
    global SENTENCE_TRANSFORMERS_AVAILABLE
    if SENTENCE_TRANSFORMERS_AVAILABLE is None:
        try:
            import sentence_transformers
            import sklearn.metrics.pairwise
            SENTENCE_TRANSFORMERS_AVAILABLE = True
        except ImportError:
            SENTENCE_TRANSFORMERS_AVAILABLE = False
            logger.warning("sentence-transformers not available - semantic matching will be disabled")
    return SENTENCE_TRANSFORMERS_AVAILABLE


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


class TaskSemanticPatternMatcher:
    """
    Matches task queries to intents using semantic similarity instead of exact string matching.
    
    This handles paraphrases way better - like "show me my tasks" vs "what tasks do I have" 
    will both match the "list" intent. We prefer Gemini embeddings when available since they're 
    more accurate, but fall back to sentence-transformers if Gemini isn't set up.
    """
    
    def __init__(self, config=None, embedding_provider=None):
        """
        Set up the semantic matcher. Tries Gemini first, then falls back to sentence-transformers.
        
        Args:
            config: Config object if you want to use Gemini embeddings
            embedding_provider: If you already have an embedding provider, pass it here to reuse it
        """
        self.config = config
        self.embedding_provider = embedding_provider
        self.use_gemini = False
        self.model = None
        self.pattern_embeddings = {}
        
        # Try Gemini embeddings first - they're more accurate and cached, so repeated queries are fast
        # Google's API uses "models/embedding-001" which is actually gemini-embedding-001 under the hood
        if config and config.ai and config.ai.api_key:
            try:
                from ....ai.rag.core.embedding_provider import create_embedding_provider
                from ....utils.config import RAGConfig
                
                rag_config = RAGConfig(
                    embedding_provider="gemini",
                    embedding_model="models/embedding-001"  # This is gemini-embedding-001 in Google's format
                )
                self.embedding_provider = create_embedding_provider(config, rag_config)
                
                # Make sure we actually got Gemini and not some fallback
                from ....ai.rag.core.embedding_provider import GeminiEmbeddingProvider
                if isinstance(self.embedding_provider, GeminiEmbeddingProvider):
                    self.use_gemini = True
                    logger.info("[ENHANCED] Using gemini-embedding-001 for task semantic matching (more accurate, 768D, cached)")
                else:
                    logger.info("[ENHANCED] Gemini embeddings unavailable, falling back to sentence-transformers")
            except Exception as e:
                logger.debug(f"Gemini embeddings (gemini-embedding-001) not available: {e}, falling back to sentence-transformers")
        
        # If Gemini didn't work, use sentence-transformers as a fallback - it's local and fast
        if not self.use_gemini:
            # Lazy check for sentence-transformers availability
            if not _check_sentence_transformers_available():
                logger.warning("TaskSemanticPatternMatcher: No embedding provider available")
                return
            
            try:
                # Lazy import - only import when actually needed
                from sentence_transformers import SentenceTransformer
                # Using a lightweight model that's fast and doesn't need API calls
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("[ENHANCED] Using sentence-transformers (all-MiniLM-L6-v2) for task semantic matching (fast, local, 384D)")
            except Exception as e:
                logger.warning(f"Failed to initialize sentence-transformers fallback: {e}")
                return
        
        # Pre-compute embeddings for all our patterns so matching is fast
        self.pattern_embeddings = self._load_pattern_embeddings()
        if self.pattern_embeddings:
            logger.info("[ENHANCED] TaskSemanticPatternMatcher initialized successfully")
    
    def _load_pattern_embeddings(self) -> Dict[str, np.ndarray]:
        """Pre-compute embeddings for all task patterns so we don't have to do it every time"""
        patterns = {
            'list': TASK_LIST_PATTERNS + TASK_QUESTION_PATTERNS,
            'create': TASK_CREATE_PATTERNS,
            'complete': TASK_COMPLETION_PATTERNS,
            'analyze': TASK_ANALYSIS_PATTERNS,
            'delete': [
                'delete task', 'remove task', 'cancel task', 'delete todo',
                'remove todo', 'cancel todo', 'delete reminder'
            ],
            'search': [
                'find tasks', 'search tasks', 'look for tasks', 'find todo',
                'search for tasks', 'tasks about', 'tasks with'
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
            logger.warning("No embedding provider available for task pattern matching")
            return {}
        
        return embeddings
    
    def match_semantic(self, query: str, threshold: float = TaskParserConfig.DEFAULT_SEMANTIC_THRESHOLD) -> Optional[str]:
        """
        Find which intent this query matches using semantic similarity.
        
        We use Gemini embeddings if available (they're more accurate), otherwise sentence-transformers.
        Gemini caches results so repeated queries are super fast.
        
        Args:
            query: What the user asked
            threshold: How similar it needs to be (0.0-1.0). Gemini embeddings work slightly 
                      differently so we adjust the threshold a bit lower for them.
            
        Returns:
            The matched intent if we found one above the threshold, None otherwise
        """
        if not self.pattern_embeddings:
            return None
        
        try:
            # Get query embedding
            if self.use_gemini and self.embedding_provider:
                # Use Gemini (cached, more accurate)
                query_embedding = np.array(self.embedding_provider.encode_query(query))
                # Adjust threshold slightly for Gemini (different embedding space)
                effective_threshold = threshold * TaskParserConfig.GEMINI_THRESHOLD_MULTIPLIER
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
                logger.debug(f"[ENHANCED] Task semantic match ({provider}): '{query}' → {best_match} (score: {best_score:.2f})")
                return best_match
            
            return None
        except Exception as e:
            logger.warning(f"Task semantic matching failed: {e}")
            return None
