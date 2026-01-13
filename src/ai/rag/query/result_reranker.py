"""
Advanced Result Reranking Module

Improves RAG accuracy by reranking search results using multiple signals.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from ....utils.logger import setup_logger
from .rules import URGENCY_SUBJECT_PATTERNS, IMPORTANCE_CONTENT_KEYWORDS, NOTIFICATION_SENDER_PATTERNS
from ..utils.utils import extract_keywords, calculate_keyword_score, deduplicate_results, parse_timestamp, calculate_semantic_score

logger = setup_logger(__name__)


class ResultReranker:
    """
    Advanced reranker for RAG results.
    
    Reranks search results based on a weighted combination of:
    - Semantic similarity (from vector search)
    - Keyword relevance (BM25 or alignment)
    - Metadata importance (sender, subject, folder)
    - Recency (time decay)
    - Content quality (length, structure)
    """
    
    def __init__(
        self,
        semantic_weight: float = 0.4,
        keyword_weight: float = 0.2,
        metadata_weight: float = 0.2,
        recency_weight: float = 0.2
    ):
        """
        Initialize reranker with weights.
        
        Args:
            semantic_weight: Importance of semantic similarity
            keyword_weight: Importance of keyword matching
            metadata_weight: Importance of metadata (people, subjects)
            recency_weight: Importance of time/recency
        """
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.metadata_weight = metadata_weight
        self.recency_weight = recency_weight
        
    def rerank(self, results: List[Dict[str, Any]], query: str, k: int = 10) -> List[Dict[str, Any]]:
        """
        Rerank results using multi-signal scoring.
        
        Args:
            results: Initial search results
            query: User query
            k: Number of results to return
            
        Returns:
            Reranked top-k results
        """
        if not results:
            return []
            
        logger.debug(f"Reranking {len(results)} results for query: '{query}'")
        
        query_lower = query.lower()
        scored_results = []
        
        for result in results:
            # 1. Base Scores (Semantic/BM25)
            # Normalize semantic score (usually 0-1, sometimes cosine dist)
            semantic_score = float(result.get('score', 0.0))
            if 'bm25_score' in result: 
                # Normalize BM25 if present (simple heuristic)
                bm25_score = min(1.0, float(result['bm25_score']) / 10.0) 
                # Combine if fusion
                base_score = (semantic_score * 0.7) + (bm25_score * 0.3)
            else:
                base_score = semantic_score
                
            # 2. Extract Data
            metadata = result.get('metadata', {})
            content = result.get('content', '') or metadata.get('content', '')
            
            # 3. Calculate Component Scores
            meta_score = self._metadata_score(query_lower, metadata, content)
            recency_score = self._recency_score(metadata)
            quality_score = self._quality_score(content)
            alignment_score = self._alignment_score(query_lower, content, metadata)
            
            # 4. Keyword Score (if not already handled by fusion)
            # If no explicit keyword score, alignment proxies for it
            keyword_score = alignment_score 

            # 5. Weighted Combination
            final_score = (
                (base_score * self.semantic_weight) +
                (keyword_score * self.keyword_weight) +
                (meta_score * self.metadata_weight) +
                (recency_score * self.recency_weight) +
                (quality_score * 0.1) # Small bonus for quality
            )
            
            # Add urgency boost (critical for "important" emails)
            urgency_boost = self.detect_content_urgency(
                metadata.get('subject', ''), 
                content, 
                metadata
            ) * 0.2
            final_score += urgency_boost
            
            # Create enriched result
            enriched_result = result.copy()
            enriched_result['rerank_score'] = final_score
            enriched_result['debug_scores'] = {
                'base': base_score,
                'metadata': meta_score,
                'recency': recency_score,
                'quality': quality_score,
                'urgency': urgency_boost
            }
            scored_results.append(enriched_result)
            
        # Sort by final score
        scored_results.sort(key=lambda x: x['rerank_score'], reverse=True)
        
        return scored_results[:k]

    @staticmethod
    def detect_content_urgency(subject: str, content: str, metadata: Dict[str, Any]) -> float:
        """
        Detect urgency/importance based on email content, not sender domain.
        
        Args:
            subject: Email subject line
            content: Email body content
            metadata: Email metadata (read status, important flag, etc.)
            
        Returns:
            Urgency score (0.0 to 1.0)
        """
        urgency_score = 0.0
        subject_lower = subject.lower() if subject else ''
        content_lower = content.lower() if content else ''
        combined_text = f"{subject_lower} {content_lower}"
        
        # Check subject line for urgency indicators
        subject_urgency_matches = sum(
            1 for pattern in URGENCY_SUBJECT_PATTERNS
            if pattern in subject_lower
        )
        if subject_urgency_matches > 0:
            # More matches = higher urgency
            urgency_score += min(0.4, subject_urgency_matches * 0.1)
        
        # Check content for importance keywords
        content_importance_matches = sum(
            1 for keyword in IMPORTANCE_CONTENT_KEYWORDS
            if keyword in combined_text
        )
        if content_importance_matches > 0:
            # More matches = higher importance
            urgency_score += min(0.3, content_importance_matches * 0.05)
        
        # Boost for unread emails (might be more urgent)
        if metadata.get('read', True) == False:
            urgency_score += 0.15
        
        # Boost for explicitly marked important/starred
        if metadata.get('important', False) or metadata.get('starred', False):
            urgency_score += 0.2
        
        # Boost for emails with attachments (might contain important documents)
        if metadata.get('has_attachments', False):
            urgency_score += 0.05
        
        # Boost for recent emails (within last 24 hours)
        timestamp = metadata.get('timestamp', '')
        if timestamp:
            email_date = parse_timestamp(timestamp)
            if email_date:
                now = datetime.now(timezone.utc)
                if email_date.tzinfo:
                    hours_old = (now - email_date).total_seconds() / 3600
                else:
                    # If email_date is naive, assume UTC or force it
                    hours_old = (now - email_date.replace(tzinfo=timezone.utc)).total_seconds() / 3600
                if hours_old < 24:
                    urgency_score += 0.1  # Recent emails might be more urgent
        
        return min(1.0, urgency_score)
    
    def _metadata_score(self, query_lower: str, metadata: Dict[str, Any], content: str = '') -> float:
        """
        Calculate metadata relevance score based on content.
        Uses content-based urgency detection to identify important emails.
        """
        score = 0.0
        query_terms = set(query_lower.split())
        
        # Check subject match
        subject = metadata.get('subject', '').lower()
        if subject:
             if any(term in subject for term in query_terms if len(term) > 3):
                 score += 0.3
        
        # Check sender match
        sender = metadata.get('sender', '').lower()
        if sender:
            if any(term in sender for term in query_terms if len(term) > 3):
                score += 0.2
        
        # Content-based urgency detection
        email_content = content or metadata.get('content', '') or ''
        urgency_score = self.detect_content_urgency(subject, email_content, metadata)
        
        # Boost based on content urgency
        if urgency_score > 0.3:
            score += urgency_score * 0.4
        
        # Check for notification patterns
        if sender:
            if any(pattern in sender for pattern in NOTIFICATION_SENDER_PATTERNS):
                score += 0.1
        
        # Check folder/label match
        folder = metadata.get('folder', '').lower()
        if folder:
             if any(term in folder for term in query_terms if len(term) > 3):
                 score += 0.1
        
        # Unread emails
        if metadata.get('read', True) == False:
            score += 0.15
        
        # Important/starred emails
        if metadata.get('important', False) or metadata.get('starred', False):
            score += 0.25
        
        return min(1.0, score)
    
    def _recency_score(self, metadata: Dict[str, Any]) -> float:
        """Calculate recency score with aggressive boosting for recent emails."""
        timestamp = metadata.get('timestamp', '')
        if not timestamp:
            return 0.3
        
        email_date = parse_timestamp(timestamp)
        if not email_date:
            return 0.3
        
        now = datetime.now(timezone.utc)
        if email_date.tzinfo:
            time_diff = now - email_date
        else:
            time_diff = now - email_date.replace(tzinfo=timezone.utc)
        
        days_old = time_diff.days
        hours_old = time_diff.total_seconds() / 3600
        
        if days_old < 0: return 1.0 
        elif hours_old < 1: return 1.0
        elif hours_old < 24: return 0.95
        elif days_old <= 3: return 0.9 - (days_old * 0.1 / 3)
        elif days_old <= 7: return 0.8 - ((days_old - 3) * 0.2 / 4)
        elif days_old <= 30: return 0.6 - ((days_old - 7) * 0.3 / 23)
        else: return max(0.1, 0.3 - ((days_old - 30) * 0.2 / 365))
    
    def _quality_score(self, content: str) -> float:
        """Calculate content quality score."""
        if not content: return 0.0
        score = 0.5
        
        word_count = len(content.split())
        if word_count > 50: score += 0.2
        elif word_count > 20: score += 0.1
        
        if '\n' in content or '•' in content: score += 0.1
        if '?' in content: score += 0.1
        
        return min(1.0, score)
    
    def _alignment_score(self, query_lower: str, content: str, metadata: Dict[str, Any]) -> float:
        """Calculate query-result alignment score (optimized)."""
        score = 0.0
        
        # Use sets for faster lookup
        query_terms = {t for t in query_lower.split() if len(t) > 2}
        if not query_terms:
            return 0.0
            
        content_lower = content.lower()
        
        # Count matches
        matches = sum(1 for term in query_terms if term in content_lower)
        score += (matches / len(query_terms)) * 0.5
        
        # Check subject alignment
        subject = metadata.get('subject', '').lower()
        if subject:
            subject_matches = sum(1 for term in query_terms if term in subject)
            score += (subject_matches / len(query_terms)) * 0.5
        
        return min(1.0, score)
    

