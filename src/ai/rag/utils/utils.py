"""
RAG Utilities - Shared helper functions for RAG operations

Consolidates common functionality to avoid duplication across RAG modules.
"""
import re
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


# Common stopwords for keyword extraction
_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have',
    'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could',
    'may', 'might', 'must', 'can'
}


def extract_keywords(query: str, max_keywords: int = 10) -> List[str]:
    """
    Extract meaningful keywords from a query.
    
    Args:
        query: Query string
        max_keywords: Maximum number of keywords to return
        
    Returns:
        List of extracted keywords
    """
    words = re.findall(r'\b\w+\b', query.lower())
    keywords = [w for w in words if w not in _STOPWORDS and len(w) > 2]
    return keywords[:max_keywords]


def calculate_keyword_score(content: str, keywords: List[str]) -> float:
    """
    Calculate keyword match score for content.
    
    Args:
        content: Content to score
        keywords: List of keywords to match
        
    Returns:
        Keyword match score (0.0 to 1.0)
    """
    if not keywords:
        return 0.0
    
    content_lower = content.lower()
    matches = sum(1 for kw in keywords if kw in content_lower)
    return matches / len(keywords) if keywords else 0.0


def deduplicate_results(results: List[Dict[str, Any]], 
                        use_content_hash: bool = False) -> List[Dict[str, Any]]:
    """
    Remove duplicate results based on document ID, subject, and content.
    
    Args:
        results: List of result dictionaries
        use_content_hash: If True, use content hash for deduplication (more aggressive)
        
    Returns:
        Deduplicated list of results
    """
    seen = set()
    deduplicated = []
    
    for result in results:
        doc_id = result.get('id') or result.get('metadata', {}).get('email_id', '')
        subject = result.get('metadata', {}).get('subject', '')
        content = result.get('content', '')
        
        if use_content_hash:
            # More aggressive deduplication using content hash
            content_hash = hashlib.md5(content[:200].encode()).hexdigest()
            signature = f"{doc_id}|{subject}|{content_hash}"
        else:
            # Standard deduplication
            signature = f"{doc_id}|{subject}|{hash(content[:100])}"
        
        if signature not in seen:
            seen.add(signature)
            deduplicated.append(result)
    
    return deduplicated


def parse_timestamp(timestamp: str) -> Optional[datetime]:
    """
    Parse timestamp string with multiple fallback strategies.
    
    Args:
        timestamp: Timestamp string in various formats
        
    Returns:
        Parsed datetime object or None if parsing fails
    """
    if not timestamp:
        return None
    
    # Try dateutil parser first (most flexible)
    try:
        from dateutil import parser
        return parser.parse(timestamp)
    except ImportError:
        pass
    except Exception:
        pass
    
    # Fallback to ISO format
    try:
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except Exception:
        pass
    
    # Fallback to common format
    try:
        return datetime.strptime(timestamp[:19], '%Y-%m-%dT%H:%M:%S')
    except Exception:
        pass
    
    logger.debug(f"Failed to parse timestamp: {timestamp}")
    return None


def calculate_semantic_score(distance: float) -> float:
    """
    Convert distance to semantic similarity score (0.0 to 1.0).
    
    Args:
        distance: Vector distance
        
    Returns:
        Normalized similarity score
    """
    if distance <= 1.0:
        return max(0.0, 1.0 - distance)
    else:
        return 1.0 / (1.0 + distance)

