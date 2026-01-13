"""
Voice Response Formatter
Converts text responses to voice-optimized format
"""
import re
from datetime import datetime
from typing import Optional

from src.utils.logger import setup_logger
from .voice_config import VoiceConfig

logger = setup_logger(__name__)


class VoiceFormatter:
    """
    Formats responses for voice output (TTS optimization).
    
    Uses VoiceConfig for all configuration values and helper methods.
    """
    
    def __init__(self, max_length: Optional[int] = None):
        """
        Initialize formatter.
        
        Args:
            max_length: Optional override for max output length
        """
        self.max_length = max_length or VoiceConfig.DEFAULT_MAX_LENGTH
    
    def format(self, text: str) -> str:
        """
        Format text response for voice output.
        
        Transformations:
        - Remove markdown formatting
        - Convert lists to natural speech
        - Add conversational elements and contractions
        - Add time-appropriate greeting if needed
        - Shorten if too long
        """
        if not text:
            return text
        
        # Remove markdown
        text = self._remove_markdown(text)
        
        # Apply conversational contractions
        text = VoiceConfig.apply_contractions(text)
        
        # Convert lists to natural speech
        text = self._convert_lists(text)
        
        # Add conversational elements
        text = self._add_conversational_elements(text)
        
        # Truncate if too long
        if len(text) > self.max_length:
            text = self._truncate_intelligently(text)
        
        return text
    
    def _remove_markdown(self, text: str) -> str:
        """Remove markdown formatting using VoiceConfig patterns."""
        patterns = VoiceConfig.MARKDOWN_PATTERNS
        
        # Remove code blocks first (multi-line)
        text = re.sub(patterns['code_block'], '', text, flags=re.DOTALL)
        
        # Remove other markdown elements
        text = re.sub(patterns['bold_asterisk'], r'\1', text)
        text = re.sub(patterns['italic_asterisk'], r'\1', text)
        text = re.sub(patterns['bold_underscore'], r'\1', text)
        text = re.sub(patterns['italic_underscore'], r'\1', text)
        text = re.sub(patterns['inline_code'], r'\1', text)
        text = re.sub(patterns['header'], '', text)
        text = re.sub(patterns['link'], r'\1', text)
        text = re.sub(patterns['horizontal_rule'], '', text, flags=re.MULTILINE)
        
        return text.strip()
    
    def _convert_lists(self, text: str) -> str:
        """Convert bullet points and numbered lists to natural speech."""
        lines = text.split('\n')
        result = []
        list_item_count = 0
        in_list = False
        
        for line in lines:
            # Detect list items
            is_bullet = re.match(VoiceConfig.BULLET_PATTERN, line)
            is_numbered = re.match(VoiceConfig.NUMBERED_PATTERN, line)
            
            if is_bullet or is_numbered:
                if not in_list:
                    result.append("Here's what I found:")
                    in_list = True
                    list_item_count = 0
                
                # Remove bullet/number
                item = re.sub(VoiceConfig.BULLET_PATTERN, '', line)
                item = re.sub(VoiceConfig.NUMBERED_PATTERN, '', item)
                item = item.strip()
                
                # Check if we've exceeded max spoken items
                if list_item_count >= VoiceConfig.MAX_LIST_ITEMS_SPOKEN:
                    continue  # Skip, we'll add summary at end
                
                # Add natural connector
                connector = VoiceConfig.get_connector(list_item_count)
                result.append(f"{connector}, {item}")
                list_item_count += 1
            else:
                if in_list and list_item_count > VoiceConfig.MAX_LIST_ITEMS_SPOKEN:
                    remaining = list_item_count - VoiceConfig.MAX_LIST_ITEMS_SPOKEN
                    result.append(VoiceConfig.LIST_MORE_ITEMS.format(count=remaining))
                in_list = False
                list_item_count = 0
                if line.strip():
                    result.append(line)
        
        return '\n'.join(result)
    
    def _add_conversational_elements(self, text: str) -> str:
        """Add conversational fillers and confirmations."""
        # Check if already has confirmation
        if VoiceConfig.is_confirmation(text):
            return text
        
        # Add confirmation prefix for action keywords
        if VoiceConfig.has_action_keyword(text):
            text = f"I've {text[0].lower()}{text[1:]}"
        
        return text
    
    def _truncate_intelligently(self, text: str) -> str:
        """Truncate text at sentence boundary."""
        if len(text) <= self.max_length:
            return text
        
        # Find last sentence boundary before max_length
        truncated = text[:self.max_length]
        last_period = truncated.rfind('.')
        last_exclamation = truncated.rfind('!')
        last_question = truncated.rfind('?')
        
        cutoff = max(last_period, last_exclamation, last_question)
        
        threshold = int(self.max_length * VoiceConfig.TRUNCATION_THRESHOLD)
        if cutoff > threshold:
            return truncated[:cutoff + 1] + f" {VoiceConfig.TRUNCATION_SUFFIX}"
        else:
            return truncated + VoiceConfig.WORD_TRUNCATION_SUFFIX
    
    @staticmethod
    def get_time_greeting() -> str:
        """
        Get time-appropriate greeting.
        
        Returns:
            Greeting based on current time of day
        """
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "Good morning"
        elif 12 <= hour < 17:
            return "Good afternoon"
        elif 17 <= hour < 21:
            return "Good evening"
        else:
            return "Hello"

