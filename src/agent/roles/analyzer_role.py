"""
Analyzer Role: Understand query intent and complexity

Responsible for:
- Classifying user query intent
- Detecting domains involved
- Extracting entities
- Assessing query complexity
- Determining if multi-step reasoning required
- Advanced NLP processing for sentiment and entity linking
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

# Import enhanced NLP processing
from ..capabilities.nlp_processor import NLPProcessor

# Import intent classification from agent/intent/ module
from ..intent import classify_query_intent


@dataclass
class QueryAnalysis:
    """Result of analyzing a user query"""
    query: str
    intent: str
    domains: List[str] = field(default_factory=list)
    complexity_score: float = 0.0
    entities: Dict[str, Any] = field(default_factory=dict)
    is_multi_step: bool = False
    confidence: float = 0.0
    sentiment: Optional[str] = None
    sentiment_score: float = 0.5
    extracted_entities: List[Dict[str, Any]] = field(default_factory=list)
    keywords: List[tuple] = field(default_factory=list)
    language_complexity: float = 0.0
    analysis_timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Validate analysis results"""
        if not 0 <= self.complexity_score <= 1:
            self.complexity_score = min(1.0, max(0.0, self.complexity_score))
        if not 0 <= self.confidence <= 1:
            self.confidence = min(1.0, max(0.0, self.confidence))


