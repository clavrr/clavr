"""
Result Diversity Enhancement

Implements Maximal Marginal Relevance (MMR) algorithm to reduce near-duplicate
results and improve result diversity.
"""
import re
from typing import List, Dict, Any, Optional
import numpy as np

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
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
    Uses regex for robust tokenization (handles punctuation).
    
    Args:
        text1: First text
        text2: Second text
        
    Returns:
        Similarity score (0-1)
    """
    try:
        # Tokenize using regex to handle punctuation
        words1 = set(re.findall(r'\b\w+\b', text1.lower()))
        words2 = set(re.findall(r'\b\w+\b', text2.lower()))
        
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
    Optimized implementation updates max-similarity vector iteratively.
    
    Args:
        results: List of search results ("candidates")
        query_embedding: Optional query embedding for semantic similarity
        k: Number of results to return
        lambda_param: Balance between relevance (1.0) and diversity (0.0)
        similarity_key: Key to use for relevance scores
        
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
            relevance_scores.append(0.5)
    
    # Normalize relevance scores to 0-1
    if relevance_scores:
        max_score = max(relevance_scores)
        min_score = min(relevance_scores)
        if max_score > min_score:
            relevance_scores = [(s - min_score) / (max_score - min_score) for s in relevance_scores]
    
    # Pruning Optimization: Keep top N candidates to reduce matrix size
    # For very large result sets (e.g. 500+), computing N*N matrix is slow.
    if len(results) > 100:
         # Sort by relevance
         results_with_scores = list(zip(results, relevance_scores))
         results_with_scores.sort(key=lambda x: x[1], reverse=True)
         # Keep top 100
         results_with_scores = results_with_scores[:100]
         results, relevance_scores = zip(*results_with_scores)
         results = list(results)
         relevance_scores = list(relevance_scores)
    
    n = len(results)
    
    # Build similarity matrix
    similarity_matrix = np.zeros((n, n))
    
    # Check if we can use vectorized embedding calculation
    embeddings = []
    has_embeddings = True
    for r in results:
        if 'embedding' not in r or not r['embedding']:
            has_embeddings = False
            break
        embeddings.append(r['embedding'])
        
    if has_embeddings and len(embeddings) == n:
        try:
            # Stack embeddings into matrix
            emb_matrix = np.array(embeddings)
            # Normalize rows
            norm = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
            norm[norm == 0] = 1e-10
            normalized_emb = emb_matrix / norm
            # Compute similarity matrix via dot product
            similarity_matrix = np.dot(normalized_emb, normalized_emb.T)
            similarity_matrix = np.clip(similarity_matrix, 0.0, 1.0)
        except Exception as e:
            logger.warning(f"Vectorized similarity failed: {e}, falling back to loop")
            has_embeddings = False
            
    if not has_embeddings:
        # Fallback to loop (slower)
        for i in range(n):
            for j in range(i + 1, n):
                if 'embedding' in results[i] and 'embedding' in results[j]:
                    sim = cosine_similarity(results[i]['embedding'], results[j]['embedding'])
                elif 'content' in results[i] and 'content' in results[j]:
                    sim = text_similarity(results[i]['content'], results[j]['content'])
                else:
                    sim = 0.3
                
                similarity_matrix[i][j] = sim
                similarity_matrix[j][i] = sim
                
    # MMR Algorithm (Optimized)
    selected_indices = []
    remaining_indices = set(range(n))
    
    # Array to track max similarity of each candidate to ANY selected doc
    # Initialize with 0.0 (or -1.0)
    current_max_sim = np.zeros(n)
    
    # 1. Select first document (highest relevance)
    first_idx = np.argmax(relevance_scores)
    selected_indices.append(first_idx)
    remaining_indices.remove(first_idx)
    
    # Update max_sim for all docs against this first selection
    current_max_sim = np.maximum(current_max_sim, similarity_matrix[first_idx])
    
    # 2. Iteratively select remaining documents
    while len(selected_indices) < k and remaining_indices:
        best_mmr_score = -float('inf')
        best_idx = -1
        
        # We only check remaining indices
        # Optimization: convert to list for iteration or use numpy masking if n is large
        # For n=100, simple loop is fine.
        
        for idx in remaining_indices:
            # Relevance component
            relevance = relevance_scores[idx]
            
            # Diversity component (already updated in current_max_sim)
            max_sim = current_max_sim[idx]
            
            # MMR score
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
            
            if mmr_score > best_mmr_score:
                best_mmr_score = mmr_score
                best_idx = idx
        
        if best_idx == -1: break # Should not happen
        
        selected_indices.append(best_idx)
        remaining_indices.remove(best_idx)
        
        # 3. Update max similarities for next round
        # Update vector only against the NEWLY selected document
        current_max_sim = np.maximum(current_max_sim, similarity_matrix[best_idx])
    
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
