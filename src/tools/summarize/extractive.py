"""
Extractive Summarization Module

Handles non-LLM based summarization using extraction techniques.
This is the fallback when LLM is not available.
"""
import re
from typing import List, Dict, Any
from .constants import (
    SENTENCE_SCORING, CONTENT_LENGTH_BASELINE,
    SENTENCE_MULTIPLIER_SHORT, SENTENCE_MULTIPLIER_MEDIUM, SENTENCE_MULTIPLIER_LONG,
    MIN_SENTENCES_SHORT, MIN_SENTENCES_MEDIUM, MIN_SENTENCES_LONG,
    DEFAULT_SENTENCE_COUNT
)

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class ExtractiveSummarizer:
    """Extractive summarization using sentence selection heuristics"""
    
    def __init__(self):
        """Initialize extractive summarizer"""
        self.scoring = SENTENCE_SCORING
    
    def summarize(
        self,
        content: str,
        format: str = "paragraph",
        length: str = "medium"
    ) -> str:
        """
        Extract key sentences to create summary
        
        Args:
            content: Content to summarize
            format: Output format (paragraph, bullet_points, key_points)
            length: Summary length (short, medium, long)
            
        Returns:
            Formatted extractive summary
        """
        # Split into sentences
        sentences = self._split_sentences(content)
        
        if not sentences:
            return self._format_empty_summary(format)
        
        # Calculate target number of sentences
        num_sentences = self._calculate_target_sentences(content, length)
        
        # Select most informative sentences
        selected = self._select_key_sentences(sentences, num_sentences)
        
        # Format output
        return self._format_summary(selected, format)
    
    def _split_sentences(self, content: str) -> List[str]:
        """
        Split content into sentences (handles abbreviations and numbers)
        
        Args:
            content: Text to split
            
        Returns:
            List of sentences
        """
        # Smart sentence splitting that handles abbreviations and numbers
        # Pattern: Split on sentence endings followed by space and capital letter
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', content)
        return [s.strip() for s in sentences if s.strip()]
    
    def _calculate_target_sentences(self, content: str, length: str) -> int:
        """
        Calculate target number of sentences based on content length and desired summary length
        
        Args:
            content: Original content
            length: Desired summary length
            
        Returns:
            Number of sentences to extract
        """
        # Dynamic sentence count based on content length
        content_length_factor = len(content) / CONTENT_LENGTH_BASELINE
        
        base_map = {
            'short': max(MIN_SENTENCES_SHORT, int(SENTENCE_MULTIPLIER_SHORT * content_length_factor)),
            'medium': max(MIN_SENTENCES_MEDIUM, int(SENTENCE_MULTIPLIER_MEDIUM * content_length_factor)),
            'long': max(MIN_SENTENCES_LONG, int(SENTENCE_MULTIPLIER_LONG * content_length_factor))
        }
        
        return base_map.get(length, DEFAULT_SENTENCE_COUNT)
    
    def _select_key_sentences(self, sentences: List[str], num: int) -> List[str]:
        """
        Select most informative sentences using scoring heuristics
        
        Args:
            sentences: List of sentences to score
            num: Number of sentences to select
            
        Returns:
            Selected key sentences
        """
        if len(sentences) <= num:
            return sentences
        
        # Score each sentence
        scored = []
        for sentence in sentences:
            score = self._score_sentence(sentence)
            scored.append((score, sentence))
        
        # Sort by score (descending) and take top N
        scored.sort(key=lambda x: x[0], reverse=True)
        return [sentence for _, sentence in scored[:num]]
    
    def _score_sentence(self, sentence: str) -> float:
        """
        Score a sentence based on informativeness
        
        Args:
            sentence: Sentence to score
            
        Returns:
            Informativeness score
        """
        score = 0
        sentence_len = len(sentence)
        
        # Optimal length sentences (50-200 chars) are more informative
        if self.scoring['optimal_length_min'] < sentence_len < self.scoring['optimal_length_max']:
            score += self.scoring['optimal_score']
        elif self.scoring['acceptable_length_min'] < sentence_len <= self.scoring['acceptable_length_max']:
            score += self.scoring['acceptable_score']
        
        # Sentences with numbers often contain important information
        if re.search(r'\d+', sentence):
            score += self.scoring['has_numbers_bonus']
        
        # Sentences with question words indicate key points
        if re.search(r'\b(what|when|where|who|why|how)\b', sentence, re.IGNORECASE):
            score += self.scoring['has_questions_bonus']
        
        # Penalize very short sentences
        if len(sentence.strip()) < self.scoring['min_length_threshold']:
            score += self.scoring['min_length_penalty']
        
        # Bonus for sentences at the beginning (often contain main ideas)
        # This would need access to sentence position, can be added later
        
        return score
    
    def _format_summary(self, sentences: List[str], format: str) -> str:
        """
        Format selected sentences into desired output format
        
        Args:
            sentences: Selected sentences
            format: Output format
            
        Returns:
            Formatted summary
        """
        if format == "bullet_points":
            output = "**📋 Summary (Key Points):**\n\n"
            for sentence in sentences:
                if sentence.strip():
                    output += f"• {sentence.strip()}\n"
        
        elif format == "key_points":
            output = "**🔑 Key Takeaways:**\n\n"
            for i, sentence in enumerate(sentences, 1):
                if sentence.strip():
                    output += f"{i}. {sentence.strip()}\n"
        
        else:  # paragraph
            output = "**📄 Summary:**\n\n"
            combined = '. '.join(s.strip() for s in sentences if s.strip())
            output += combined + '.' if combined else "No summary available."
        
        return output
    
    def _format_empty_summary(self, format: str) -> str:
        """Format empty summary message"""
        if format == "bullet_points":
            return "**📋 Summary (Key Points):**\n\n• No content available to summarize."
        elif format == "key_points":
            return "**🔑 Key Takeaways:**\n\n1. No content available to summarize."
        else:
            return "**📄 Summary:**\n\nNo content available to summarize."
