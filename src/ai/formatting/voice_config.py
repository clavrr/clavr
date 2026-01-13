"""
Voice Formatting Configuration

Centralizes all configuration constants for voice output formatting,
eliminating hardcoded values in voice_formatter.py.

Usage:
    from .voice_config import VoiceConfig
    
    max_len = VoiceConfig.DEFAULT_MAX_LENGTH
    connectors = VoiceConfig.LIST_CONNECTORS
"""

from typing import List, Dict, Pattern
import re


class VoiceConfig:
    """
    Configuration for voice formatting (TTS optimization)
    
    Defines thresholds, limits, and patterns for converting text
    to natural-sounding speech output.
    """
    
    # =========================================================================
    # Length Limits
    # =========================================================================
    
    DEFAULT_MAX_LENGTH = 500
    """Default maximum length for voice output (characters)"""
    
    TRUNCATION_THRESHOLD = 0.7
    """Keep at least this percentage of content when truncating at sentence boundary"""
    
    # =========================================================================
    # List Formatting
    # =========================================================================
    
    MAX_LIST_ITEMS_SPOKEN = 5
    """Maximum number of list items to speak individually"""
    
    LIST_CONNECTORS: List[str] = [
        "First", "Second", "Third", "Fourth", "Fifth",
        "Sixth", "Seventh", "Eighth", "Ninth", "Tenth"
    ]
    """Ordinal connectors for spoken lists"""
    
    LIST_INTRO_SINGLE = "Here's what I found: {item}"
    """Introduction for single-item lists"""
    
    LIST_INTRO_MULTIPLE = "Here's what I found: {connector}, {item}"
    """Introduction for multi-item lists"""
    
    LIST_MORE_ITEMS = "And {count} more items"
    """Message for additional items beyond max"""
    
    # =========================================================================
    # Action Detection
    # =========================================================================
    
    ACTION_KEYWORDS: List[str] = [
        "created", "scheduled", "sent", "added", "updated", 
        "deleted", "completed", "removed", "cancelled", "moved"
    ]
    """Keywords indicating an action was performed"""
    
    CONFIRMATION_PREFIXES: List[str] = [
        "i've", "i have", "got it", "done", "all set", 
        "completed", "finished", "success"
    ]
    """Prefixes that indicate confirmation (don't need to add "I've")"""
    
    # =========================================================================
    # Conversational Replacements
    # =========================================================================
    
    CONTRACTIONS: Dict[str, str] = {
        r'\bI will\b': "I'll",
        r'\bI would\b': "I'd", 
        r'\bI am\b': "I'm",
        r'\bYou have\b': "You've got",
        r'\bHere are\b': "Here's",
        r'\bThere are\b': "There's",
        r'\bWe will\b': "We'll",
        r'\bWe are\b': "We're",
        r'\bThey are\b': "They're",
    }
    """Regular expressions for making text more conversational"""
    
    # =========================================================================
    # Markdown Patterns
    # =========================================================================
    
    MARKDOWN_PATTERNS: Dict[str, str] = {
        'bold_asterisk': r'\*\*([^*]+)\*\*',
        'italic_asterisk': r'\*([^*]+)\*',
        'bold_underscore': r'__([^_]+)__',
        'italic_underscore': r'_([^_]+)_',
        'code_block': r'```[^`]*```',
        'inline_code': r'`([^`]+)`',
        'header': r'#+\s*',
        'link': r'\[([^\]]+)\]\([^\)]+\)',
        'horizontal_rule': r'^---+$',
    }
    """Regex patterns for markdown elements to remove"""
    
    # =========================================================================
    # List Detection Patterns
    # =========================================================================
    
    BULLET_PATTERN = r'^[\s]*[•\-\*\+]\s+'
    """Pattern for detecting bullet points"""
    
    NUMBERED_PATTERN = r'^\d+[\.]\s+'
    """Pattern for detecting numbered lists"""
    
    # =========================================================================
    # Truncation Messages
    # =========================================================================
    
    TRUNCATION_SUFFIX = "That's the main information."
    """Message appended when truncating at sentence boundary"""
    
    WORD_TRUNCATION_SUFFIX = "..."
    """Message appended when truncating at word boundary"""
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    @classmethod
    def get_connector(cls, index: int) -> str:
        """
        Get ordinal connector for list position.
        
        Args:
            index: Zero-based position in list
            
        Returns:
            Ordinal word (e.g., "First", "Second")
        """
        if index < len(cls.LIST_CONNECTORS):
            return cls.LIST_CONNECTORS[index]
        return f"Item {index + 1}"
    
    @classmethod
    def is_confirmation(cls, text: str) -> bool:
        """
        Check if text already starts with a confirmation.
        
        Args:
            text: Text to check
            
        Returns:
            True if text starts with confirmation prefix
        """
        text_lower = text.lower()
        return any(text_lower.startswith(prefix) for prefix in cls.CONFIRMATION_PREFIXES)
    
    @classmethod
    def has_action_keyword(cls, text: str) -> bool:
        """
        Check if text contains action keywords.
        
        Args:
            text: Text to check
            
        Returns:
            True if text contains action keyword
        """
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in cls.ACTION_KEYWORDS)
    
    @classmethod
    def apply_contractions(cls, text: str) -> str:
        """
        Apply all conversational contractions to text.
        
        Args:
            text: Text to transform
            
        Returns:
            Text with contractions applied
        """
        for pattern, replacement in cls.CONTRACTIONS.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text
