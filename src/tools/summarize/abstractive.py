"""
Abstractive (LLM-based) summarization
Uses AI to generate concise, coherent summaries
"""
from typing import Optional, Dict, Any
from .constants import (
    LLM_TEMPERATURE, LLM_MAX_TOKENS,
    SHORT_CONTENT_THRESHOLD, MEDIUM_CONTENT_THRESHOLD,
    NLP_ENHANCEMENT_MIN_LENGTH,
    CHARS_PER_WORD_ESTIMATE,
    WORD_COUNT_THRESHOLD_SMALL, WORD_COUNT_THRESHOLD_MEDIUM,
    TARGET_WORDS_SHORT_SMALL, TARGET_WORDS_SHORT_MEDIUM, TARGET_WORDS_SHORT_LARGE,
    TARGET_WORDS_MEDIUM_SMALL, TARGET_WORDS_MEDIUM_MEDIUM, TARGET_WORDS_MEDIUM_LARGE,
    TARGET_WORDS_LONG_SMALL, TARGET_WORDS_LONG_MEDIUM, TARGET_WORDS_LONG_LARGE,
    WORD_DIVISOR_SHORT, WORD_DIVISOR_MEDIUM, WORD_DIVISOR_LONG
)
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class AbstractiveSummarizer:
    """LLM-based summarization using AI"""
    
    def __init__(self, llm_client=None):
        """
        Initialize abstractive summarizer
        
        Args:
            llm_client: LLM client instance
        """
        self.llm_client = llm_client
    
    def summarize(
        self,
        content: str,
        format_type: str = "paragraph",
        length: str = "medium",
        focus: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Generate AI-powered summary
        
        Args:
            content: Content to summarize
            format_type: Output format (paragraph, bullet_points, key_points)
            length: Summary length (short, medium, long)
            focus: Optional focus area
            metadata: Optional context metadata
            
        Returns:
            Generated summary or None if LLM unavailable
        """
        if not self.llm_client:
            logger.warning("[ABSTRACTIVE] No LLM client available")
            return None
        
        try:
            # Build prompt
            prompt = self._build_prompt(content, format_type, length, focus, metadata)
            
            # Get system message
            system_message = self._build_system_message(format_type, metadata)
            
            # Generate summary
            logger.info(f"[ABSTRACTIVE] Generating {length} {format_type} summary...")
            
            response = self.llm_client.chat.completions.create(
                model=self.llm_client.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS
            )
            
            summary = response.choices[0].message.content.strip()
            logger.info(f"[ABSTRACTIVE] Generated summary ({len(summary)} chars)")
            
            return summary
            
        except Exception as e:
            logger.error(f"[ABSTRACTIVE] LLM summarization failed: {e}")
            return None
    
    def _build_system_message(
        self,
        format_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build system message for LLM
        
        Args:
            format_type: Output format
            metadata: Optional context metadata
            
        Returns:
            System message
        """
        base_message = (
            "You are an expert document summarizer. Your summaries are clear, "
            "concise, and capture the most important information. You avoid redundancy "
            "and focus on key insights."
        )
        
        # Add format-specific instructions
        if format_type == "bullet_points":
            base_message += "\n\nFormat your response as bullet points (•) with clear, concise statements."
        elif format_type == "key_points":
            base_message += "\n\nFormat your response as numbered key points, highlighting the most critical information."
        else:  # paragraph
            base_message += "\n\nFormat your response as well-structured paragraphs."
        
        # Add context from metadata
        if metadata:
            source_type = metadata.get('source_type')
            if source_type == 'email':
                base_message += "\n\nYou are summarizing an email or email thread. Focus on action items, decisions, and key discussion points."
            elif source_type == 'calendar':
                base_message += "\n\nYou are summarizing calendar events or meetings. Focus on timing, participants, and agenda items."
            elif source_type == 'conversation':
                base_message += "\n\nYou are summarizing a conversation. Focus on main topics, decisions, and action items."
        
        return base_message
    
    def _build_prompt(
        self,
        content: str,
        format_type: str,
        length: str,
        focus: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build prompt for LLM
        
        Args:
            content: Content to summarize
            format_type: Output format
            length: Summary length
            focus: Optional focus area
            metadata: Optional context metadata
            
        Returns:
            Formatted prompt
        """
        # Calculate target length
        target_length = self._get_target_length(len(content), length)
        
        # Build base prompt
        prompt = f"Summarize the following content in approximately {target_length} words"
        
        # Add focus if specified
        if focus:
            prompt += f", focusing on: {focus}"
        
        # Add format instruction
        format_instruction = self._get_format_instruction(format_type)
        prompt += f". {format_instruction}"
        
        # Add content
        prompt += f"\n\nContent:\n{content}"
        
        return prompt
    
    def _get_target_length(self, content_length: int, length: str) -> int:
        """
        Calculate target summary length in words
        
        Args:
            content_length: Original content length
            length: Desired summary length
            
        Returns:
            Target word count
        """
        # Estimate words in content
        estimated_words = content_length // CHARS_PER_WORD_ESTIMATE
        
        # Set target based on length preference
        if length == "short":
            if estimated_words < WORD_COUNT_THRESHOLD_SMALL:
                return max(TARGET_WORDS_SHORT_SMALL, estimated_words // WORD_DIVISOR_SHORT)
            elif estimated_words < WORD_COUNT_THRESHOLD_MEDIUM:
                return TARGET_WORDS_SHORT_MEDIUM
            else:
                return TARGET_WORDS_SHORT_LARGE
        
        elif length == "long":
            if estimated_words < WORD_COUNT_THRESHOLD_SMALL:
                return max(TARGET_WORDS_LONG_SMALL, estimated_words // WORD_DIVISOR_LONG)
            elif estimated_words < WORD_COUNT_THRESHOLD_MEDIUM:
                return TARGET_WORDS_LONG_MEDIUM
            else:
                return TARGET_WORDS_LONG_LARGE
        
        else:  # medium
            if estimated_words < WORD_COUNT_THRESHOLD_SMALL:
                return max(TARGET_WORDS_MEDIUM_SMALL, estimated_words // WORD_DIVISOR_MEDIUM)
            elif estimated_words < WORD_COUNT_THRESHOLD_MEDIUM:
                return TARGET_WORDS_MEDIUM_MEDIUM
            else:
                return TARGET_WORDS_MEDIUM_LARGE
    
    def _get_format_instruction(self, format_type: str) -> str:
        """
        Get format-specific instruction
        
        Args:
            format_type: Output format
            
        Returns:
            Format instruction
        """
        if format_type == "bullet_points":
            return "Use bullet points (•) to list the main ideas"
        elif format_type == "key_points":
            return "List the key points as numbered items"
        else:  # paragraph
            return "Write in paragraph form with clear, concise sentences"
    
    def can_use_nlp_enhancement(self, content: str) -> bool:
        """
        Check if content is suitable for NLP enhancement
        
        Args:
            content: Content to check
            
        Returns:
            True if NLP enhancement recommended
        """
        return len(content) >= NLP_ENHANCEMENT_MIN_LENGTH
