"""
Working Memory System

Session-scoped working memory that tracks:
- Last N turns of conversation (turn buffer)
- Current active entities mentioned
- Current topics/themes in focus
- Pending facts to be consolidated
- Current goal/intent context

This is the "short-term" memory layer that enables context continuity
within a conversation session and provides rich context to agents.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set
from collections import OrderedDict
import json
import asyncio

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class Turn:
    """A single conversation turn."""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Entity/topic extraction results
    entities: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    agent_name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "entities": self.entities,
            "topics": self.topics,
            "agent_name": self.agent_name
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Turn":
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.utcnow()
            
        return cls(
            role=data.get("role", "unknown"),
            content=data.get("content", ""),
            timestamp=timestamp,
            metadata=data.get("metadata", {}),
            entities=data.get("entities", []),
            topics=data.get("topics", []),
            agent_name=data.get("agent_name")
        )


@dataclass
class PendingFact:
    """A fact waiting to be consolidated into long-term memory."""
    content: str
    category: str
    source: str  # 'inferred', 'explicit', 'learned'
    confidence: float = 0.5
    timestamp: datetime = field(default_factory=datetime.utcnow)
    related_turn_index: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "category": self.category,
            "source": self.source,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "related_turn_index": self.related_turn_index
        }


@dataclass 
class WorkingMemory:
    """
    Session-scoped working memory.
    
    Persists:
    - Last N turns of conversation
    - Current task/goal context
    - Active entities mentioned
    - Active topics/themes
    - Pending facts (not yet committed to long-term storage)
    
    This enables agents to have full context of the recent conversation
    and understand the current focus of the user.
    """
    user_id: int
    session_id: str
    
    # Turn buffer - stores recent conversation
    turn_buffer: List[Turn] = field(default_factory=list)
    max_turns: int = 15  # Keep last 15 turns
    
    # Current focus tracking
    active_entities: List[str] = field(default_factory=list)
    active_topics: List[str] = field(default_factory=list)
    current_goal: Optional[str] = None
    current_intent: Optional[str] = None
    
    # Uncommitted facts (will be consolidated to SemanticMemory)
    pending_facts: List[PendingFact] = field(default_factory=list)
    
    # Session metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    total_turns: int = 0
    
    # Entity/topic history for salience
    entity_mentions: Dict[str, int] = field(default_factory=dict)
    topic_mentions: Dict[str, int] = field(default_factory=dict)
    
    def add_turn(
        self, 
        role: str, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None,
        entities: Optional[List[str]] = None,
        topics: Optional[List[str]] = None,
        agent_name: Optional[str] = None
    ) -> Turn:
        """
        Add a turn to the buffer, evicting old turns if necessary.
        
        Args:
            role: 'user' or 'assistant'
            content: The message content
            metadata: Optional metadata (tool calls, etc.)
            entities: Entities mentioned in this turn
            topics: Topics discussed in this turn
            agent_name: Name of the agent that handled this (for assistant turns)
            
        Returns:
            The created Turn object
        """
        turn = Turn(
            role=role,
            content=content,
            metadata=metadata or {},
            entities=entities or [],
            topics=topics or [],
            agent_name=agent_name
        )
        
        self.turn_buffer.append(turn)
        self.total_turns += 1
        self.last_activity = datetime.utcnow()
        
        # Update entity/topic tracking
        for entity in turn.entities:
            self.entity_mentions[entity] = self.entity_mentions.get(entity, 0) + 1
            if entity not in self.active_entities:
                self.active_entities.append(entity)
                
        for topic in turn.topics:
            self.topic_mentions[topic] = self.topic_mentions.get(topic, 0) + 1
            if topic not in self.active_topics:
                self.active_topics.append(topic)
        
        # Evict old turns if buffer is full
        if len(self.turn_buffer) > self.max_turns:
            evicted = self.turn_buffer[:-self.max_turns]
            self.turn_buffer = self.turn_buffer[-self.max_turns:]
            
            # Log eviction for debugging
            logger.debug(
                f"[WorkingMemory] Evicted {len(evicted)} turns for user {self.user_id}, "
                f"session {self.session_id}"
            )
            
            # Clean up entity/topic tracking for evicted turns
            self._cleanup_stale_entities()
        
        return turn
    
    def get_context_window(self, n: int = 5) -> List[Turn]:
        """
        Get the last N turns for context injection.
        
        Args:
            n: Number of recent turns to retrieve
            
        Returns:
            List of recent turns (oldest first)
        """
        return self.turn_buffer[-n:] if n > 0 else []
    
    def get_formatted_context(self, n: int = 5, max_content_length: int = 200) -> str:
        """
        Get formatted context string for LLM injection.
        
        Args:
            n: Number of recent turns to include
            max_content_length: Max characters per turn content
            
        Returns:
            Formatted string for LLM context
        """
        turns = self.get_context_window(n)
        if not turns:
            return ""
            
        lines = ["RECENT CONVERSATION:"]
        for turn in turns:
            role_label = "USER" if turn.role == "user" else "ASSISTANT"
            content = turn.content[:max_content_length]
            if len(turn.content) > max_content_length:
                content += "..."
            
            # Add agent info for assistant turns
            agent_suffix = f" ({turn.agent_name})" if turn.agent_name else ""
            lines.append(f"- {role_label}{agent_suffix}: {content}")
            
        return "\n".join(lines)
    
    def get_active_context(self) -> Dict[str, Any]:
        """
        Get the current active context (entities, topics, goal).
        
        Returns:
            Dictionary with active context information
        """
        return {
            "active_entities": self.active_entities[:10],  # Top 10
            "active_topics": self.active_topics[:5],  # Top 5
            "current_goal": self.current_goal,
            "current_intent": self.current_intent,
            "session_duration_minutes": (datetime.utcnow() - self.created_at).seconds // 60,
            "total_turns": self.total_turns
        }
    
    def set_goal(self, goal: str):
        """Set the current goal/objective for this session."""
        self.current_goal = goal
        logger.debug(f"[WorkingMemory] Set goal for user {self.user_id}: {goal[:50]}...")
        
    def set_intent(self, intent: str):
        """Set the current intent classification."""
        self.current_intent = intent
        
    def add_pending_fact(
        self, 
        content: str, 
        category: str, 
        source: str = "inferred",
        confidence: float = 0.5
    ):
        """
        Add a fact to be consolidated later.
        
        Args:
            content: The fact content
            category: Fact category (preference, contact, work, etc.)
            source: How the fact was derived
            confidence: Confidence score (0-1)
        """
        fact = PendingFact(
            content=content,
            category=category,
            source=source,
            confidence=confidence,
            related_turn_index=len(self.turn_buffer) - 1 if self.turn_buffer else None
        )
        self.pending_facts.append(fact)
        
        logger.debug(
            f"[WorkingMemory] Added pending fact for user {self.user_id}: "
            f"{content[:50]}... (confidence: {confidence})"
        )
    
    def get_pending_facts(self, min_confidence: float = 0.0) -> List[PendingFact]:
        """Get pending facts above a confidence threshold."""
        return [f for f in self.pending_facts if f.confidence >= min_confidence]
    
    def clear_pending_facts(self):
        """Clear all pending facts (after consolidation)."""
        count = len(self.pending_facts)
        self.pending_facts = []
        logger.debug(f"[WorkingMemory] Cleared {count} pending facts for user {self.user_id}")
    
    def get_entity_salience(self, entity: str) -> float:
        """
        Get salience score for an entity based on mention frequency.
        
        Returns:
            Salience score (0-1) based on relative frequency
        """
        if not self.entity_mentions:
            return 0.0
        max_mentions = max(self.entity_mentions.values())
        mentions = self.entity_mentions.get(entity, 0)
        return mentions / max_mentions if max_mentions > 0 else 0.0
    
    def _cleanup_stale_entities(self):
        """Remove entities/topics that are no longer in the buffer."""
        # Get all entities/topics still in buffer
        current_entities: Set[str] = set()
        current_topics: Set[str] = set()
        
        for turn in self.turn_buffer:
            current_entities.update(turn.entities)
            current_topics.update(turn.topics)
        
        # Update active lists
        self.active_entities = [e for e in self.active_entities if e in current_entities]
        self.active_topics = [t for t in self.active_topics if t in current_topics]
        
        # Recalculate mention counts
        self.entity_mentions = {}
        self.topic_mentions = {}
        for turn in self.turn_buffer:
            for entity in turn.entities:
                self.entity_mentions[entity] = self.entity_mentions.get(entity, 0) + 1
            for topic in turn.topics:
                self.topic_mentions[topic] = self.topic_mentions.get(topic, 0) + 1
    
    def is_stale(self, max_idle_minutes: int = 30) -> bool:
        """Check if this working memory is stale (no activity for a while)."""
        idle_time = datetime.utcnow() - self.last_activity
        return idle_time > timedelta(minutes=max_idle_minutes)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "turn_buffer": [t.to_dict() for t in self.turn_buffer],
            "active_entities": self.active_entities,
            "active_topics": self.active_topics,
            "current_goal": self.current_goal,
            "current_intent": self.current_intent,
            "pending_facts": [f.to_dict() for f in self.pending_facts],
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "total_turns": self.total_turns,
            "entity_mentions": self.entity_mentions,
            "topic_mentions": self.topic_mentions
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkingMemory":
        """Create from dictionary (for loading from persistence)."""
        wm = cls(
            user_id=data["user_id"],
            session_id=data["session_id"]
        )
        
        wm.turn_buffer = [Turn.from_dict(t) for t in data.get("turn_buffer", [])]
        wm.active_entities = data.get("active_entities", [])
        wm.active_topics = data.get("active_topics", [])
        wm.current_goal = data.get("current_goal")
        wm.current_intent = data.get("current_intent")
        wm.pending_facts = [
            PendingFact(**f) for f in data.get("pending_facts", [])
        ]
        wm.total_turns = data.get("total_turns", len(wm.turn_buffer))
        wm.entity_mentions = data.get("entity_mentions", {})
        wm.topic_mentions = data.get("topic_mentions", {})
        
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            wm.created_at = datetime.fromisoformat(created_at)
            
        last_activity = data.get("last_activity")
        if isinstance(last_activity, str):
            wm.last_activity = datetime.fromisoformat(last_activity)
            
        return wm


class WorkingMemoryManager:
    """
    Manages working memory instances across users and sessions.
    
    Provides:
    - In-memory cache for active sessions
    - Optional persistence to database
    - Automatic cleanup of stale sessions
    """
    
    def __init__(
        self, 
        max_sessions_per_user: int = 3,
        max_idle_minutes: int = 30,
        persistence_enabled: bool = True
    ):
        # Cache: user_id -> {session_id -> WorkingMemory}
        self._cache: Dict[int, Dict[str, WorkingMemory]] = {}
        self.max_sessions_per_user = max_sessions_per_user
        self.max_idle_minutes = max_idle_minutes
        self.persistence_enabled = persistence_enabled
        
        # Database session (set externally)
        self._db = None
        
    def set_db(self, db):
        """Set the database session for persistence."""
        self._db = db
        
    async def get_or_create(
        self, user_id: int, session_id: str
    ) -> WorkingMemory:
        """
        Get existing working memory or create a new one.
        Attempts to load from DB on cache miss.
        
        Args:
            user_id: User ID
            session_id: Session ID (e.g., from Gemini Interactions API)
            
        Returns:
            WorkingMemory instance
        """
        # Initialize user cache if needed
        if user_id not in self._cache:
            self._cache[user_id] = {}
            
        # Check cache first
        if session_id in self._cache[user_id]:
            return self._cache[user_id][session_id]
        
        # Try loading from database
        if self.persistence_enabled:
            wm = await self._load_from_db(user_id, session_id)
            if wm:
                self._cache[user_id][session_id] = wm
                logger.info(
                    f"[WorkingMemoryManager] Restored working memory from DB for "
                    f"user {user_id}, session {session_id[:20]}... ({wm.total_turns} turns)"
                )
                return wm
            
        # Create new working memory
        wm = WorkingMemory(user_id=user_id, session_id=session_id)
        self._cache[user_id][session_id] = wm
        
        # Cleanup stale sessions for this user
        await self._cleanup_stale_sessions(user_id)
        
        logger.info(
            f"[WorkingMemoryManager] Created new working memory for "
            f"user {user_id}, session {session_id[:20]}..."
        )
        
        return wm
    
    def get(self, user_id: int, session_id: str) -> Optional[WorkingMemory]:
        """Get working memory if it exists."""
        return self._cache.get(user_id, {}).get(session_id)
    
    async def _cleanup_stale_sessions(self, user_id: int):
        """Remove stale sessions for a user, persisting before eviction."""
        if user_id not in self._cache:
            return
            
        sessions = self._cache[user_id]
        stale_sessions = [
            sid for sid, wm in sessions.items() 
            if wm.is_stale(self.max_idle_minutes)
        ]
        
        for sid in stale_sessions:
            # Persist before evicting so pending facts survive
            if self.persistence_enabled:
                await self.persist_to_db(sessions[sid])
            del sessions[sid]
            logger.debug(f"[WorkingMemoryManager] Cleaned up stale session {sid[:20]}...")
            
        # Also enforce max sessions per user (keep most recent)
        if len(sessions) > self.max_sessions_per_user:
            # Sort by last_activity, keep most recent
            sorted_sessions = sorted(
                sessions.items(),
                key=lambda x: x[1].last_activity,
                reverse=True
            )
            for sid, wm in sorted_sessions[self.max_sessions_per_user:]:
                if self.persistence_enabled:
                    await self.persist_to_db(wm)
                del sessions[sid]
                logger.debug(
                    f"[WorkingMemoryManager] Evicted old session {sid[:20]}... "
                    f"(max sessions: {self.max_sessions_per_user})"
                )
    
    def get_all_for_user(self, user_id: int) -> Dict[str, WorkingMemory]:
        """Get all working memories for a user."""
        return self._cache.get(user_id, {}).copy()
    
    def clear_user(self, user_id: int):
        """Clear all working memories for a user."""
        if user_id in self._cache:
            del self._cache[user_id]
            logger.info(f"[WorkingMemoryManager] Cleared all sessions for user {user_id}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about working memory usage."""
        total_users = len(self._cache)
        total_sessions = sum(len(sessions) for sessions in self._cache.values())
        total_turns = sum(
            wm.total_turns 
            for sessions in self._cache.values() 
            for wm in sessions.values()
        )
        
        return {
            "total_users": total_users,
            "total_sessions": total_sessions,
            "total_turns": total_turns,
            "average_turns_per_session": total_turns / total_sessions if total_sessions > 0 else 0
        }
    
    async def persist_to_db(self, wm: WorkingMemory):
        """
        Persist a WorkingMemory snapshot to the database.
        Uses upsert logic (update if exists, insert if not).
        """
        try:
            from src.database import get_async_db_context
            from src.database.models import WorkingMemorySnapshot
            from sqlalchemy import select
            
            async with get_async_db_context() as db:
                result = await db.execute(
                    select(WorkingMemorySnapshot).where(
                        WorkingMemorySnapshot.user_id == wm.user_id,
                        WorkingMemorySnapshot.session_id == wm.session_id
                    )
                )
                snapshot = result.scalar_one_or_none()
                
                snapshot_data = wm.to_dict()
                
                if snapshot:
                    snapshot.snapshot_data = snapshot_data
                    snapshot.turn_count = wm.total_turns
                    snapshot.active_entities = wm.active_entities[:20]
                    snapshot.active_topics = wm.active_topics[:10]
                    snapshot.current_goal = wm.current_goal
                else:
                    snapshot = WorkingMemorySnapshot(
                        user_id=wm.user_id,
                        session_id=wm.session_id,
                        snapshot_data=snapshot_data,
                        turn_count=wm.total_turns,
                        active_entities=wm.active_entities[:20],
                        active_topics=wm.active_topics[:10],
                        current_goal=wm.current_goal,
                    )
                    db.add(snapshot)
                
                await db.commit()
                logger.debug(
                    f"[WorkingMemoryManager] Persisted snapshot for user {wm.user_id}, "
                    f"session {wm.session_id[:20]}... ({wm.total_turns} turns)"
                )
                
        except Exception as e:
            logger.debug(f"[WorkingMemoryManager] Could not persist snapshot: {e}")
    
    async def _load_from_db(self, user_id: int, session_id: str) -> Optional[WorkingMemory]:
        """
        Load a WorkingMemory from the database snapshot.
        Returns None if no snapshot exists or it's stale.
        """
        try:
            from src.database import get_async_db_context
            from src.database.models import WorkingMemorySnapshot
            from sqlalchemy import select
            
            async with get_async_db_context() as db:
                result = await db.execute(
                    select(WorkingMemorySnapshot).where(
                        WorkingMemorySnapshot.user_id == user_id,
                        WorkingMemorySnapshot.session_id == session_id
                    )
                )
                snapshot = result.scalar_one_or_none()
                
                if not snapshot or not snapshot.snapshot_data:
                    return None
                
                # Check if snapshot is too old (stale)
                if snapshot.updated_at:
                    idle_time = datetime.utcnow() - snapshot.updated_at
                    if idle_time > timedelta(minutes=self.max_idle_minutes * 2):
                        return None
                
                # Reconstruct WorkingMemory from snapshot
                wm = WorkingMemory.from_dict(snapshot.snapshot_data)
                return wm
                
        except Exception as e:
            logger.debug(f"[WorkingMemoryManager] Could not load snapshot: {e}")
            return None


# Global instance (can be replaced with dependency injection)
_working_memory_manager: Optional[WorkingMemoryManager] = None


def get_working_memory_manager() -> WorkingMemoryManager:
    """Get the global WorkingMemoryManager instance."""
    global _working_memory_manager
    if _working_memory_manager is None:
        _working_memory_manager = WorkingMemoryManager()
    return _working_memory_manager


def init_working_memory_manager(
    max_sessions_per_user: int = 3,
    max_idle_minutes: int = 30
) -> WorkingMemoryManager:
    """Initialize the global WorkingMemoryManager with custom settings."""
    global _working_memory_manager
    _working_memory_manager = WorkingMemoryManager(
        max_sessions_per_user=max_sessions_per_user,
        max_idle_minutes=max_idle_minutes
    )
    return _working_memory_manager
