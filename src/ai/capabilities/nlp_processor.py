"""
NLP Processor Capability

Provides advanced natural language understanding features:
- Keyword extraction
- Complexity analysis
- Sentiment analysis hooks
- Entity linking assistance
"""
import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

# Use shared logger
from src.utils.logger import setup_logger

# Import centralized keywords
from src.agents.constants import (
    URGENT_KEYWORDS,
    CONFUSION_KEYWORDS,
    POSITIVE_KEYWORDS,
    NEGATIVE_KEYWORDS,
    TECHNICAL_TERMS,
)

logger = setup_logger(__name__)

@dataclass
class EntityLink:
    """Represents a linked entity from text"""
    text: str
    entity_type: str
    confidence: float
    resolved_value: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class SentimentType:
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    CONFUSED = "confused"
    URGENT = "urgent"

class NLPProcessor:
    """
    Advanced NLP processing for agent queries.
    Focuses on understanding intent nuances and extracting rich context.
    """
    
    EMAIL_PATTERNS = {
        'email_address': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        'email_domain': r'@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    }
    
    TIME_PATTERNS = {
        'date_iso': r'\d{4}-\d{2}-\d{2}',
        'time_24h': r'([01]?[0-9]|2[0-3]):[0-5][0-9]',
        'relative_day': r'\b(today|tomorrow|yesterday)\b',
        'weekday': r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
    }
    
    PERSON_INDICATORS = {
        'prefixes': ['mr.', 'mrs.', 'ms.', 'dr.', 'prof.'],
        'name_patterns': r'\b([A-Z][a-z]+ [A-Z][a-z]+)\b' 
    }
    
    def __init__(self):
        self.stats = {
            'queries_processed': 0,
            'avg_sentiment_score': 0.5,
            'avg_complexity': 0.0
        }
        self.keyword_importance_model = self._build_keyword_model()
        
    def process_query(self, query: str) -> Dict[str, Any]:
        """
        Process a query to extract rich metadata
        """
        self.stats['queries_processed'] += 1
        
        # 1. Basic properties
        complexity = self._assess_language_complexity(query)
        sentiment = self._analyze_sentiment_heuristic(query)
        
        # 2. Key information extraction
        keywords = self._extract_keywords(query)
        entities = self._extract_and_link_entities(query)
        
        # 3. Intent hints
        intent_adjustments = self._calculate_intent_adjustments(query, sentiment, entities)
        
        # Update stats
        n = self.stats['queries_processed']
        prev_complex = float(self.stats['avg_complexity'])
        self.stats['avg_complexity'] = ((prev_complex * (n-1)) + complexity) / n
        
        return {
            'complexity_score': complexity,
            'sentiment': sentiment,
            'keywords': keywords,
            'entities': entities,
            'intent_adjustments': intent_adjustments,
            'is_complex': complexity > 0.6,
            'requires_clarification': sentiment['type'] == SentimentType.CONFUSED
        }
        
    def _analyze_sentiment_heuristic(self, query: str) -> Dict[str, Any]:
        """Simple heuristic sentiment analysis using centralized keywords."""
        text = query.lower()
        
        # Urgent indicators (using centralized URGENT_KEYWORDS)
        if any(w in text for w in URGENT_KEYWORDS):
            return {'type': SentimentType.URGENT, 'score': 0.9}
            
        # Confusion indicators (using centralized CONFUSION_KEYWORDS)
        if any(w in text for w in CONFUSION_KEYWORDS) or ('?' in text and len(text.split()) < 4):
            return {'type': SentimentType.CONFUSED, 'score': 0.3}
            
        # Positive/Polite (using centralized POSITIVE_KEYWORDS)
        if any(w in text for w in POSITIVE_KEYWORDS):
            return {'type': SentimentType.POSITIVE, 'score': 0.8}
            
        # Negative/Frustrated indicators (using centralized NEGATIVE_KEYWORDS)
        if any(w in text for w in NEGATIVE_KEYWORDS):
            return {'type': SentimentType.NEGATIVE, 'score': 0.2}
            
        return {'type': SentimentType.NEUTRAL, 'score': 0.5}

    def _extract_and_link_entities(self, query: str) -> List[EntityLink]:
        """
        Extract entities from query and attempt to link them to known values
        """
        entities: List[EntityLink] = []
        
        # Extract emails
        email_matches = re.finditer(self.EMAIL_PATTERNS['email_address'], query)
        for match in email_matches:
            entity = EntityLink(
                text=match.group(0),
                entity_type='email_address',
                confidence=0.95,
                resolved_value=match.group(0),
                metadata={'domain': re.search(self.EMAIL_PATTERNS['email_domain'], match.group(0)).group(1)}
            )
            entities.append(entity)
        
        # Extract dates
        for date_type, pattern in self.TIME_PATTERNS.items():
            matches = re.finditer(pattern, query, re.IGNORECASE)
            for match in matches:
                entity = EntityLink(
                    text=match.group(0),
                    entity_type=date_type,
                    confidence=0.85,
                    resolved_value=match.group(0),
                    metadata={'raw': match.group(0)}
                )
                entities.append(entity)
        
        # Extract potential person names
        name_matches = re.finditer(self.PERSON_INDICATORS['name_patterns'], query)
        for match in name_matches:
            text = match.group(0)
            # Heuristic: if it's capitalized and not at start of sentence, likely a name
            # Also check strictly interior words or ensure simple capitalization check
            if text[0].isupper() and len(text) > 2:
                # Avoid common capitalized start-of-sentence words if easy (simple heuristic here)
                entity = EntityLink(
                    text=text,
                    entity_type='person_name',
                    confidence=0.6,  # Lower confidence for names without NER model
                    metadata={'capitalized': True}
                )
                # Avoid duplicates
                if not any(e.text == text and e.entity_type == 'person_name' for e in entities):
                    entities.append(entity)
        
        return entities
    
    @staticmethod
    @lru_cache(maxsize=256)
    def _extract_keywords_cached(query: str) -> Tuple[Tuple[str, float], ...]:
        """
        Cached keyword extraction - returns tuple for hashability.
        """
        # Stop words to filter out
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
            'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
            'must', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
            'it', 'we', 'they', 'what', 'which', 'who', 'when', 'where', 'why', 'how',
            'from', 'with', 'by', 'up', 'about', 'as', 'if', 'of', 'my', 'me', 'my'
        }
        
        # Tokenize
        words = re.findall(r'\b[a-zA-Z]+\b', query.lower())
        if not words:
            words = [w.strip(".,!?") for w in query.lower().split()]

        # Filter stop words
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        
        # Score keywords (using default importance since static)
        keyword_importance = {
            'urgent': 0.9, 'important': 0.85, 'priority': 0.8, 'asap': 0.85,
            'today': 0.7, 'tomorrow': 0.6, 'send': 0.75, 'schedule': 0.75,
            'create': 0.8, 'delete': 0.8, 'update': 0.7,
            'email': 0.6, 'calendar': 0.6, 'task': 0.6, 'meeting': 0.65,
            'event': 0.65, 'reminder': 0.65,
            'show': 0.4, 'list': 0.4, 'view': 0.4, 'check': 0.5, 'look': 0.35,
        }
        
        scored_keywords = []
        for keyword in set(keywords):
            frequency = keywords.count(keyword)
            importance = keyword_importance.get(keyword, 0.5)
            combined_score = (frequency * 0.4 + importance * 0.6)
            scored_keywords.append((keyword, combined_score))
        
        # Sort by score and return top keywords
        return tuple(sorted(scored_keywords, key=lambda x: x[1], reverse=True)[:10])
    
    def _extract_keywords(self, query: str) -> List[Tuple[str, float]]:
        """
        Extract keywords with importance scoring (uses cached version).
        Returns list of (keyword, importance) tuples sorted by importance.
        """
        return list(self._extract_keywords_cached(query))
    
    def _assess_language_complexity(self, query: str) -> float:
        """
        Assess language complexity on scale 0-1
        """
        complexity = 0.0
        
        # Sentence length (longer = more complex)
        words = query.split()
        avg_word_len = sum(len(w) for w in words) / len(words) if words else 0
        sentence_length_factor = min(len(words) / 20, 1.0)  # Max at 20 words
        complexity += sentence_length_factor * 0.3
        
        # Word length
        word_len_factor = min(avg_word_len / 8, 1.0)  # Max at 8 chars average
        complexity += word_len_factor * 0.2
        
        # Subordinate clauses
        clause_indicators = ['which', 'that', 'because', 'although', 'since', 'if']
        clause_count = sum(1 for indicator in clause_indicators if indicator in query.lower())
        complexity += min(clause_count * 0.15, 0.3)
        
        # Technical terms (using centralized TECHNICAL_TERMS)
        tech_count = sum(1 for term in TECHNICAL_TERMS if term in query.lower())
        complexity += tech_count * 0.05
        
        return min(complexity, 1.0)
    
    def _calculate_intent_adjustments(
        self,
        query: str,
        sentiment: Dict[str, Any],
        entities: List[EntityLink]
    ) -> Dict[str, float]:
        """
        Calculate adjustments to intent confidence based on NLP analysis
        """
        adjustments = {
            'search': 0.0,
            'create': 0.0,
            'update': 0.0,
            'delete': 0.0,
            'analyze': 0.0,
            'query': 0.0
        }
        
        # Sentiment adjustments
        if sentiment['type'] == SentimentType.CONFUSED:
            # Uncertain user, lower confidence in all intents
            for intent in adjustments:
                adjustments[intent] -= 0.1
            # Increase confidence in search/analyze (informational queries)
            adjustments['search'] += 0.15
            adjustments['analyze'] += 0.1
        
        # Entity-based adjustments
        if len(entities) > 0:
            # More entities = more specific intent
            adjustments['search'] += 0.1
            if any(e.entity_type == 'email_address' for e in entities):
                # If email is present, less likely to be generic 'create' unless specific
                adjustments['create'] -= 0.05 
            if any(e.entity_type == 'person_name' for e in entities):
                adjustments['analyze'] += 0.05
        
        # Query content adjustments
        query_lower = query.lower()
        if any(word in query_lower for word in ['specific', 'exactly', 'precisely']):
            adjustments['search'] += 0.15
        
        if any(word in query_lower for word in ['new', 'create', 'add', 'make']):
            adjustments['create'] += 0.2
        
        if any(word in query_lower for word in ['delete', 'remove', 'clear']):
            adjustments['delete'] += 0.2
        
        return adjustments
    
    def _build_keyword_model(self) -> Dict[str, float]:
        """Build a keyword importance model"""
        return {
            # High importance action keywords
            'urgent': 0.9, 'important': 0.85, 'priority': 0.8, 'asap': 0.85,
            'today': 0.7, 'tomorrow': 0.6, 'send': 0.75, 'schedule': 0.75,
            'create': 0.8, 'delete': 0.8, 'update': 0.7,
            
            # Medium importance
            'email': 0.6, 'calendar': 0.6, 'task': 0.6, 'meeting': 0.65,
            'event': 0.65, 'reminder': 0.65,
            
            # Lower importance
            'show': 0.4, 'list': 0.4, 'view': 0.4, 'check': 0.5, 'look': 0.35,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get NLP processor statistics"""
        cache_info = self._extract_keywords_cached.cache_info()
        return {
            'queries_processed': self.stats['queries_processed'],
            'avg_sentiment_score': f"{self.stats['avg_sentiment_score']:.2f}",
            'avg_complexity': f"{self.stats['avg_complexity']:.2f}",
            'cache_hits': cache_info.hits,
            'cache_misses': cache_info.misses,
            'cache_size': cache_info.currsize
        }
