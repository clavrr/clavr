"""
Email Sender Extractor - Unified sender extraction logic

This module provides centralized sender extraction to eliminate duplication
across handlers. Used by classification, search, and utility handlers.

Usage:
    from .sender_extractor import SenderExtractor
    
    extractor = SenderExtractor(email_parser)
    senders = extractor.extract_senders_from_query("emails from John Smith")
"""

import re
from typing import List, Optional
from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class SenderExtractor:
    """Unified sender extraction logic"""
    
    def __init__(self, email_parser=None):
        """
        Initialize sender extractor
        
        Args:
            email_parser: Reference to parent EmailParser (optional)
        """
        self.email_parser = email_parser
    
    def extract_sender(self, query: str) -> Optional[str]:
        """
        Extract a single sender from query
        
        Args:
            query: User query
            
        Returns:
            Extracted sender email or name, or None
        """
        senders = self.extract_senders(query)
        return senders[0] if senders else None
    
    def extract_senders(self, query: str) -> List[str]:
        """
        Extract all senders from query using LLM-based semantic understanding
        
        Handles:
        - Single sender: "from John Smith", "from boss", "from my manager"
        - Multiple senders with 'or': "from John or Sarah or Mike"
        - Email addresses: "from john@example.com"
        - Mixed formats: "from john@example.com or Sarah"
        - Semantic references: "from boss" = "from [user's boss name]"
        
        Args:
            query: User query
            
        Returns:
            List of extracted senders
        """
        # PRIORITY 1: Use LLM for semantic extraction (handles synonyms, context, etc.)
        if self.email_parser and hasattr(self.email_parser, 'llm_client') and self.email_parser.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                import json
                import re
                
                prompt = f"""Extract sender names/emails from this email query. Understand semantic meaning, not just literal words.

Query: "{query}"

Examples:
- "emails from boss" → extract "boss" (user might mean their manager's name)
- "from John Smith" → extract "John Smith"
- "from john@example.com" → extract "john@example.com"
- "from my manager" → extract "manager" (or try to resolve to actual name if possible)
- "from the first one" → null (not a sender reference)

Extract ALL senders mentioned. If query says "from X or Y", extract both.

Respond with ONLY valid JSON:
{{
    "senders": ["sender1", "sender2", ...],
    "confidence": 0.0-1.0
}}"""

                response = self.email_parser.llm_client.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    llm_senders = result.get('senders', [])
                    confidence = result.get('confidence', 0.7)
                    
                    if llm_senders and confidence >= 0.7:
                        # Filter out invalid senders
                        valid_senders = [s for s in llm_senders if self.validate_sender(s)]
                        if valid_senders:
                            logger.info(f"[EMAIL] LLM extracted senders: {valid_senders} (confidence: {confidence})")
                            return valid_senders
            except Exception as e:
                logger.debug(f"[EMAIL] LLM sender extraction failed, using patterns: {e}")
        
        # FALLBACK: Pattern-based extraction
        query_lower = query.lower()
        senders = []
        
        # Pattern 1: "from X" where X can be multiple values with "or"
        # CRITICAL: Include common verbs/auxiliary words as stop words to prevent false matches
        from_match = re.search(r'from\s+(.+?)(?:\s+(?:about|regarding|that|email|emails|messages|subject|with|do|does|did|have|has|had|are|were|was|is|get|got|new|recent|\?|$))', query, re.IGNORECASE)
        if from_match:
            sender_text = from_match.group(1).strip()
            # Split by "or" to handle multiple senders
            if ' or ' in sender_text.lower():
                senders = self._split_senders_by_or(sender_text)
            else:
                # Single sender - clean it up
                sender = self._clean_sender(sender_text)
                if sender:
                    senders.append(sender)
        
        # Pattern 2: Explicit email addresses
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, query)
        if emails and not senders:
            senders.extend(emails)
        
        # Pattern 3: "when was the last time...from [sender]"
        if not senders and 'when was the last time' in query_lower:
            time_from_match = re.search(r'when was the last time.*?from\s+([^\s?]+(?:\s+[^\s?]+)?)', query, re.IGNORECASE)
            if time_from_match:
                sender = self._clean_sender(time_from_match.group(1))
                if sender:
                    senders.append(sender)
        
        # Remove duplicates and empty values
        senders = list(dict.fromkeys(filter(None, senders)))
        
        logger.debug(f"Extracted {len(senders)} senders from query: {senders}")
        return senders
    
    def _split_senders_by_or(self, sender_text: str) -> List[str]:
        """
        Split sender text by "or" and clean each sender
        
        Args:
            sender_text: Sender text with "or" separators
            
        Returns:
            List of cleaned senders
        """
        senders = []
        # Split by "or" (case-insensitive)
        parts = re.split(r'\s+or\s+', sender_text, flags=re.IGNORECASE)
        
        for part in parts:
            sender = self._clean_sender(part)
            if sender:
                senders.append(sender)
        
        return senders
    
    def _clean_sender(self, sender_text: str) -> Optional[str]:
        """
        Clean and validate sender text
        
        Args:
            sender_text: Raw sender text
            
        Returns:
            Cleaned sender, or None if invalid
        """
        sender = sender_text.strip()
        
        # Remove trailing punctuation
        sender = sender.rstrip('?.;,!\'\"')
        
        # Remove question words and function words that might have been captured
        skip_patterns = [
            r'^(what|about|did|does|do|when|where|why|how|the|my|me|i|was|were|is|are|have|has|had|been|being|get|got|new|recent)',
            r'(what|about|did|does|do|when|where|why|how|the|my|me|i|was|were|is|are|have|has|had|been|being|get|got|new|recent)$',
        ]
        
        for pattern in skip_patterns:
            sender = re.sub(pattern, '', sender, flags=re.IGNORECASE).strip()
        
        # Must have at least 2 characters
        if len(sender) < 2:
            return None
        
        # Skip if it's just a common word or common verb/auxiliary word
        common_words = {'and', 'or', 'the', 'to', 'from', 'email', 'message', 'do', 'does', 'did', 'have', 'has', 'had', 'are', 'were', 'was', 'is', 'get', 'got', 'new', 'recent'}
        if sender.lower() in common_words:
            return None
        
        # Skip if sender is a combination of only common verbs/auxiliary words
        sender_words = sender.lower().split()
        common_verbs = {'do', 'does', 'did', 'have', 'has', 'had', 'are', 'were', 'was', 'is', 'get', 'got', 'what', 'about', 'the', 'my', 'me', 'i', 'when', 'where', 'why', 'how', 'new', 'recent'}
        if all(word in common_verbs for word in sender_words):
            return None
        
        # Validate: must be email OR have at least one letter
        if not re.search(r'@', sender) and not re.search(r'[a-zA-Z]', sender):
            return None
        
        return sender
    
    def extract_senders_from_or_query(self, query: str) -> List[str]:
        """
        Extract senders from "or" queries
        
        Specialized handler for queries like:
        - "from Amex Recruiting or American Express"
        - "emails from John or Sarah or Mike"
        
        Args:
            query: User query containing "or"
            
        Returns:
            List of extracted senders
        """
        if ' or ' not in query.lower():
            return []
        
        # Look for pattern "from X or Y"
        or_pattern = r'from\s+([^?]+?)(?:\s*\?|$)'
        or_match = re.search(or_pattern, query, re.IGNORECASE)
        
        if not or_match:
            return []
        
        sender_text = or_match.group(1).strip()
        return self._split_senders_by_or(sender_text)
    
    def validate_sender(self, sender: str) -> bool:
        """
        Validate if sender is a valid email or name
        
        Args:
            sender: Sender email or name
            
        Returns:
            True if valid sender
        """
        if not sender or len(sender) < 2:
            return False
        
        # Valid if it's an email address
        if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', sender):
            return True
        
        # Valid if it's a name (at least 2 letters)
        if re.search(r'[a-zA-Z]{2,}', sender):
            return True
        
        return False
    
    def normalize_sender(self, sender: str) -> str:
        """
        Normalize sender for comparison
        
        Args:
            sender: Sender email or name
            
        Returns:
            Normalized sender
        """
        # Convert to lowercase for comparison
        normalized = sender.lower().strip()
        
        # Remove extra whitespace
        normalized = ' '.join(normalized.split())
        
        return normalized
    
    def senders_match(self, sender1: str, sender2: str) -> bool:
        """
        Check if two senders refer to the same person
        
        Args:
            sender1: First sender
            sender2: Second sender
            
        Returns:
            True if senders match
        """
        norm1 = self.normalize_sender(sender1)
        norm2 = self.normalize_sender(sender2)
        
        # Exact match
        if norm1 == norm2:
            return True
        
        # Email match (extract domain-less part)
        email_part1 = re.sub(r'@.*$', '', norm1)
        email_part2 = re.sub(r'@.*$', '', norm2)
        if email_part1 and email_part2 and email_part1 == email_part2:
            return True
        
        # Name substring match (for cases like "John Smith" vs "John")
        if len(norm1) > 3 and len(norm2) > 3:
            if norm1 in norm2 or norm2 in norm1:
                return True
        
        return False
