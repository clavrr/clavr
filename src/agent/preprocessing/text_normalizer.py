"""
Text Normalizer Tool - Pre-Processing for Robustness

Handles "broken English," typos, and dialectal variations before queries
reach the Orchestrator LLM. This is the first line of defense for handling
informal, grammatically loose language common in Slack environments.
"""

import re
from typing import Dict, Any, Optional
from difflib import SequenceMatcher

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class TextNormalizer:
    """
    Text Normalizer for pre-processing user queries
    
    Implements:
    - Spell check/correction using Levenshtein distance
    - Tokenization & stemming
    - Common typo correction
    - Dialect transformation (internal normalization)
    """
    
    def __init__(self):
        """Initialize text normalizer with common corrections"""
        # Common typos and corrections (domain-specific)
        self.common_typos = {
            # Scheduling/Calendar
            'meeing': 'meeting',
            'schedul': 'schedule',
            'calender': 'calendar',
            'appoitment': 'appointment',
            'tomorow': 'tomorrow',
            'tommorow': 'tomorrow',
            'nex week': 'next week',
            'nex': 'next',
            
            # Tasks
            'taks': 'task',
            'taks': 'tasks',
            'reminder': 'reminder',
            'remind': 'remind',
            'due': 'due',
            
            # Email
            'emial': 'email',
            'emails': 'emails',
            'send': 'send',
            'replay': 'reply',
            'foward': 'forward',
            
            # Common words
            'wit': 'with',
            'teh': 'the',
            'adn': 'and',
            'taht': 'that',
            'recieve': 'receive',
            'seperate': 'separate',
            'occured': 'occurred',
        }
        
        # Common action verb corrections
        self.action_corrections = {
            'book': 'schedule',
            'set': 'create',
            'make': 'create',
            'add': 'create',
            'show': 'list',
            'display': 'list',
            'find': 'search',
            'look': 'search',
        }
    
    def normalize(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Normalize text input with multi-layered approach
        
        Args:
            text: Raw user input text
            context: Optional context (user_id, domain hints, etc.)
            
        Returns:
            Dictionary with:
            - normalized_text: Cleaned text
            - original_text: Original input
            - corrections_applied: List of corrections made
            - confidence: Normalization confidence score
        """
        original_text = text
        corrections_applied = []
        
        # Step 1: Basic cleaning
        normalized = self._basic_clean(text)
        
        # Step 2: Spell check and typo correction
        normalized, typos_fixed = self._spell_check(normalized)
        corrections_applied.extend(typos_fixed)
        
        # Step 3: Tokenization and stemming
        normalized = self._tokenize_and_stem(normalized)
        
        # Step 4: Action verb normalization
        normalized, actions_fixed = self._normalize_actions(normalized)
        corrections_applied.extend(actions_fixed)
        
        # Step 5: Dialect transformation (internal normalization)
        normalized = self._dialect_transform(normalized)
        
        # Calculate confidence
        confidence = self._calculate_confidence(original_text, normalized, corrections_applied)
        
        result = {
            'normalized_text': normalized,
            'original_text': original_text,
            'corrections_applied': corrections_applied,
            'confidence': confidence,
            'was_modified': original_text.lower() != normalized.lower()
        }
        
        logger.debug(f"Text normalized: '{original_text}' -> '{normalized}' (confidence: {confidence:.2f})")
        
        return result
    
    def _basic_clean(self, text: str) -> str:
        """Basic text cleaning"""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove leading/trailing whitespace
        text = text.strip()
        # Fix common punctuation issues
        text = re.sub(r'\.{2,}', '.', text)  # Multiple periods
        text = re.sub(r'\?{2,}', '?', text)  # Multiple question marks
        return text
    
    def _spell_check(self, text: str) -> tuple[str, list]:
        """Spell check using common typos dictionary and Levenshtein distance"""
        words = text.split()
        corrected_words = []
        corrections = []
        
        for word in words:
            word_lower = word.lower()
            
            # Check against common typos
            if word_lower in self.common_typos:
                correction = self.common_typos[word_lower]
                # Preserve original capitalization
                if word[0].isupper():
                    correction = correction.capitalize()
                corrected_words.append(correction)
                corrections.append({
                    'type': 'typo',
                    'original': word,
                    'corrected': correction,
                    'method': 'dictionary'
                })
            else:
                # Use Levenshtein distance for similar words
                best_match = self._find_closest_match(word_lower, self.common_typos.keys())
                if best_match and self._levenshtein_ratio(word_lower, best_match) > 0.8:
                    correction = self.common_typos[best_match]
                    if word[0].isupper():
                        correction = correction.capitalize()
                    corrected_words.append(correction)
                    corrections.append({
                        'type': 'typo',
                        'original': word,
                        'corrected': correction,
                        'method': 'levenshtein'
                    })
                else:
                    corrected_words.append(word)
        
        return ' '.join(corrected_words), corrections
    
    def _find_closest_match(self, word: str, candidates: list) -> Optional[str]:
        """Find closest match using Levenshtein distance"""
        best_match = None
        best_ratio = 0.0
        
        for candidate in candidates:
            ratio = self._levenshtein_ratio(word, candidate)
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = candidate
        
        return best_match if best_ratio > 0.8 else None
    
    def _levenshtein_ratio(self, s1: str, s2: str) -> float:
        """Calculate similarity ratio using Levenshtein distance"""
        return SequenceMatcher(None, s1, s2).ratio()
    
    def _tokenize_and_stem(self, text: str) -> str:
        """Tokenize and stem words to root forms"""
        words = text.split()
        stemmed_words = []
        
        # Simple stemming rules (can be enhanced with NLTK if needed)
        for word in words:
            stemmed = self._stem_word(word)
            stemmed_words.append(stemmed)
        
        return ' '.join(stemmed_words)
    
    def _stem_word(self, word: str) -> str:
        """Simple stemming - reduce to root form"""
        word_lower = word.lower()
        original_case = word[0].isupper()
        
        # Common verb endings
        if word_lower.endswith('ing'):
            root = word_lower[:-3]
            # Add 'e' if needed (e.g., "scheduling" -> "schedule")
            if root + 'e' in ['schedule', 'create', 'update', 'delete']:
                root = root + 'e'
        elif word_lower.endswith('ed'):
            root = word_lower[:-2]
            if root + 'e' in ['schedule', 'create', 'update', 'delete']:
                root = root + 'e'
        elif word_lower.endswith('s') and len(word_lower) > 3:
            # Plural forms
            root = word_lower[:-1]
        else:
            root = word_lower
        
        # Preserve original capitalization
        if original_case:
            root = root.capitalize()
        
        return root if root else word
    
    def _normalize_actions(self, text: str) -> tuple[str, list]:
        """Normalize action verbs to standard forms"""
        words = text.split()
        normalized_words = []
        corrections = []
        
        for word in words:
            word_lower = word.lower()
            
            if word_lower in self.action_corrections:
                correction = self.action_corrections[word_lower]
                if word[0].isupper():
                    correction = correction.capitalize()
                normalized_words.append(correction)
                corrections.append({
                    'type': 'action_normalization',
                    'original': word,
                    'corrected': correction
                })
            else:
                normalized_words.append(word)
        
        return ' '.join(normalized_words), corrections
    
    def _dialect_transform(self, text: str) -> str:
        """
        Dialect transformation - convert non-standard English to standardized form
        
        This handles common dialectal variations internally without changing
        the user's original intent.
        """
        # Common dialect transformations
        transformations = {
            # Indian English variations
            r'\bdone\s+with\b': 'completed',
            r'\bdo\s+the\s+needful\b': 'handle this',
            r'\bkindly\s+do\b': 'please',
            
            # Singlish variations
            r'\blah\b': '',
            r'\blor\b': '',
            r'\bcan\s+anot\b': 'can',
            r'\balready\b': '',
            
            # Common informal variations
            r'\bgonna\b': 'going to',
            r'\bwanna\b': 'want to',
            r'\bgotta\b': 'got to',
            r'\blemme\b': 'let me',
            r'\bcuz\b': 'because',
            r'\bthru\b': 'through',
        }
        
        normalized = text
        for pattern, replacement in transformations.items():
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        
        # Clean up extra spaces
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _calculate_confidence(self, original: str, normalized: str, corrections: list) -> float:
        """Calculate confidence score for normalization"""
        if not corrections:
            return 1.0
        
        # Base confidence
        confidence = 0.9
        
        # Reduce confidence if many corrections were made
        correction_ratio = len(corrections) / max(len(original.split()), 1)
        if correction_ratio > 0.3:  # More than 30% of words corrected
            confidence = 0.7
        elif correction_ratio > 0.5:  # More than 50% corrected
            confidence = 0.5
        
        # Increase confidence if Levenshtein similarity is high
        similarity = self._levenshtein_ratio(original.lower(), normalized.lower())
        confidence = (confidence + similarity) / 2
        
        return min(confidence, 1.0)

