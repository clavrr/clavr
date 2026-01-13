"""
Agent Memory Lane

Domain-specific memory for each agent type.

Each agent (Email, Calendar, Tasks, etc.) has its own "memory lane" where
domain-specific patterns, preferences, and learned behaviors are stored.

This enables:
- EmailAgent remembering email formatting preferences
- CalendarAgent learning scheduling patterns
- TaskAgent understanding task prioritization preferences
- Each agent evolving its behavior based on user interactions

AgentMemoryLane provides:
- Domain-specific pattern storage
- Learned tool preferences
- Success/failure tracking per intent
- Agent-specific fact storage
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
import json

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class LearnedPattern:
    """A pattern learned by an agent from user interactions."""
    pattern_id: str
    agent_name: str
    pattern_type: str  # 'tool_usage', 'response_style', 'preference', 'workflow'
    description: str
    
    # Pattern data
    trigger: str  # What triggers this pattern (intent, keyword, context)
    action: str  # What action this pattern suggests
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Statistics
    success_count: int = 0
    failure_count: int = 0
    last_used: Optional[datetime] = None
    first_seen: datetime = field(default_factory=datetime.utcnow)
    
    # Confidence based on success rate
    @property
    def confidence(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5  # Default confidence
        return self.success_count / total
    
    def record_usage(self, success: bool):
        """Record pattern usage outcome."""
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        self.last_used = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "pattern_id": self.pattern_id,
            "agent_name": self.agent_name,
            "pattern_type": self.pattern_type,
            "description": self.description,
            "trigger": self.trigger,
            "action": self.action,
            "parameters": self.parameters,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "first_seen": self.first_seen.isoformat(),
            "confidence": self.confidence
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnedPattern":
        """Deserialize from dictionary."""
        pattern = cls(
            pattern_id=data["pattern_id"],
            agent_name=data["agent_name"],
            pattern_type=data["pattern_type"],
            description=data["description"],
            trigger=data["trigger"],
            action=data["action"],
            parameters=data.get("parameters", {})
        )
        pattern.success_count = data.get("success_count", 0)
        pattern.failure_count = data.get("failure_count", 0)
        if data.get("last_used"):
            pattern.last_used = datetime.fromisoformat(data["last_used"])
        if data.get("first_seen"):
            pattern.first_seen = datetime.fromisoformat(data["first_seen"])
        return pattern


@dataclass
class AgentFact:
    """A fact learned specifically for an agent's domain."""
    fact_id: str
    agent_name: str
    user_id: int
    content: str
    category: str  # 'preference', 'behavior', 'constraint', 'history'
    
    # Metadata
    confidence: float = 0.5
    source: str = "inferred"  # 'explicit', 'inferred', 'pattern'
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_reinforced: Optional[datetime] = None
    reinforcement_count: int = 0
    
    def reinforce(self, boost: float = 0.1):
        """Reinforce this fact (increase confidence)."""
        self.confidence = min(1.0, self.confidence + boost)
        self.reinforcement_count += 1
        self.last_reinforced = datetime.utcnow()
    
    def decay(self, decay_rate: float = 0.02):
        """Apply time-based decay to confidence."""
        self.confidence = max(0.1, self.confidence - decay_rate)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "fact_id": self.fact_id,
            "agent_name": self.agent_name,
            "user_id": self.user_id,
            "content": self.content,
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "last_reinforced": self.last_reinforced.isoformat() if self.last_reinforced else None,
            "reinforcement_count": self.reinforcement_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentFact":
        """Deserialize from dictionary."""
        fact = cls(
            fact_id=data["fact_id"],
            agent_name=data["agent_name"],
            user_id=data["user_id"],
            content=data["content"],
            category=data["category"]
        )
        fact.confidence = data.get("confidence", 0.5)
        fact.source = data.get("source", "inferred")
        if data.get("created_at"):
            fact.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("last_reinforced"):
            fact.last_reinforced = datetime.fromisoformat(data["last_reinforced"])
        fact.reinforcement_count = data.get("reinforcement_count", 0)
        return fact


