"""
Self-RAG Hallucination Checker

Compares LLM-generated responses against graph-stored facts to detect
and prevent hallucinations before they reach the user.

Part of the Self-RAG architecture for high-precision retrieval.
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import re
from datetime import datetime
from dateutil import parser as date_parser

from ....utils.logger import setup_logger
from src.services.service_constants import ServiceConstants

logger = setup_logger(__name__)


class ContradictionType(Enum):
    """Types of detected contradictions."""
    FACTUAL = "factual"        # Response contradicts a fact in the graph
    TEMPORAL = "temporal"      # Wrong dates, times, or sequences
    IDENTITY = "identity"      # Wrong person, company, or entity
    NUMERICAL = "numerical"    # Wrong numbers, amounts, counts
    NONE = "none"              # No contradiction detected


@dataclass
class Contradiction:
    """A detected contradiction between response and facts."""
    type: ContradictionType
    response_claim: str        # What the response said
    graph_fact: str           # What the graph says
    entity: str               # The entity involved (person, date, etc.)
    confidence: float         # 0.0-1.0 confidence in the contradiction
    source_node_id: Optional[str] = None  # Graph node with the fact


@dataclass
class HallucinationResult:
    """Result of hallucination checking."""
    is_valid: bool                # True if no significant contradictions
    contradictions: List[Contradiction] = field(default_factory=list)
    confidence: float = 1.0       # Overall confidence in the response
    should_regenerate: bool = False  # Recommendation to regenerate
    corrected_response: Optional[str] = None  # Suggested correction if minor issue


class HallucinationChecker:
    """
    Self-RAG Hallucination Critic - Validates responses against graph facts.
    
    Implements the "Critic Agent" pattern:
    1. Extract factual claims from the LLM response
    2. Query knowledge graph for related facts
    3. Compare claims against facts to detect contradictions
    4. If contradiction found, flag for regeneration
    
    Features:
    - Entity extraction and verification
    - Temporal consistency checking
    - Numerical validation
    - Configurable strictness levels
    """
    
    # Contradiction thresholds
    BLOCK_THRESHOLD = 0.8     # High confidence contradictions block response
    WARN_THRESHOLD = 0.5      # Medium confidence get warning
    
    def __init__(
        self,
        graph_manager: Optional[Any] = None,
        block_on_contradiction: bool = True,
        strictness: str = "normal"  # "strict", "normal", or "lenient"
    ):
        """
        Initialize hallucination checker.
        
        Args:
            graph_manager: Knowledge graph manager for fact lookup
            block_on_contradiction: If True, recommend regeneration on contradictions
            strictness: How strict to be about contradictions
        """
        self.graph = graph_manager
        self.block_on_contradiction = block_on_contradiction
        self.strictness = strictness
        
        # Adjust thresholds based on strictness
        if strictness == "strict":
            self.BLOCK_THRESHOLD = ServiceConstants.HALLUCINATION_BLOCK_THRESHOLD_STRICT
            self.WARN_THRESHOLD = ServiceConstants.HALLUCINATION_WARN_THRESHOLD_STRICT
        elif strictness == "lenient":
            self.BLOCK_THRESHOLD = ServiceConstants.HALLUCINATION_BLOCK_THRESHOLD_LENIENT
            self.WARN_THRESHOLD = ServiceConstants.HALLUCINATION_WARN_THRESHOLD_LENIENT
        else:
            self.BLOCK_THRESHOLD = ServiceConstants.HALLUCINATION_BLOCK_THRESHOLD_NORMAL
            self.WARN_THRESHOLD = ServiceConstants.HALLUCINATION_WARN_THRESHOLD_NORMAL
        
        logger.info(
            f"HallucinationChecker initialized (strictness={strictness}, "
            f"block_on_contradiction={block_on_contradiction})"
        )
    
    async def check(
        self,
        response: str,
        context: List[Dict[str, Any]],
        query: Optional[str] = None,
        extracted_entities: Optional[Dict[str, Any]] = None
    ) -> HallucinationResult:
        """
        Check response for hallucinations against retrieved context and graph.
        
        Args:
            response: The LLM-generated response to validate
            context: Retrieved chunks used as context for generation
            query: Original user query (for context)
            extracted_entities: Pre-extracted entities from query
            
        Returns:
            HallucinationResult with any detected contradictions
        """
        if not response:
            return HallucinationResult(is_valid=True, confidence=1.0)
        
        contradictions = []
        
        # 1. Extract claims from response
        claims = self._extract_claims(response)
        
        # 2. Build fact set from context
        context_facts = self._extract_facts_from_context(context)
        
        # 3. Check claims against context facts
        for claim in claims:
            contradiction = self._check_claim_against_facts(claim, context_facts)
            if contradiction:
                contradictions.append(contradiction)
        
        # 4. If graph available, verify against graph
        if self.graph:
            graph_contradictions = await self._verify_against_graph(
                claims, extracted_entities
            )
            contradictions.extend(graph_contradictions)
        
        # 5. Evaluate results
        if not contradictions:
            return HallucinationResult(
                is_valid=True,
                confidence=1.0,
                contradictions=[],
                should_regenerate=False
            )
        
        # Check if any contradiction is severe enough to block
        high_confidence = [c for c in contradictions if c.confidence >= self.BLOCK_THRESHOLD]
        
        if high_confidence and self.block_on_contradiction:
            return HallucinationResult(
                is_valid=False,
                contradictions=contradictions,
                confidence=1.0 - max(c.confidence for c in contradictions),
                should_regenerate=True,
                corrected_response=self._suggest_correction(response, high_confidence[0])
            )
        
        # Warnings only
        return HallucinationResult(
            is_valid=True,  # Allow but with warnings
            contradictions=contradictions,
            confidence=1.0 - (sum(c.confidence for c in contradictions) / len(contradictions) * 0.5),
            should_regenerate=False
        )
    
    def _extract_claims(self, response: str) -> List[Dict[str, Any]]:
        """
        Extract verifiable claims from the response.
        
        Focuses on:
        - Named entities (people, companies, places)
        - Dates and times
        - Numbers and quantities
        - Factual statements
        """
        claims = []
        
        # Date claims: Match dates in various formats
        date_patterns = [
            r'(?:on|at|by|before|after|during)\s+(\w+\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)',
            r'(\d{1,2}/\d{1,2}/\d{2,4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'(today|tomorrow|yesterday|next\s+\w+|last\s+\w+)',
        ]
        for pattern in date_patterns:
            for match in re.finditer(pattern, response, re.IGNORECASE):
                claims.append({
                    'type': 'temporal',
                    'text': match.group(0),
                    'value': match.group(1) if match.lastindex else match.group(0),
                    'position': match.start()
                })
        
        # Number claims: Match quantities, amounts, counts
        number_patterns = [
            r'(\$[\d,]+(?:\.\d{2})?)',  # Currency
            r'(\d+(?:\.\d+)?)\s*(?:hours?|minutes?|days?|weeks?|months?)',  # Duration
            r'(\d+)\s*(?:emails?|messages?|meetings?|tasks?|items?)',  # Counts
        ]
        for pattern in number_patterns:
            for match in re.finditer(pattern, response, re.IGNORECASE):
                claims.append({
                    'type': 'numerical',
                    'text': match.group(0),
                    'value': match.group(1) if match.lastindex else match.group(0),
                    'position': match.start()
                })
        
        # Identity claims: Match "X said", "from X", "with X"
        identity_patterns = [
            r'(?:from|by|with|to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:said|mentioned|wrote|sent|scheduled)',
        ]
        for pattern in identity_patterns:
            for match in re.finditer(pattern, response):
                # Filter out common words
                name = match.group(1)
                if name.lower() not in {'the', 'this', 'that', 'what', 'which', 'when', 'where'}:
                    claims.append({
                        'type': 'identity',
                        'text': match.group(0),
                        'value': name,
                        'position': match.start()
                    })
        
        return claims
    
    def _extract_facts_from_context(self, context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract verifiable facts from retrieved context."""
        facts = []
        
        for chunk in context:
            content = chunk.get('content', '') or chunk.get('text', '')
            metadata = chunk.get('metadata', {})
            
            # Extract from metadata (more reliable)
            if metadata.get('sender'):
                facts.append({
                    'type': 'identity',
                    'entity': 'sender',
                    'value': metadata['sender'],
                    'source': 'metadata'
                })
            
            if metadata.get('timestamp') or metadata.get('date'):
                facts.append({
                    'type': 'temporal',
                    'entity': 'date',
                    'value': metadata.get('timestamp') or metadata.get('date'),
                    'source': 'metadata'
                })
            
            if metadata.get('subject'):
                facts.append({
                    'type': 'content',
                    'entity': 'subject',
                    'value': metadata['subject'],
                    'source': 'metadata'
                })
            
            # Extract numbers from content
            for match in re.finditer(r'\$[\d,]+(?:\.\d{2})?', content):
                facts.append({
                    'type': 'numerical',
                    'entity': 'amount',
                    'value': match.group(0),
                    'source': 'content',
                    'context': content[max(0, match.start()-50):match.end()+50]
                })
        
        return facts
    
    def _check_claim_against_facts(
        self,
        claim: Dict[str, Any],
        facts: List[Dict[str, Any]]
    ) -> Optional[Contradiction]:
        """Check if a claim contradicts any known facts."""
        
        claim_type = claim.get('type')
        claim_value = claim.get('value', '').lower()
        
        for fact in facts:
            if fact.get('type') != claim_type:
                continue
            
            fact_value = str(fact.get('value', '')).lower()
            
            # Check for contradiction
            if claim_type == 'identity':
                # Check if claim mentions a different person than fact
                if claim_value and fact_value and claim_value != fact_value:
                    # Are they referring to the same role/context?
                    if fact.get('entity') == 'sender':
                        return Contradiction(
                            type=ContradictionType.IDENTITY,
                            response_claim=claim.get('text', ''),
                            graph_fact=f"Sender was {fact['value']}",
                            entity=claim_value,
                            confidence=0.7
                        )
            
            elif claim_type == 'numerical':
                # Check if amounts differ significantly
                claim_num = self._parse_number(claim_value)
                fact_num = self._parse_number(fact_value)
                
                if claim_num is not None and fact_num is not None and claim_num != fact_num:
                    # Allow tolerance for rounding
                    tolerance = ServiceConstants.HALLUCINATION_NUMERICAL_TOLERANCE
                    denominator = max(abs(claim_num), abs(fact_num))
                    
                    # Handle zero case
                    if denominator == 0:
                         # Both are zero (covered by claim_num != fact_num check above, but safe to check)
                         pass
                    elif abs(claim_num - fact_num) / denominator > tolerance:
                        return Contradiction(
                            type=ContradictionType.NUMERICAL,
                            response_claim=claim.get('text', ''),
                            graph_fact=f"Amount in context: {fact['value']}",
                            entity='amount',
                            confidence=0.8
                        )
            
            elif claim_type == 'temporal':
                # Date contradiction checking
                try:
                    search_dt = date_parser.parse(claim_value, fuzzy=True, default=datetime.utcnow())
                    fact_dt = date_parser.parse(fact_value, fuzzy=True, default=datetime.utcnow())
                    
                    # Compare only if we have high confidence they are the same type of date (ignoring time for now)
                    if search_dt.date() != fact_dt.date():
                        # Basic check: if they are wildly different (more than 2 days)
                        diff_days = abs((search_dt.date() - fact_dt.date()).days)
                        if diff_days > 2:
                             return Contradiction(
                                type=ContradictionType.TEMPORAL,
                                response_claim=claim.get('text', ''),
                                graph_fact=f"Date in context: {fact['value']}",
                                entity='date',
                                confidence=0.7
                            )
                except Exception:
                    # Date parsing failed, skip
                    pass
        
        return None
    
    async def _verify_against_graph(
        self,
        claims: List[Dict[str, Any]],
        entities: Optional[Dict[str, Any]] = None
    ) -> List[Contradiction]:
        """Verify claims against knowledge graph facts."""
        contradictions = []
        
        if not self.graph:
            return contradictions
        
        # Check identity claims against graph
        for claim in claims:
            if claim.get('type') == 'identity':
                name = claim.get('value', '')
                
                try:
                    # Query graph for this person
                    from src.services.indexing.graph.schema import NodeType
                    
                    # Try to find the person
                    nodes = await self.graph.find_nodes_by_property(
                        'name', name, node_type=NodeType.CONTACT
                    )
                    
                    if len(nodes) > 1:
                        # Ambiguous identity! This could lead to hallucination
                        contradictions.append(Contradiction(
                            type=ContradictionType.IDENTITY,
                            response_claim=claim.get('text', ''),
                            graph_fact=f"Multiple contacts named '{name}' exist",
                            entity=name,
                            confidence=0.6  # Warning level
                        ))
                    elif len(nodes) == 1:
                        # Single match - verify attributes if mentioned
                        pass
                        
                except Exception as e:
                    logger.debug(f"Graph lookup failed for {name}: {e}")
        
        return contradictions
    
    def _parse_number(self, text: str) -> Optional[float]:
        """Parse a number from text."""
        if not text:
            return None
        
        # Remove $ and commas
        cleaned = re.sub(r'[$,]', '', str(text))
        
        # Extract first number
        match = re.search(r'[\d.]+', cleaned)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                pass
        return None
    
    def _suggest_correction(self, response: str, contradiction: Contradiction) -> str:
        """Suggest a corrected response if possible."""
        if contradiction.type == ContradictionType.IDENTITY:
            # Suggest using the correct identity
            return f"(Correction needed: {contradiction.graph_fact})"
        elif contradiction.type == ContradictionType.NUMERICAL:
            return f"(Correction needed: {contradiction.graph_fact})"
        return ""
