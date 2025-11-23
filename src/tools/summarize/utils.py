"""
Utility functions for summarization
Includes caching, validation, preprocessing, and helper functions
"""
import re
import hashlib
from typing import Optional, Dict, Any, List
from collections import OrderedDict
from .constants import (
    VALID_FORMATS, VALID_LENGTHS, MAX_CONTENT_LENGTH,
    CACHE_MAX_SIZE, HASH_LENGTH,
    TRUNCATION_BOUNDARY_THRESHOLD
)
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class SummaryCache:
    """Simple LRU-like cache for summaries"""
    
    def __init__(self, max_size: int = CACHE_MAX_SIZE):
        """
        Initialize cache
        
        Args:
            max_size: Maximum number of cached summaries
        """
        self.max_size = max_size
        self.cache: OrderedDict[str, str] = OrderedDict()
    
    def get(self, key: str) -> Optional[str]:
        """
        Get cached summary
        
        Args:
            key: Cache key
            
        Returns:
            Cached summary or None
        """
        if key in self.cache:
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            logger.debug(f"[CACHE HIT] {key}")
            return self.cache[key]
        
        logger.debug(f"[CACHE MISS] {key}")
        return None
    
    def set(self, key: str, value: str):
        """
        Cache a summary
        
        Args:
            key: Cache key
            value: Summary to cache
        """
        # Remove oldest if at capacity
        if len(self.cache) >= self.max_size:
            oldest_key = next(iter(self.cache))
            self.cache.pop(oldest_key)
            logger.debug(f"[CACHE EVICT] {oldest_key}")
        
        self.cache[key] = value
        self.cache.move_to_end(key)
        logger.debug(f"[CACHE SET] {key}")
    
    def clear(self):
        """Clear all cached summaries"""
        self.cache.clear()
        logger.debug("[CACHE CLEAR] All summaries cleared")
    
    def size(self) -> int:
        """Get current cache size"""
        return len(self.cache)


class InputValidator:
    """Validate summarization inputs"""
    
    @staticmethod
    def validate_content(content: str) -> tuple[bool, Optional[str]]:
        """
        Validate content input
        
        Args:
            content: Content to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not content:
            return False, "Content cannot be empty"
        
        if not content.strip():
            return False, "Content cannot be whitespace only"
        
        if len(content) > MAX_CONTENT_LENGTH:
            return False, f"Content too long ({len(content)} > {MAX_CONTENT_LENGTH} chars)"
        
        return True, None
    
    @staticmethod
    def validate_format(format_type: str) -> tuple[bool, Optional[str]]:
        """
        Validate format input
        
        Args:
            format_type: Format to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if format_type not in VALID_FORMATS:
            return False, f"Invalid format '{format_type}'. Must be one of: {', '.join(VALID_FORMATS)}"
        
        return True, None
    
    @staticmethod
    def validate_length(length: str) -> tuple[bool, Optional[str]]:
        """
        Validate length input
        
        Args:
            length: Length to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if length not in VALID_LENGTHS:
            return False, f"Invalid length '{length}'. Must be one of: {', '.join(VALID_LENGTHS)}"
        
        return True, None
    
    @staticmethod
    def validate_all(
        content: str,
        format_type: str,
        length: str
    ) -> tuple[bool, Optional[str]]:
        """
        Validate all inputs
        
        Args:
            content: Content to validate
            format_type: Format to validate
            length: Length to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Validate content
        is_valid, error = InputValidator.validate_content(content)
        if not is_valid:
            return False, error
        
        # Validate format
        is_valid, error = InputValidator.validate_format(format_type)
        if not is_valid:
            return False, error
        
        # Validate length
        is_valid, error = InputValidator.validate_length(length)
        if not is_valid:
            return False, error
        
        return True, None


class ContentPreprocessor:
    """Preprocess and clean content before summarization"""
    
    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean and normalize text
        
        Args:
            text: Text to clean
            
        Returns:
            Cleaned text
        """
        if not text:
            return ""
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove email artifacts
        text = re.sub(r'On .+ wrote:', '', text)
        text = re.sub(r'From:.*?Subject:', '', text, flags=re.DOTALL)
        
        # Remove URLs (optional - sometimes URLs are important)
        # text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
        
        # Remove multiple consecutive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()
    
    @staticmethod
    def extract_metadata(text: str) -> Dict[str, Any]:
        """
        Extract metadata from text (dates, emails, etc.)
        
        Args:
            text: Text to analyze
            
        Returns:
            Metadata dictionary
        """
        metadata = {}
        
        # Extract email addresses
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        if emails:
            metadata['emails'] = list(set(emails))
        
        # Extract dates (basic patterns)
        dates = re.findall(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', text)
        if dates:
            metadata['dates'] = list(set(dates))
        
        # Extract URLs
        urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', text)
        if urls:
            metadata['urls'] = list(set(urls))
        
        return metadata
    
    @staticmethod
    def truncate_content(text: str, max_length: int) -> str:
        """
        Truncate content to maximum length
        
        Args:
            text: Text to truncate
            max_length: Maximum length
            
        Returns:
            Truncated text
        """
        if len(text) <= max_length:
            return text
        
        # Try to truncate at sentence boundary
        truncated = text[:max_length]
        last_period = truncated.rfind('.')
        
        if last_period > max_length * TRUNCATION_BOUNDARY_THRESHOLD:
            return truncated[:last_period + 1]
        
        return truncated + "..."


def generate_cache_key(
    content: str,
    format_type: str,
    length: str,
    focus: Optional[str] = None
) -> str:
    """
    Generate cache key for content
    
    Args:
        content: Content to hash
        format_type: Summary format
        length: Summary length
        focus: Optional focus area
        
    Returns:
        Cache key (hash)
    """
    cache_str = f"{content}{format_type}{length}{focus or ''}"
    hash_obj = hashlib.sha256(cache_str.encode())
    return hash_obj.hexdigest()[:HASH_LENGTH]


def format_summary_output(
    summary: str,
    format_type: str,
    add_emoji: bool = True
) -> str:
    """
    Format summary output with appropriate styling
    
    Args:
        summary: Summary text
        format_type: Format type
        add_emoji: Whether to add emoji prefix
        
    Returns:
        Formatted summary
    """
    from .constants import FORMAT_EMOJIS, FORMAT_TITLES
    
    if add_emoji and format_type in FORMAT_EMOJIS:
        emoji = FORMAT_EMOJIS[format_type]
        title = FORMAT_TITLES.get(format_type, "Summary")
        return f"{emoji} {title}\n\n{summary}"
    
    return summary
