"""
Memory Consolidation Worker

Background job that consolidates and optimizes memory over time.

Similar to how human memory consolidates during sleep, this worker:
- Promotes frequently accessed facts from working memory to long-term
- Decays confidence of stale/unused memories
- Consolidates similar memories into stronger unified facts
- Removes redundant or contradictory information
- Creates summary memories from patterns

Runs periodically (nightly or hourly) to maintain memory quality.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import asyncio
from collections import defaultdict

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class ConsolidationResult:
    """Results from a consolidation run."""
    user_id: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    
    # Counts
    facts_promoted: int = 0
    facts_decayed: int = 0
    facts_consolidated: int = 0
    facts_removed: int = 0
    patterns_reinforced: int = 0
    goals_archived: int = 0
    
    # Errors
    errors: List[str] = field(default_factory=list)
    
    @property
    def duration_seconds(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "facts_promoted": self.facts_promoted,
            "facts_decayed": self.facts_decayed,
            "facts_consolidated": self.facts_consolidated,
            "facts_removed": self.facts_removed,
            "patterns_reinforced": self.patterns_reinforced,
            "goals_archived": self.goals_archived,
            "error_count": len(self.errors)
        }


class MemoryConsolidationWorker:
    """
    Background worker for memory consolidation.
    
    Responsibilities:
    1. Promote high-confidence pending facts to semantic memory
    2. Decay stale/unused fact confidence
    3. Consolidate similar facts
    4. Remove low-confidence facts
    5. Archive completed goals
    6. Reinforce frequently-used patterns
    """
    
    # Consolidation thresholds
    PROMOTION_CONFIDENCE_THRESHOLD = 0.7  # Min confidence to promote
    DECAY_RATE = 0.05  # Confidence decay per day of non-use
    REMOVAL_CONFIDENCE_THRESHOLD = 0.1  # Below this, remove fact
    CONSOLIDATION_SIMILARITY_THRESHOLD = 0.85  # For merging similar facts
    GOAL_ARCHIVE_DAYS = 30  # Archive completed goals after this many days
    
    def __init__(
        self,
        working_memory_manager: Optional[Any] = None,
        semantic_memory: Optional[Any] = None,
        goal_tracker: Optional[Any] = None,
        agent_lane_manager: Optional[Any] = None,
        db: Optional[Any] = None
    ):
        """
        Initialize the consolidation worker.
        
        Args:
            working_memory_manager: WorkingMemoryManager instance
            semantic_memory: SemanticMemory instance
            goal_tracker: GoalTracker instance
            agent_lane_manager: AgentMemoryLaneManager instance
            db: Optional database session
        """
        self.working_memory_manager = working_memory_manager
        self.semantic_memory = semantic_memory
        self.goal_tracker = goal_tracker
        self.agent_lane_manager = agent_lane_manager
        self.db = db
        
        # Track last consolidation per user
        self._last_consolidation: Dict[int, datetime] = {}
        
        # Consolidation history
        self._history: List[ConsolidationResult] = []
        
        logger.info("[MemoryConsolidationWorker] Initialized")
    
    async def consolidate_user(self, user_id: int) -> ConsolidationResult:
        """
        Run full consolidation for a single user.
        
        Args:
            user_id: User to consolidate
            
        Returns:
            ConsolidationResult with stats
        """
        result = ConsolidationResult(
            user_id=user_id,
            started_at=datetime.utcnow()
        )
        
        logger.info(f"[Consolidation] Starting for user {user_id}")
        
        try:
            # 1. Promote pending facts from working memory
            promoted = await self._promote_pending_facts(user_id, result)
            
            # 2. Decay stale facts
            decayed = await self._decay_stale_facts(user_id, result)
            
            # 3. Consolidate similar facts
            consolidated = await self._consolidate_similar_facts(user_id, result)
            
            # 4. Remove low-confidence facts
            removed = await self._remove_low_confidence_facts(user_id, result)
            
            # 5. Archive old completed goals
            archived = await self._archive_completed_goals(user_id, result)
            
            # 6. Reinforce agent patterns
            reinforced = await self._reinforce_patterns(user_id, result)
            
        except Exception as e:
            result.errors.append(f"Consolidation failed: {str(e)}")
            logger.error(f"[Consolidation] Error for user {user_id}: {e}")
        
        result.completed_at = datetime.utcnow()
        self._last_consolidation[user_id] = result.completed_at
        self._history.append(result)
        
        logger.info(
            f"[Consolidation] Completed for user {user_id} in "
            f"{result.duration_seconds:.2f}s: "
            f"promoted={result.facts_promoted}, "
            f"decayed={result.facts_decayed}, "
            f"consolidated={result.facts_consolidated}, "
            f"removed={result.facts_removed}"
        )
        
        return result
    
    async def _promote_pending_facts(
        self, 
        user_id: int, 
        result: ConsolidationResult
    ) -> int:
        """Promote high-confidence pending facts to semantic memory."""
        promoted = 0
        
        if not self.working_memory_manager or not self.semantic_memory:
            return 0
        
        try:
            # Get all sessions for user
            sessions = self.working_memory_manager.get_sessions_for_user(user_id)
            
            for session_id in sessions:
                wm = self.working_memory_manager.get(user_id, session_id)
                if not wm:
                    continue
                
                # Get pending facts ready for promotion
                pending = wm.get_pending_facts()
                for fact in pending:
                    if fact.confidence >= self.PROMOTION_CONFIDENCE_THRESHOLD:
                        # Promote to semantic memory
                        if hasattr(self.semantic_memory, "learn_fact"):
                            await self.semantic_memory.learn_fact(
                                user_id=user_id,
                                content=fact.content,
                                category=fact.category,
                                source=fact.source,
                                confidence=fact.confidence
                            )
                            promoted += 1
                            
                            # Mark as promoted (remove from pending)
                            wm.pending_facts.remove(fact)
        
        except Exception as e:
            result.errors.append(f"Promotion failed: {str(e)}")
            logger.debug(f"[Consolidation] Promotion error: {e}")
        
        result.facts_promoted = promoted
        return promoted
    
    async def _decay_stale_facts(
        self, 
        user_id: int, 
        result: ConsolidationResult
    ) -> int:
        """Apply confidence decay to facts not accessed recently."""
        decayed = 0
        
        if not self.semantic_memory:
            return 0
        
        try:
            # Get all facts for user
            if hasattr(self.semantic_memory, "get_all_facts"):
                facts = await self.semantic_memory.get_all_facts(user_id)
                cutoff = datetime.utcnow() - timedelta(days=7)
                
                for fact in (facts or []):
                    last_accessed = getattr(fact, "last_accessed", None)
                    last_accessed = last_accessed or getattr(fact, "updated_at", None)
                    
                    if last_accessed and last_accessed < cutoff:
                        # Calculate days since access
                        days_stale = (datetime.utcnow() - last_accessed).days
                        decay_amount = self.DECAY_RATE * (days_stale / 7)
                        
                        # Apply decay
                        current_confidence = getattr(fact, "confidence", 0.5)
                        new_confidence = max(0.0, current_confidence - decay_amount)
                        
                        if new_confidence < current_confidence:
                            if hasattr(self.semantic_memory, "update_fact_confidence"):
                                await self.semantic_memory.update_fact_confidence(
                                    fact_id=fact.id,
                                    new_confidence=new_confidence
                                )
                            decayed += 1
        
        except Exception as e:
            result.errors.append(f"Decay failed: {str(e)}")
            logger.debug(f"[Consolidation] Decay error: {e}")
        
        result.facts_decayed = decayed
        return decayed
    
    async def _consolidate_similar_facts(
        self, 
        user_id: int, 
        result: ConsolidationResult
    ) -> int:
        """Merge similar facts into stronger unified facts."""
        consolidated = 0
        
        if not self.semantic_memory:
            return 0
        
        try:
            if hasattr(self.semantic_memory, "get_all_facts"):
                facts = await self.semantic_memory.get_all_facts(user_id)
                
                if not facts or len(facts) < 2:
                    return 0
                
                # Group facts by category
                by_category = defaultdict(list)
                for fact in facts:
                    category = getattr(fact, "category", "general")
                    by_category[category].append(fact)
                
                # Find similar facts within each category
                for category, category_facts in by_category.items():
                    if len(category_facts) < 2:
                        continue
                    
                    # Simple word overlap similarity
                    to_merge = []
                    for i, fact1 in enumerate(category_facts):
                        for fact2 in category_facts[i+1:]:
                            similarity = self._calculate_similarity(
                                getattr(fact1, "content", ""),
                                getattr(fact2, "content", "")
                            )
                            
                            if similarity >= self.CONSOLIDATION_SIMILARITY_THRESHOLD:
                                to_merge.append((fact1, fact2, similarity))
                    
                    # Merge pairs
                    for fact1, fact2, sim in to_merge:
                        # Keep the one with higher confidence
                        conf1 = getattr(fact1, "confidence", 0.5)
                        conf2 = getattr(fact2, "confidence", 0.5)
                        
                        if conf1 >= conf2:
                            keep, remove = fact1, fact2
                        else:
                            keep, remove = fact2, fact1
                        
                        # Boost confidence of kept fact
                        if hasattr(self.semantic_memory, "update_fact_confidence"):
                            new_conf = min(1.0, getattr(keep, "confidence", 0.5) + 0.1)
                            await self.semantic_memory.update_fact_confidence(
                                fact_id=keep.id,
                                new_confidence=new_conf
                            )
                        
                        # Remove duplicate
                        if hasattr(self.semantic_memory, "delete_fact"):
                            await self.semantic_memory.delete_fact(remove.id)
                        
                        consolidated += 1
        
        except Exception as e:
            result.errors.append(f"Consolidation failed: {str(e)}")
            logger.debug(f"[Consolidation] Merge error: {e}")
        
        result.facts_consolidated = consolidated
        return consolidated
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate word overlap similarity between two texts."""
        if not text1 or not text2:
            return 0.0
        
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return intersection / union if union > 0 else 0.0
    
    async def _remove_low_confidence_facts(
        self, 
        user_id: int, 
        result: ConsolidationResult
    ) -> int:
        """Remove facts with very low confidence."""
        removed = 0
        
        if not self.semantic_memory:
            return 0
        
        try:
            if hasattr(self.semantic_memory, "get_all_facts"):
                facts = await self.semantic_memory.get_all_facts(user_id)
                
                for fact in (facts or []):
                    confidence = getattr(fact, "confidence", 0.5)
                    
                    if confidence < self.REMOVAL_CONFIDENCE_THRESHOLD:
                        if hasattr(self.semantic_memory, "delete_fact"):
                            await self.semantic_memory.delete_fact(fact.id)
                            removed += 1
        
        except Exception as e:
            result.errors.append(f"Removal failed: {str(e)}")
            logger.debug(f"[Consolidation] Removal error: {e}")
        
        result.facts_removed = removed
        return removed
    
    async def _archive_completed_goals(
        self, 
        user_id: int, 
        result: ConsolidationResult
    ) -> int:
        """Archive old completed goals."""
        archived = 0
        
        if not self.goal_tracker:
            return 0
        
        try:
            # Access goals directly (internal API)
            if hasattr(self.goal_tracker, "_goals"):
                user_goals = self.goal_tracker._goals.get(user_id, {})
                cutoff = datetime.utcnow() - timedelta(days=self.GOAL_ARCHIVE_DAYS)
                
                to_archive = []
                
                for goal_id, goal in user_goals.items():
                    if goal.status.value == "completed":
                        if goal.completed_at and goal.completed_at < cutoff:
                            to_archive.append(goal_id)
                
                for goal_id in to_archive:
                    # Mark as archived (move to archived status instead of deleting)
                    goal = user_goals[goal_id]
                    goal.status = GoalStatus.ARCHIVED
                    archived += 1
                    
                    # Store in database if available
                    if self.db:
                        try:
                            from src.database.models import AgentGoal
                            db_goal = self.db.query(AgentGoal).filter(
                                AgentGoal.id == int(goal_id.replace('goal_', '')) if 'goal_' in goal_id else 0,
                                AgentGoal.user_id == user_id
                            ).first()
                            
                            if db_goal:
                                db_goal.status = 'archived'
                                self.db.commit()
                        except Exception as e:
                            logger.debug(f"[Consolidation] Failed to persist archived goal {goal_id} to DB: {e}")
                            self.db.rollback()
        
        except Exception as e:
            result.errors.append(f"Archival failed: {str(e)}")
            logger.debug(f"[Consolidation] Archive error: {e}")
        
        result.goals_archived = archived
        return archived
    
    async def _reinforce_patterns(
        self, 
        user_id: int, 
        result: ConsolidationResult
    ) -> int:
        """Reinforce frequently-used agent patterns."""
        reinforced = 0
        
        if not self.agent_lane_manager:
            return 0
        
        try:
            lanes = self.agent_lane_manager.get_all_for_user(user_id)
            
            for agent_name, lane in lanes.items():
                for pattern_id, pattern in lane.patterns.items():
                    # Reinforce patterns with high success rate
                    if pattern.success_count >= 5 and pattern.confidence >= 0.8:
                        # Pattern doesn't need reinforcement, it's already strong
                        continue
                    
                    # Decay patterns not used recently
                    if pattern.last_used:
                        days_since_use = (datetime.utcnow() - pattern.last_used).days
                        if days_since_use > 14 and pattern.confidence > 0.3:
                            # Decay unused patterns
                            pattern.failure_count += 1  # Simulates soft decay
                            reinforced -= 1  # Track negative reinforcement
        
        except Exception as e:
            result.errors.append(f"Pattern reinforcement failed: {str(e)}")
            logger.debug(f"[Consolidation] Pattern error: {e}")
        
        result.patterns_reinforced = max(0, reinforced)
        return reinforced
    
    async def consolidate_all_users(self) -> List[ConsolidationResult]:
        """Run consolidation for all tracked users."""
        results = []
        
        # Get users from working memory manager
        user_ids = set()
        
        if self.working_memory_manager and hasattr(self.working_memory_manager, "_memories"):
            user_ids.update(self.working_memory_manager._memories.keys())
        
        if self.goal_tracker and hasattr(self.goal_tracker, "_goals"):
            user_ids.update(self.goal_tracker._goals.keys())
        
        if self.agent_lane_manager and hasattr(self.agent_lane_manager, "_lanes"):
            user_ids.update(self.agent_lane_manager._lanes.keys())
        
        logger.info(f"[Consolidation] Running for {len(user_ids)} users")
        
        for user_id in user_ids:
            result = await self.consolidate_user(user_id)
            results.append(result)
        
        return results
    
    def should_consolidate(self, user_id: int, min_hours: int = 6) -> bool:
        """Check if user should be consolidated (hasn't been done recently)."""
        last = self._last_consolidation.get(user_id)
        if not last:
            return True
        
        hours_since = (datetime.utcnow() - last).total_seconds() / 3600
        return hours_since >= min_hours
    
    def get_last_consolidation(self, user_id: int) -> Optional[datetime]:
        """Get last consolidation time for a user."""
        return self._last_consolidation.get(user_id)
    
    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get consolidation history."""
        return [r.to_dict() for r in self._history[-limit:]]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall consolidation statistics."""
        if not self._history:
            return {"total_runs": 0}
        
        return {
            "total_runs": len(self._history),
            "total_users_consolidated": len(self._last_consolidation),
            "total_facts_promoted": sum(r.facts_promoted for r in self._history),
            "total_facts_decayed": sum(r.facts_decayed for r in self._history),
            "total_facts_consolidated": sum(r.facts_consolidated for r in self._history),
            "total_facts_removed": sum(r.facts_removed for r in self._history),
            "total_goals_archived": sum(r.goals_archived for r in self._history),
            "last_run": self._history[-1].started_at.isoformat() if self._history else None
        }


# Global instance
_consolidation_worker: Optional[MemoryConsolidationWorker] = None


def get_consolidation_worker() -> Optional[MemoryConsolidationWorker]:
    """Get the global MemoryConsolidationWorker instance."""
    return _consolidation_worker


def init_consolidation_worker(
    working_memory_manager: Optional[Any] = None,
    semantic_memory: Optional[Any] = None,
    goal_tracker: Optional[Any] = None,
    agent_lane_manager: Optional[Any] = None,
    db: Optional[Any] = None
) -> MemoryConsolidationWorker:
    """Initialize the global MemoryConsolidationWorker."""
    global _consolidation_worker
    _consolidation_worker = MemoryConsolidationWorker(
        working_memory_manager=working_memory_manager,
        semantic_memory=semantic_memory,
        goal_tracker=goal_tracker,
        agent_lane_manager=agent_lane_manager,
        db=db
    )
    logger.info("[MemoryConsolidationWorker] Global instance initialized")
    return _consolidation_worker
