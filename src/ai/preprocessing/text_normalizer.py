"""
Text Normalizer Tool - Pre-Processing for Robustness

Handles "broken English," typos, and dialectal variations before queries
reach the Orchestrator LLM. This is the first line of defense for handling
informal, grammatically loose language common in Slack environments.
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from difflib import SequenceMatcher

from src.utils.logger import setup_logger
from .normalization_rules import GLOBAL_TYPOS, DOMAIN_RULES, DIALECT_TRANSFORMATIONS

logger = setup_logger(__name__)


class TextNormalizer:
    """
    Text Normalizer for pre-processing user queries.
    
    Implements:
    - Memory-aware entity protection (preserves known names/projects)
    - Categorized typo correction (Global + Domain-specific)
    - Dialect transformation (Regional variations)
    - Context-aware normalization
    - Phonetic similarity matching
    """
    
    def __init__(self):
        """Initialize text normalizer with structured rules."""
        self.global_typos = GLOBAL_TYPOS
        self.domain_rules = DOMAIN_RULES
        
        # Pre-compile dialect patterns by category
        self.dialect_categories = {}
        for category, rules in DIALECT_TRANSFORMATIONS.items():
            self.dialect_categories[category] = [
                (re.compile(pattern, flags=re.IGNORECASE), replacement)
                for pattern, replacement in rules.items()
            ]
        
        # Pre-compile cleaning patterns
        self.whitespace_pattern = re.compile(r'\s+')
        self.multi_period_pattern = re.compile(r'\.{2,}')
        self.multi_question_pattern = re.compile(r'\?{2,}')
    
    def normalize(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Normalize text input with memory and context awareness.
        """
        original_text = text
        corrections_applied = []
        context = context or {}
        domain = context.get('domain')
        # known_entities: List of strings from memory (names, projects) to PROTECT
        known_entities = [e.lower() for e in context.get('known_entities', [])]
        
        # Step 1: Basic cleaning
        normalized = self._basic_clean(text)
        
        # Step 2: Dialect transformation (Applied before tokenization for phrase matching)
        normalized, dialect_corrections = self._apply_dialect_transforms(normalized)
        corrections_applied.extend(dialect_corrections)
        
        # Step 3: Token-level normalization
        tokens = normalized.split()
        normalized_tokens = []
        
        for word in tokens:
            word_lower = word.lower()
            
            # ENTITY PROTECTION: Skip normalization if word is a known entity from memory
            if word_lower in known_entities:
                normalized_tokens.append(word)
                continue
            
            # TYPO CORRECTION: Global -> Domain-specific
            correction = self._get_correction(word_lower, domain)
            if correction:
                # Preserve original capitalization
                if word[0].isupper():
                    correction = correction.capitalize()
                normalized_tokens.append(correction)
                corrections_applied.append({
                    'type': 'typo',
                    'original': word,
                    'corrected': correction
                })
            else:
                normalized_tokens.append(word)
        
        normalized = ' '.join(normalized_tokens)
        
        # Calculate confidence
        confidence = self._calculate_confidence(original_text, normalized, corrections_applied)
        
        return {
            'normalized_text': normalized,
            'original_text': original_text,
            'corrections_applied': corrections_applied,
            'confidence': confidence,
            'was_modified': original_text.lower() != normalized.lower()
        }
    
    def _basic_clean(self, text: str) -> str:
        """Standard whitespace and punctuation cleaning."""
        text = self.whitespace_pattern.sub(' ', text).strip()
        text = self.multi_period_pattern.sub('.', text)
        text = self.multi_question_pattern.sub('?', text)
        return text

    def _apply_dialect_transforms(self, text: str) -> Tuple[str, List[Dict]]:
        """Apply regional/informal phrase transformations."""
        normalized = text
        corrections = []
        
        for category, patterns in self.dialect_categories.items():
            for pattern, replacement in patterns:
                if pattern.search(normalized):
                    match = pattern.search(normalized).group(0)
                    normalized = pattern.sub(replacement, normalized)
                    corrections.append({
                        'type': f'dialect_{category}',
                        'original': match,
                        'corrected': replacement
                    })
        return normalized, corrections

    def _get_correction(self, word: str, domain: Optional[str]) -> Optional[str]:
        """Get best correction with domain prioritizaton."""
        # 1. Check Global Typos
        if word in self.global_typos:
            return self.global_typos[word]
            
        # 2. Check Domain-Specific Rules
        if domain and domain in self.domain_rules:
            if word in self.domain_rules[domain]:
                return self.domain_rules[domain][word]
        
        # 3. Phonetic/Levenshtein matching (Fallback)
        if len(word) > 3:
            # Check global candidates
            candidates = list(self.global_typos.keys())
            if domain and domain in self.domain_rules:
                candidates.extend(self.domain_rules[domain].keys())
                
            best_match = self._find_closest_match(word, candidates)
            if best_match:
                # Return the correction for that candidate
                if best_match in self.global_typos:
                    return self.global_typos[best_match]
                if domain and best_match in self.domain_rules[domain]:
                    return self.domain_rules[domain][best_match]
                    
        return None

    def _find_closest_match(self, word: str, candidates: List[str]) -> Optional[str]:
        """Phonetic-aware similarity matching."""
        best_match = None
        best_ratio = 0.0
        
        for candidate in candidates:
            # Skip candidates with wild length differences
            if abs(len(word) - len(candidate)) > 2:
                continue
                
            ratio = SequenceMatcher(None, word, candidate).ratio()
            # High threshold to avoid over-correction
            if ratio > 0.82:
                if ratio > best_ratio:

                    best_ratio = ratio
                    best_match = candidate
        
        return best_match

    def _calculate_confidence(self, original: str, normalized: str, corrections: list) -> float:
        """Determine reliability of normalization."""
        if not corrections:
            return 1.0
        
        # Base confidence for non-human intervention
        confidence = 0.95
        
        # Penalty for aggressive transformation
        if len(corrections) > 3:
            confidence -= 0.1
            
        # Geometric similarity as a weights
        similarity = SequenceMatcher(None, original.lower(), normalized.lower()).ratio()
        return round((confidence + similarity) / 2, 2)
