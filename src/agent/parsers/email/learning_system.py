"""
Email Learning System - Learns from user corrections and successful queries

Extracted from email_parser.py to improve maintainability.
"""
from datetime import datetime
from typing import Dict, Any, Optional, List
from ....utils.logger import setup_logger

logger = setup_logger(__name__)

# Constants for learning system
MAX_CORRECTIONS_STORED = 100
MAX_SUCCESSFUL_QUERIES_STORED = 50
SIMILARITY_THRESHOLD_LOW = 0.3
SIMILARITY_THRESHOLD_HIGH = 0.6
DEFAULT_SIMILAR_EXAMPLES_LIMIT = 3


class EmailLearningSystem:
    """
    Learning system for email parser that improves from user corrections and successful queries.
    """
    
    def __init__(self, memory=None):
        self.memory = memory
        self.corrections = []  # Store corrections
        self.successful_queries = []  # Store successful queries for few-shot learning
        self.pattern_success_rates = {}  # Track pattern success rates
    
    def record_correction(self, query: str, wrong_intent: str, correct_intent: str):
        """Record a user correction for learning"""
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
        
        logger.info(f"[LEARNING] Recorded email correction: '{query}' ({wrong_intent} → {correct_intent})")
    
    def record_success(self, query: str, intent: str, classification: Dict[str, Any]):
        """Record a successful query for few-shot learning"""
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
    
    def get_similar_successes(self, query: str, limit: int = DEFAULT_SIMILAR_EXAMPLES_LIMIT) -> List[Dict[str, Any]]:
        """Get similar successful queries for few-shot learning"""
        # Simple word overlap for now (could be enhanced with embeddings)
        query_words = set(query.lower().split())
        
        similarities = []
        for success in self.successful_queries:
            success_words = set(success['query'].lower().split())
            overlap = len(query_words & success_words) / max(len(query_words), len(success_words), 1)
            if overlap > SIMILARITY_THRESHOLD_LOW:  # At least threshold word overlap
                similarities.append((overlap, success))
        
        # Sort by similarity and return top matches
        similarities.sort(reverse=True, key=lambda x: x[0])
        return [s[1] for s in similarities[:limit]]
    
    def get_learned_intent(self, query: str) -> Optional[str]:
        """Check if we've learned the correct intent for similar queries"""
        query_words = set(query.lower().split())
        
        for correction in self.corrections:
            correction_words = set(correction['query'].lower().split())
            overlap = len(query_words & correction_words) / max(len(query_words), len(correction_words), 1)
            
            if overlap > SIMILARITY_THRESHOLD_HIGH:  # High similarity
                logger.info(f"[LEARNING] Using learned email intent from similar correction: {correction['correct_intent']}")
                return correction['correct_intent']
        
        return None