@dataclass
class ToolUsageStats:
    """Statistics for tool usage by an agent."""
    tool_name: str
    agent_name: str
    user_id: int
    
    # Usage counts
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    
    # Average execution time (ms)
    avg_execution_time_ms: float = 0.0
    total_execution_time_ms: float = 0.0
    
    # Common parameters
    common_params: Dict[str, int] = field(default_factory=dict)
    
    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls
    
    def record_call(
        self, 
        success: bool, 
        execution_time_ms: float = 0.0,
        params: Optional[Dict[str, Any]] = None
    ):
        """Record a tool call."""
        self.total_calls += 1
        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
        
        # Update average execution time
        self.total_execution_time_ms += execution_time_ms
        self.avg_execution_time_ms = self.total_execution_time_ms / self.total_calls
        
        # Track common parameters
        if params:
            for key, value in params.items():
                param_key = f"{key}={value}" if not isinstance(value, (dict, list)) else key
                self.common_params[param_key] = self.common_params.get(param_key, 0) + 1
    
    def get_most_common_params(self, top_k: int = 5) -> List[str]:
        """Get most commonly used parameters."""
        sorted_params = sorted(
            self.common_params.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        return [p[0] for p in sorted_params[:top_k]]


class AgentMemoryLane:
    """
    Domain-specific memory for an individual agent.
    
    Each agent has its own memory lane that stores:
    - Learned patterns (tool usage, response style, workflows)
    - Domain-specific facts (user preferences for this agent)
    - Tool usage statistics
    - Intent success/failure tracking
    """
    
    def __init__(
        self, 
        agent_name: str, 
        user_id: int,
        db: Optional[Any] = None
    ):
        """
        Initialize an agent memory lane.
        
        Args:
            agent_name: Name of the agent (email, calendar, tasks, etc.)
            user_id: User ID this memory lane belongs to
            db: Optional database session for persistence
        """
        self.agent_name = agent_name
        self.user_id = user_id
        self.db = db
        
        # In-memory storage
        self.patterns: Dict[str, LearnedPattern] = {}
        self.facts: Dict[str, AgentFact] = {}
        self.tool_stats: Dict[str, ToolUsageStats] = {}
        
        # Intent tracking: intent -> {success_count, failure_count}
        self.intent_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failure": 0}
        )
        
        # Session-level context
        self.session_context: Dict[str, Any] = {}
        
        # Pattern ID counter
        self._next_pattern_id = 1
        self._next_fact_id = 1
    
    def _generate_pattern_id(self) -> str:
        """Generate unique pattern ID."""
        pid = f"{self.agent_name}_pattern_{self._next_pattern_id}"
        self._next_pattern_id += 1
        return pid
    
    def _generate_fact_id(self) -> str:
        """Generate unique fact ID."""
        fid = f"{self.agent_name}_fact_{self._next_fact_id}"
        self._next_fact_id += 1
        return fid
    
    async def learn_pattern(
        self,
        pattern_type: str,
        trigger: str,
        action: str,
        description: str,
        parameters: Optional[Dict[str, Any]] = None,
        initial_confidence: float = 0.5
    ) -> LearnedPattern:
        """
        Learn a new pattern or reinforce existing one.
        
        Args:
            pattern_type: Type of pattern
            trigger: What triggers this pattern
            action: What action to take
            description: Human-readable description
            parameters: Optional additional parameters
            initial_confidence: Starting confidence for new patterns
            
        Returns:
            The learned or reinforced pattern
        """
        # Check if pattern already exists
        existing = self._find_similar_pattern(trigger, action)
        if existing:
            existing.record_usage(success=True)
            logger.debug(f"[{self.agent_name}] Reinforced pattern: {existing.pattern_id}")
            return existing
        
        # Create new pattern
        pattern = LearnedPattern(
            pattern_id=self._generate_pattern_id(),
            agent_name=self.agent_name,
            pattern_type=pattern_type,
            description=description,
            trigger=trigger,
            action=action,
            parameters=parameters or {}
        )
        
        self.patterns[pattern.pattern_id] = pattern
        logger.info(
            f"[{self.agent_name}] Learned new pattern: "
            f"'{description[:30]}...' (type: {pattern_type})"
        )
        
        return pattern
    
    def _find_similar_pattern(self, trigger: str, action: str) -> Optional[LearnedPattern]:
        """Find a pattern with similar trigger and action."""
        trigger_lower = trigger.lower()
        action_lower = action.lower()
        
        for pattern in self.patterns.values():
            if (pattern.trigger.lower() == trigger_lower and 
                pattern.action.lower() == action_lower):
                return pattern
        return None
    
    async def learn_fact(
        self,
        content: str,
        category: str,
        source: str = "inferred",
        confidence: float = 0.5
    ) -> AgentFact:
        """
        Learn a domain-specific fact.
        
        Args:
            content: The fact content
            category: Category (preference, behavior, constraint, history)
            source: How this fact was learned
            confidence: Initial confidence score
            
        Returns:
            The learned or reinforced fact
        """
        # Check for duplicate/similar fact
        existing = self._find_similar_fact(content)
        if existing:
            existing.reinforce()
            logger.debug(f"[{self.agent_name}] Reinforced fact: {existing.fact_id}")
            return existing
        
        # Create new fact
        fact = AgentFact(
            fact_id=self._generate_fact_id(),
            agent_name=self.agent_name,
            user_id=self.user_id,
            content=content,
            category=category,
            source=source,
            confidence=confidence
        )
        
        self.facts[fact.fact_id] = fact
        logger.info(
            f"[{self.agent_name}] Learned fact: "
            f"'{content[:40]}...' (category: {category})"
        )
        
        return fact
    
    def _find_similar_fact(self, content: str) -> Optional[AgentFact]:
        """Find a fact with similar content."""
        content_lower = content.lower()
        
        for fact in self.facts.values():
            if fact.content.lower() == content_lower:
                return fact
            # Check word overlap for fuzzy matching
            fact_words = set(fact.content.lower().split())
            content_words = set(content_lower.split())
            overlap = len(fact_words & content_words)
            if overlap >= min(len(fact_words), len(content_words)) * 0.8:
                return fact
        return None
    
    def record_tool_usage(
        self,
        tool_name: str,
        success: bool,
        execution_time_ms: float = 0.0,
        params: Optional[Dict[str, Any]] = None
    ):
        """Record a tool usage for statistics."""
        if tool_name not in self.tool_stats:
            self.tool_stats[tool_name] = ToolUsageStats(
                tool_name=tool_name,
                agent_name=self.agent_name,
                user_id=self.user_id
            )
        
        self.tool_stats[tool_name].record_call(
            success=success,
            execution_time_ms=execution_time_ms,
            params=params
        )
    
    def record_intent(self, intent: str, success: bool):
        """Record intent success/failure."""
        if success:
            self.intent_stats[intent]["success"] += 1
        else:
            self.intent_stats[intent]["failure"] += 1
    
    def get_patterns_for_trigger(
        self, 
        trigger: str, 
        min_confidence: float = 0.5
    ) -> List[LearnedPattern]:
        """Get patterns that match a trigger."""
        trigger_lower = trigger.lower()
        matching = []
        
        for pattern in self.patterns.values():
            if pattern.confidence >= min_confidence:
                if trigger_lower in pattern.trigger.lower():
                    matching.append(pattern)
        
        # Sort by confidence descending
        matching.sort(key=lambda p: p.confidence, reverse=True)
        return matching
    
    def get_facts_for_context(
        self, 
        category: Optional[str] = None,
        min_confidence: float = 0.3
    ) -> List[AgentFact]:
        """Get facts for context injection."""
        facts = []
        
        for fact in self.facts.values():
            if fact.confidence >= min_confidence:
                if category is None or fact.category == category:
                    facts.append(fact)
        
        # Sort by confidence descending
        facts.sort(key=lambda f: f.confidence, reverse=True)
        return facts
    
    def get_tool_preference(self) -> Optional[str]:
        """Get the most successful tool for this agent."""
        if not self.tool_stats:
            return None
        
        best_tool = None
        best_rate = 0.0
        
        for tool_name, stats in self.tool_stats.items():
            if stats.total_calls >= 3 and stats.success_rate > best_rate:
                best_rate = stats.success_rate
                best_tool = tool_name
        
        return best_tool
    
    def get_context_for_agent(self) -> Dict[str, Any]:
        """Get all relevant context for this agent's next action."""
        top_patterns = sorted(
            self.patterns.values(), 
            key=lambda p: p.confidence, 
            reverse=True
        )[:5]
        
        top_facts = sorted(
            self.facts.values(), 
            key=lambda f: f.confidence, 
            reverse=True
        )[:5]
        
        return {
            "patterns": [p.to_dict() for p in top_patterns],
            "facts": [f.to_dict() for f in top_facts],
            "preferred_tool": self.get_tool_preference(),
            "session_context": self.session_context
        }
    
    def format_for_prompt(self) -> str:
        """Format memory lane context for LLM prompt injection."""
        lines = []
        
        top_facts = self.get_facts_for_context(min_confidence=0.5)[:3]
        if top_facts:
            lines.append(f"[{self.agent_name.upper()} PREFERENCES]")
            for fact in top_facts:
                lines.append(f"- {fact.content}")
        
        top_patterns = self.get_patterns_for_trigger("", min_confidence=0.7)[:2]
        if top_patterns:
            lines.append(f"\n[LEARNED {self.agent_name.upper()} BEHAVIORS]")
            for pattern in top_patterns:
                lines.append(f"- When {pattern.trigger}: {pattern.action}")
        
        return "\n".join(lines) if lines else ""
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for this memory lane."""
        total_tool_calls = sum(s.total_calls for s in self.tool_stats.values())
        avg_success_rate = (
            sum(s.success_rate for s in self.tool_stats.values()) / len(self.tool_stats)
            if self.tool_stats else 0.0
        )
        
        return {
            "agent_name": self.agent_name,
            "user_id": self.user_id,
            "pattern_count": len(self.patterns),
            "fact_count": len(self.facts),
            "tool_count": len(self.tool_stats),
            "total_tool_calls": total_tool_calls,
            "avg_success_rate": avg_success_rate,
            "intent_count": len(self.intent_stats)
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize entire memory lane."""
        return {
            "agent_name": self.agent_name,
            "user_id": self.user_id,
            "patterns": {k: v.to_dict() for k, v in self.patterns.items()},
            "facts": {k: v.to_dict() for k, v in self.facts.items()},
            "intent_stats": dict(self.intent_stats),
            "session_context": self.session_context
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMemoryLane":
        """Deserialize from dictionary."""
        lane = cls(
            agent_name=data["agent_name"],
            user_id=data["user_id"]
        )
        
        for k, v in data.get("patterns", {}).items():
            lane.patterns[k] = LearnedPattern.from_dict(v)
        
        for k, v in data.get("facts", {}).items():
            lane.facts[k] = AgentFact.from_dict(v)
        
        lane.intent_stats = defaultdict(
            lambda: {"success": 0, "failure": 0},
            data.get("intent_stats", {})
        )
        lane.session_context = data.get("session_context", {})
        
        return lane


class AgentMemoryLaneManager:
    """
    Manages AgentMemoryLane instances across all agents and users.
    
    Provides:
    - Lane creation and retrieval
    - Cross-agent pattern sharing
    - Persistence management
    """
    
    def __init__(self, db: Optional[Any] = None):
        """
        Initialize the manager.
        
        Args:
            db: Optional database session for persistence
        """
        self.db = db
        
        # user_id -> agent_name -> AgentMemoryLane
        self._lanes: Dict[int, Dict[str, AgentMemoryLane]] = {}
    
    def get_or_create(
        self, 
        agent_name: str, 
        user_id: int
    ) -> AgentMemoryLane:
        """Get or create a memory lane for an agent."""
        if user_id not in self._lanes:
            self._lanes[user_id] = {}
        
        if agent_name not in self._lanes[user_id]:
            self._lanes[user_id][agent_name] = AgentMemoryLane(
                agent_name=agent_name,
                user_id=user_id,
                db=self.db
            )
            logger.debug(
                f"[AgentMemoryLaneManager] Created lane for "
                f"agent={agent_name}, user={user_id}"
            )
        
        return self._lanes[user_id][agent_name]
    
    def get(self, agent_name: str, user_id: int) -> Optional[AgentMemoryLane]:
        """Get memory lane if it exists."""
        return self._lanes.get(user_id, {}).get(agent_name)
    
    def get_all_for_user(self, user_id: int) -> Dict[str, AgentMemoryLane]:
        """Get all memory lanes for a user."""
        return self._lanes.get(user_id, {})
    
    async def share_pattern(
        self,
        pattern: LearnedPattern,
        from_agent: str,
        to_agents: List[str],
        user_id: int
    ):
        """Share a pattern from one agent to others."""
        for agent_name in to_agents:
            if agent_name == from_agent:
                continue
            
            lane = self.get_or_create(agent_name, user_id)
            await lane.learn_pattern(
                pattern_type=pattern.pattern_type,
                trigger=pattern.trigger,
                action=pattern.action,
                description=f"(Shared from {from_agent}) {pattern.description}",
                parameters=pattern.parameters,
                initial_confidence=pattern.confidence * 0.8  # Slight discount
            )
        
        logger.info(
            f"[AgentMemoryLaneManager] Shared pattern '{pattern.pattern_id}' "
            f"from {from_agent} to {to_agents}"
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics."""
        total_lanes = sum(len(lanes) for lanes in self._lanes.values())
        total_patterns = sum(
            len(lane.patterns) 
            for lanes in self._lanes.values() 
            for lane in lanes.values()
        )
        total_facts = sum(
            len(lane.facts) 
            for lanes in self._lanes.values() 
            for lane in lanes.values()
        )
        
        return {
            "total_users": len(self._lanes),
            "total_lanes": total_lanes,
            "total_patterns": total_patterns,
            "total_facts": total_facts
        }


# Global instance
_lane_manager: Optional[AgentMemoryLaneManager] = None


def get_agent_memory_lane_manager() -> Optional[AgentMemoryLaneManager]:
    """Get the global AgentMemoryLaneManager instance."""
    return _lane_manager


def init_agent_memory_lane_manager(db: Optional[Any] = None) -> AgentMemoryLaneManager:
    """Initialize the global AgentMemoryLaneManager."""
    global _lane_manager
    _lane_manager = AgentMemoryLaneManager(db=db)
    logger.info("[AgentMemoryLaneManager] Global instance initialized")
    return _lane_manager
