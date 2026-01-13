"""
Memory Utilities

Shared utility functions for the memory module.
Consolidates common logic to avoid duplication.
"""
import re
import numpy as np
from typing import List, Set, Optional, Dict, Any
from functools import lru_cache

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# =============================================================================
# ENTITY EXTRACTION
# =============================================================================

# Words to exclude from entity extraction (expanded)
EXCLUDED_ENTITIES: Set[str] = {
    # Pronouns
    "User", "The", "This", "That", "I", "We", "They", "My", "Your",
    "It", "He", "She", "You", "Their", "Our", "Its", "Me", "Him", "Her",
    # Common sentence starters
    "However", "Therefore", "Furthermore", "Moreover", "Although",
    "Because", "Since", "When", "Where", "What", "Which", "Who",
    "Please", "Thanks", "Thank", "Hello", "Hi", "Hey", "OK", "Yes", "No",
    # Time/Date words that get capitalized
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    # Common words often capitalized at sentence start
    "After", "Before", "During", "Also", "And", "But", "Or", "So", "Just",
    "Here", "There", "Now", "Today", "Tomorrow", "Yesterday",
}

# Organization patterns
ORG_PATTERNS = [
    r'\b([A-Z]{2,6})\b',  # Acronyms: IBM, NASA, USPS, FAANG
    r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Inc|Corp|Ltd|LLC|Co|Company|Group|Labs?)\b',  # Companies
]


def extract_entities(text: str) -> List[str]:
    """
    Extract named entities from text.
    
    Uses heuristics:
    - Capitalized multi-word names (excluding sentence starters)
    - Organization acronyms (2-6 uppercase letters)
    - Company names with suffixes (Inc, Corp, Ltd, etc.)
    
    Args:
        text: Input text to extract entities from
        
    Returns:
        List of unique entity strings
    """
    entities = []
    
    # Split into sentences to detect sentence-start capitalization
    sentences = re.split(r'[.!?]\s+', text)
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        # Pattern for capitalized names - skip first word of sentence if it's common
        # Match names NOT at sentence start
        name_pattern = r'(?<!^)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
        names = re.findall(name_pattern, sentence)
        
        for name in names:
            if name not in EXCLUDED_ENTITIES and len(name) > 2:
                entities.append(name)
        
        # Also check first word if it's a proper noun (multi-word or unusual)
        first_word_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', sentence)
        if first_word_match:
            name = first_word_match.group(1)
            if name not in EXCLUDED_ENTITIES:
                entities.append(name)
    
    # Extract organization patterns from full text
    for pattern in ORG_PATTERNS:
        matches = re.findall(pattern, text)
        for match in matches:
            # Filter out common acronyms that aren't organizations
            if match not in {"I", "A", "OK", "PM", "AM", "US", "UK"} and len(match) >= 2:
                entities.append(match)
    
    return list(set(entities))


def normalize_fact_content(content: str) -> str:
    """
    Normalize fact content for comparison.
    
    Removes extra whitespace and standardizes case.
    """
    return ' '.join(content.lower().split())


# =============================================================================
# EMBEDDING UTILITIES
# =============================================================================

_embedding_provider = None


def get_embedding_provider():
    """
    Get or create a sentence transformer embedding provider.
    
    Reuses the RAG module's provider for consistency.
    """
    global _embedding_provider
    
    if _embedding_provider is None:
        try:
            from src.ai.rag.core.embedding_provider import SentenceTransformerEmbeddingProvider
            
            # Use lightweight model for fact search
            _embedding_provider = SentenceTransformerEmbeddingProvider(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
            logger.info("[MemoryUtils] Initialized SentenceTransformer embedding provider")
        except Exception as e:
            logger.warning(f"[MemoryUtils] Failed to initialize embeddings: {e}")
            return None
    
    return _embedding_provider


def compute_embedding(text: str) -> Optional[List[float]]:
    """
    Compute embedding for a single text.
    
    Args:
        text: Text to embed
        
    Returns:
        List of floats (embedding vector) or None on failure
    """
    provider = get_embedding_provider()
    if provider is None:
        return None
    
    try:
        return provider.encode(text)
    except Exception as e:
        logger.warning(f"[MemoryUtils] Embedding failed: {e}")
        return None


def compute_batch_embeddings(texts: List[str]) -> Optional[List[List[float]]]:
    """
    Compute embeddings for multiple texts.
    
    Args:
        texts: List of texts to embed
        
    Returns:
        List of embedding vectors or None on failure
    """
    provider = get_embedding_provider()
    if provider is None:
        return None
    
    try:
        return provider.encode_batch(texts)
    except Exception as e:
        logger.warning(f"[MemoryUtils] Batch embedding failed: {e}")
        return None


def compute_similarity_scores(query: str, candidates: List[Dict[str, Any]], content_key: str = "content") -> List[float]:
    """
    Compute semantic similarity between query and candidate facts.
    
    Args:
        query: Query string
        candidates: List of fact dictionaries
        content_key: Key to extract content from candidates
        
    Returns:
        List of similarity scores (0-1) for each candidate
    """
    if not candidates:
        return []
    
    provider = get_embedding_provider()
    if provider is None:
        # Fallback to simple keyword overlap
        return _keyword_similarity_fallback(query, candidates, content_key)
    
    try:
        # Encode query
        query_embedding = np.array(provider.encode_query(query))
        
        # Encode all candidates
        candidate_texts = [c.get(content_key, "") for c in candidates]
        candidate_embeddings = np.array(provider.encode_batch(candidate_texts))
        
        # Compute cosine similarity
        query_norm = np.linalg.norm(query_embedding)
        if query_norm == 0:
            return [0.0] * len(candidates)
        
        similarities = []
        for emb in candidate_embeddings:
            emb_norm = np.linalg.norm(emb)
            if emb_norm == 0:
                similarities.append(0.0)
            else:
                sim = np.dot(query_embedding, emb) / (query_norm * emb_norm)
                similarities.append(float(max(0, min(1, sim))))  # Clamp to [0, 1]
        
        return similarities
        
    except Exception as e:
        logger.warning(f"[MemoryUtils] Similarity computation failed: {e}")
        return _keyword_similarity_fallback(query, candidates, content_key)


def _keyword_similarity_fallback(query: str, candidates: List[Dict[str, Any]], content_key: str) -> List[float]:
    """Fallback keyword-based similarity when embeddings unavailable."""
    query_words = set(query.lower().split())
    
    scores = []
    for candidate in candidates:
        content = candidate.get(content_key, "").lower()
        content_words = set(content.split())
        
        if not query_words or not content_words:
            scores.append(0.0)
            continue
        
        overlap = len(query_words & content_words)
        score = overlap / max(len(query_words), 1)
        scores.append(min(1.0, score))
    
    return scores

