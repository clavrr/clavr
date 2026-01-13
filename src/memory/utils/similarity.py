"""
Similarity Utility

Helper functions for calculating similarity between patterns and queries.
"""
from typing import Set

def calculate_pattern_similarity(pattern1: str, pattern2: str) -> float:
    """
    Calculate similarity between two patterns using Jaccard similarity.
    
    Args:
        pattern1: First pattern string
        pattern2: Second pattern string
        
    Returns:
        Similarity score between 0.0 and 1.0
    """
    # Simple word-based similarity
    words1 = set(pattern1.lower().split('_'))
    words2 = set(pattern2.lower().split('_'))
    
    if not words1 or not words2:
        return 0.0
    
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    
    return intersection / union if union > 0 else 0.0
