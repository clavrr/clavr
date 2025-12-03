"""
NLP Processing Module

Provides advanced natural language processing capabilities for the AnalyzerRole
including sentiment analysis, entity linking, and intent confidence scoring.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import re
from datetime import datetime


class SentimentType(str, Enum):
    """Sentiment types for queries"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    CONFUSED = "confused"


@dataclass
class EntityLink:
    """Linked entity with metadata"""
    text: str
    entity_type: str
    confidence: float
    resolved_value: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NLPAnalysisResult:
    """Result of advanced NLP analysis"""
    query: str
    sentiment: SentimentType
    sentiment_score: float
    entities: List[EntityLink] = field(default_factory=list)
    keywords: List[Tuple[str, float]] = field(default_factory=list)  # (keyword, importance)
    language_complexity: float = 0.0
    intent_confidence_adjustments: Dict[str, float] = field(default_factory=dict)
    analysis_timestamp: datetime = field(default_factory=datetime.now)


class NLPProcessor:
    """
    Advanced NLP processing for query understanding
    
    Provides:
    - Sentiment analysis and emotional context
    - Entity linking and resolution
    - Keyword extraction with importance scoring
    - Language complexity assessment
    - Intent confidence adjustments
    """
    
    # Sentiment indicators
    POSITIVE_WORDS = {
        'please', 'thank', 'great', 'good', 'excellent', 'perfect', 'amazing',
        'wonderful', 'fantastic', 'awesome', 'happy', 'love', 'best', 'quickly',
        'asap', 'urgent', 'important', 'priority'
    }
    
    NEGATIVE_WORDS = {
        'urgent', 'emergency', 'missing', 'lost', 'broken', 'error', 'problem',
        'issue', 'failed', 'fail', 'crash', 'slow', 'delay', 'late', 'worried',
        'confused', 'not', 'no', 'never', 'cant', 'can\'t', 'won\'t', 'wont'
    }
    
    CONFUSED_WORDS = {
        'what', 'which', 'how', 'where', 'when', 'why', 'confused', 'unclear',
        'help', 'explain', 'understand', 'not sure', 'maybe', 'possibly'
    }
    
    # Entity type patterns
    EMAIL_PATTERNS = {
        'email_address': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'email_domain': r'@([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})',
    }
    
    TIME_PATTERNS = {
        'date_iso': r'\d{4}-\d{2}-\d{2}',
        'date_us': r'\d{1,2}/\d{1,2}/\d{2,4}',
        'time_24h': r'\d{1,2}:\d{2}(?::\d{2})?',
    }
    
    PERSON_INDICATORS = {
        'prefixes': ['mr.', 'mrs.', 'ms.', 'dr.', 'prof.'],
        'name_patterns': r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize NLP processor"""
        self.config = config or {}
        self.entity_cache: Dict[str, EntityLink] = {}
        self.keyword_importance_model = self._build_keyword_model()
        self.stats = {
            'queries_processed': 0,
            'avg_sentiment_score': 0.0,
            'avg_complexity': 0.0,
        }
    
    async def analyze(self, query: str) -> NLPAnalysisResult:
        """
        Perform comprehensive NLP analysis on a query
        
        Args:
            query: The query to analyze
            
        Returns:
            NLPAnalysisResult with detailed analysis
        """
        self.stats['queries_processed'] += 1
        
        # Perform analyses in parallel conceptually
        sentiment = self._analyze_sentiment(query)
        entities = self._extract_and_link_entities(query)
        keywords = self._extract_keywords(query)
        complexity = self._assess_language_complexity(query)
        intent_adjustments = self._calculate_intent_adjustments(query, sentiment, entities)
        
        result = NLPAnalysisResult(
            query=query,
            sentiment=sentiment['type'],
            sentiment_score=sentiment['score'],
            entities=entities,
            keywords=keywords,
            language_complexity=complexity,
            intent_confidence_adjustments=intent_adjustments
        )
        
        # Update stats
        self.stats['avg_sentiment_score'] = (
            self.stats['avg_sentiment_score'] * 0.9 + sentiment['score'] * 0.1
        )
        self.stats['avg_complexity'] = (
            self.stats['avg_complexity'] * 0.9 + complexity * 0.1
        )
        
        return result
    
    def _analyze_sentiment(self, query: str) -> Dict[str, Any]:
        """
        Analyze sentiment of query
        
        Returns confidence-scored sentiment type
        """
        query_lower = query.lower()
        
        positive_count = sum(1 for word in self.POSITIVE_WORDS if word in query_lower)
        negative_count = sum(1 for word in self.NEGATIVE_WORDS if word in query_lower)
        confused_count = sum(1 for word in self.CONFUSED_WORDS if word in query_lower)
        
        total = positive_count + negative_count + confused_count
        
        if total == 0:
            return {
                'type': SentimentType.NEUTRAL,
                'score': 0.5,
                'breakdown': {'positive': 0, 'negative': 0, 'confused': 0}
            }
        
        # Determine dominant sentiment
        if confused_count > positive_count and confused_count > negative_count:
            sentiment_type = SentimentType.CONFUSED
            score = 0.3 + (confused_count / total) * 0.4
        elif negative_count > positive_count:
            sentiment_type = SentimentType.NEGATIVE
            score = 0.3 - (negative_count / total) * 0.3
        elif positive_count > 0:
            sentiment_type = SentimentType.POSITIVE
            score = 0.7 + (positive_count / total) * 0.3
        else:
            sentiment_type = SentimentType.NEUTRAL
            score = 0.5
        
        return {
            'type': sentiment_type,
            'score': max(0.0, min(1.0, score)),
            'breakdown': {
                'positive': positive_count,
                'negative': negative_count,
                'confused': confused_count
            }
        }
    
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
            matches = re.finditer(pattern, query)
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
            if text[0].isupper() and len(text) > 2:
                entity = EntityLink(
                    text=text,
                    entity_type='person_name',
                    confidence=0.6,  # Lower confidence for names
                    metadata={'capitalized': True}
                )
                # Avoid duplicates
                if not any(e.text == text and e.entity_type == 'person_name' for e in entities):
                    entities.append(entity)
        
        return entities
    
    def _extract_keywords(self, query: str) -> List[Tuple[str, float]]:
        """
        Extract keywords with importance scoring
        
        Returns list of (keyword, importance) tuples sorted by importance
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
        
        # Filter stop words
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        
        # Score keywords based on importance model
        scored_keywords = []
        for keyword in set(keywords):  # Remove duplicates
            frequency = keywords.count(keyword)
            importance = self.keyword_importance_model.get(keyword, 0.5)
            combined_score = (frequency * 0.4 + importance * 0.6)
            scored_keywords.append((keyword, combined_score))
        
        # Sort by score and return top keywords
        return sorted(scored_keywords, key=lambda x: x[1], reverse=True)[:10]
    
    def _assess_language_complexity(self, query: str) -> float:
        """
        Assess language complexity on scale 0-1
        
        Factors:
        - Sentence length
        - Word length distribution
        - Subordinate clauses
        - Technical jargon
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
        
        # Technical terms
        tech_terms = {'api', 'sync', 'cache', 'database', 'query', 'filter', 'parse'}
        tech_count = sum(1 for term in tech_terms if term in query.lower())
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
        
        Returns dict mapping intent types to confidence adjustments
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
            # Increase confidence in search/analyze
            adjustments['search'] += 0.15
            adjustments['analyze'] += 0.1
        
        # Entity-based adjustments
        if len(entities) > 0:
            # More entities = more specific intent
            adjustments['search'] += 0.1
            if any(e.entity_type == 'email_address' for e in entities):
                adjustments['create'] -= 0.05  # Less likely to create with specific email
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
        """
        Build a keyword importance model
        
        Maps common keywords to their inherent importance
        """
        return {
            # High importance action keywords
            'urgent': 0.9,
            'important': 0.85,
            'priority': 0.8,
            'asap': 0.85,
            'today': 0.7,
            'tomorrow': 0.6,
            'send': 0.75,
            'schedule': 0.75,
            'create': 0.8,
            'delete': 0.8,
            'update': 0.7,
            
            # Medium importance
            'email': 0.6,
            'calendar': 0.6,
            'task': 0.6,
            'meeting': 0.65,
            'event': 0.65,
            'reminder': 0.65,
            
            # Lower importance
            'show': 0.4,
            'list': 0.4,
            'view': 0.4,
            'check': 0.5,
            'look': 0.35,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get NLP processor statistics"""
        return {
            'queries_processed': self.stats['queries_processed'],
            'avg_sentiment_score': f"{self.stats['avg_sentiment_score']:.2f}",
            'avg_complexity': f"{self.stats['avg_complexity']:.2f}",
            'cached_entities': len(self.entity_cache)
        }
