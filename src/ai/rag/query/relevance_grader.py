"""
Self-RAG Relevance Grader

Analyzes retrieved chunks to determine if they contain sufficient information 
to answer the user's query. If relevance is too low, triggers query expansion
rather than allowing the LLM to hallucinate.

Part of the Self-RAG architecture for high-precision retrieval.
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class RelevanceLevel(Enum):
    """Relevance classification levels."""
    HIGH = "high"           # Chunks directly answer the query (>0.7)
    MEDIUM = "medium"       # Chunks partially relevant (0.4-0.7)
    LOW = "low"             # Chunks marginally relevant (0.2-0.4)
    IRRELEVANT = "irrelevant"  # Chunks don't help (<0.2)


@dataclass
class RelevanceResult:
    """Result of relevance grading."""
    level: RelevanceLevel
    score: float   # 0.0 to 1.0
    should_expand_query: bool
    reasoning: str
    chunk_scores: List[Dict[str, float]]  # Individual chunk scores


class RelevanceGrader:
    """
    Self-RAG Relevance Grader - Analyzes chunk relevance before generation.
    
    Implements the "double-check homework" pattern:
    1. Score each retrieved chunk against the query
    2. Aggregate scores to determine overall relevance
    3. If insufficient, trigger query expansion instead of hallucinating
    
    Features:
    - Configurable thresholds for different use cases
    - LLM-based grading (optional) for nuanced relevance
    - Fast heuristic grading for low-latency scenarios
    """
    
    # Default thresholds
    EXPANSION_THRESHOLD = 0.4   # Below this, expand query
    CONFIDENCE_THRESHOLD = 0.7  # Above this, high confidence
    MIN_CHUNKS_FOR_ANSWER = 2   # Need at least this many relevant chunks
    
    def __init__(
        self,
        expansion_threshold: float = 0.4,
        confidence_threshold: float = 0.7,
        min_relevant_chunks: int = 2,
        use_llm_grading: bool = False,
        llm_client: Optional[Any] = None
    ):
        """
        Initialize relevance grader.
        
        Args:
            expansion_threshold: Score below which to expand query
            confidence_threshold: Score above which to proceed with confidence
            min_relevant_chunks: Minimum chunks needed for confident answer
            use_llm_grading: Use LLM for nuanced grading (slower but more accurate)
            llm_client: LLM client for advanced grading
        """
        self.expansion_threshold = expansion_threshold
        self.confidence_threshold = confidence_threshold
        self.min_relevant_chunks = min_relevant_chunks
        self.use_llm_grading = use_llm_grading
        self.llm_client = llm_client
        
        logger.info(
            f"RelevanceGrader initialized (expansion_threshold={expansion_threshold}, "
            f"llm_grading={use_llm_grading})"
        )
    
    def grade(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        query_intent: Optional[str] = None
    ) -> RelevanceResult:
        """
        Grade the relevance of retrieved chunks to the query.
        
        Args:
            query: The user's original query
            chunks: Retrieved chunks with content and metadata
            query_intent: Optional detected intent (search, action, question, etc.)
            
        Returns:
            RelevanceResult with aggregated score and expansion recommendation
        """
        if not chunks:
            return RelevanceResult(
                level=RelevanceLevel.IRRELEVANT,
                score=0.0,
                should_expand_query=True,
                reasoning="No chunks retrieved - query expansion needed",
                chunk_scores=[]
            )
        
        # Score each chunk
        chunk_scores = []
        for i, chunk in enumerate(chunks):
            content = chunk.get('content', '') or chunk.get('text', '')
            metadata = chunk.get('metadata', {})
            
            # Get existing score from vector search if available
            vector_score = chunk.get('score', chunk.get('confidence', 0.5))
            
            # Calculate relevance score using multiple signals
            relevance_score = self._calculate_chunk_relevance(
                query=query,
                content=content,
                metadata=metadata,
                vector_score=vector_score,
                intent=query_intent
            )
            
            chunk_scores.append({
                'chunk_index': i,
                'relevance_score': relevance_score,
                'vector_score': vector_score,
                'content_preview': content[:100] if content else ''
            })
        
        # Aggregate scores
        scores = [c['relevance_score'] for c in chunk_scores]
        
        # Use top-k average (more robust than mean)
        top_k = min(3, len(scores))
        sorted_scores = sorted(scores, reverse=True)
        avg_top_score = sum(sorted_scores[:top_k]) / top_k
        
        # Count chunks above threshold
        relevant_count = sum(1 for s in scores if s >= self.expansion_threshold)
        
        # Determine level and action
        level, should_expand, reasoning = self._determine_action(
            avg_score=avg_top_score,
            relevant_count=relevant_count,
            total_chunks=len(chunks)
        )
        
        return RelevanceResult(
            level=level,
            score=avg_top_score,
            should_expand_query=should_expand,
            reasoning=reasoning,
            chunk_scores=chunk_scores
        )
    
    async def grade_with_llm(
        self,
        query: str,
        chunks: List[Dict[str, Any]]
    ) -> RelevanceResult:
        """
        Grade relevance using LLM for nuanced analysis.
        
        This is slower but more accurate for ambiguous cases.
        Falls back to heuristic grading if LLM unavailable.
        """
        if not self.llm_client:
            logger.warning("LLM client not available, falling back to heuristic grading")
            return self.grade(query, chunks)
        
        try:
            # Prepare context for LLM
            chunk_texts = [
                f"[Chunk {i+1}]: {c.get('content', '')[:500]}"
                for i, c in enumerate(chunks[:5])  # Limit to top 5 for efficiency
            ]
            
            prompt = f"""Analyze whether these retrieved chunks can answer the user's query.

