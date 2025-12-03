"""
Advanced Result Reranking Module

Improves RAG accuracy by reranking search results using multiple signals.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime

from ....utils.logger import setup_logger
from ..utils.utils import extract_keywords, calculate_keyword_score, deduplicate_results, parse_timestamp, calculate_semantic_score

logger = setup_logger(__name__)


class ResultReranker:
    """
    Advanced reranker for RAG results.
    
    Uses multiple signals:
    - Semantic similarity
    - Keyword matching
    - Metadata relevance
    - Recency
    - Content quality
    - Query-result alignment
    """
    
    def __init__(self, 
                 semantic_weight: float = 0.4,
                 keyword_weight: float = 0.2,
                 metadata_weight: float = 0.2,
                 recency_weight: float = 0.2):
        """
        Initialize reranker.
        
        Args:
            semantic_weight: Weight for semantic similarity (0-1)
            keyword_weight: Weight for keyword matching (0-1)
            metadata_weight: Weight for metadata relevance (0-1)
            recency_weight: Weight for recency boost (0-1)
        """
        # Normalize weights
        total = semantic_weight + keyword_weight + metadata_weight + recency_weight
        self.semantic_weight = semantic_weight / total
        self.keyword_weight = keyword_weight / total
        self.metadata_weight = metadata_weight / total
        self.recency_weight = recency_weight / total
    
    def rerank(self, query: str, results: List[Dict[str, Any]], 
               query_keywords: Optional[List[str]] = None,
               k: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Rerank search results.
        
        Args:
            query: Original query
            results: Search results to rerank
            query_keywords: Optional pre-extracted keywords
            k: Number of results to return
            
        Returns:
            Reranked results
        """
        if not results:
            return []
        
        k = k or len(results)
        query_lower = query.lower()
        
        # Extract keywords if not provided
        if query_keywords is None:
            query_keywords = extract_keywords(query)
        
        # Score each result
        scored_results = []
        for result in results:
            score = self._calculate_score(query, query_lower, query_keywords, result)
            result['rerank_score'] = score
            scored_results.append(result)
        
        # Sort by score (descending)
        scored_results.sort(key=lambda x: x.get('rerank_score', 0), reverse=True)
        
        # Deduplicate (use content hash for more aggressive deduplication)
        deduplicated = deduplicate_results(scored_results, use_content_hash=True)
        
        return deduplicated[:k]
    
    def _calculate_score(self, query: str, query_lower: str, 
                        keywords: List[str], result: Dict[str, Any]) -> float:
        """Calculate comprehensive relevance score."""
        content = result.get('content', '')
        metadata = result.get('metadata', {})
        distance = result.get('distance', 1.0)
        
        # 1. Semantic score (from vector similarity)
        semantic_score = self._semantic_score(distance)
        
        # 2. Keyword score
        keyword_score = self._keyword_score(content, keywords)
        
        # 3. Metadata score (pass content for content-based urgency detection)
        metadata_score = self._metadata_score(query_lower, metadata, content)
        
        # 4. Recency score
        recency_score = self._recency_score(metadata)
        
        # 5. Content quality score
        quality_score = self._quality_score(content)
        
        # 6. Query-result alignment
        alignment_score = self._alignment_score(query_lower, content, metadata)
        
        # Weighted combination
        final_score = (
            self.semantic_weight * semantic_score +
            self.keyword_weight * keyword_score +
            self.metadata_weight * metadata_score +
            self.recency_weight * recency_score +
            0.05 * quality_score +  # Small weight for quality
            0.05 * alignment_score  # Small weight for alignment
        )
        
        return final_score
    
    def _semantic_score(self, distance: float) -> float:
        """Convert distance to similarity score."""
        return calculate_semantic_score(distance)
    
    def _keyword_score(self, content: str, keywords: List[str]) -> float:
        """Calculate keyword match score with enhanced matching."""
        if not keywords:
            return 0.0
        
        content_lower = content.lower()
        
        # Exact matches
        exact_matches = sum(1 for kw in keywords if kw.lower() in content_lower)
        
        # Partial matches (substring)
        partial_matches = sum(1 for kw in keywords 
                            if any(kw.lower() in word for word in content_lower.split()))
        
        # Weight exact matches higher
        score = (exact_matches * 1.0 + partial_matches * 0.5) / len(keywords)
        
        return min(1.0, score)
    
    def _metadata_score(self, query_lower: str, metadata: Dict[str, Any], content: str = '') -> float:
        """
        Calculate metadata relevance score based on content, not hardcoded sender domains.
        Uses content-based urgency detection to identify important emails from any sender.
        
        Args:
            query_lower: Lowercase query string
            metadata: Email metadata dictionary
            content: Email content (passed separately as it may not be in metadata)
        """
        score = 0.0
        
        # Check subject match
        subject = metadata.get('subject', '').lower()
        if subject and any(kw in subject for kw in query_lower.split() if len(kw) > 3):
            score += 0.3
        
        # Check sender match (for queries like "emails from John")
        sender = metadata.get('sender', '').lower()
        sender_domain = metadata.get('sender_domain', '').lower()
        
        if sender and any(kw in sender for kw in query_lower.split() if len(kw) > 3):
            score += 0.2
        
        # Content-based urgency detection (not domain-based)
        # This works for ANY sender - friends, professors, colleagues, etc.
        from .query_enhancer import QueryEnhancer
        email_content = content or metadata.get('content', '') or ''
        urgency_score = QueryEnhancer.detect_content_urgency(subject, email_content, metadata)
        
        # Boost based on content urgency (works for all senders)
        if urgency_score > 0.3:  # Moderate to high urgency
            score += urgency_score * 0.4  # Significant boost for urgent content
        
        # Check for notification patterns in sender (not specific domains)
        # These patterns indicate automated/notification emails regardless of company
        if sender:
            notification_patterns = {'noreply', 'no-reply', 'notifications', 'alerts', 
                                   'notify', 'automated', 'system', 'do-not-reply'}
            if any(pattern in sender.lower() for pattern in notification_patterns):
                # These might be important notifications, but not necessarily urgent
                score += 0.1
        
        # Check folder/label match
        folder = metadata.get('folder', '').lower()
        if folder and any(kw in folder for kw in query_lower.split() if len(kw) > 3):
            score += 0.1
        
        # Unread emails might be more relevant
        if metadata.get('read', True) == False:
            score += 0.15
        
        # Important/starred emails (explicitly marked by user)
        if metadata.get('important', False) or metadata.get('starred', False):
            score += 0.25
        
        return min(1.0, score)
    
    def _recency_score(self, metadata: Dict[str, Any]) -> float:
        """Calculate recency score with aggressive boosting for recent emails."""
        timestamp = metadata.get('timestamp', '')
        if not timestamp:
            return 0.3  # Lower score if no timestamp (not recent)
        
        # Parse timestamp using shared utility
        email_date = parse_timestamp(timestamp)
        if not email_date:
            return 0.3  # Lower score if parsing fails
        
        # Calculate time difference
        if email_date.tzinfo:
            time_diff = datetime.now(email_date.tzinfo) - email_date
        else:
            time_diff = datetime.now() - email_date.replace(tzinfo=None)
        
        days_old = time_diff.days
        hours_old = time_diff.total_seconds() / 3600
        
        # More aggressive recency scoring
        # Emails from last hour = 1.0, today = 0.95, this week = 0.8+, this month = 0.5+
        if days_old < 0:
            return 1.0  # Future dates (shouldn't happen)
        elif hours_old < 1:
            return 1.0  # Last hour
        elif hours_old < 24:
            return 0.95  # Today
        elif days_old <= 3:
            return 0.9 - (days_old * 0.1 / 3)  # Last 3 days
        elif days_old <= 7:
            return 0.8 - ((days_old - 3) * 0.2 / 4)  # This week
        elif days_old <= 30:
            return 0.6 - ((days_old - 7) * 0.3 / 23)  # This month
        else:
            return max(0.1, 0.3 - ((days_old - 30) * 0.2 / 365))  # Older
    
    def _quality_score(self, content: str) -> float:
        """Calculate content quality score."""
        if not content:
            return 0.0
        
        score = 0.5  # Base score
        
        # Longer content might be more informative
        word_count = len(content.split())
        if word_count > 50:
            score += 0.2
        elif word_count > 20:
            score += 0.1
        
        # Check for structured content (lists, questions, etc.)
        if '\n' in content or '•' in content or '-' in content[:100]:
            score += 0.1
        
        # Check for questions (might indicate important content)
        if '?' in content:
            score += 0.1
        
        return min(1.0, score)
    
    def _alignment_score(self, query_lower: str, content: str, metadata: Dict[str, Any]) -> float:
        """Calculate query-result alignment score."""
        score = 0.0
        
        # Check if query terms appear in content
        query_terms = [t for t in query_lower.split() if len(t) > 2]
        content_lower = content.lower()
        
        matches = sum(1 for term in query_terms if term in content_lower)
        if query_terms:
            score += (matches / len(query_terms)) * 0.5
        
        # Check subject alignment
        subject = metadata.get('subject', '').lower()
        if subject:
            subject_matches = sum(1 for term in query_terms if term in subject)
            if query_terms:
                score += (subject_matches / len(query_terms)) * 0.5
        
        return min(1.0, score)
    

