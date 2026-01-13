"""
Fact Inference Engine

Derives new facts from existing knowledge through pattern recognition,
logical inference, and semantic reasoning.

This enables the memory system to "connect the dots" and surface
insights that weren't explicitly stated but can be inferred from
patterns in existing facts.

Inference types:
1. Pattern-based: Repeated behaviors → preferences
2. Relationship: Meeting patterns → collaborator identification
3. Temporal: Time patterns → scheduling preferences
4. Semantic: Category membership → broader generalizations
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Set
from enum import Enum
import re

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class InferenceType(str, Enum):
    """Types of inferences the engine can make."""
    PATTERN = "pattern"          # From repeated behaviors
    RELATIONSHIP = "relationship" # From interaction patterns
    TEMPORAL = "temporal"        # From time-based patterns
    SEMANTIC = "semantic"        # From category/meaning
    COMPOSITE = "composite"      # Combining multiple facts


class ConfidenceLevel(str, Enum):
    """Confidence levels for inferred facts."""
    HIGH = "high"           # 0.85-1.0
    MEDIUM = "medium"       # 0.6-0.84
    LOW = "low"             # 0.4-0.59
    SPECULATIVE = "speculative"  # < 0.4


@dataclass
class InferredFact:
    """A fact derived through inference."""
    content: str
    inference_type: InferenceType
    confidence: float
    confidence_level: ConfidenceLevel
    
    # What this inference is based on
    supporting_facts: List[Dict[str, Any]] = field(default_factory=list)
    supporting_fact_ids: List[int] = field(default_factory=list)
    
    # Reasoning chain
    reasoning: str = ""
    
    # Entities involved
    entities: List[str] = field(default_factory=list)
    
    # Category suggestion
    suggested_category: str = "inferred"
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    rule_applied: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "inference_type": self.inference_type.value,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level.value,
            "supporting_fact_ids": self.supporting_fact_ids,
            "reasoning": self.reasoning,
            "entities": self.entities,
            "suggested_category": self.suggested_category,
            "rule_applied": self.rule_applied
        }


@dataclass
class InferenceRule:
    """A rule for making inferences."""
    name: str
    description: str
    inference_type: InferenceType
    
    # Pattern to match (simplified regex or keyword-based)
    pattern: str
    
    # Template for generating inferred fact
    output_template: str
    
    # Minimum facts needed to trigger
    min_supporting_facts: int = 2
    
    # Base confidence when triggered
    base_confidence: float = 0.7
    
    # Category for output
    output_category: str = "inferred"


class FactInferenceEngine:
    """
    Derives new facts from existing knowledge.
    
    The engine applies inference rules to find patterns in existing
    facts and generates new inferred facts with provenance tracking.
    """
    
    def __init__(self, llm: Optional[Any] = None):
        """
        Initialize the inference engine.
        
        Args:
            llm: Optional LLM for complex semantic inference
        """
        self.llm = llm
        self._rules = self._build_default_rules()
    
    def _build_default_rules(self) -> List[InferenceRule]:
        """Build default inference rules."""
        return [
            # Preference patterns
            InferenceRule(
                name="repeated_time_preference",
                description="Infer time preference from repeated scheduling patterns",
                inference_type=InferenceType.TEMPORAL,
                pattern=r"(morning|afternoon|evening)",
                output_template="User prefers {pattern} for {category}",
                min_supporting_facts=3,
                base_confidence=0.75,
                output_category="preference"
            ),
            
            # Relationship patterns
            InferenceRule(
                name="frequent_collaborator",
                description="Infer collaborator relationship from frequent mentions",
                inference_type=InferenceType.RELATIONSHIP,
                pattern=r"(?:meeting|email|call|chat).*(?:with|from|to)\s+([A-Z][a-z]+)",
                output_template="{entity} is a frequent collaborator",
                min_supporting_facts=3,
                base_confidence=0.8,
                output_category="relationship"
            ),
            
            # Work style patterns
            InferenceRule(
                name="communication_preference",
                description="Infer communication preferences",
                inference_type=InferenceType.PATTERN,
                pattern=r"(email|slack|teams|call|meeting)",
                output_template="User prefers {pattern} for communication",
                min_supporting_facts=3,
                base_confidence=0.7,
                output_category="preference"
            ),
            
            # Domain expertise
            InferenceRule(
                name="topic_expertise",
                description="Infer expertise from frequent engagement with topic",
                inference_type=InferenceType.SEMANTIC,
                pattern=r"(?:expert|specialist|experienced|senior|lead).*(\w+)",
                output_template="User has expertise in {topic}",
                min_supporting_facts=2,
                base_confidence=0.65,
                output_category="expertise"
            ),
        ]
    
    async def infer_from_facts(
        self,
        facts: List[Dict[str, Any]],
        user_id: int,
        max_inferences: int = 10
    ) -> List[InferredFact]:
        """
        Analyze facts and generate inferred facts.
        
        Args:
            facts: List of existing facts
            user_id: User ID for context
            max_inferences: Maximum inferences to return
            
        Returns:
            List of inferred facts
        """
        inferences = []
        
        # Apply rule-based inference
        rule_inferences = await self._apply_rules(facts)
        inferences.extend(rule_inferences)
        
        # Apply pattern-based inference
        pattern_inferences = await self._infer_from_patterns(facts)
        inferences.extend(pattern_inferences)
        
        # Apply relationship inference
        relationship_inferences = await self._infer_relationships(facts)
        inferences.extend(relationship_inferences)
        
        # Apply LLM-based inference if available
        if self.llm and len(facts) >= 5:
            try:
                llm_inferences = await self._infer_with_llm(facts)
                inferences.extend(llm_inferences)
            except Exception as e:
                logger.debug(f"LLM inference failed: {e}")
        
        # Deduplicate and sort by confidence
        unique_inferences = self._deduplicate_inferences(inferences)
        sorted_inferences = sorted(
            unique_inferences, 
            key=lambda x: x.confidence, 
            reverse=True
        )
        
        return sorted_inferences[:max_inferences]
    
    async def _apply_rules(
        self, 
        facts: List[Dict[str, Any]]
    ) -> List[InferredFact]:
        """Apply inference rules to facts."""
        inferences = []
        
        for rule in self._rules:
            try:
                # Find facts matching this rule's pattern
                matching_facts = []
                pattern = re.compile(rule.pattern, re.IGNORECASE)
                
                for fact in facts:
                    content = fact.get("content", "")
                    if pattern.search(content):
                        matching_facts.append(fact)
                
                # Check if we have enough supporting facts
                if len(matching_facts) >= rule.min_supporting_facts:
                    # Extract entities/patterns from matches
                    extracted = self._extract_from_matches(
                        matching_facts, 
                        pattern
                    )
                    
                    # Generate inferred fact
                    for item, count in extracted.items():
                        confidence = min(
                            1.0, 
                            rule.base_confidence + (count - rule.min_supporting_facts) * 0.05
                        )
                        
                        inference = InferredFact(
                            content=rule.output_template.format(
                                pattern=item,
                                category=rule.output_category,
                                entity=item,
                                topic=item
                            ),
                            inference_type=rule.inference_type,
                            confidence=confidence,
                            confidence_level=self._get_confidence_level(confidence),
                            supporting_facts=matching_facts[:5],
                            supporting_fact_ids=[f.get("id") for f in matching_facts[:5] if f.get("id")],
                            reasoning=f"Based on {count} occurrences matching pattern: {rule.description}",
                            entities=[item] if item.istitle() else [],
                            suggested_category=rule.output_category,
                            rule_applied=rule.name
                        )
                        inferences.append(inference)
                        
            except Exception as e:
                logger.debug(f"Rule {rule.name} failed: {e}")
        
        return inferences
    
    def _extract_from_matches(
        self, 
        facts: List[Dict[str, Any]], 
        pattern: re.Pattern
    ) -> Dict[str, int]:
        """Extract and count pattern matches from facts."""
        counts = {}
        
        for fact in facts:
            content = fact.get("content", "")
            matches = pattern.findall(content)
            
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                match = match.lower().strip()
                if len(match) > 2:
                    counts[match] = counts.get(match, 0) + 1
        
        return counts
    
    async def _infer_from_patterns(
        self, 
        facts: List[Dict[str, Any]]
    ) -> List[InferredFact]:
        """Infer preferences from repeated patterns."""
        inferences = []
        
        # Extract common entities and patterns
        entity_mentions = {}
        topic_mentions = {}
        time_patterns = {}
        
        for fact in facts:
            content = fact.get("content", "").lower()
            
            # Extract time patterns
            for time_word in ["morning", "afternoon", "evening", "night", "early", "late"]:
                if time_word in content:
                    time_patterns[time_word] = time_patterns.get(time_word, 0) + 1
            
            # Extract topics
            for topic in ["email", "meeting", "report", "project", "deadline", "budget"]:
                if topic in content:
                    topic_mentions[topic] = topic_mentions.get(topic, 0) + 1
        
        # Infer from time patterns
        for time_word, count in time_patterns.items():
            if count >= 3:
                confidence = min(0.9, 0.6 + count * 0.05)
                inferences.append(InferredFact(
                    content=f"User shows preference for {time_word} scheduling",
                    inference_type=InferenceType.TEMPORAL,
                    confidence=confidence,
                    confidence_level=self._get_confidence_level(confidence),
                    reasoning=f"Pattern '{time_word}' appeared in {count} facts",
                    suggested_category="preference",
                    rule_applied="time_pattern_detection"
                ))
        
        return inferences
    
    async def _infer_relationships(
        self, 
        facts: List[Dict[str, Any]]
    ) -> List[InferredFact]:
        """Infer relationships from interaction patterns."""
        inferences = []
        
        # Find person names mentioned frequently
        person_mentions = {}
        person_pattern = re.compile(r'\b([A-Z][a-z]+)\b')
        
        for fact in facts:
            content = fact.get("content", "")
            names = person_pattern.findall(content)
            
            # Filter common words that look like names
            excluded = {"User", "The", "This", "That", "Yes", "No", "Please", "Thanks"}
            
            for name in names:
                if name not in excluded and len(name) > 2:
                    person_mentions[name] = person_mentions.get(name, 0) + 1
        
        # Generate relationship inferences for frequent mentions
        for person, count in person_mentions.items():
            if count >= 3:
                confidence = min(0.85, 0.5 + count * 0.1)
                inferences.append(InferredFact(
                    content=f"{person} is a frequent contact or collaborator",
                    inference_type=InferenceType.RELATIONSHIP,
                    confidence=confidence,
                    confidence_level=self._get_confidence_level(confidence),
                    entities=[person],
                    reasoning=f"Name '{person}' mentioned in {count} facts",
                    suggested_category="relationship",
                    rule_applied="person_mention_frequency"
                ))
        
        return inferences
    
    async def _infer_with_llm(
        self, 
        facts: List[Dict[str, Any]]
    ) -> List[InferredFact]:
        """Use LLM for complex semantic inference."""
        if not self.llm:
            return []
        
        # Prepare facts for LLM
        fact_texts = [f.get("content", "") for f in facts[:20]]
        facts_str = "\n".join(f"- {f}" for f in fact_texts)
        
        prompt = f"""Analyze these facts about a user and infer 2-3 new insights that aren't explicitly stated but can be reasonably concluded. For each inference, explain your reasoning.

