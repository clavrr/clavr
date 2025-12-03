"""
Task Learning System

Helps the task parser learn from mistakes and get better over time.
When a user corrects us or we get something right, we remember it so we can 
handle similar queries better in the future.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime

from ....utils.logger import setup_logger
from .constants import TaskParserConfig

logger = setup_logger(__name__)


class TaskLearningSystem:
    """
    Helps the task parser learn from mistakes and get better over time.
    
    When a user corrects us or we get something right, we remember it so we can 
    handle similar queries better in the future.
    """
    
    def __init__(self, memory=None):
        self.memory = memory
        self.corrections = []  # When users correct us
        self.successful_queries = []  # Queries we got right (for few-shot learning)
        self.pattern_success_rates = {}  # Track which patterns work well
    
    def record_correction(self, query: str, wrong_intent: str, correct_intent: str):
        """Remember when a user corrected us so we don't make the same mistake again"""
        correction = {
            'query': query,
            'wrong_intent': wrong_intent,
            'correct_intent': correct_intent,
            'timestamp': datetime.now()
        }
        self.corrections.append(correction)
        
        # Keep only recent corrections
        if len(self.corrections) > TaskParserConfig.MAX_CORRECTIONS_STORED:
            self.corrections = self.corrections[-TaskParserConfig.MAX_CORRECTIONS_STORED:]
        
        logger.info(f"[LEARNING] Recorded task correction: '{query}' ({wrong_intent} → {correct_intent})")
    
    def record_success(self, query: str, intent: str, classification: Dict[str, Any]):
        """Remember queries we got right - we'll use these as examples for similar queries later"""
        success = {
            'query': query,
            'intent': intent,
            'classification': classification,
            'timestamp': datetime.now()
        }
        self.successful_queries.append(success)
        
        # Keep only recent successes
        if len(self.successful_queries) > TaskParserConfig.MAX_SUCCESSFUL_QUERIES_STORED:
            self.successful_queries = self.successful_queries[-TaskParserConfig.MAX_SUCCESSFUL_QUERIES_STORED:]
    
    def record_classification_result(self, query: str, predicted_action: str, llm_classification: Dict[str, Any], success: bool):
        """Record the result of a classification attempt for learning"""
        if success:
            # Record as success
            self.record_success(query, predicted_action, llm_classification)
        else:
            # Could record as correction if we know the correct action
            logger.debug(f"[LEARNING] Classification failed for query: {query}, predicted: {predicted_action}")
    
    def get_similar_successes(self, query: str, limit: int = TaskParserConfig.DEFAULT_SIMILAR_EXAMPLES_LIMIT) -> List[Dict[str, Any]]:
        """Find similar queries we handled successfully before - useful for few-shot learning"""
        # Using simple word overlap for now, could upgrade to embeddings later
        query_words = set(query.lower().split())
        
        similarities = []
        for success in self.successful_queries:
            success_words = set(success['query'].lower().split())
            overlap = len(query_words & success_words) / max(len(query_words), len(success_words), 1)
            if overlap > TaskParserConfig.SIMILARITY_THRESHOLD_LOW:  # At least threshold word overlap
                similarities.append((overlap, success))
        
        # Sort by similarity and return top matches
        similarities.sort(reverse=True, key=lambda x: x[0])
        return [s[1] for s in similarities[:limit]]
    
    def get_learned_intent(self, query: str) -> Optional[str]:
        """See if we've seen a similar query before and learned the right intent for it"""
        query_words = set(query.lower().split())
        
        for correction in self.corrections:
            correction_words = set(correction['query'].lower().split())
            overlap = len(query_words & correction_words) / max(len(query_words), len(correction_words), 1)
            
            if overlap > TaskParserConfig.SIMILARITY_THRESHOLD_HIGH:  # High similarity
                logger.info(f"[LEARNING] Using learned task intent from similar correction: {correction['correct_intent']}")
                return correction['correct_intent']
        
        return None
