"""
Adaptive Reranking Module

Dynamically adjusts reranking weights based on query intent for better accuracy.
"""
from typing import Dict, Tuple

from ....utils.logger import setup_logger
from .query_enhancer import QueryEnhancer
from .rules import RERANKING_WEIGHTS

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
    
    @staticmethod
    def get_weights_for_intent(intent: str) -> Dict[str, float]:
        """
        Get optimal reranking weights for a given query intent.
        
        Args:
            intent: Query intent ('recent', 'action', 'search', 'specific', etc.)
            
        Returns:
            Dictionary with weight values
        """
        weights = RERANKING_WEIGHTS.get(
            intent.lower(),
            RERANKING_WEIGHTS['default']
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
        # Use unified logic from QueryEnhancer
        return QueryEnhancer.detect_intent(query)
    
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
        return RERANKING_WEIGHTS.copy()


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
