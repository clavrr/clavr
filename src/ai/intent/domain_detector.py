"""
Domain Detector - Centralized domain detection utility

This module provides a unified API for detecting query domains (email, calendar, task)
to avoid code duplication across parsers and analyzers.
"""
from typing import Dict, List, Set, Optional
from dataclasses import dataclass

from .config.intent_constants import (
    TASK_QUESTION_PATTERNS, TASK_CREATE_PATTERNS, TASK_LIST_PATTERNS, TASK_ANALYSIS_PATTERNS,
    CALENDAR_PATTERNS, CALENDAR_QUESTION_PATTERNS,
    EMAIL_PATTERNS, EMAIL_MANAGEMENT_PATTERNS,
    TASK_KEYWORDS, CALENDAR_KEYWORDS, EMAIL_KEYWORDS
)


@dataclass
class DomainResult:
    """Result of domain detection"""
    primary_domain: Optional[str]  # 'email', 'calendar', 'task', or None
    domains: List[str]  # All detected domains
    is_cross_domain: bool  # True if multiple domains detected
    confidence: float  # 0.0 to 1.0
    keyword_matches: Dict[str, List[str]]  # Matched keywords by domain


class DomainDetector:
    """
    Centralized domain detection utility.
    
    Detects whether a query is about email, calendar, or tasks using
    keyword matching and pattern detection.
    
    Example:
        detector = DomainDetector()
        result = detector.detect("what meetings do I have tomorrow?")
        # result.primary_domain == 'calendar'
    """
    
    # Domain keyword sets (using constants from intent_constants.py)
    TASK_KEYWORDS: Set[str] = set(TASK_KEYWORDS)
    CALENDAR_KEYWORDS: Set[str] = set(CALENDAR_KEYWORDS)
    EMAIL_KEYWORDS: Set[str] = set(EMAIL_KEYWORDS)
    
    # Pattern lists by domain
    TASK_PATTERNS: List[str] = (
        TASK_QUESTION_PATTERNS + TASK_CREATE_PATTERNS + 
        TASK_LIST_PATTERNS + TASK_ANALYSIS_PATTERNS
    )
    CALENDAR_ALL_PATTERNS: List[str] = CALENDAR_PATTERNS + CALENDAR_QUESTION_PATTERNS
    EMAIL_ALL_PATTERNS: List[str] = EMAIL_PATTERNS + EMAIL_MANAGEMENT_PATTERNS
    
    def detect(self, query: str) -> DomainResult:
        """
        Detect the domain(s) of a query.
        
        Args:
            query: User query string
            
        Returns:
            DomainResult with detected domain information
        """
        query_lower = query.lower()
        domains = []
        keyword_matches: Dict[str, List[str]] = {}
        
        # Check each domain
        task_matches = self._check_domain(query_lower, 'task')
        calendar_matches = self._check_domain(query_lower, 'calendar')
        email_matches = self._check_domain(query_lower, 'email')
        
        if task_matches:
            domains.append('task')
            keyword_matches['task'] = task_matches
            
        if calendar_matches:
            domains.append('calendar')
            keyword_matches['calendar'] = calendar_matches
            
        if email_matches:
            domains.append('email')
            keyword_matches['email'] = email_matches
        
        # Determine primary domain (most matches wins, with priority order)
        primary = self._determine_primary(domains, keyword_matches)
        
        # Calculate confidence
        confidence = self._calculate_confidence(keyword_matches, primary)
        
        return DomainResult(
            primary_domain=primary,
            domains=domains,
            is_cross_domain=len(domains) > 1,
            confidence=confidence,
            keyword_matches=keyword_matches
        )
    
    def _check_domain(self, query_lower: str, domain: str) -> List[str]:
        """Check if query matches a specific domain"""
        matches = []
        
        if domain == 'task':
            # Check keywords
            for kw in self.TASK_KEYWORDS:
                if kw in query_lower:
                    matches.append(kw)
            # Check patterns
            for pattern in self.TASK_PATTERNS:
                if pattern in query_lower and pattern not in matches:
                    matches.append(pattern)
                    
        elif domain == 'calendar':
            for kw in self.CALENDAR_KEYWORDS:
                if kw in query_lower:
                    matches.append(kw)
            for pattern in self.CALENDAR_ALL_PATTERNS:
                if pattern in query_lower and pattern not in matches:
                    matches.append(pattern)
                    
        elif domain == 'email':
            for kw in self.EMAIL_KEYWORDS:
                if kw in query_lower:
                    matches.append(kw)
            for pattern in self.EMAIL_ALL_PATTERNS:
                if pattern in query_lower and pattern not in matches:
                    matches.append(pattern)
        
        return matches
    
    def _determine_primary(self, domains: List[str], 
                          keyword_matches: Dict[str, List[str]]) -> Optional[str]:
        """Determine the primary domain based on match count and priority"""
        if not domains:
            return None
            
        if len(domains) == 1:
            return domains[0]
        
        # Multiple domains - pick the one with most matches
        # Priority order for ties: task > calendar > email
        priority_order = ['task', 'calendar', 'email']
        
        max_matches = 0
        primary = None
        
        for domain in priority_order:
            if domain in keyword_matches:
                count = len(keyword_matches[domain])
                if count > max_matches:
                    max_matches = count
                    primary = domain
        
        return primary
    
    def _calculate_confidence(self, keyword_matches: Dict[str, List[str]], 
                             primary: Optional[str]) -> float:
        """Calculate confidence score based on matches"""
        if not primary or primary not in keyword_matches:
            return 0.0
        
        primary_count = len(keyword_matches[primary])
        
        # Base confidence from match count
        if primary_count >= 3:
            confidence = 0.9
        elif primary_count == 2:
            confidence = 0.75
        elif primary_count == 1:
            confidence = 0.5
        else:
            confidence = 0.3
        
        # Reduce confidence if cross-domain
        if len(keyword_matches) > 1:
            confidence *= 0.85
        
        return min(1.0, confidence)
    
    def is_domain(self, query: str, domain: str) -> bool:
        """
        Check if query belongs to a specific domain.
        
        Args:
            query: User query
            domain: Domain to check ('email', 'calendar', 'task')
            
        Returns:
            True if query is primarily about the specified domain
        """
        result = self.detect(query)
        return result.primary_domain == domain
    
    def should_reject_from_domain(self, query: str, current_domain: str) -> bool:
        """
        Check if a query should be rejected from a parser based on domain mismatch.
        
        This is useful for parsers to quickly reject queries that don't belong to them.
        
        Args:
            query: User query
            current_domain: The domain of the parser ('email', 'calendar', 'task')
            
        Returns:
            True if the query should be rejected (belongs to a different domain)
        """
        result = self.detect(query)
        
        # If no clear domain or matches current, don't reject
        if not result.primary_domain or result.primary_domain == current_domain:
            return False
        
        # If current domain is in the detected domains, don't reject
        if current_domain in result.domains:
            return False
        
        # Query belongs to a different domain - reject
        return result.confidence > 0.5


# Singleton instance for convenience
_detector_instance: Optional[DomainDetector] = None


def get_domain_detector() -> DomainDetector:
    """Get singleton DomainDetector instance"""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = DomainDetector()
    return _detector_instance


def detect_domain(query: str) -> DomainResult:
    """Convenience function to detect query domain"""
    return get_domain_detector().detect(query)
