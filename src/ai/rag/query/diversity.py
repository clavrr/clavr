"""
Result Diversity Enhancement

Implements Maximal Marginal Relevance (MMR) algorithm to reduce near-duplicate
results and improve result diversity.
"""
from typing import List, Dict, Any, Optional
import numpy as np

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
    
    Args:
        vec1: First vector
        vec2: Second vector
        
    Returns:
        Cosine similarity score (0-1)
    """
    try:
        a = np.array(vec1)
        b = np.array(vec2)
        
        # Handle zero vectors
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    except Exception as e:
        logger.warning(f"Cosine similarity calculation failed: {e}")
        return 0.0


def text_similarity(text1: str, text2: str) -> float:
    """
    Calculate simple text similarity using Jaccard coefficient.
    
    Args:
        text1: First text
        text2: Second text
        
    Returns:
        Similarity score (0-1)
    """
    try:
        # Tokenize and create sets
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        # Jaccard similarity
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    except Exception as e:
        logger.warning(f"Text similarity calculation failed: {e}")
        return 0.0


def maximal_marginal_relevance(
    results: List[Dict[str, Any]],
    query_embedding: Optional[List[float]] = None,
    k: int = 10,
    lambda_param: float = 0.5,
    similarity_key: str = 'rerank_score'
) -> List[Dict[str, Any]]:
    """
    Apply Maximal Marginal Relevance (MMR) to diversify search results.
    
    MMR balances relevance and diversity by selecting documents that are:
    1. Relevant to the query (high similarity)
    2. Different from already selected documents (low similarity to each other)
    
    Args:
        results: List of search results with scores
        query_embedding: Optional query embedding for semantic similarity
        k: Number of results to return
        lambda_param: Balance between relevance (1.0) and diversity (0.0)
                     0.5 = balanced (default)
        similarity_key: Key to use for relevance scores ('rerank_score', 'distance', etc.)
        
    Returns:
        Diversified list of results
    """
    if not results or k <= 0:
        return results
    
    # If fewer results than k, return all
    if len(results) <= k:
        return results
    
    # Extract relevance scores (normalize to 0-1)
    relevance_scores = []
    for r in results:
        if similarity_key in r:
            score = r[similarity_key]
            # If using distance, invert it (lower is better)
            if similarity_key == 'distance':
                score = 1.0 / (1.0 + score)
            relevance_scores.append(score)
        else:
            # Default score
            relevance_scores.append(0.5)
    
    # Normalize relevance scores to 0-1
    if relevance_scores:
        max_score = max(relevance_scores)
        min_score = min(relevance_scores)
        if max_score > min_score:
            relevance_scores = [(s - min_score) / (max_score - min_score) for s in relevance_scores]
    
    # Build similarity matrix between documents
    n = len(results)
    similarity_matrix = np.zeros((n, n))
    
    for i in range(n):
        for j in range(i + 1, n):
            # Try to use embeddings if available, otherwise use text similarity
            if 'embedding' in results[i] and 'embedding' in results[j]:
                sim = cosine_similarity(results[i]['embedding'], results[j]['embedding'])
            elif 'content' in results[i] and 'content' in results[j]:
                sim = text_similarity(results[i]['content'], results[j]['content'])
            else:
                # Default: assume some similarity
                sim = 0.3
            
            similarity_matrix[i][j] = sim
            similarity_matrix[j][i] = sim
    
    # MMR algorithm
    selected_indices = []
    remaining_indices = list(range(n))
    
    # Select first document (highest relevance)
    first_idx = np.argmax(relevance_scores)
    selected_indices.append(first_idx)
    remaining_indices.remove(first_idx)
    
    # Iteratively select remaining documents
    while len(selected_indices) < k and remaining_indices:
        mmr_scores = []
        
        for idx in remaining_indices:
            # Relevance component (how relevant to query)
            relevance = relevance_scores[idx]
            
            # Diversity component (max similarity to already selected docs)
            max_similarity = max([similarity_matrix[idx][s] for s in selected_indices])
            
            # MMR score: balance relevance and diversity
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_similarity
            mmr_scores.append(mmr_score)
        
        # Select document with highest MMR score
        best_idx = remaining_indices[np.argmax(mmr_scores)]
        selected_indices.append(best_idx)
        remaining_indices.remove(best_idx)
    
    # Return selected documents in order
    diversified_results = [results[i] for i in selected_indices]
    
    logger.debug(f"MMR diversification: {len(results)} → {len(diversified_results)} results (λ={lambda_param})")
    
    return diversified_results


def remove_near_duplicates(
    results: List[Dict[str, Any]],
    similarity_threshold: float = 0.9,
    content_key: str = 'content'
) -> List[Dict[str, Any]]:
    """
    Remove near-duplicate results based on content similarity.
    
    Args:
        results: List of search results
        similarity_threshold: Threshold for considering documents as duplicates (0-1)
        content_key: Key to use for content comparison
        
    Returns:
        Deduplicated list of results
    """
    if not results:
        return results
    
    deduplicated = []
    seen_contents = []
    
    for result in results:
        content = result.get(content_key, '')
        
        # Check similarity with already selected documents
        is_duplicate = False
        for seen_content in seen_contents:
            similarity = text_similarity(content, seen_content)
            if similarity >= similarity_threshold:
                is_duplicate = True
                logger.debug(f"Duplicate detected (similarity={similarity:.2f}): {content[:50]}...")
                break
        
        if not is_duplicate:
            deduplicated.append(result)
            seen_contents.append(content)
    
    if len(deduplicated) < len(results):
        logger.info(f"Removed {len(results) - len(deduplicated)} near-duplicates")
    
    return deduplicated


def apply_diversity(
    results: List[Dict[str, Any]],
    k: int,
    diversity_mode: str = 'mmr',
    lambda_param: float = 0.5,
    duplicate_threshold: float = 0.9
) -> List[Dict[str, Any]]:
    """
    Apply diversity enhancement to search results.
    
    Args:
        results: List of search results
        k: Number of results to return
        diversity_mode: 'mmr' for MMR algorithm, 'dedup' for deduplication only
        lambda_param: MMR lambda parameter (0=diversity, 1=relevance)
        duplicate_threshold: Similarity threshold for deduplication
        
    Returns:
        Diversified results
    """
    if diversity_mode == 'mmr':
        return maximal_marginal_relevance(
            results=results,
            k=k,
            lambda_param=lambda_param
        )
    elif diversity_mode == 'dedup':
        deduplicated = remove_near_duplicates(
            results=results,
            similarity_threshold=duplicate_threshold
        )
        return deduplicated[:k]
    else:
        logger.warning(f"Unknown diversity mode: {diversity_mode}, returning top-k")
        return results[:k]
