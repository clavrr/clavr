"""
Calendar Learning System - Improves from user corrections and successful queries

This module provides a learning system that:
- Records user corrections for improved intent classification
- Tracks successful queries for few-shot learning
- Integrates with memory system for persistence (if available)
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from ....utils.logger import setup_logger

logger = setup_logger(__name__)

# Constants for learning system configuration
MAX_CORRECTIONS_STORED = 100  # Maximum number of corrections to keep in memory
MAX_SUCCESSFUL_QUERIES_STORED = 50  # Maximum number of successful queries to keep
SIMILARITY_THRESHOLD_LOW = 0.3  # Minimum similarity for finding similar successes (30%)
SIMILARITY_THRESHOLD_HIGH = 0.6  # Minimum similarity for learned intent matching (60%)
DEFAULT_SIMILAR_EXAMPLES_LIMIT = 3  # Default number of similar examples to return


class CalendarLearningSystem:
    """
    Learning system that improves from user corrections and successful queries.
    
    Features:
    - Records user corrections for improved intent classification
    - Tracks successful queries for few-shot learning
    - Integrates with memory system for persistence (if provided)
    - Provides similarity-based query matching
    """
    
    def __init__(self, memory=None):
        """
        Initialize learning system
        
        Args:
            memory: Optional memory instance (SimplifiedMemorySystem or HybridMemorySystem)
                   for persistent storage. If provided, corrections and successes will be
                   persisted across sessions.
        """
        self.memory = memory
        self.corrections: List[Dict[str, Any]] = []  # Store corrections
        self.successful_queries: List[Dict[str, Any]] = []  # Store successful queries for few-shot learning
        
        # Load from memory if available
        if self.memory:
            self._load_from_memory()
    
    def record_correction(self, query: str, wrong_intent: str, correct_intent: str):
        """
        Record a user correction for learning
        
        Args:
            query: User query
            wrong_intent: Incorrectly detected intent
            correct_intent: Correct intent
        """
        correction = {
            'query': query,
            'wrong_intent': wrong_intent,
            'correct_intent': correct_intent,
            'timestamp': datetime.now()
        }
        self.corrections.append(correction)
        
        # Keep only recent corrections
        if len(self.corrections) > MAX_CORRECTIONS_STORED:
            self.corrections = self.corrections[-MAX_CORRECTIONS_STORED:]
        
        # Persist to memory if available
        if self.memory:
            self._save_correction_to_memory(correction)
        
        logger.info(f"[LEARNING] Recorded correction: '{query}' ({wrong_intent} → {correct_intent})")
    
    def record_success(self, query: str, intent: str, classification: Dict[str, Any]):
        """
        Record a successful query for few-shot learning
        
        Args:
            query: User query
            intent: Detected intent
            classification: Full classification result
        """
        success = {
            'query': query,
            'intent': intent,
            'classification': classification,
            'timestamp': datetime.now()
        }
        self.successful_queries.append(success)
        
        # Keep only recent successes
        if len(self.successful_queries) > MAX_SUCCESSFUL_QUERIES_STORED:
            self.successful_queries = self.successful_queries[-MAX_SUCCESSFUL_QUERIES_STORED:]
        
        # Persist to memory if available
        if self.memory:
            self._save_success_to_memory(success)
    
    def get_similar_successes(self, query: str, limit: int = DEFAULT_SIMILAR_EXAMPLES_LIMIT) -> List[Dict[str, Any]]:
        """
        Get similar successful queries for few-shot learning.
        
        Uses word overlap similarity matching. Could be enhanced with embeddings
        if semantic matching is needed.
        
        Args:
            query: User query
            limit: Maximum number of similar queries to return (default: DEFAULT_SIMILAR_EXAMPLES_LIMIT)
            
        Returns:
            List of similar successful queries, sorted by similarity (most similar first)
        """
        if not self.successful_queries:
            return []
        
        query_words = set(query.lower().split())
        
        similarities = []
        for success in self.successful_queries:
            success_words = set(success['query'].lower().split())
            # Calculate Jaccard similarity (intersection over union)
            intersection = len(query_words & success_words)
            union = len(query_words | success_words)
            overlap = intersection / union if union > 0 else 0.0
            
            if overlap >= SIMILARITY_THRESHOLD_LOW:
                similarities.append((overlap, success))
        
        # Sort by similarity (descending) and return top matches
        similarities.sort(reverse=True, key=lambda x: x[0])
        return [s[1] for s in similarities[:limit]]
    
    def get_learned_intent(self, query: str) -> Optional[str]:
        """
        Check if we've learned the correct intent for similar queries.
        
        Uses high similarity threshold to ensure we only apply learned intents
        when we're confident the queries are very similar.
        
        Args:
            query: User query
            
        Returns:
            Learned intent if found for a highly similar query, None otherwise
        """
        if not self.corrections:
            return None
        
        query_words = set(query.lower().split())
        
        # Find the most similar correction
        best_match = None
        best_similarity = 0.0
        
        for correction in self.corrections:
            correction_words = set(correction['query'].lower().split())
            # Calculate Jaccard similarity
            intersection = len(query_words & correction_words)
            union = len(query_words | correction_words)
            overlap = intersection / union if union > 0 else 0.0
            
            if overlap >= SIMILARITY_THRESHOLD_HIGH and overlap > best_similarity:
                best_similarity = overlap
                best_match = correction
        
        if best_match:
            logger.info(
                f"[LEARNING] Using learned intent from similar correction "
                f"(similarity: {best_similarity:.2f}): {best_match['correct_intent']}"
            )
            return best_match['correct_intent']
        
        return None
    
    def record_user_correction(self, query: str, wrong_action: str, correct_action: str):
        """
        Public method to record user corrections.
        
        This is the public API for recording corrections, typically called from
        API endpoints when users provide feedback. It delegates to record_correction
        but provides a clear public interface.
        
        Args:
            query: User query
            wrong_action: Incorrectly detected action
            correct_action: Correct action
        """
        self.record_correction(query, wrong_action, correct_action)
        logger.info(f"[LEARNING] User correction recorded via public API: '{query}' ({wrong_action} → {correct_action})")
    
    def _load_from_memory(self):
        """
        Load corrections and successful queries from memory system if available.
        
        This method is called during initialization to restore learning data
        from persistent storage.
        """
        if not self.memory or not hasattr(self.memory, 'query_patterns'):
            return
        
        try:
            # Load corrections from memory patterns
            # Memory system stores patterns with intent, we can reconstruct corrections
            # by looking for patterns with low success rates that were corrected
            logger.debug("[LEARNING] Loading learning data from memory system")
            # Note: This is a simplified implementation. Full integration would
            # require memory system to have specific methods for learning data
        except Exception as e:
            logger.warning(f"[LEARNING] Failed to load from memory: {e}")
    
    def _save_correction_to_memory(self, correction: Dict[str, Any]):
        """
        Save correction to memory system for persistence.
        
        Args:
            correction: Correction dictionary to save
        """
        if not self.memory or not hasattr(self.memory, 'learn_query_pattern'):
            return
        
        try:
            # Save correction as a pattern with the correct intent
            # This allows the memory system to learn from corrections
            self.memory.learn_query_pattern(
                query=correction['query'],
                intent=correction['correct_intent'],
                tools_used=['calendar'],
                success=True,  # Correction means we learned the right way
                user_id=None  # Could be extracted from context if available
            )
        except Exception as e:
            logger.debug(f"[LEARNING] Failed to save correction to memory: {e}")
    
    def _save_success_to_memory(self, success: Dict[str, Any]):
        """
        Save successful query to memory system for persistence.
        
        Args:
            success: Success dictionary to save
        """
        if not self.memory or not hasattr(self.memory, 'learn_query_pattern'):
            return
        
        try:
            # Save successful query as a pattern
            self.memory.learn_query_pattern(
                query=success['query'],
                intent=success['intent'],
                tools_used=['calendar'],
                success=True,
                user_id=None  # Could be extracted from context if available
            )
        except Exception as e:
            logger.debug(f"[LEARNING] Failed to save success to memory: {e}")
