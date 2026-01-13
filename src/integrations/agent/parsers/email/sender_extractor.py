"""
Sender Extractor - Intelligently extracts sender names/emails from natural language queries

This module extracts sender information from queries like:
- "emails from John"
- "messages sent by Sarah Johnson"
- "find vicky's emails"
- "email from john@example.com"

Uses regex patterns for fast extraction with optional LLM fallback for complex cases.
"""
import re
from typing import Optional, Any
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class SenderExtractor:
    """
    Intelligent sender extractor for email search queries.
    
    Extracts sender names or email addresses from natural language queries
    using pattern matching and optional LLM support for complex cases.
    """
    
    # Patterns for extracting sender from query (ordered by specificity)
    SENDER_PATTERNS = [
        # Email address patterns
        r"from\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        r"by\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        
        # Name patterns with "from"
        r"(?:emails?|messages?|mail)\s+from\s+([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+)*)",
        r"from\s+([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+)*)",
        
        # Name patterns with "by"
        r"(?:sent|written|received)\s+by\s+([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+)*)",
        
        # Possessive patterns
        r"([A-Z][a-zA-Z\-\']+(?:\s+[A-Z][a-zA-Z\-\']+)*)(?:'s|s')\s+(?:emails?|messages?|mail)",
        
        # Simple lowercase patterns (fallback)
        r"(?:emails?|messages?)\s+from\s+([a-zA-Z][a-zA-Z\-\']+(?:\s+[a-zA-Z][a-zA-Z\-\']+)*)",
        r"from\s+([a-zA-Z][a-zA-Z\-\']+)",
    ]
    
    # Words that should not be extracted as sender names
    STOP_WORDS = {
        'me', 'you', 'them', 'us', 'myself', 'yourself',
        'today', 'yesterday', 'tomorrow', 'last', 'next',
        'week', 'month', 'year', 'day', 'morning', 'afternoon', 'evening',
        'inbox', 'sent', 'drafts', 'trash', 'spam', 'archive',
        'about', 'regarding', 'concerning', 'with', 'subject',
        'email', 'emails', 'mail', 'message', 'messages',
        'new', 'unread', 'read', 'important', 'starred',
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at',
    }
    
    def __init__(self, email_parser: Optional[Any] = None):
        """
        Initialize sender extractor.
        
        Args:
            email_parser: Optional parser with LLM client for complex extraction
        """
        self.email_parser = email_parser
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.SENDER_PATTERNS]
    
    def extract_sender(self, query: str) -> Optional[str]:
        """
        Extract sender name or email from a natural language query.
        
        Args:
            query: Natural language query like "emails from John"
            
        Returns:
            Extracted sender name/email or None if not found
        """
        if not query or len(query.strip()) < 3:
            return None
        
        query = query.strip()
        
        # Try regex patterns first (fast path)
        extracted = self._extract_with_patterns(query)
        if extracted:
            return extracted
        
        # Try LLM fallback for complex cases (if available)
        if self.email_parser and hasattr(self.email_parser, 'llm_client') and self.email_parser.llm_client:
            try:
                extracted = self._extract_with_llm(query)
                if extracted:
                    return extracted
            except Exception as e:
                logger.debug(f"LLM sender extraction failed: {e}")
        
        return None
    
    def _extract_with_patterns(self, query: str) -> Optional[str]:
        """
        Extract sender using regex patterns.
        
        Args:
            query: The search query
            
        Returns:
            Extracted sender or None
        """
        for pattern in self._compiled_patterns:
            match = pattern.search(query)
            if match:
                candidate = match.group(1).strip()
                
                # Validate the candidate
                if self._is_valid_sender(candidate):
                    logger.debug(f"[SenderExtractor] Pattern matched: '{candidate}' from query '{query}'")
                    return candidate
        
        return None
    
    def _is_valid_sender(self, candidate: str) -> bool:
        """
        Validate that a candidate is actually a sender name/email.
        
        Args:
            candidate: Potential sender string
            
        Returns:
            True if valid sender, False otherwise
        """
        if not candidate or len(candidate) < 2:
            return False
        
        # Check if it's an email address (always valid)
        if '@' in candidate and '.' in candidate:
            return True
        
        # Check against stop words
        candidate_lower = candidate.lower()
        if candidate_lower in self.STOP_WORDS:
            return False
        
        # Check each word in multi-word names
        words = candidate_lower.split()
        if all(word in self.STOP_WORDS for word in words):
            return False
        
        # Must contain at least one letter
        if not any(c.isalpha() for c in candidate):
            return False
        
        # Reasonable length check
        if len(candidate) > 100:
            return False
        
        return True
    
    def _extract_with_llm(self, query: str) -> Optional[str]:
        """
        Use LLM to extract sender from complex queries.
        
        Args:
            query: The search query
            
        Returns:
            Extracted sender or None
        """
        prompt = f"""Extract the sender's name or email address from this email search query.
If no sender is mentioned, respond with "NONE".
Only extract the name/email, nothing else.

Query: "{query}"

Sender:"""
        
        try:
            response = self.email_parser.llm_client.generate(prompt)
            if response and isinstance(response, str):
                result = response.strip().strip('"').strip("'")
                if result.upper() != "NONE" and len(result) > 1:
                    return result
        except Exception as e:
            logger.debug(f"LLM extraction error: {e}")
        
        return None
    
    def extract_all_entities(self, query: str) -> dict:
        """
        Extract multiple entities from query: sender, subject keywords, date hints.
        
        Args:
            query: Natural language query
            
        Returns:
            Dict with extracted entities
        """
        entities = {
            'sender': None,
            'subject_keywords': [],
            'has_date_reference': False,
            'is_unread_request': False,
        }
        
        # Extract sender
        entities['sender'] = self.extract_sender(query)
        
        query_lower = query.lower()
        
        # Check for unread/new request
        if any(word in query_lower.split() for word in ['new', 'unread', 'recent']):
            entities['is_unread_request'] = True
        
        # Check for date references
        date_words = ['today', 'yesterday', 'week', 'month', 'last', 'recent', 'latest']
        if any(word in query_lower for word in date_words):
            entities['has_date_reference'] = True
        
        # Extract potential subject keywords (words that aren't part of the structure)
        structure_words = self.STOP_WORDS | {'from', 'sent', 'by', 'find', 'show', 'get', 'search'}
        words = query_lower.split()
        for word in words:
            if word not in structure_words and len(word) > 3:
                entities['subject_keywords'].append(word)
        
        return entities
