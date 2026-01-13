"""
Incremental Learner - Continuous Fact Extraction

Observes every interaction and proactively extracts facts to build
long-term memory over time. This enables the memory to grow incrementally
from natural conversations without explicit "learn this" commands.

Usage:
    learner = IncrementalLearner(enhanced_memory, extractor)
    
    # On every user message
    facts = await learner.observe_message(user_id, message, context)
    
    # On every assistant response
    facts = await learner.observe_response(user_id, response, query)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import asyncio
import re

from src.utils.logger import setup_logger
from .memory_config import (
    MIN_MESSAGE_LENGTH_FOR_EXTRACTION,
    MAX_FACTS_PER_MESSAGE,
    AUTO_LEARN_CONFIDENCE_THRESHOLD,
    REINFORCEMENT_BOOST,
)

logger = setup_logger(__name__)


@dataclass
class ExtractedFact:
    """A fact extracted from conversation."""
    content: str
    category: str
    confidence: float
    source: str  # 'user_statement', 'assistant_inference', 'explicit_preference'
    entities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningResult:
    """Result of incremental learning operation."""
    facts_extracted: int
    facts_learned: int
    facts_reinforced: int
    facts_skipped: int
    details: List[Dict[str, Any]] = field(default_factory=list)


class IncrementalLearner:
    """
    Continuously extracts and learns facts from conversations.
    
    This is the "always-on" learning component that makes the memory
    system grow smarter over time without explicit commands.
    
    Extraction strategies:
    1. Preference detection ("I like...", "I prefer...", "I always...")
    2. Entity relationships ("John is my manager", "Sarah works at...")
    3. Behavioral patterns (repeated actions, time preferences)
    4. Explicit statements ("Remember that...", "Note that...")
    """
    
    # Preference patterns
    PREFERENCE_PATTERNS = [
        (r'\bi (?:really )?(?:like|love|enjoy|prefer)\s+(.+?)(?:\.|,|$)', 'preference', 0.8),
        (r'\bi (?:don\'t|do not|never|hate|dislike)\s+(.+?)(?:\.|,|$)', 'preference', 0.8),
        (r'\bi always\s+(.+?)(?:\.|,|$)', 'preference', 0.7),
        (r'\bi usually\s+(.+?)(?:\.|,|$)', 'preference', 0.65),
        (r'my favorite\s+(.+?)\s+is\s+(.+?)(?:\.|,|$)', 'preference', 0.85),
    ]
    
    # Relationship patterns
    RELATIONSHIP_PATTERNS = [
        (r'(\w+)\s+is my\s+(manager|boss|colleague|friend|partner|assistant)', 'relationship', 0.9),
        (r'(\w+)\s+works (?:at|for|with)\s+(.+?)(?:\.|,|$)', 'relationship', 0.75),
        (r'i work (?:at|for|with)\s+(.+?)(?:\.|,|$)', 'work', 0.85),
    ]
    
    # Explicit memory patterns
    EXPLICIT_PATTERNS = [
        (r'remember that\s+(.+?)(?:\.|$)', 'explicit', 0.95),
        (r'note that\s+(.+?)(?:\.|$)', 'explicit', 0.9),
        (r'keep in mind\s+(.+?)(?:\.|$)', 'explicit', 0.9),
        (r'for future reference[,:]?\s+(.+?)(?:\.|$)', 'explicit', 0.9),
    ]
    
    # Schedule/time patterns
    SCHEDULE_PATTERNS = [
        (r'i (?:have|\'ve got) (?:a )?(.+?) (?:at|on|every)\s+(.+?)(?:\.|,|$)', 'schedule', 0.75),
        (r'my (.+?) (?:is|are) (?:on|at)\s+(.+?)(?:\.|,|$)', 'schedule', 0.7),
    ]
    
    def __init__(
        self,
        enhanced_memory: Optional[Any] = None,
        fact_extractor: Optional[Any] = None,
        llm: Optional[Any] = None
    ):
        """
        Initialize incremental learner.
        
        Args:
            enhanced_memory: EnhancedSemanticMemory for storing facts
            fact_extractor: FactExtractor for NLP-based extraction
            llm: Optional LLM for complex extraction
        """
        self.memory = enhanced_memory
        self.extractor = fact_extractor
        self.llm = llm
        
        # Compile patterns for efficiency
        self._compiled_patterns = self._compile_patterns()
        
        # Track recent extractions to avoid duplicates
        self._recent_extractions: Dict[int, List[str]] = {}  # user_id -> recent fact hashes
        
        logger.info("IncrementalLearner initialized")
    
    def _compile_patterns(self) -> Dict[str, List[Tuple[re.Pattern, str, float]]]:
        """Compile regex patterns for faster matching."""
        compiled = {
            'preference': [],
            'relationship': [],
            'explicit': [],
            'schedule': [],
        }
        
        for pattern, category, confidence in self.PREFERENCE_PATTERNS:
            compiled['preference'].append((re.compile(pattern, re.IGNORECASE), category, confidence))
        
        for pattern, category, confidence in self.RELATIONSHIP_PATTERNS:
            compiled['relationship'].append((re.compile(pattern, re.IGNORECASE), category, confidence))
            
        for pattern, category, confidence in self.EXPLICIT_PATTERNS:
            compiled['explicit'].append((re.compile(pattern, re.IGNORECASE), category, confidence))
            
        for pattern, category, confidence in self.SCHEDULE_PATTERNS:
            compiled['schedule'].append((re.compile(pattern, re.IGNORECASE), category, confidence))
        
        return compiled
    
    async def observe_message(
        self,
        user_id: int,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> LearningResult:
        """
        Observe a user message and extract/learn facts.
        
        Args:
            user_id: User ID
            message: The user's message
            context: Optional context (current task, entities, etc.)
            
        Returns:
            LearningResult with extraction statistics
        """
        result = LearningResult(
            facts_extracted=0,
            facts_learned=0,
            facts_reinforced=0,
            facts_skipped=0
        )
        
        # Skip very short messages
        if len(message.strip()) < MIN_MESSAGE_LENGTH_FOR_EXTRACTION:
            return result
        
        # Extract facts using patterns
        extracted_facts = self._extract_from_patterns(message)
        
        # Use fact extractor if available for deeper extraction
        if self.extractor:
            try:
                additional = await self._extract_with_nlp(message)
                extracted_facts.extend(additional)
            except Exception as e:
                logger.warning(f"NLP extraction failed: {e}")
        
        result.facts_extracted = len(extracted_facts)
        
        # Limit facts per message
        extracted_facts = extracted_facts[:MAX_FACTS_PER_MESSAGE]
        
        # Learn each fact
        for fact in extracted_facts:
            try:
                learn_result = await self._learn_fact(user_id, fact)
                if learn_result == 'learned':
                    result.facts_learned += 1
                elif learn_result == 'reinforced':
                    result.facts_reinforced += 1
                else:
                    result.facts_skipped += 1
                    
                result.details.append({
                    'content': fact.content,
                    'category': fact.category,
                    'result': learn_result
                })
            except Exception as e:
                logger.error(f"Failed to learn fact: {e}")
                result.facts_skipped += 1
        
        logger.debug(f"IncrementalLearner: extracted={result.facts_extracted}, learned={result.facts_learned}")
        return result
    
    def _extract_from_patterns(self, message: str) -> List[ExtractedFact]:
        """Extract facts using compiled patterns."""
        facts = []
        
        for pattern_type, patterns in self._compiled_patterns.items():
            for regex, category, base_confidence in patterns:
                matches = regex.finditer(message)
                for match in matches:
                    # Build fact content from match
                    content = self._build_fact_content(pattern_type, match)
                    if content:
                        facts.append(ExtractedFact(
                            content=content,
                            category=category,
                            confidence=base_confidence,
                            source=f'pattern:{pattern_type}',
                            entities=self._extract_entities(match.group(0))
                        ))
        
        return facts
    
    def _build_fact_content(self, pattern_type: str, match: re.Match) -> Optional[str]:
        """Build fact content from regex match."""
        try:
            if pattern_type == 'preference':
                # "I like coffee" -> "User prefers coffee"
                preference = match.group(1).strip()
                if 'don\'t' in match.group(0).lower() or 'not' in match.group(0).lower():
                    return f"User does not prefer {preference}"
                return f"User prefers {preference}"
                
            elif pattern_type == 'relationship':
                # "John is my manager" -> "John is the user's manager"
                groups = match.groups()
                if len(groups) >= 2:
                    return f"{groups[0]} is the user's {groups[1]}"
                return None
                
            elif pattern_type == 'explicit':
                # "Remember that X" -> "X"
                return match.group(1).strip()
                
            elif pattern_type == 'schedule':
                # "I have a meeting at 3pm" -> "User has meeting at 3pm"
                groups = match.groups()
                if len(groups) >= 2:
                    return f"User has {groups[0]} scheduled for {groups[1]}"
                return None
                
            return match.group(0)
        except Exception:
            return None
    
    def _extract_entities(self, text: str) -> List[str]:
        """Extract named entities from text using shared utility."""
        from .memory_utils import extract_entities
        return extract_entities(text)
    
    async def _extract_with_nlp(self, message: str) -> List[ExtractedFact]:
        """Use NLP extractor for deeper fact extraction."""
        if not self.extractor:
            return []
        
        try:
            extracted = self.extractor.extract(message)
            return [
                ExtractedFact(
                    content=fact.get('content', ''),
                    category=fact.get('category', 'general'),
                    confidence=fact.get('confidence', 0.6),
                    source='nlp_extractor',
                    entities=fact.get('entities', [])
                )
                for fact in extracted
                if fact.get('content')
            ]
        except Exception:
            return []
    
    async def _learn_fact(self, user_id: int, fact: ExtractedFact) -> str:
        """
        Learn a fact using the memory system.
        
        Returns:
            'learned' - new fact stored
            'reinforced' - existing fact reinforced
            'skipped' - fact not stored (low confidence, duplicate, etc.)
        """
        # Check confidence threshold
        if fact.confidence < AUTO_LEARN_CONFIDENCE_THRESHOLD:
            return 'skipped'
        
        # Check for recent duplicate
        fact_hash = hash(fact.content.lower())
        if user_id in self._recent_extractions:
            if fact_hash in self._recent_extractions[user_id]:
                return 'skipped'
        
        # Store fact
        if self.memory:
            try:
                result = await self.memory.learn_fact_enhanced(
                    user_id=user_id,
                    content=fact.content,
                    category=fact.category,
                    source=fact.source,
                    confidence=fact.confidence,
                    entities=fact.entities
                )
                
                # Track to avoid duplicates
                if user_id not in self._recent_extractions:
                    self._recent_extractions[user_id] = []
                self._recent_extractions[user_id].append(fact_hash)
                # Keep only last 100 hashes
                self._recent_extractions[user_id] = self._recent_extractions[user_id][-100:]
                
                if result.validation_result == 'reinforcement':
                    return 'reinforced'
                return 'learned'
            except Exception as e:
                logger.error(f"Memory store failed: {e}")
                return 'skipped'
        
        return 'skipped'
    
    async def feedback(
        self,
        user_id: int,
        fact_id: int,
        was_useful: bool
    ) -> bool:
        """
        Provide feedback on a fact's usefulness.
        
        This enables the memory to learn from usage:
        - Useful facts get reinforced (confidence boost)
        - Unhelpful facts decay (confidence penalty)
        
        Args:
            user_id: User ID
            fact_id: Fact ID to provide feedback on
            was_useful: Whether the fact was useful
            
        Returns:
            True if feedback was recorded
        """
        if not self.memory:
            return False
        
        try:
            if was_useful:
                # Reinforce the fact
                await self.memory.base_memory.reinforce_fact(fact_id, boost=REINFORCEMENT_BOOST)
                logger.debug(f"Reinforced fact {fact_id}")
            else:
                # Decay the fact
                await self.memory.base_memory.decay_fact(fact_id, penalty=0.2)
                logger.debug(f"Decayed fact {fact_id}")
            return True
        except Exception as e:
            logger.error(f"Feedback failed: {e}")
            return False


# ============================================================================
# Singleton
# ============================================================================

_learner_instance: Optional[IncrementalLearner] = None


def get_incremental_learner() -> Optional[IncrementalLearner]:
    """Get the global IncrementalLearner instance."""
    return _learner_instance


def init_incremental_learner(
    enhanced_memory: Optional[Any] = None,
    fact_extractor: Optional[Any] = None,
    llm: Optional[Any] = None
) -> IncrementalLearner:
    """Initialize and return the global IncrementalLearner."""
    global _learner_instance
    _learner_instance = IncrementalLearner(
        enhanced_memory=enhanced_memory,
        fact_extractor=fact_extractor,
        llm=llm
    )
    return _learner_instance
