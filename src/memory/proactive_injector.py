"""
Proactive Memory Injector

Pushes relevant memories to agents BEFORE they need them.

Instead of waiting for agents to query memory, this component:
- Monitors active context and identifies relevant memories
- Pre-loads memories that might be needed based on patterns
- Surfaces important memories that haven't been accessed recently
- Injects "you should know" context proactively

This enables truly intelligent agents that anticipate needs.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple
from enum import Enum
import asyncio

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class InjectionReason(str, Enum):
    """Why a memory was proactively injected."""
    ENTITY_MATCH = "entity_match"  # Memory mentions same entity
    TOPIC_RELATED = "topic_related"  # Memory relates to current topic
    TIME_SENSITIVE = "time_sensitive"  # Memory has time relevance
    PATTERN_MATCH = "pattern_match"  # Matches a learned pattern
    GOAL_RELATED = "goal_related"  # Related to active goal
    UNACCESSED_IMPORTANT = "unaccessed_important"  # Important but not recently accessed
    CONFLICT_DETECTED = "conflict_detected"  # Conflicts with current action
    OPPORTUNITY = "opportunity"  # Opportunity based on context
    PROTECTION_ADVISORY = "protection_advisory"  # Advice based on Deep Work status
    CROSS_STACK_INSIGHT = "cross_stack_insight"  # Insight synthesized from multiple sources
    WORKLOAD_ADVISORY = "workload_advisory"  # User has heavy calendar or overdue items
    RELATIONSHIP_NUDGE = "relationship_nudge"  # Fading contact or open loop with someone mentioned


@dataclass
class ProactiveMemory:
    """A memory that should be proactively surfaced."""
    content: str
    reason: InjectionReason
    relevance_score: float  # 0.0 to 1.0
    source: str  # 'semantic', 'graph', 'pattern', 'goal'
    
    # Context about why this is relevant
    explanation: str
    related_entities: List[str] = field(default_factory=list)
    
    # Metadata
    memory_id: Optional[str] = None
    urgency: str = "normal"  # 'critical', 'high', 'normal', 'low'
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def format_for_context(self) -> str:
        """Format for LLM context injection."""
        urgency_prefix = {
            "critical": "🚨 ",
            "high": "⚠️ ",
            "normal": "ℹ️ ",
            "low": "💡 "
        }
        prefix = urgency_prefix.get(self.urgency, "ℹ️ ")
        
        return f"{prefix}{self.explanation}: {self.content}"


@dataclass 
class InjectionContext:
    """Context for determining what to inject."""
    user_id: int
    agent_name: str
    current_query: str
    active_entities: List[str] = field(default_factory=list)
    active_topics: List[str] = field(default_factory=list)
    active_goals: List[str] = field(default_factory=list)
    current_intent: Optional[str] = None
    session_id: Optional[str] = None


class ProactiveInjector:
    """
    Proactively pushes relevant memories to agents.
    
    Responsibilities:
    - Identify memories that should be surfaced
    - Score memories by relevance to current context
    - Filter to avoid overwhelming agents
    - Track what has been injected to avoid repetition
    """
    
    # Configuration
    MAX_INJECTIONS_PER_TURN = 3
    MIN_RELEVANCE_THRESHOLD = 0.5
    RECENCY_WINDOW_HOURS = 24
    
    def __init__(
        self,
        semantic_memory: Optional[Any] = None,
        graph_manager: Optional[Any] = None,
        goal_tracker: Optional[Any] = None,
        salience_scorer: Optional[Any] = None
    ):
        """
        Initialize the proactive injector.
        
        Args:
            semantic_memory: SemanticMemory instance
            graph_manager: KnowledgeGraphManager instance
            goal_tracker: GoalTracker instance
            salience_scorer: SalienceScorer instance
        """
        self.semantic_memory = semantic_memory
        self.graph_manager = graph_manager
        self.goal_tracker = goal_tracker
        self.salience_scorer = salience_scorer
        
        # Track recently injected memories to avoid repetition
        # user_id -> set of memory IDs
        self._recently_injected: Dict[int, Set[str]] = {}
        self._injection_timestamps: Dict[int, List[datetime]] = {}
    
    async def get_proactive_memories(
        self,
        context: InjectionContext,
        max_memories: int = None
    ) -> List[ProactiveMemory]:
        """
        Get memories that should be proactively surfaced.
        
        Args:
            context: Current context for injection decisions
            max_memories: Maximum memories to return
            
        Returns:
            List of ProactiveMemory to inject, sorted by relevance
        """
        max_memories = max_memories or self.MAX_INJECTIONS_PER_TURN
        candidates = []
        
        # Gather candidates from various sources
        tasks = [
            self._find_entity_related_memories(context),
            self._find_goal_related_memories(context),
            self._find_time_sensitive_memories(context),
            self._find_conflict_memories(context),
            self._find_opportunity_memories(context),
            self._find_linear_proactive_memories(context),
            self._find_protection_memories(context),
            self._find_workload_memories(context)
        ]
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.debug(f"[ProactiveInjector] Source failed: {result}")
                    continue
                if result:
                    candidates.extend(result)
        
        except Exception as e:
            logger.warning(f"[ProactiveInjector] Memory gathering failed: {e}")
        
        # Deduplicate and filter
        filtered = self._filter_candidates(candidates, context.user_id)
        
        # Sort by relevance and urgency
        sorted_memories = sorted(
            filtered,
            key=lambda m: (
                {"critical": 3, "high": 2, "normal": 1, "low": 0}[m.urgency],
                m.relevance_score
            ),
            reverse=True
        )
        
        # Take top N
        result = sorted_memories[:max_memories]
        
        # Record what we're injecting
        self._record_injection(context.user_id, result)
        
        logger.debug(
            f"[ProactiveInjector] Returning {len(result)} memories for "
            f"user={context.user_id}, agent={context.agent_name}"
        )
        
        return result
    
    async def _find_entity_related_memories(
        self, 
        context: InjectionContext
    ) -> List[ProactiveMemory]:
        """Find memories related to active entities."""
        memories = []
        
        if not context.active_entities or not self.semantic_memory:
            return memories
        
        try:
            for entity in context.active_entities[:3]:
                if hasattr(self.semantic_memory, "search_facts"):
                    facts = await self.semantic_memory.search_facts(
                        query=entity,
                        user_id=context.user_id,
                        limit=2
                    )
                    
                    for fact in (facts or []):
                        content = getattr(fact, "content", str(fact))
                        confidence = getattr(fact, "confidence", 0.5)
                        
                        if confidence >= 0.5:
                            memories.append(ProactiveMemory(
                                content=content,
                                reason=InjectionReason.ENTITY_MATCH,
                                relevance_score=confidence,
                                source="semantic",
                                explanation=f"About {entity}",
                                related_entities=[entity],
                                urgency="normal" if confidence < 0.8 else "high"
                            ))
        
        except Exception as e:
            logger.debug(f"[ProactiveInjector] Entity search failed: {e}")
        
        return memories
    
    async def _find_goal_related_memories(
        self, 
        context: InjectionContext
    ) -> List[ProactiveMemory]:
        """Find memories related to active goals."""
        memories = []
        
        if not context.active_goals or not self.goal_tracker:
            return memories
        
        try:
            active_goals = await self.goal_tracker.get_active_goals(context.user_id)
            
            for goal in active_goals[:2]:
                # Check for overdue goals
                if goal.is_overdue():
                    memories.append(ProactiveMemory(
                        content=goal.description,
                        reason=InjectionReason.GOAL_RELATED,
                        relevance_score=1.0,
                        source="goal",
                        explanation="Overdue goal",
                        urgency="critical"
                    ))
                
                # Check for due-soon goals
                elif goal.days_until_due() is not None and goal.days_until_due() <= 2:
                    memories.append(ProactiveMemory(
                        content=goal.description,
                        reason=InjectionReason.GOAL_RELATED,
                        relevance_score=0.9,
                        source="goal",
                        explanation=f"Due in {goal.days_until_due()} days",
                        urgency="high"
                    ))
        
        except Exception as e:
            logger.debug(f"[ProactiveInjector] Goal search failed: {e}")
        
        return memories
    
    async def _find_time_sensitive_memories(
        self, 
        context: InjectionContext
    ) -> List[ProactiveMemory]:
        """Find time-sensitive memories (upcoming events, deadlines)."""
        memories = []
        
        if not self.graph_manager:
            return memories
        
        try:
            # Look for upcoming calendar events
            if hasattr(self.graph_manager, "query"):
                now = datetime.utcnow()
                soon = now + timedelta(hours=4)
                
                # Query for events in the next 4 hours
                query = """
                FOR e IN CalendarEvent
                    FILTER e.user_id == @user_id
                      AND e.start_time >= @now
                      AND e.start_time <= @soon
                    LIMIT 2
                    RETURN { title: e.title, start_time: e.start_time }
                """
                
                results = await self.graph_manager.query(
                    query,
                    {"user_id": context.user_id, "now": now.isoformat(), "soon": soon.isoformat()}
                )
                
                for record in results:
                    memories.append(ProactiveMemory(
                        content=f"Upcoming: {record['e.title']}",
                        reason=InjectionReason.TIME_SENSITIVE,
                        relevance_score=0.85,
                        source="graph",
                        explanation="Event coming up soon",
                        urgency="high"
                    ))
        
        except Exception as e:
            logger.debug(f"[ProactiveInjector] Time-sensitive search failed: {e}")
        
        # Check for Linear deadlines if available
        if self.graph_manager:
            try:
                # Query for Linear issues due within 24 hours
                now = datetime.utcnow()
                tomorrow = now + timedelta(days=1)
                
                query = """
                FOR i IN LinearIssue
                    FILTER i.user_id == @user_id
                      AND i.dueDate >= @now
                      AND i.dueDate <= @tomorrow
                      AND i.priority IN [1, 2]
                    LIMIT 2
                    RETURN { title: i.title, identifier: i.identifier, priority: i.priority }
                """
                
                results = await self.graph_manager.query(
                    query,
                    {"user_id": context.user_id, "now": now.isoformat(), "tomorrow": tomorrow.isoformat()}
                )
                
                for record in results:
                    memories.append(ProactiveMemory(
                        content=f"Deadline: {record['i.identifier']} - {record['i.title']}",
                        reason=InjectionReason.TIME_SENSITIVE,
                        relevance_score=0.9,
                        source="graph",
                        explanation="Linear issue due soon",
                        urgency="critical" if record['i.priority'] == 1 else "high"
                    ))
            except Exception as e:
                logger.debug(f"[ProactiveInjector] Linear deadline search failed: {e}")
        
        return memories
    
    async def _find_conflict_memories(
        self, 
        context: InjectionContext
    ) -> List[ProactiveMemory]:
        """Find potential conflicts with current action."""
        memories = []
        
        # Look for scheduling conflicts if calendar-related
        if context.agent_name == "calendar" and self.graph_manager:
            try:
                # Check if any entities mentioned are marked as unavailable
                for entity in context.active_entities:
                    if hasattr(self.graph_manager, "query"):
                        query = """
                        FOR p IN Person
                            FILTER CONTAINS(LOWER(p.name), LOWER(@entity))
                            FOR s IN OUTBOUND p HAS_STATUS
                                FILTER s.type IN ['OOO', 'Busy', 'Unavailable']
                                LIMIT 1
                                RETURN { name: p.name, type: s.type, until: s.until }
                        """
                        
                        results = await self.graph_manager.query(
                            query,
                            {"entity": entity}
                        )
                        
                        for record in results:
                            memories.append(ProactiveMemory(
                                content=f"{record['p.name']} is currently {record['s.type']}",
                                reason=InjectionReason.CONFLICT_DETECTED,
                                relevance_score=0.95,
                                source="graph",
                                explanation="Potential conflict",
                                related_entities=[entity],
                                urgency="high"
                            ))
            
            except Exception as e:
                logger.debug(f"[ProactiveInjector] Conflict search failed: {e}")
        
        return memories
    
    async def _find_opportunity_memories(
        self, 
        context: InjectionContext
    ) -> List[ProactiveMemory]:
        """Find opportunities based on context."""
        memories = []
        
        # Example: If user mentions a person, surface recent interactions
        if context.active_entities and self.semantic_memory:
            try:
                for entity in context.active_entities[:2]:
                    # Look for communication patterns
                    if hasattr(self.semantic_memory, "search_facts"):
                        facts = await self.semantic_memory.search_facts(
                            query=f"communication {entity}",
                            user_id=context.user_id,
                            limit=1
                        )
                        
                        for fact in (facts or []):
                            content = getattr(fact, "content", str(fact))
                            if "prefer" in content.lower() or "like" in content.lower():
                                memories.append(ProactiveMemory(
                                    content=content,
                                    reason=InjectionReason.OPPORTUNITY,
                                    relevance_score=0.7,
                                    source="semantic",
                                    explanation=f"Tip for {entity}",
                                    related_entities=[entity],
                                    urgency="low"
                                ))
            
            except Exception as e:
                logger.debug(f"[ProactiveInjector] Opportunity search failed: {e}")
        
        return memories

    async def _find_linear_proactive_memories(
        self, 
        context: InjectionContext
    ) -> List[ProactiveMemory]:
        """Find Linear issues that should be proactively surfaced."""
        memories = []
        
        # Placeholder for Linear-specific proactive discovery.
        # Could query Linear for blockers or high-priority unassigned issues.
        return memories

    async def _find_protection_memories(
        self, 
        context: InjectionContext
    ) -> List[ProactiveMemory]:
        """Find protection (Deep Work) advisories."""
        memories = []
        
        # If the user is in Deep Work, inject a reminder for the agent to be brief
        # and not ask for elaborate clarifications unless necessary.
        return memories

    async def _find_workload_memories(
        self, 
        context: InjectionContext
    ) -> List[ProactiveMemory]:
        """Find workload advisories — nudge when user is overloaded."""
        memories = []
        
        if not self.graph_manager:
            return memories
        
        try:
            # Check how many meetings the user has today
            if hasattr(self.graph_manager, "query"):
                now = datetime.utcnow()
                today_start = now.replace(hour=0, minute=0, second=0)
                today_end = now.replace(hour=23, minute=59, second=59)
                
                query = """
                FOR e IN CalendarEvent
                    FILTER e.user_id == @user_id
                      AND e.start_time >= @today_start
                      AND e.start_time <= @today_end
                    COLLECT WITH COUNT INTO total
                    RETURN total
                """
                
                results = await self.graph_manager.query(
                    query,
                    {
                        "user_id": context.user_id,
                        "today_start": today_start.isoformat(),
                        "today_end": today_end.isoformat()
                    }
                )
                
                meeting_count = results[0] if results else 0
                
                if meeting_count >= 6:
                    memories.append(ProactiveMemory(
                        content=f"User has {meeting_count} meetings today",
                        reason=InjectionReason.WORKLOAD_ADVISORY,
                        relevance_score=0.8,
                        source="graph",
                        explanation=f"Heavy day — {meeting_count} meetings. Keep responses tight and offer to defer non-critical items.",
                        urgency="high"
                    ))
                elif meeting_count >= 4:
                    memories.append(ProactiveMemory(
                        content=f"User has {meeting_count} meetings today",
                        reason=InjectionReason.WORKLOAD_ADVISORY,
                        relevance_score=0.6,
                        source="graph",
                        explanation=f"Busy day with {meeting_count} meetings. Be mindful of the user's time.",
                        urgency="normal"
                    ))
        except Exception as e:
            logger.debug(f"[ProactiveInjector] Workload check failed: {e}")
        
        return memories
    
    def _filter_candidates(
        self, 
        candidates: List[ProactiveMemory],
        user_id: int
    ) -> List[ProactiveMemory]:
        """Filter and deduplicate candidates."""
        filtered = []
        seen_content = set()
        recently_injected = self._recently_injected.get(user_id, set())
        
        for memory in candidates:
            # Skip below threshold
            if memory.relevance_score < self.MIN_RELEVANCE_THRESHOLD:
                continue
            
            # Skip duplicates
            content_key = memory.content.lower()[:100]
            if content_key in seen_content:
                continue
            seen_content.add(content_key)
            
            # Skip recently injected (unless critical)
            if memory.memory_id and memory.memory_id in recently_injected:
                if memory.urgency != "critical":
                    continue
            
            filtered.append(memory)
        
        return filtered
    
    def _record_injection(self, user_id: int, memories: List[ProactiveMemory]):
        """Record injected memories to avoid repetition."""
        if user_id not in self._recently_injected:
            self._recently_injected[user_id] = set()
        
        for memory in memories:
            if memory.memory_id:
                self._recently_injected[user_id].add(memory.memory_id)
        
        # Also record timestamp for cleanup
        if user_id not in self._injection_timestamps:
            self._injection_timestamps[user_id] = []
        self._injection_timestamps[user_id].append(datetime.utcnow())
        
        # Cleanup old records (older than 1 hour)
        self._cleanup_old_records(user_id)
    
    def _cleanup_old_records(self, user_id: int):
        """Remove old injection records."""
        cutoff = datetime.utcnow() - timedelta(hours=1)
        
        if user_id in self._injection_timestamps:
            self._injection_timestamps[user_id] = [
                ts for ts in self._injection_timestamps[user_id]
                if ts > cutoff
            ]
            
            # If all timestamps are old, clear the recently injected set
            if not self._injection_timestamps[user_id]:
                self._recently_injected[user_id] = set()
    
    def format_proactive_context(
        self, 
        memories: List[ProactiveMemory]
    ) -> str:
        """Format proactive memories for LLM injection."""
        if not memories:
            return ""
        
        lines = ["PROACTIVE CONTEXT:"]
        for memory in memories:
            lines.append(memory.format_for_context())
        
        return "\n".join(lines)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get injector statistics."""
        total_users = len(self._recently_injected)
        total_injected = sum(
            len(ids) for ids in self._recently_injected.values()
        )
        
        return {
            "total_users_tracked": total_users,
            "total_memories_injected": total_injected,
            "max_injections_per_turn": self.MAX_INJECTIONS_PER_TURN,
            "relevance_threshold": self.MIN_RELEVANCE_THRESHOLD
        }


# Global instance
_proactive_injector: Optional[ProactiveInjector] = None


def get_proactive_injector() -> Optional[ProactiveInjector]:
    """Get the global ProactiveInjector instance."""
    return _proactive_injector


def init_proactive_injector(
    semantic_memory: Optional[Any] = None,
    graph_manager: Optional[Any] = None,
    goal_tracker: Optional[Any] = None,
    salience_scorer: Optional[Any] = None
) -> ProactiveInjector:
    """Initialize the global ProactiveInjector."""
    global _proactive_injector
    _proactive_injector = ProactiveInjector(
        semantic_memory=semantic_memory,
        graph_manager=graph_manager,
        goal_tracker=goal_tracker,
        salience_scorer=salience_scorer
    )
    logger.info("[ProactiveInjector] Global instance initialized")
    return _proactive_injector
