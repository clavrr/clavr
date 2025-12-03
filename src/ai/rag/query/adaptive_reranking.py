"""
Adaptive Reranking Module

Dynamically adjusts reranking weights based on query intent for better accuracy.
"""
from typing import Dict, Tuple
from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class AdaptiveRerankingWeights:
    """
    Provides adaptive reranking weights based on query intent.
    
    Different query types benefit from different ranking signals:
    - Recent queries: Prioritize recency
    - Action queries: Prioritize keywords (specific terms like "send", "delete")
    - Search queries: Prioritize semantic similarity
    - Specific queries: Prioritize metadata (names, dates, labels)
    """
    
    # Intent-to-weights mapping
    INTENT_WEIGHTS = {
        'recent': {
            'semantic_weight': 0.25,
            'keyword_weight': 0.15,
            'metadata_weight': 0.15,
            'recency_weight': 0.45,  # Heavily favor recent emails
            'description': 'Optimized for recent/latest queries'
        },
        'action': {
            'semantic_weight': 0.30,
            'keyword_weight': 0.35,  # Keywords are critical for actions
            'metadata_weight': 0.20,
            'recency_weight': 0.15,
            'description': 'Optimized for action queries (send, delete, archive)'
        },
        'search': {
            'semantic_weight': 0.50,  # Prioritize semantic understanding
            'keyword_weight': 0.20,
            'metadata_weight': 0.15,
            'recency_weight': 0.15,
            'description': 'Optimized for general search queries'
        },
        'specific': {
            'semantic_weight': 0.25,
            'keyword_weight': 0.25,
            'metadata_weight': 0.35,  # Names, dates, labels matter most
            'recency_weight': 0.15,
            'description': 'Optimized for specific queries (names, dates, labels)'
        },
        'default': {
            'semantic_weight': 0.40,
            'keyword_weight': 0.20,
            'metadata_weight': 0.20,
            'recency_weight': 0.20,
            'description': 'Balanced weights for general queries'
        }
    }
    
    @staticmethod
    def get_weights_for_intent(intent: str) -> Dict[str, float]:
        """
        Get optimal reranking weights for a given query intent.
        
        Args:
            intent: Query intent ('recent', 'action', 'search', 'specific', etc.)
            
        Returns:
            Dictionary with weight values
        """
        weights = AdaptiveRerankingWeights.INTENT_WEIGHTS.get(
            intent.lower(),
            AdaptiveRerankingWeights.INTENT_WEIGHTS['default']
        )
        
        logger.debug(f"Using {weights['description']} for intent: {intent}")
        
        return {
            'semantic_weight': weights['semantic_weight'],
            'keyword_weight': weights['keyword_weight'],
            'metadata_weight': weights['metadata_weight'],
            'recency_weight': weights['recency_weight']
        }
    
    @staticmethod
    def detect_intent_from_query(query: str) -> str:
        """
        Detect query intent from query text (fallback if QueryEnhancer doesn't provide it).
        
        Args:
            query: Query text
            
        Returns:
            Detected intent
        """
        query_lower = query.lower()
        
        # Recent queries
        recent_keywords = ['recent', 'latest', 'new', 'today', 'yesterday', 'this week', 'last']
        if any(keyword in query_lower for keyword in recent_keywords):
            return 'recent'
        
        # Action queries
        action_keywords = ['send', 'sent', 'reply', 'forward', 'delete', 'archive', 'move', 'mark']
        if any(keyword in query_lower for keyword in action_keywords):
            return 'action'
        
        # Specific queries (names, dates, specific labels)
        # Look for capitalized words (names), dates, or specific patterns
        specific_patterns = ['from:', 'to:', 'label:', 'subject:', '@', '.com']
        has_capitalized = any(word[0].isupper() for word in query.split() if len(word) > 1)
        has_specific_pattern = any(pattern in query_lower for pattern in specific_patterns)
        
        if has_capitalized or has_specific_pattern:
            return 'specific'
        
        # Default to search
        return 'search'
    
    @staticmethod
    def get_adaptive_weights(
        query: str,
        enhanced_intent: str = None,
        custom_weights: Dict[str, float] = None
    ) -> Tuple[Dict[str, float], str]:
        """
        Get adaptive weights for a query with fallback logic.
        
        Args:
            query: Query text
            enhanced_intent: Intent from QueryEnhancer (if available)
            custom_weights: Optional custom weights to override
            
        Returns:
            Tuple of (weights dict, detected intent)
        """
        # Use custom weights if provided
        if custom_weights:
            return custom_weights, 'custom'
        
        # Use enhanced intent if available
        if enhanced_intent:
            intent = enhanced_intent
        else:
            # Fallback: detect intent from query
            intent = AdaptiveRerankingWeights.detect_intent_from_query(query)
        
        weights = AdaptiveRerankingWeights.get_weights_for_intent(intent)
        
        return weights, intent
    
    @staticmethod
    def get_all_intent_profiles() -> Dict[str, Dict]:
        """
        Get all available intent profiles for documentation/debugging.
        
        Returns:
            Dictionary of all intent profiles with their weights
        """
        return AdaptiveRerankingWeights.INTENT_WEIGHTS.copy()


def create_adaptive_reranker(intent: str):
    """
    Factory function to create a ResultReranker with adaptive weights.
    
    Args:
        intent: Query intent
        
    Returns:
        ResultReranker instance with optimized weights
    """
    from .result_reranker import ResultReranker
    
    weights = AdaptiveRerankingWeights.get_weights_for_intent(intent)
    
    return ResultReranker(
        semantic_weight=weights['semantic_weight'],
        keyword_weight=weights['keyword_weight'],
        metadata_weight=weights['metadata_weight'],
        recency_weight=weights['recency_weight']
    )