class AnalyzerRole:
    """
    Analyzer Role: Understands user query intent and complexity
    
    The Analyzer is responsible for breaking down user queries and understanding:
    - What the user wants to accomplish (intent)
    - Which domains are involved (email, calendar, tasks)
    - What entities are relevant (dates, people, items)
    - How complex the query is (single-step vs multi-step)
    - How confident we are in our analysis
    
    This role uses the intent_patterns module to perform analysis.
    """
    
    # Domain indicators for different domains
    EMAIL_INDICATORS = {
        'keywords': ['email', 'mail', 'message', 'send', 'forward', 'reply', 'inbox', 'unread', 'archive'],
        'domains': ['email', 'gmail']
    }
    
    CALENDAR_INDICATORS = {
        'keywords': ['calendar', 'meeting', 'event', 'schedule', 'appointment', 'busy', 'available', 'when'],
        'domains': ['calendar', 'google_calendar']
    }
    
    TASK_INDICATORS = {
        'keywords': ['task', 'tasks', 'todo', 'todos', 'remind', 'reminder', 'checklist', 'deadline', 'assignment'],
        'domains': ['tasks', 'google_tasks']
    }
    
    CROSS_DOMAIN_KEYWORDS = {
        'keywords': ['between', 'across', 'both', 'all', 'from', 'sync', 'connect', 'related'],
        'indicates_multi_domain': True
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize AnalyzerRole
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.analysis_cache: Dict[str, QueryAnalysis] = {}
        self.stats = {
            'queries_analyzed': 0,
            'multi_step_queries': 0,
            'single_step_queries': 0,
            'avg_confidence': 0.0
        }
        self.nlp_processor = NLPProcessor()
    
    async def analyze(self, query: str) -> QueryAnalysis:
        """
        Analyze a user query to understand intent and complexity
        
        Args:
            query: The user query string
            
        Returns:
            QueryAnalysis object with detailed breakdown
        """
        # Check cache first
        if query in self.analysis_cache:
            return self.analysis_cache[query]
        
        self.stats['queries_analyzed'] += 1
        
        # Step 1: Clean and normalize query
        normalized_query = self._normalize_query(query)
        
        # Step 2: Classify intent using agent/intent/ module
        intent_result = classify_query_intent(query)
        primary_intent = intent_result.get('primary_intent', 'general_query')
        intent_confidence_str = intent_result.get('confidence', 'low')
        detected_domains = intent_result.get('domain', 'general')
        
        # Extract action intent from primary_intent (e.g., 'email_management' -> 'search', 'task_creation' -> 'create')
        intent = self._extract_action_intent(primary_intent)
        
        # Step 3: Detect domains involved (use agent/intent/ result, fallback to manual detection)
        domains = self._detect_domains(normalized_query, intent, detected_domain=detected_domains)
        
        # Step 4: Extract entities
        entities = self._extract_entities(normalized_query)
        
        # Step 5: Assess complexity
        complexity_score, is_multi_step = self._assess_complexity(
            normalized_query, intent, domains, entities
        )
        
        # Step 6: Calculate confidence (use intent confidence from agent/intent/)
        confidence = self._calculate_confidence(
            intent, domains, entities, complexity_score, 
            intent_confidence_str=intent_confidence_str
        )
        
        # Enhanced NLP processing
        sentiment = None
        sentiment_score = 0.5
        extracted_entities = []
        keywords = []
        language_complexity = 0.0
        intent_adjustments = {}
        
        if self.nlp_processor:
            nlp_result = await self.nlp_processor.analyze(query)
            sentiment = nlp_result.sentiment.value
            sentiment_score = nlp_result.sentiment_score
            extracted_entities = [
                {
                    'text': e.text,
                    'type': e.entity_type,
                    'confidence': e.confidence,
                    'resolved_value': e.resolved_value
                }
                for e in nlp_result.entities
            ]
            keywords = nlp_result.keywords
            language_complexity = nlp_result.language_complexity
            intent_adjustments = nlp_result.intent_confidence_adjustments
            
            # Apply intent adjustments to confidence
            if intent in intent_adjustments:
                confidence = max(0.1, min(1.0, confidence + intent_adjustments[intent]))
        
        # Create analysis result
        analysis = QueryAnalysis(
            query=query,
            intent=intent,
            domains=domains,
            complexity_score=complexity_score,
            entities=entities,
            is_multi_step=is_multi_step,
            confidence=confidence,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            extracted_entities=extracted_entities,
            keywords=keywords,
            language_complexity=language_complexity
        )
        
        # Cache result
        self.analysis_cache[query] = analysis
        
        # Update stats
        if is_multi_step:
            self.stats['multi_step_queries'] += 1
        else:
            self.stats['single_step_queries'] += 1
        
        return analysis
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query for analysis"""
        return query.lower().strip()
    
    def _extract_action_intent(self, primary_intent: str) -> str:
        """
        Extract action intent from primary_intent returned by classify_query_intent().
        
        Maps domain-specific intents (e.g., 'email_management', 'task_creation') 
        to action intents (e.g., 'search', 'create') expected by QueryAnalysis.
        
        Args:
            primary_intent: Primary intent from classify_query_intent() 
                          (e.g., 'email_management', 'task_creation', 'calendar_query')
        
        Returns:
            Action intent string ('search', 'create', 'update', 'delete', 'analyze', 'query')
        """
        # Map primary_intent to action intent
        # Note: This maps domain-specific intents from classify_query_intent() 
        # to action intents expected by QueryAnalysis
        intent_mapping = {
            # Email intents
            'email_management': 'search',    # Managing emails (search, list, etc.)
            'email_operation': 'search',      # Email operations (find, get, etc.)
            # Task intents
            'task_creation': 'create',       # Creating tasks
            'task_analysis': 'analyze',      # Analyzing tasks
            'task_listing': 'search',        # Listing/searching tasks
            # Calendar intents
            'calendar_query': 'search',      # Querying calendar
            'calendar_management': 'create',  # Managing calendar (create events)
            # General intents
            'analysis': 'analyze',           # General analysis
            'summarization': 'analyze',      # Summarization
            'general_query': 'query'         # General/ambiguous query
        }
        
        return intent_mapping.get(primary_intent, 'query')
    
    def _detect_domains(self, query: str, intent: str, detected_domain: str = None) -> List[str]:
        """
        Detect which domains are involved in the query.
        
        Uses domain from agent/intent/ classify_query_intent() as primary source,
        with fallback to manual detection for edge cases.
        
        Args:
            query: Query string
            intent: Action intent (for fallback)
            detected_domain: Domain detected by classify_query_intent() (e.g., 'email', 'task', 'calendar')
        
        Returns:
            List of domain strings
        """
        domains = []
        query_lower = query.lower()
        
        # Use domain from agent/intent/ as primary source
        if detected_domain and detected_domain != 'general':
            # Normalize domain name (e.g., 'task' -> 'tasks')
            if detected_domain == 'task':
                detected_domain = 'tasks'
            domains.append(detected_domain)
        
        # Fallback: Manual detection for edge cases (e.g., Notion, multi-domain queries)
        # Check Notion indicators (not covered by agent/intent/)
        notion_keywords = ['notion', 'page', 'database', 'notion page', 'notion database']
        if any(keyword in query_lower for keyword in notion_keywords):
            if 'notion' not in domains:
                domains.append('notion')
        
        # If no domains detected, use fallback
        if not domains:
            domains = self._infer_domain_from_intent(intent)
        
        return domains
    
    def _infer_domain_from_intent(self, intent: str) -> List[str]:
        """Infer domain from intent when keywords don't match"""
        # This is a fallback - in production, we'd use the LLM
        # For now, return a default multi-domain approach
        return ['email', 'calendar', 'tasks']
    
    def _extract_entities(self, query: str) -> Dict[str, Any]:
        """Extract named entities from query"""
        entities = {
            'time_references': self._extract_time_refs(query),
            'people': self._extract_people(query),
            'keywords': self._extract_keywords(query),
        }
        return entities
    
    def _extract_time_refs(self, query: str) -> List[str]:
        """Extract time references from query"""
        time_keywords = [
            'today', 'tomorrow', 'yesterday',
            'week', 'month', 'year',
            'morning', 'afternoon', 'evening',
            'next', 'last', 'this',
            'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
            'january', 'february', 'march', 'april', 'may', 'june',
            'july', 'august', 'september', 'october', 'november', 'december'
        ]
        
        found_times = []
        query_lower = query.lower()
        for keyword in time_keywords:
            if keyword in query_lower:
                found_times.append(keyword)
        return found_times
    
    def _extract_people(self, query: str) -> List[str]:
        """Extract people references from query"""
        # Simple heuristic: look for quoted names or common person indicators
        people = []
        # In production, use NER (Named Entity Recognition)
        return people
    
    def _extract_keywords(self, query: str) -> List[str]:
        """Extract important keywords from query"""
        # Filter out common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'is', 'are', 'from', 'to', 'in', 'on', 'at'}
        words = query.lower().split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return keywords
    
    def _assess_complexity(
        self,
        query: str,
        intent: str,
        domains: List[str],
        entities: Dict[str, Any]
    ) -> tuple[float, bool]:
        """Assess query complexity and determine if multi-step"""
        score = 0.0
        
        # Multiple domains add complexity
        score += len(domains) * 0.2
        
        # Multiple entities add complexity
        total_entities = sum(len(v) if isinstance(v, list) else 1 for v in entities.values())
        score += min(total_entities * 0.1, 0.3)
        
        # Certain intents are more complex
        complex_intents = {'analyze', 'update', 'delete'}
        if intent in complex_intents:
            score += 0.2
        
        # Keywords indicating multi-step
        multi_step_keywords = ['and then', 'after', 'before', 'then', 'create based on']
        if any(kw in query.lower() for kw in multi_step_keywords):
            score += 0.3
        
        # Normalize to 0-1 range
        score = min(score, 1.0)
        
        # Determine if multi-step (threshold at 0.4)
        is_multi_step = score >= 0.4
        
        return score, is_multi_step
    
    def _calculate_confidence(
        self,
        intent: str,
        domains: List[str],
        entities: Dict[str, Any],
        complexity_score: float,
        intent_confidence_str: str = 'low'
    ) -> float:
        """
        Calculate confidence in the analysis.
        
        Uses intent confidence from agent/intent/ classify_query_intent() as primary signal,
        with additional adjustments based on action intent, domains, and entities.
        
        Args:
            intent: Action intent ('search', 'create', 'update', etc.)
            domains: List of detected domains
            entities: Extracted entities
            complexity_score: Query complexity score
            intent_confidence_str: Confidence from classify_query_intent() ('high', 'medium', 'low')
        
        Returns:
            Confidence score (0.0-1.0)
        """
        # Base confidence from agent/intent/ classification
        intent_confidence_map = {
            'high': 0.8,
            'medium': 0.6,
            'low': 0.4
        }
        confidence = intent_confidence_map.get(intent_confidence_str, 0.5)
        
        # Action intent adjustment (refines confidence based on action clarity)
        # Specific actions (create, delete, update) boost confidence
        # Ambiguous actions (query) reduce confidence
        action_adjustment_map = {
            'create': 0.1,   # Clear action - boost
            'delete': 0.1,   # Clear action - boost
            'update': 0.1,   # Clear action - boost
            'search': 0.05,  # Common action - slight boost
            'analyze': 0.0,  # Neutral - no change
            'query': -0.1    # Ambiguous - reduce
        }
        confidence += action_adjustment_map.get(intent, 0.0)
        
        # Complexity adjustment: higher complexity = lower confidence (more ambiguity)
        # Lower complexity = higher confidence (clearer query)
        # Complexity score is 0.0-1.0, so we subtract it (scaled) from confidence
        complexity_penalty = complexity_score * 0.15  # Max 0.15 penalty for very complex queries
        confidence -= complexity_penalty
        
        # More domains = less confidence (ambiguity)
        confidence -= len(domains) * 0.1
        
        # More entities = more confidence (specific query)
        total_entities = sum(len(v) if isinstance(v, list) else 1 for v in entities.values())
        confidence += min(total_entities * 0.05, 0.2)
        
        # Normalize
        confidence = max(0.1, min(confidence, 1.0))
        
        return confidence
    
    def get_stats(self) -> Dict[str, Any]:
        """Get analyzer statistics"""
        total = self.stats['queries_analyzed']
        if total > 0:
            multi_step_pct = (self.stats['multi_step_queries'] / total) * 100
        else:
            multi_step_pct = 0
        
        return {
            'total_analyzed': total,
            'multi_step_queries': self.stats['multi_step_queries'],
            'single_step_queries': self.stats['single_step_queries'],
            'multi_step_percentage': f"{multi_step_pct:.1f}%",
            'cache_size': len(self.analysis_cache)
        }
    
    def clear_cache(self):
        """Clear the analysis cache"""
        self.analysis_cache.clear()
