"""
Semantic Memory Manager

Manages the storage and retrieval of discrete facts and preferences (Semantic Memory).
Serves as the "Long-term Knowledge" store for agents, distinct from the episodic conversation log.

Features:
- CRUD for AgentFact model
- Categorized fact retrieval
- Semantic search (via RAG integration) support
- Smart Fact Learning with contradiction detection
- Fact consolidation and confidence scoring

Version: 2.0.0 - Enhanced with contradiction detection
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from enum import Enum
from difflib import SequenceMatcher
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, desc, update

from src.database.models import AgentFact
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class FactValidationResult(str, Enum):
    """Result of validating a new fact against existing knowledge."""
    NEW = "new"                      # Completely new information
    DUPLICATE = "duplicate"          # Exact or near-exact duplicate
    REINFORCEMENT = "reinforcement"  # Supports existing fact
    CONTRADICTION = "contradiction"  # Conflicts with existing fact
    UPDATE = "update"                # Updates/supersedes existing fact


class SemanticMemory:
    """
    Manages Semantic Memory (Facts/Preferences) for agents.
    
    Enhanced with Smart Fact Learning:
    - Validates new facts against existing knowledge
    - Detects contradictions and redundancies
    - Consolidates related facts
    - Maintains fact confidence scores
    """
    
    # Thresholds for fact similarity
    DUPLICATE_THRESHOLD = 0.95       # Near-exact match
    HIGH_SIMILARITY_THRESHOLD = 0.75 # Very similar (lowered to catch slight rephrasings)
    RELATED_THRESHOLD = 0.50         # Related enough to compare
    
    # Contradiction keywords that indicate opposite meanings
    CONTRADICTION_INDICATORS = [
        ("likes", "dislikes"),
        ("loves", "hates"),
        ("prefers", "avoids"),
        ("wants", "doesn't want"),
        ("is", "isn't"),
        ("has", "doesn't have"),
        ("can", "cannot"),
        ("will", "won't"),
        ("always", "never"),
        ("yes", "no"),
    ]
    
    def __init__(self, db: AsyncSession, rag_engine: Optional[Any] = None, llm: Optional[Any] = None):
        """
        Initialize Semantic Memory.
        
        Args:
            db: Database session
            rag_engine: Optional RAG engine for semantic searches
            llm: Optional LLM for contradiction detection
        """
        self.db = db
        self.rag = rag_engine
        self.llm = llm
        
    async def learn_fact_with_evidence(
        self, 
        user_id: int, 
        content: str, 
        category: str = "general"
    ) -> Tuple[Optional[int], float]:
        """
        Learn a fact and calculate confidence based on graph evidence.
        
        Used for inferred facts from BehaviorLearner.
        
        Returns:
            Tuple of (fact_id, evidence_confidence)
        """
        # 1. Standard validation
        validation, existing = await self._validate_fact(user_id, content, category)
        
        # 2. Search graph for supporting evidence if it's a preference
        evidence_count = 0
        if "prefers" in content.lower() or "likes" in content.lower():
            # e.g., "User prefers morning meetings" -> Search for evidence
            # This is a placeholder for deeper graph queries
            # In a real impl, we'd query the graph for corroboration
            pass
        
        # 3. Adjust confidence based on validation and evidence
        base_confidence = 0.7
        
        if validation == FactValidationResult.REINFORCEMENT:
            base_confidence = 0.9
        elif validation == FactValidationResult.CONTRADICTION:
            base_confidence = 0.4
            
        # 4. Store with enhanced confidence
        fact_id, _ = await self.learn_fact(
            user_id, content, category, 
            confidence=base_confidence,
            source='inferred'
        )
        
        return fact_id, base_confidence

    async def learn_fact(self, 
                         user_id: int, 
                         content: str, 
                         category: str = "general", 
                         source: str = "agent", 
                         confidence: float = 1.0,
                         validate: bool = True) -> Tuple[Optional[int], FactValidationResult]:
        """
        Store a new fact in semantic memory with validation.
        
        Args:
            user_id: User who the fact is about
            content: The fact content (e.g. "User likes coffee")
            category: Category (preference, contact, work, etc.)
            source: Source of the fact (e.g. "email_agent")
            confidence: Confidence score (0.0-1.0)
            validate: Whether to validate against existing facts
            
        Returns:
            Tuple of (fact_id, validation_result)
        """
        try:
            # Step 1: Validate against existing facts if enabled
            if validate:
                validation_result, existing_fact = await self._validate_fact(
                    user_id, content, category
                )
                
                if validation_result == FactValidationResult.DUPLICATE:
                    # Just update confidence, don't create new
                    if existing_fact:
                        existing_fact.confidence = max(existing_fact.confidence, confidence)
                        await self.db.commit()
                        logger.debug(f"Duplicate fact detected, updated confidence: {content[:50]}...")
                        return existing_fact.id, validation_result
                    return None, validation_result
                    
                elif validation_result == FactValidationResult.CONTRADICTION:
                    # Handle contradiction - log and potentially flag for user review
                    logger.warning(
                        f"Contradiction detected for user {user_id}: "
                        f"New: '{content[:50]}...' vs Existing: '{existing_fact.content[:50] if existing_fact else 'N/A'}...'"
                    )
                    # Store the new fact but with lower confidence and flagged
                    confidence = min(confidence, 0.5)  # Reduce confidence for contradictions
                    
                elif validation_result == FactValidationResult.UPDATE:
                    # Supersede the old fact
                    if existing_fact:
                        await self._supersede_fact(existing_fact.id, content)
                        
                elif validation_result == FactValidationResult.REINFORCEMENT:
                    # Boost confidence of existing fact
                    if existing_fact:
                        existing_fact.confidence = min(1.0, existing_fact.confidence + 0.1)
                        await self.db.commit()
                        logger.info(f"Reinforced existing fact: {existing_fact.content[:50]}...")
                        return existing_fact.id, validation_result
            else:
                validation_result = FactValidationResult.NEW
            
            # Step 2: Create the new fact
            fact = AgentFact(
                user_id=user_id,
                content=content,
                category=category,
                source=source,
                confidence=confidence
            )
            
            self.db.add(fact)
            await self.db.commit()
            await self.db.refresh(fact)
            
            # Step 3: Index in RAG if enabled for semantic search
            if self.rag:
                try:
                    await self._index_fact_in_rag(fact)
                except Exception as e:
                    logger.warning(f"Failed to index fact in RAG: {e}")
                    
            logger.info(f"Learned new fact for user {user_id}: {content[:50]}... (validation: {validation_result.value})")
            return fact.id, validation_result
            
        except Exception as e:
            logger.error(f"Failed to learn fact: {e}")
            await self.db.rollback()
            return None, FactValidationResult.NEW

    async def _validate_fact(
        self,
        user_id: int,
        new_content: str,
        category: str
    ) -> Tuple[FactValidationResult, Optional[AgentFact]]:
        """
        Validate a new fact against existing facts.
        
        Returns:
            Tuple of (validation_result, most_similar_existing_fact)
        """
        try:
            # Get existing facts in the same category
            stmt = select(AgentFact).where(
                AgentFact.user_id == user_id,
                AgentFact.category == category
            ).limit(50)  # Limit for performance
            
            result = await self.db.execute(stmt)
            existing_facts = result.scalars().all()
            
            if not existing_facts:
                return FactValidationResult.NEW, None
            
            best_match = None
            best_similarity = 0.0
            
            new_content_lower = new_content.lower().strip()
            
            for fact in existing_facts:
                existing_lower = fact.content.lower().strip()
                
                # Calculate text similarity
                similarity = self._calculate_similarity(new_content_lower, existing_lower)
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = fact
            
            # Determine validation result based on similarity
            if best_similarity >= self.DUPLICATE_THRESHOLD:
                return FactValidationResult.DUPLICATE, best_match
                
            elif best_similarity >= self.HIGH_SIMILARITY_THRESHOLD:
                # Check if it's an update or reinforcement
                if self._is_update(new_content_lower, best_match.content.lower()):
                    return FactValidationResult.UPDATE, best_match
                return FactValidationResult.REINFORCEMENT, best_match
                
            elif best_similarity >= self.RELATED_THRESHOLD:
                # Check for contradiction
                if self._detect_contradiction(new_content_lower, best_match.content.lower()):
                    return FactValidationResult.CONTRADICTION, best_match
                return FactValidationResult.NEW, best_match
                
            return FactValidationResult.NEW, None
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Fact validation failed: {e}")
            return FactValidationResult.NEW, None

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity using SequenceMatcher."""
        return SequenceMatcher(None, text1, text2).ratio()

    def _detect_contradiction(self, new_fact: str, existing_fact: str) -> bool:
        """
        Detect if two facts contradict each other.
        Uses keyword-based heuristics, negation pattern matching, and semantic comparison.
        
        Enhanced to handle:
        - Direct negation: "likes" vs "does not like"
        - Contracted negation: "likes" vs "doesn't like"
        - Opposite keywords: "likes" vs "dislikes"
        """
        # Step 1: Normalize both facts by removing/standardizing negation patterns
        new_normalized, new_is_negated = self._normalize_negation(new_fact)
        existing_normalized, existing_is_negated = self._normalize_negation(existing_fact)
        
        # Step 2: Check if normalized forms are similar (same core meaning)
        similarity = self._calculate_similarity(new_normalized, existing_normalized)
        
        if similarity >= 0.75:
            # High similarity - check if one is negated and other isn't
            if new_is_negated != existing_is_negated:
                return True
        
        # Step 3: Check for antonym pairs (likes vs dislikes, loves vs hates)
        for positive, negative in self.CONTRADICTION_INDICATORS:
            new_has_positive = positive in new_fact and negative not in new_fact
            new_has_negative = negative in new_fact
            existing_has_positive = positive in existing_fact and negative not in existing_fact
            existing_has_negative = negative in existing_fact
            
            if (new_has_positive and existing_has_negative) or \
               (new_has_negative and existing_has_positive):
                # Check if they're about the same subject
                new_subject = self._extract_subject(new_fact)
                existing_subject = self._extract_subject(existing_fact)
                if self._calculate_similarity(new_subject, existing_subject) > 0.6:
                    return True
        
        # Step 4: Legacy subject matching (fallback)
        new_words = new_fact.split()
        existing_words = existing_fact.split()
        
        if len(new_words) >= 2 and len(existing_words) >= 2:
            if new_words[0] == existing_words[0]:  # Same subject (e.g., "user")
                # Check for opposite modifiers
                new_rest = ' '.join(new_words[1:])
                existing_rest = ' '.join(existing_words[1:])
                
                # Check for value contradictions (e.g., "color is blue" vs "color is red")
                if self._detect_value_contradiction(new_rest, existing_rest):
                    return True
        
        return False
    
    def _normalize_negation(self, text: str) -> tuple:
        """
        Normalize negation patterns and return (normalized_text, is_negated).
        
        Converts various negation forms to a standard form:
        - "does not like" -> "like" (negated=True)
        - "doesn't like" -> "like" (negated=True)
        - "not preferred" -> "preferred" (negated=True)
        - "likes" -> "like" (negated=False)
        """
        text = text.lower().strip()
        is_negated = False
        
        # Negation patterns to detect and remove
        negation_patterns = [
            (r'\bdoes not\b', True),
            (r'\bdo not\b', True),
            (r'\bdoesn\'t\b', True),
            (r'\bdon\'t\b', True),
            (r'\bwill not\b', True),
            (r'\bwon\'t\b', True),
            (r'\bcannot\b', True),
            (r'\bcan\'t\b', True),
            (r'\bis not\b', True),
            (r'\bisn\'t\b', True),
            (r'\bare not\b', True),
            (r'\baren\'t\b', True),
            (r'\bnot\b', True),
            (r'\bnever\b', True),
            (r'\bavoid\b', True),    # Treat avoid as negation
            (r'\bavoids\b', True),   # Treat avoids as negation
        ]
        
        import re
        for pattern, negates in negation_patterns:
            if re.search(pattern, text):
                text = re.sub(pattern, '', text)
                is_negated = True
                break  # Only apply first match
        
        # Clean up extra spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text, is_negated
    
    def _extract_subject(self, text: str) -> str:
        """Extract the subject of a fact (words before the main verb)."""
        # Simple heuristic: take first 3 words or up to the verb
        words = text.lower().split()
        verbs = ['likes', 'loves', 'prefers', 'hates', 'dislikes', 'wants', 'is', 'has', 'does']
        
        subject_words = []
        for word in words:
            if word in verbs or word in ['not', "doesn't", "don't"]:
                break
            subject_words.append(word)
        
        return ' '.join(subject_words[:3]) if subject_words else ' '.join(words[:2])
    
    def _detect_value_contradiction(self, text1: str, text2: str) -> bool:
        """
        Detect if two texts describe contradictory values.
        E.g., "color is blue" vs "color is red"
        """
        # Look for patterns like "X is Y" where Y differs
        import re
        
        pattern = r'(\w+)\s+is\s+(\w+)'
        match1 = re.search(pattern, text1)
        match2 = re.search(pattern, text2)
        
        if match1 and match2:
            attr1, val1 = match1.groups()
            attr2, val2 = match2.groups()
            
            # Same attribute, different value = contradiction
            if attr1 == attr2 and val1 != val2:
                return True
        
        # Check for preference contradictions ("prefers X" vs "prefers Y")
        pref_pattern = r'prefers?\s+(\w+)'
        pref1 = re.search(pref_pattern, text1)
        pref2 = re.search(pref_pattern, text2)
        
        if pref1 and pref2:
            if pref1.group(1) != pref2.group(1):
                # Check for mutually exclusive preferences
                exclusive_pairs = [
                    ('dark', 'light'), ('morning', 'evening'), ('early', 'late'),
                    ('hot', 'cold'), ('high', 'low'), ('fast', 'slow'),
                ]
                v1, v2 = pref1.group(1), pref2.group(1)
                for a, b in exclusive_pairs:
                    if (v1 == a and v2 == b) or (v1 == b and v2 == a):
                        return True
        
        return False

    def _is_update(self, new_fact: str, existing_fact: str) -> bool:
        """Check if new fact is an update (supersedes) the existing fact."""
        # Look for temporal indicators suggesting newer info
        update_indicators = [
            "now", "currently", "recently", "updated", "changed to",
            "as of", "moved to", "switched to", "new"
        ]
        return any(indicator in new_fact for indicator in update_indicators)

    async def _supersede_fact(self, old_fact_id: int, new_content: str) -> None:
        """Mark an old fact as superseded."""
        try:
            stmt = update(AgentFact).where(
                AgentFact.id == old_fact_id
            ).values(
                confidence=0.1,  # Reduce confidence instead of deleting
            )
            await self.db.execute(stmt)
            await self.db.commit()
            logger.info(f"Superseded fact {old_fact_id} with newer information")
        except Exception as e:
            logger.error(f"Failed to supersede fact: {e}")

    async def _index_fact_in_rag(self, fact: AgentFact) -> None:
        """Index a fact in RAG for semantic search."""
        if not self.rag:
            return
            
        try:
            doc = {
                'id': f"fact_{fact.id}",
                'content': fact.content,
                'metadata': {
                    'type': 'fact',
                    'user_id': str(fact.user_id),
                    'category': fact.category,
                    'source': fact.source,
                    'confidence': fact.confidence,
                }
            }
            # Use RAG's indexing method
            import asyncio
            await asyncio.to_thread(self.rag.index_document, doc['id'], doc['content'], doc['metadata'])
        except Exception as e:
            logger.warning(f"Failed to index fact in RAG: {e}")

    async def get_facts(self, 
                        user_id: int, 
                        category: Optional[str] = None, 
                        limit: int = 20,
                        min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        """
        Retrieve facts for a user, optionally filtered by category.
        
        Args:
            user_id: User ID
            category: Optional category filter
            limit: Max results
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of facts
        """
        try:
            stmt = select(AgentFact).where(
                AgentFact.user_id == user_id,
                AgentFact.confidence >= min_confidence
            )
            
            if category:
                stmt = stmt.where(AgentFact.category == category)
                
            stmt = stmt.order_by(desc(AgentFact.confidence), desc(AgentFact.created_at)).limit(limit)
            
            result = await self.db.execute(stmt)
            facts = result.scalars().all()
            
            return [
                {
                    "id": f.id,
                    "content": f.content,
                    "category": f.category,
                    "confidence": f.confidence,
                    "source": f.source,
                    "created_at": f.created_at.isoformat() if f.created_at else None
                }
                for f in facts
            ]
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to retrieve facts: {e}")
            return []

    async def search_facts(self, 
                           query: str, 
                           user_id: int, 
                           limit: int = 5,
                           use_semantic: bool = True) -> List[Dict[str, Any]]:
        """
        Search for facts relevant to a query.
        
        Search hierarchy:
        1. RAG semantic search (if configured)
        2. Embedding-based search (using SentenceTransformers)
        3. Keyword search (fallback)
        
        Args:
            query: Search query
            user_id: User ID
            limit: Max results
            use_semantic: Whether to use semantic search
        """
        # 1. Try RAG semantic search first
        if use_semantic and self.rag:
            try:
                results = await self._semantic_fact_search(query, user_id, limit)
                if results:
                    return results
            except Exception as e:
                logger.debug(f"RAG fact search unavailable: {e}")
        
        # 2. Try embedding-based search (SentenceTransformers)
        if use_semantic:
            try:
                results = await self._embedding_fact_search(query, user_id, limit)
                if results:
                    return results
            except Exception as e:
                logger.debug(f"Embedding fact search failed: {e}")
        
        # 3. Fallback to keyword search
        return await self._keyword_fact_search(query, user_id, limit)

    async def _embedding_fact_search(
        self,
        query: str,
        user_id: int,
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        Search facts using embedding-based similarity.
        
        Uses local SentenceTransformer embeddings for semantic matching
        when RAG engine is not available.
        """
        from .memory_utils import compute_similarity_scores
        
        # Get all facts for user (with reasonable limit for embedding)
        all_facts = await self.get_facts(user_id, limit=100, min_confidence=0.3)
        
        if not all_facts:
            return []
        
        # Compute similarity scores
        scores = compute_similarity_scores(
            query,
            [{"content": f.get("content", "")} if isinstance(f, dict) else {"content": f.content} 
             for f in all_facts]
        )
        
        # Pair facts with scores and sort
        scored_facts = list(zip(all_facts, scores))
        scored_facts.sort(key=lambda x: x[1], reverse=True)
        
        # Return top results above threshold
        min_score = 0.3
        results = []
        for fact, score in scored_facts[:limit]:
            if score < min_score:
                continue
            
            if isinstance(fact, dict):
                result = dict(fact)
                result["score"] = score
            else:
                result = {
                    "id": fact.id,
                    "content": fact.content,
                    "category": fact.category,
                    "confidence": fact.confidence,
                    "score": score,
                    "source": fact.source
                }
            results.append(result)
        
        return results

    async def _semantic_fact_search(
        self, 
        query: str, 
        user_id: int, 
        limit: int
    ) -> List[Dict[str, Any]]:
        """Search facts using semantic similarity via RAG."""
        import asyncio
        
        results = await asyncio.to_thread(
            self.rag.search,
            query,
            k=limit,
            filters={'type': 'fact', 'user_id': str(user_id)}
        )
        
        # Extract fact IDs and fetch from DB
        fact_ids = []
        scores = {}
        for result in results:
            fact_id_str = result.get('metadata', {}).get('id', '') or result.get('id', '')
            if fact_id_str.startswith('fact_'):
                fact_id = int(fact_id_str.replace('fact_', ''))
                fact_ids.append(fact_id)
                scores[fact_id] = result.get('score', result.get('confidence', 0.5))
        
        if not fact_ids:
            return []
        
        try:
            stmt = select(AgentFact).where(AgentFact.id.in_(fact_ids))
            result = await self.db.execute(stmt)
            facts = result.scalars().all()
            
            return [
                {
                    "id": f.id,
                    "content": f.content,
                    "category": f.category,
                    "confidence": f.confidence,
                    "score": scores.get(f.id, 0.5),
                    "source": f.source
                }
                for f in facts
            ]
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Semantic fact search DB query failed: {e}")
            return []

    async def _keyword_fact_search(
        self, 
        query: str, 
        user_id: int, 
        limit: int
    ) -> List[Dict[str, Any]]:
        """Search facts using keyword matching."""
        try:
            keywords = [w for w in query.split() if len(w) > 3]
            if not keywords:
                return await self.get_facts(user_id, limit=limit)
                
            from sqlalchemy import or_
            conditions = [AgentFact.content.ilike(f"%{kw}%") for kw in keywords]
            
            stmt = select(AgentFact).where(
                AgentFact.user_id == user_id,
                or_(*conditions)
            ).order_by(desc(AgentFact.confidence)).limit(limit)
            
            result = await self.db.execute(stmt)
            facts = result.scalars().all()
            
            return [
                {
                    "id": f.id,
                    "content": f.content,
                    "category": f.category,
                    "confidence": f.confidence,
                    "score": 0.7,  # Keyword match score
                    "source": f.source
                }
                for f in facts
            ]
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Keyword fact search failed: {e}")
            return []

    async def get_contradictions(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get facts that may have contradictions (low confidence from contradiction detection).
        
        Returns facts that were flagged during learning due to conflicts.
        """
        try:
            stmt = select(AgentFact).where(
                AgentFact.user_id == user_id,
                AgentFact.confidence <= 0.5
            ).order_by(desc(AgentFact.created_at)).limit(limit)
            
            result = await self.db.execute(stmt)
            facts = result.scalars().all()
            
            return [
                {
                    "id": f.id,
                    "content": f.content,
                    "category": f.category,
                    "confidence": f.confidence,
                    "source": f.source,
                    "needs_review": True
                }
                for f in facts
            ]
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to get contradictions: {e}")
            return []

    async def resolve_contradiction(
        self, 
        fact_id: int, 
        resolution: str,
        new_confidence: float = 1.0
    ) -> bool:
        """
        Resolve a contradiction by user decision.
        
        Args:
            fact_id: ID of the fact to update
            resolution: 'keep' (restore confidence), 'delete', or 'update' (with new content)
            new_confidence: New confidence if keeping
        """
        try:
            if resolution == 'delete':
                stmt = delete(AgentFact).where(AgentFact.id == fact_id)
                await self.db.execute(stmt)
            elif resolution == 'keep':
                stmt = update(AgentFact).where(
                    AgentFact.id == fact_id
                ).values(confidence=new_confidence)
                await self.db.execute(stmt)
            
            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to resolve contradiction: {e}")
            await self.db.rollback()
            return False

    async def consolidate_facts(self, user_id: int, category: str) -> int:
        """
        Consolidate similar facts in a category to reduce redundancy.
        
        Returns:
            Number of facts consolidated (removed as duplicates)
        """
        facts = await self.get_facts(user_id, category=category, limit=100)
        
        if len(facts) < 2:
            return 0
        
        consolidated = 0
        to_delete = set()
        
        for i, fact1 in enumerate(facts):
            if fact1['id'] in to_delete:
                continue
                
            for fact2 in facts[i+1:]:
                if fact2['id'] in to_delete:
                    continue
                    
                similarity = self._calculate_similarity(
                    fact1['content'].lower(), 
                    fact2['content'].lower()
                )
                
                if similarity >= self.DUPLICATE_THRESHOLD:
                    # Keep the one with higher confidence
                    if fact1.get('confidence', 0) >= fact2.get('confidence', 0):
                        to_delete.add(fact2['id'])
                    else:
                        to_delete.add(fact1['id'])
                    consolidated += 1
        
        # Delete duplicates
        if to_delete:
            stmt = delete(AgentFact).where(AgentFact.id.in_(list(to_delete)))
            await self.db.execute(stmt)
            await self.db.commit()
            logger.info(f"Consolidated {consolidated} duplicate facts for user {user_id}")
        
        return consolidated

    # Feedback Loop - Learn from usage
    
    async def reinforce_fact(self, fact_id: int, boost: float = 0.1) -> bool:
        """
        Reinforce a fact that was useful.
        
        Increases confidence and resets any decay. Used when a fact
        was retrieved and the user confirmed it was helpful.
        
        Args:
            fact_id: Fact ID to reinforce
            boost: Confidence boost amount (default 0.1)
            
        Returns:
            True if successful
        """
        try:
            # Get current fact
            stmt = select(AgentFact).where(AgentFact.id == fact_id)
            result = await self.db.execute(stmt)
            fact = result.scalar_one_or_none()
            
            if not fact:
                return False
            
            # Boost confidence (cap at 1.0)
            new_confidence = min(1.0, fact.confidence + boost)
            
            stmt = update(AgentFact).where(
                AgentFact.id == fact_id
            ).values(
                confidence=new_confidence,
                updated_at=datetime.utcnow()
            )
            await self.db.execute(stmt)
            await self.db.commit()
            
            logger.info(f"Reinforced fact {fact_id}: {fact.confidence:.2f} -> {new_confidence:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reinforce fact: {e}")
            await self.db.rollback()
            return False
    
    async def decay_fact(self, fact_id: int, penalty: float = 0.2) -> bool:
        """
        Decay a fact that was not useful.
        
        Decreases confidence. Used when a fact was retrieved but
        the user indicated it was unhelpful or incorrect.
        
        Args:
            fact_id: Fact ID to decay
            penalty: Confidence penalty amount (default 0.2)
            
        Returns:
            True if successful
        """
        try:
            stmt = select(AgentFact).where(AgentFact.id == fact_id)
            result = await self.db.execute(stmt)
            fact = result.scalar_one_or_none()
            
            if not fact:
                return False
            
            # Reduce confidence (floor at 0.1 - don't delete, just deprioritize)
            new_confidence = max(0.1, fact.confidence - penalty)
            
            stmt = update(AgentFact).where(
                AgentFact.id == fact_id
            ).values(
                confidence=new_confidence,
                updated_at=datetime.utcnow()
            )
            await self.db.execute(stmt)
            await self.db.commit()
            
            logger.info(f"Decayed fact {fact_id}: {fact.confidence:.2f} -> {new_confidence:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to decay fact: {e}")
            await self.db.rollback()
            return False