Facts:
{facts_str}

Respond in this exact format for each inference:
INFERENCE: [the inferred fact]
CONFIDENCE: [high/medium/low]
REASONING: [why this can be inferred]
CATEGORY: [preference/relationship/work_style/expertise]

Only make inferences you're reasonably confident about based on the evidence."""

        try:
            response = await self.llm.agenerate([prompt])
            text = response.generations[0][0].text
            
            # Parse LLM response
            inferences = self._parse_llm_response(text, facts)
            return inferences
            
        except Exception as e:
            logger.debug(f"LLM inference failed: {e}")
            return []
    
    def _parse_llm_response(
        self, 
        text: str, 
        supporting_facts: List[Dict[str, Any]]
    ) -> List[InferredFact]:
        """Parse LLM response into InferredFact objects."""
        inferences = []
        
        # Split by INFERENCE: markers
        sections = text.split("INFERENCE:")
        
        for section in sections[1:]:  # Skip first empty section
            lines = section.strip().split("\n")
            
            if not lines:
                continue
            
            content = lines[0].strip()
            confidence_str = "medium"
            reasoning = ""
            category = "inferred"
            
            for line in lines[1:]:
                line = line.strip()
                if line.startswith("CONFIDENCE:"):
                    confidence_str = line.replace("CONFIDENCE:", "").strip().lower()
                elif line.startswith("REASONING:"):
                    reasoning = line.replace("REASONING:", "").strip()
                elif line.startswith("CATEGORY:"):
                    category = line.replace("CATEGORY:", "").strip().lower()
            
            # Map confidence string to number
            confidence_map = {"high": 0.85, "medium": 0.65, "low": 0.45}
            confidence = confidence_map.get(confidence_str, 0.6)
            
            if content and len(content) > 5:
                inferences.append(InferredFact(
                    content=content,
                    inference_type=InferenceType.SEMANTIC,
                    confidence=confidence,
                    confidence_level=self._get_confidence_level(confidence),
                    supporting_facts=supporting_facts[:5],
                    supporting_fact_ids=[f.get("id") for f in supporting_facts[:5] if f.get("id")],
                    reasoning=reasoning,
                    suggested_category=category,
                    rule_applied="llm_semantic_inference"
                ))
        
        return inferences
    
    def _get_confidence_level(self, confidence: float) -> ConfidenceLevel:
        """Convert numeric confidence to level."""
        if confidence >= 0.85:
            return ConfidenceLevel.HIGH
        elif confidence >= 0.6:
            return ConfidenceLevel.MEDIUM
        elif confidence >= 0.4:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.SPECULATIVE
    
    def _deduplicate_inferences(
        self, 
        inferences: List[InferredFact]
    ) -> List[InferredFact]:
        """Remove duplicate or very similar inferences."""
        unique = []
        seen_content = set()
        
        for inf in inferences:
            # Simple dedup based on content similarity
            content_key = inf.content.lower()[:50]
            if content_key not in seen_content:
                seen_content.add(content_key)
                unique.append(inf)
        
        return unique
    
    def add_rule(self, rule: InferenceRule):
        """Add a custom inference rule."""
        self._rules.append(rule)
        logger.info(f"Added inference rule: {rule.name}")
    
    def get_rules(self) -> List[InferenceRule]:
        """Get all active inference rules."""
        return self._rules.copy()


# Global instance
_inference_engine: Optional[FactInferenceEngine] = None


def get_inference_engine() -> Optional[FactInferenceEngine]:
    """Get the global FactInferenceEngine instance."""
    return _inference_engine


def init_inference_engine(llm: Optional[Any] = None) -> FactInferenceEngine:
    """Initialize the global FactInferenceEngine."""
    global _inference_engine
    _inference_engine = FactInferenceEngine(llm=llm)
    logger.info("[FactInferenceEngine] Global instance initialized")
    return _inference_engine