Query: "{query}"

Retrieved Chunks:
{chr(10).join(chunk_texts)}

Rate the overall relevance from 0.0 to 1.0 and explain briefly.
If the chunks don't contain enough information, say "EXPAND" and explain what's missing.

Format your response as:
SCORE: [0.0-1.0]
ACTION: [PROCEED/EXPAND]
REASON: [brief explanation]
"""
            
            from google import genai
            
            response = await self.llm_client.models.generate_content_async(
                model="gemini-2.0-flash",
                contents=prompt
            )
            
            # Parse LLM response
            text = response.text
            score = self._parse_score(text)
            should_expand = "EXPAND" in text.upper()
            
            level = self._score_to_level(score)
            
            return RelevanceResult(
                level=level,
                score=score,
                should_expand_query=should_expand,
                reasoning=self._extract_reason(text),
                chunk_scores=[]  # LLM grading doesn't provide per-chunk scores
            )
            
        except Exception as e:
            logger.warning(f"LLM grading failed: {e}, falling back to heuristic")
            return self.grade(query, chunks)
    
    def _calculate_chunk_relevance(
        self,
        query: str,
        content: str,
        metadata: Dict[str, Any],
        vector_score: float,
        intent: Optional[str] = None
    ) -> float:
        """
        Calculate relevance score for a single chunk.
        
        Combines multiple signals:
        - Vector similarity score (semantic)
        - Keyword overlap (lexical)
        - Metadata match (structural)
        - Intent alignment
        """
        if not content:
            return 0.0
        
        query_lower = query.lower()
        content_lower = content.lower()
        
        # 1. Vector score (already normalized 0-1)
        semantic_score = float(vector_score)
        
        # 2. Keyword overlap
        query_terms = set(query_lower.split())
        content_terms = set(content_lower.split())
        
        # Remove common stopwords
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 
                     'to', 'of', 'and', 'or', 'in', 'on', 'at', 'for', 'with', 'my'}
        query_terms -= stopwords
        
        if query_terms:
            overlap = len(query_terms & content_terms) / len(query_terms)
            keyword_score = min(1.0, overlap)
        else:
            keyword_score = 0.5
        
        # 3. Entity match (check if key entities appear)
        entity_score = 0.0
        # Check for names, emails, subjects in metadata
        subject = metadata.get('subject', '').lower()
        sender = metadata.get('sender', '').lower()
        
        for term in query_terms:
            if len(term) > 3:  # Only meaningful terms
                if term in subject or term in sender:
                    entity_score += 0.3
        entity_score = min(1.0, entity_score)
        
        # 4. Intent alignment (boost certain content types)
        intent_boost = 0.0
        if intent:
            doc_type = metadata.get('doc_type', metadata.get('node_type', ''))
            if intent == 'email_search' and 'email' in doc_type.lower():
                intent_boost = 0.1
            elif intent == 'file_search' and 'document' in doc_type.lower():
                intent_boost = 0.1
        
        # Weighted combination
        final_score = (
            semantic_score * 0.5 +     # 50% weight on semantic similarity
            keyword_score * 0.25 +     # 25% weight on keyword match
            entity_score * 0.15 +      # 15% weight on entity match
            intent_boost               # 10% max from intent alignment
        )
        
        return min(1.0, final_score)
    
    def _determine_action(
        self,
        avg_score: float,
        relevant_count: int,
        total_chunks: int
    ) -> Tuple[RelevanceLevel, bool, str]:
        """Determine the relevance level and recommended action."""
        
        if avg_score >= self.confidence_threshold:
            if relevant_count >= self.min_relevant_chunks:
                return (
                    RelevanceLevel.HIGH,
                    False,
                    f"High relevance ({avg_score:.2f}): {relevant_count}/{total_chunks} chunks highly relevant"
                )
            else:
                return (
                    RelevanceLevel.MEDIUM,
                    False,
                    f"Medium relevance ({avg_score:.2f}): Top chunks relevant but limited coverage"
                )
        
        elif avg_score >= self.expansion_threshold:
            return (
                RelevanceLevel.MEDIUM,
                False,
                f"Medium relevance ({avg_score:.2f}): Proceeding with available context"
            )
        
        elif avg_score >= 0.2:
            return (
                RelevanceLevel.LOW,
                True,
                f"Low relevance ({avg_score:.2f}): Query expansion recommended"
            )
        
        else:
            return (
                RelevanceLevel.IRRELEVANT,
                True,
                f"Very low relevance ({avg_score:.2f}): Retrieved chunks don't match query"
            )
    
    def _score_to_level(self, score: float) -> RelevanceLevel:
        """Convert numeric score to relevance level."""
        if score >= 0.7:
            return RelevanceLevel.HIGH
        elif score >= 0.4:
            return RelevanceLevel.MEDIUM
        elif score >= 0.2:
            return RelevanceLevel.LOW
        else:
            return RelevanceLevel.IRRELEVANT
    
    def _parse_score(self, text: str) -> float:
        """Parse score from LLM response."""
        import re
        match = re.search(r'SCORE:\s*([\d.]+)', text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return 0.5  # Default to medium if parsing fails
    
    def _extract_reason(self, text: str) -> str:
        """Extract reasoning from LLM response."""
        import re
        match = re.search(r'REASON:\s*(.+?)(?:\n|$)', text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return "LLM analysis completed"
