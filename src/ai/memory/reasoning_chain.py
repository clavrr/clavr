"""
Reasoning Chain Engine

Provides explainable reasoning over facts:
- Build reasoning chains to explain conclusions
- Answer "why" questions with supporting evidence
- Connect facts through logical inference
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ReasoningType(str, Enum):
    """Types of reasoning links."""
    SUPPORTS = "supports"       # Fact supports conclusion
    CONTRADICTS = "contradicts" # Fact contradicts conclusion
    IMPLIES = "implies"         # Fact implies another
    CORRELATES = "correlates"   # Facts are correlated
    DERIVED = "derived"         # Conclusion derived from facts


@dataclass
class ReasoningStep:
    """A single step in the reasoning chain."""
    step_id: int
    fact_content: str
    fact_id: Optional[int] = None
    reasoning_type: ReasoningType = ReasoningType.SUPPORTS
    contribution: float = 0.5  # How much this step contributes to conclusion
    explanation: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "fact_content": self.fact_content,
            "fact_id": self.fact_id,
            "reasoning_type": self.reasoning_type.value,
            "contribution": self.contribution,
            "explanation": self.explanation
        }
    
    def format(self) -> str:
        """Format for display."""
        symbol = "✓" if self.reasoning_type == ReasoningType.SUPPORTS else "✗"
        return f"{symbol} {self.fact_content}"


@dataclass
class ReasoningChain:
    """A complete chain of reasoning to a conclusion."""
    query: str
    conclusion: str
    confidence: float
    
    steps: List[ReasoningStep] = field(default_factory=list)
    
    # Statistics
    supporting_count: int = 0
    contradicting_count: int = 0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def add_step(self, step: ReasoningStep):
        """Add a reasoning step."""
        step.step_id = len(self.steps) + 1
        self.steps.append(step)
        
        if step.reasoning_type == ReasoningType.SUPPORTS:
            self.supporting_count += 1
        elif step.reasoning_type == ReasoningType.CONTRADICTS:
            self.contradicting_count += 1
        
        # Update confidence based on evidence
        self._recalculate_confidence()
    
    def _recalculate_confidence(self):
        """Recalculate confidence based on steps."""
        if not self.steps:
            self.confidence = 0.5
            return
        
        # Weight by contribution and type
        total_weight = 0
        for step in self.steps:
            if step.reasoning_type == ReasoningType.SUPPORTS:
                total_weight += step.contribution
            elif step.reasoning_type == ReasoningType.CONTRADICTS:
                total_weight -= step.contribution * 0.5
        
        self.confidence = max(0.1, min(1.0, 0.5 + total_weight / len(self.steps)))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "steps": [s.to_dict() for s in self.steps],
            "supporting_count": self.supporting_count,
            "contradicting_count": self.contradicting_count
        }
    
    def format_for_display(self) -> str:
        """Format chain for human-readable display."""
        lines = [
            f"Question: {self.query}",
            f"Conclusion: {self.conclusion} (confidence: {self.confidence:.0%})",
            "",
            "Evidence:"
        ]
        
        for step in self.steps:
            lines.append(f"  {step.format()}")
            if step.explanation:
                lines.append(f"    → {step.explanation}")
        
        return "\n".join(lines)


class ReasoningEngine:
    """
    Builds reasoning chains to explain conclusions.
    
    Answers questions like:
    - "Why does user prefer morning meetings?"
    - "What makes me think Bob is important?"
    - "How confident am I about X?"
    """
    
    # Question patterns that trigger reasoning
    WHY_PATTERNS = ["why", "what makes", "how come", "reason for"]
    CONFIDENCE_PATTERNS = ["how confident", "how sure", "how certain", "reliable"]
    EVIDENCE_PATTERNS = ["what evidence", "what supports", "proof of", "based on"]
    
    def __init__(self, llm: Optional[Any] = None):
        """
        Initialize reasoning engine.
        
        Args:
            llm: Optional LLM for advanced reasoning
        """
        self.llm = llm
        self._cache: Dict[str, ReasoningChain] = {}  # Query cache
    
    def reason(
        self,
        query: str,
        facts: List[Dict[str, Any]],
        target_conclusion: Optional[str] = None
    ) -> ReasoningChain:
        """
        Build a reasoning chain about a query.
        
        Args:
            query: The question to reason about
            facts: Available facts to reason from
            target_conclusion: Optional specific conclusion to evaluate
            
        Returns:
            A ReasoningChain with steps and conclusion
        """
        # Extract topic from query
        topic = self._extract_topic(query)
        
        # Find relevant facts
        relevant_facts = self._find_relevant_facts(facts, topic)
        
        # Determine conclusion
        if target_conclusion:
            conclusion = target_conclusion
        else:
            conclusion = self._derive_conclusion(query, relevant_facts)
        
        # Build reasoning chain
        chain = ReasoningChain(
            query=query,
            conclusion=conclusion,
            confidence=0.5
        )
        
        # Add supporting/contradicting evidence
        for fact in relevant_facts:
            step = self._evaluate_fact_relevance(
                fact, 
                query, 
                conclusion
            )
            chain.add_step(step)
        
        # If we have LLM, enhance the reasoning
        if self.llm and len(relevant_facts) >= 2:
            try:
                chain = self._enhance_with_llm(chain, relevant_facts)
            except Exception as e:
                logger.debug(f"LLM reasoning enhancement failed: {e}")
        
        # Cache result
        cache_key = f"{query}:{hash(tuple(f.get('id', 0) for f in relevant_facts[:5]))}"
        self._cache[cache_key] = chain
        
        return chain
    
    def _extract_topic(self, query: str) -> str:
        """Extract the main topic from a query."""
        query_lower = query.lower()
        
        # Remove question words
        for word in ["why", "does", "do", "is", "are", "what", "how", "the", "user"]:
            query_lower = query_lower.replace(word, "")
        
        # Clean up
        topic = query_lower.strip()
        
        # Take key words
        words = [w for w in topic.split() if len(w) > 3]
        return " ".join(words[:4])
    
    def _find_relevant_facts(
        self,
        facts: List[Dict[str, Any]],
        topic: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Find facts relevant to the topic."""
        topic_words = set(topic.lower().split())
        
        scored_facts = []
        for fact in facts:
            content = fact.get("content", "").lower()
            content_words = set(content.split())
            
            # Score by word overlap
            overlap = len(topic_words & content_words)
            if overlap > 0 or any(tw in content for tw in topic_words):
                score = overlap + sum(0.5 for tw in topic_words if tw in content)
                scored_facts.append((fact, score))
        
        # Sort by relevance
        scored_facts.sort(key=lambda x: x[1], reverse=True)
        return [f for f, _ in scored_facts[:limit]]
    
    def _derive_conclusion(
        self,
        query: str,
        facts: List[Dict[str, Any]]
    ) -> str:
        """Derive a conclusion from the query and facts."""
        query_lower = query.lower()
        
        # Handle different query types
        if any(p in query_lower for p in self.WHY_PATTERNS):
            # "Why X?" -> "X because..."
            topic = self._extract_topic(query)
            if facts:
                return f"Based on {len(facts)} observations, {topic} appears to be a preference"
            return f"Insufficient evidence about {topic}"
        
        if any(p in query_lower for p in self.CONFIDENCE_PATTERNS):
            # "How confident about X?" -> Confidence assessment
            if facts:
                avg_conf = sum(f.get("confidence", 0.5) for f in facts) / len(facts)
                level = "high" if avg_conf >= 0.8 else "moderate" if avg_conf >= 0.6 else "low"
                return f"Confidence is {level} ({avg_conf:.0%}) based on {len(facts)} facts"
            return "Insufficient evidence to assess confidence"
        
        # Default: summarize evidence
        if facts:
            return f"Evidence from {len(facts)} facts suggests this is likely true"
        return "No direct evidence found"
    
    def _evaluate_fact_relevance(
        self,
        fact: Dict[str, Any],
        query: str,
        conclusion: str
    ) -> ReasoningStep:
        """Evaluate how a fact relates to the conclusion."""
        content = fact.get("content", "")
        confidence = fact.get("confidence", 0.5)
        
        # Determine reasoning type
        reasoning_type = ReasoningType.SUPPORTS  # Default
        
        # Check for contradiction indicators
        query_lower = query.lower()
        content_lower = content.lower()
        
        # Look for negation
        negation_words = ["not", "don't", "doesn't", "never", "avoid", "dislike"]
        query_negated = any(n in query_lower for n in negation_words)
        content_negated = any(n in content_lower for n in negation_words)
        
        if query_negated != content_negated:
            reasoning_type = ReasoningType.CONTRADICTS
        
        # Calculate contribution based on confidence and relevance
        topic_words = set(self._extract_topic(query).split())
        content_words = set(content_lower.split())
        word_overlap = len(topic_words & content_words) / max(len(topic_words), 1)
        
        contribution = confidence * (0.3 + 0.7 * word_overlap)
        
        # Generate explanation
        if reasoning_type == ReasoningType.SUPPORTS:
            explanation = f"Supports with {confidence:.0%} confidence"
        else:
            explanation = f"May contradict (needs verification)"
        
        return ReasoningStep(
            step_id=0,
            fact_content=content,
            fact_id=fact.get("id"),
            reasoning_type=reasoning_type,
            contribution=contribution,
            explanation=explanation
        )
    
    async def _enhance_with_llm(
        self,
        chain: ReasoningChain,
        facts: List[Dict[str, Any]]
    ) -> ReasoningChain:
        """Use LLM to enhance reasoning chain."""
        if not self.llm:
            return chain
        
        facts_text = "\n".join(f"- {f.get('content', '')}" for f in facts[:10])
        
        prompt = f"""Analyze this reasoning chain and provide brief insights:

Question: {chain.query}
Current Conclusion: {chain.conclusion}

Evidence:
{facts_text}

Provide a one-sentence refined conclusion and explanation."""

        try:
            response = await self.llm.agenerate([prompt])
            enhanced_conclusion = response.generations[0][0].text.strip()
            
            if enhanced_conclusion and len(enhanced_conclusion) > 10:
                # Add LLM insight as a step
                chain.add_step(ReasoningStep(
                    step_id=0,
                    fact_content="[LLM Analysis]",
                    reasoning_type=ReasoningType.DERIVED,
                    contribution=0.3,
                    explanation=enhanced_conclusion[:200]
                ))
                
        except Exception as e:
            logger.debug(f"LLM enhancement failed: {e}")
        
        return chain
    
    def get_question_type(self, query: str) -> str:
        """Classify the type of reasoning question."""
        query_lower = query.lower()
        
        if any(p in query_lower for p in self.WHY_PATTERNS):
            return "why"
        if any(p in query_lower for p in self.CONFIDENCE_PATTERNS):
            return "confidence"
        if any(p in query_lower for p in self.EVIDENCE_PATTERNS):
            return "evidence"
        
        return "general"
    
    def explain_confidence(
        self,
        facts: List[Dict[str, Any]],
        topic: str
    ) -> Dict[str, Any]:
        """Explain confidence level for a topic."""
        relevant = self._find_relevant_facts(facts, topic)
        
        if not relevant:
            return {
                "topic": topic,
                "confidence": 0.0,
                "level": "none",
                "explanation": "No evidence found about this topic",
                "fact_count": 0
            }
        
        avg_confidence = sum(f.get("confidence", 0.5) for f in relevant) / len(relevant)
        
        if avg_confidence >= 0.85:
            level = "very_high"
            explanation = "Multiple high-confidence observations support this"
        elif avg_confidence >= 0.7:
            level = "high"
            explanation = "Good evidence with some high-confidence facts"
        elif avg_confidence >= 0.5:
            level = "moderate"
            explanation = "Some evidence exists but confidence varies"
        else:
            level = "low"
            explanation = "Limited evidence, mostly inferred or unconfirmed"
        
        return {
            "topic": topic,
            "confidence": avg_confidence,
            "level": level,
            "explanation": explanation,
            "fact_count": len(relevant),
            "sources": [f.get("source", "unknown") for f in relevant[:3]]
        }


# Global instance
_reasoning_engine: Optional[ReasoningEngine] = None


def get_reasoning_engine() -> Optional[ReasoningEngine]:
    """Get the global ReasoningEngine instance."""
    return _reasoning_engine


def init_reasoning_engine(llm: Optional[Any] = None) -> ReasoningEngine:
    """Initialize the global ReasoningEngine."""
    global _reasoning_engine
    _reasoning_engine = ReasoningEngine(llm=llm)
    logger.info("[ReasoningEngine] Global instance initialized")
    return _reasoning_engine
