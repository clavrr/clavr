"""
Goal Tracker

Tracks user goals and intents across sessions for long-running context.

Goals are:
- Explicit: "I need to prepare my Q4 presentation by Dec 20"
- Inferred: Detected from patterns ("You've been working on X a lot")
- Updated: Progress tracked based on related actions

Goals enable:
- Long-term context for agents
- Proactive suggestions ("You mentioned needing to finish X")
- Priority-aware scheduling
- Cross-session continuity
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from enum import Enum
import json
import re

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class GoalStatus(str, Enum):
    """Goal lifecycle status."""
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    PAUSED = "paused"
    ARCHIVED = "archived"


class GoalPriority(str, Enum):
    """Goal priority levels."""
    CRITICAL = "critical"  # Must be done, blocking
    HIGH = "high"  # Important, time-sensitive
    MEDIUM = "medium"  # Should be done, flexible timing
    LOW = "low"  # Nice to have


@dataclass
class Goal:
    """A tracked user goal."""
    id: str
    user_id: int
    description: str
    status: GoalStatus = GoalStatus.ACTIVE
    priority: GoalPriority = GoalPriority.MEDIUM
    
    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    due_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_mentioned: Optional[datetime] = None
    
    # Context
    source: str = "inferred"  # 'explicit', 'inferred', 'system'
    related_entities: List[str] = field(default_factory=list)
    related_topics: List[str] = field(default_factory=list)
    
    # Progress tracking
    progress_notes: List[str] = field(default_factory=list)
    progress_percentage: float = 0.0
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "last_mentioned": self.last_mentioned.isoformat() if self.last_mentioned else None,
            "source": self.source,
            "related_entities": self.related_entities,
            "related_topics": self.related_topics,
            "progress_notes": self.progress_notes,
            "progress_percentage": self.progress_percentage,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        """Create from dictionary."""
        goal = cls(
            id=data["id"],
            user_id=data["user_id"],
            description=data["description"]
        )
        
        if "status" in data:
            goal.status = GoalStatus(data["status"])
        if "priority" in data:
            goal.priority = GoalPriority(data["priority"])
        if "created_at" in data and data["created_at"]:
            goal.created_at = datetime.fromisoformat(data["created_at"])
        if "due_date" in data and data["due_date"]:
            goal.due_date = datetime.fromisoformat(data["due_date"])
        if "completed_at" in data and data["completed_at"]:
            goal.completed_at = datetime.fromisoformat(data["completed_at"])
        if "last_mentioned" in data and data["last_mentioned"]:
            goal.last_mentioned = datetime.fromisoformat(data["last_mentioned"])
            
        goal.source = data.get("source", "inferred")
        goal.related_entities = data.get("related_entities", [])
        goal.related_topics = data.get("related_topics", [])
        goal.progress_notes = data.get("progress_notes", [])
        goal.progress_percentage = data.get("progress_percentage", 0.0)
        goal.metadata = data.get("metadata", {})
        
        return goal
    
    def is_overdue(self) -> bool:
        """Check if goal is past due date."""
        if self.due_date and self.status == GoalStatus.ACTIVE:
            return datetime.utcnow() > self.due_date
        return False
    
    def days_until_due(self) -> Optional[int]:
        """Get days until due date (negative if overdue)."""
        if self.due_date:
            delta = self.due_date - datetime.utcnow()
            return delta.days
        return None
    
    def format_for_context(self) -> str:
        """Format goal for LLM context injection."""
        parts = [f"Goal: {self.description}"]
        
        if self.due_date:
            days = self.days_until_due()
            if days is not None:
                if days < 0:
                    parts.append(f"⚠️ OVERDUE by {abs(days)} days")
                elif days == 0:
                    parts.append("⚠️ DUE TODAY")
                elif days <= 3:
                    parts.append(f"Due in {days} days")
        
        if self.progress_percentage > 0:
            parts.append(f"Progress: {int(self.progress_percentage)}%")
        
        if self.priority in [GoalPriority.CRITICAL, GoalPriority.HIGH]:
            parts.append(f"Priority: {self.priority.value.upper()}")
        
        return " | ".join(parts)


@dataclass
class DetectedGoal:
    """Result of goal detection from a message."""
    description: str
    confidence: float
    priority: GoalPriority
    due_date: Optional[datetime] = None
    entities: List[str] = field(default_factory=list)
    
    def to_goal(self, user_id: int, goal_id: str) -> Goal:
        """Convert to a full Goal object."""
        return Goal(
            id=goal_id,
            user_id=user_id,
            description=self.description,
            priority=self.priority,
            due_date=self.due_date,
            related_entities=self.entities,
            source="inferred"
        )


class GoalTracker:
    """
    Tracks user goals and intents across sessions.
    
    Provides:
    - Goal detection from natural language
    - Active goal retrieval for context injection
    - Progress tracking based on related actions
    - Goal persistence (in-memory with optional DB)
    """
    
    # Patterns for goal detection
    GOAL_PATTERNS = [
        # Explicit goal statements
        (r"(?:i\s+)?need\s+to\s+(.+?)(?:\s+by\s+(.+))?$", GoalPriority.HIGH),
        (r"(?:i\s+)?have\s+to\s+(.+?)(?:\s+by\s+(.+))?$", GoalPriority.HIGH),
        (r"(?:i\s+)?must\s+(.+?)(?:\s+by\s+(.+))?$", GoalPriority.CRITICAL),
        (r"(?:i'm\s+)?trying\s+to\s+(.+)$", GoalPriority.MEDIUM),
        (r"(?:i'm\s+)?working\s+on\s+(.+)$", GoalPriority.MEDIUM),
        (r"(?:i'm\s+)?preparing\s+(?:for\s+)?(.+)$", GoalPriority.MEDIUM),
        (r"my\s+goal\s+is\s+to\s+(.+)$", GoalPriority.HIGH),
        (r"(?:i\s+)?want\s+to\s+(.+?)(?:\s+by\s+(.+))?$", GoalPriority.MEDIUM),
        # Deadline mentions
        (r"deadline\s+(?:for\s+)?(.+?)\s+is\s+(.+)$", GoalPriority.HIGH),
    ]
    
    # Completion patterns
    COMPLETION_PATTERNS = [
        r"(?:i\s+)?(?:just\s+)?finished\s+(.+)",
        r"(?:i\s+)?(?:just\s+)?completed\s+(.+)",
        r"(?:i\s+)?(?:just\s+)?done\s+with\s+(.+)",
        r"(?:i\s+)?submitted\s+(.+)",
        r"(.+)\s+is\s+(?:now\s+)?(?:done|complete|finished)",
    ]
    
    def __init__(self, db: Optional[Any] = None, llm: Optional[Any] = None):
        """
        Initialize the goal tracker.
        
        Args:
            db: Optional database session for persistence
            llm: Optional LLM for advanced goal detection
        """
        self.db = db
        self.llm = llm
        
        # In-memory cache: user_id -> {goal_id -> Goal}
        self._goals: Dict[int, Dict[str, Goal]] = {}
        
        # Goal ID counter
        self._next_id = 1
    
    def _generate_goal_id(self) -> str:
        """Generate a unique goal ID."""
        goal_id = f"goal_{self._next_id}"
        self._next_id += 1
        return goal_id
    
    async def detect_goal(
        self, 
        user_id: int, 
        message: str,
        entities: Optional[List[str]] = None
    ) -> Optional[DetectedGoal]:
        """
        Detect if a message contains a goal statement.
        
        Args:
            user_id: User ID
            message: The message to analyze
            entities: Optional pre-extracted entities
            
        Returns:
            DetectedGoal if detected, None otherwise
        """
        message_lower = message.lower().strip()
        
        # Try pattern matching first (fast path)
        for pattern, priority in self.GOAL_PATTERNS:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                description = match.group(1).strip()
                
                # Check for due date
                due_date = None
                if len(match.groups()) > 1 and match.group(2):
                    due_date = self._parse_due_date(match.group(2))
                
                # Skip if too short or generic
                if len(description) < 5:
                    continue
                
                return DetectedGoal(
                    description=description,
                    confidence=0.8,
                    priority=priority,
                    due_date=due_date,
                    entities=entities or []
                )
        
        # Use LLM for advanced detection if available
        if self.llm:
            try:
                return await self._llm_detect_goal(message, entities)
            except Exception as e:
                logger.debug(f"[GoalTracker] LLM goal detection failed: {e}")
        
        return None

    async def _llm_detect_goal(
        self, 
        message: str, 
        entities: Optional[List[str]] = None
    ) -> Optional[DetectedGoal]:
        """
        Use LLM for advanced goal detection from natural language.
        """
        if not self.llm:
            return None
            
        prompt = f"""Analyze this user message and determine if it expresses a goal, project, or long-term objective.
        
User Message: "{message}"
Pre-extracted Entities: {entities or "None"}

If it IS a goal, respond in this format:
GOAL: [Concise description of the goal]
PRIORITY: [critical/high/medium/low]
DUE_DATE: [ISO date if mentioned, else "None"]
CONFIDENCE: [Score from 0.0 to 1.0]

If it is NOT a goal, respond with: NOT_A_GOAL"""

        try:
            # Handle different possible LLM client interfaces
            if hasattr(self.llm, 'agenerate'):
                response = await self.llm.agenerate([prompt])
                text = response.generations[0][0].text.strip()
            elif hasattr(self.llm, 'predict'):
                text = await self.llm.predict(prompt)
            else:
                # Fallback to standard call if it's a simple wrapper
                text = str(await self.llm(prompt)).strip()
            
            if "NOT_A_GOAL" in text:
                return None
            
            # Parse response
            description = ""
            priority = GoalPriority.MEDIUM
            due_date = None
            confidence = 0.7
            
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith("GOAL:"):
                    description = line.replace("GOAL:", "").strip()
                elif line.startswith("PRIORITY:"):
                    p_val = line.replace("PRIORITY:", "").strip().lower()
                    try:
                        priority = GoalPriority(p_val)
                    except ValueError:
                        pass
                elif line.startswith("DUE_DATE:"):
                    d_val = line.replace("DUE_DATE:", "").strip()
                    if d_val != "None":
                        due_date = self._parse_due_date(d_val)
                elif line.startswith("CONFIDENCE:"):
                    try:
                        confidence = float(line.replace("CONFIDENCE:", "").strip())
                    except ValueError:
                        pass
            
            if description and confidence > 0.6:
                return DetectedGoal(
                    description=description,
                    confidence=confidence,
                    priority=priority,
                    due_date=due_date,
                    entities=entities or []
                )
        except Exception as e:
            logger.debug(f"[GoalTracker] LLM inference failed: {e}")
            
        return None
    
    def _parse_due_date(self, date_str: str) -> Optional[datetime]:
        """Parse a due date string into datetime."""
        date_str = date_str.lower().strip()
        now = datetime.utcnow()
        
        # Relative dates
        relative_patterns = {
            "today": timedelta(days=0),
            "tomorrow": timedelta(days=1),
            "next week": timedelta(weeks=1),
            "next month": timedelta(days=30),
            "end of week": timedelta(days=(4 - now.weekday()) % 7),
            "end of month": None,  # Special handling
        }
        
        for pattern, delta in relative_patterns.items():
            if pattern in date_str:
                if pattern == "end of month":
                    # Last day of current month
                    if now.month == 12:
                        return datetime(now.year + 1, 1, 1) - timedelta(days=1)
                    else:
                        return datetime(now.year, now.month + 1, 1) - timedelta(days=1)
                elif delta is not None:
                    return now + delta
        
        # Try "in X days/weeks"
        in_match = re.search(r"in\s+(\d+)\s+(day|week|month)s?", date_str)
        if in_match:
            amount = int(in_match.group(1))
            unit = in_match.group(2)
            if unit == "day":
                return now + timedelta(days=amount)
            elif unit == "week":
                return now + timedelta(weeks=amount)
            elif unit == "month":
                return now + timedelta(days=amount * 30)
        
        # Try specific date formats (simplified)
        # Matches: "Dec 20", "December 20", "12/20", "12-20"
        month_names = {
            'jan': 1, 'january': 1, 'feb': 2, 'february': 2,
            'mar': 3, 'march': 3, 'apr': 4, 'april': 4,
            'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
            'aug': 8, 'august': 8, 'sep': 9, 'september': 9,
            'oct': 10, 'october': 10, 'nov': 11, 'november': 11,
            'dec': 12, 'december': 12
        }
        
        for name, month in month_names.items():
            if name in date_str:
                day_match = re.search(rf"{name}\w*\s+(\d{{1,2}})", date_str)
                if day_match:
                    day = int(day_match.group(1))
                    year = now.year
                    # If date is in the past this year, assume next year
                    target = datetime(year, month, min(day, 28))
                    if target < now:
                        target = datetime(year + 1, month, min(day, 28))
                    return target
        
        return None
    
    async def add_goal(
        self, 
        user_id: int, 
        description: str,
        priority: GoalPriority = GoalPriority.MEDIUM,
        due_date: Optional[datetime] = None,
        entities: Optional[List[str]] = None,
        source: str = "explicit"
    ) -> Goal:
        """
        Add a new goal for a user.
        
        Args:
            user_id: User ID
            description: Goal description
            priority: Goal priority
            due_date: Optional due date
            entities: Related entities
            source: How the goal was created
            
        Returns:
            The created Goal object
        """
        goal_id = self._generate_goal_id()
        
        goal = Goal(
            id=goal_id,
            user_id=user_id,
            description=description,
            priority=priority,
            due_date=due_date,
            related_entities=entities or [],
            source=source
        )
        
        # Initialize user's goal dict if needed
        if user_id not in self._goals:
            self._goals[user_id] = {}
        
        self._goals[user_id][goal_id] = goal
        
        logger.info(
            f"[GoalTracker] Added goal for user {user_id}: "
            f"'{description[:30]}...' (priority: {priority.value})"
        )
        
        return goal
    
    async def get_active_goals(
        self, 
        user_id: int,
        include_overdue: bool = True
    ) -> List[Goal]:
        """
        Get all active goals for a user.
        
        Args:
            user_id: User ID
            include_overdue: Include overdue goals
            
        Returns:
            List of active goals, sorted by priority and due date
        """
        if user_id not in self._goals:
            return []
        
        active = [
            g for g in self._goals[user_id].values()
            if g.status == GoalStatus.ACTIVE
        ]
        
        if not include_overdue:
            active = [g for g in active if not g.is_overdue()]
        
        # Sort: Critical > High > Medium > Low, then by due date
        priority_order = {
            GoalPriority.CRITICAL: 0,
            GoalPriority.HIGH: 1,
            GoalPriority.MEDIUM: 2,
            GoalPriority.LOW: 3
        }
        
        def sort_key(g: Goal):
            due_sort = g.due_date.timestamp() if g.due_date else float('inf')
            return (priority_order[g.priority], due_sort)
        
        return sorted(active, key=sort_key)
    
    async def get_goals_for_context(
        self, 
        user_id: int,
        limit: int = 5
    ) -> List[str]:
        """
        Get formatted goal strings for LLM context injection.
        
        Returns:
            List of formatted goal strings
        """
        goals = await self.get_active_goals(user_id)
        return [g.format_for_context() for g in goals[:limit]]
    
    async def update_goal_progress(
        self, 
        goal_id: str, 
        user_id: int,
        progress_note: Optional[str] = None,
        progress_percentage: Optional[float] = None
    ) -> Optional[Goal]:
        """Update goal progress."""
        if user_id not in self._goals or goal_id not in self._goals[user_id]:
            return None
        
        goal = self._goals[user_id][goal_id]
        goal.last_mentioned = datetime.utcnow()
        
        if progress_note:
            goal.progress_notes.append(f"{datetime.utcnow().isoformat()}: {progress_note}")
        
        if progress_percentage is not None:
            goal.progress_percentage = min(100.0, max(0.0, progress_percentage))
        
        return goal
    
    async def complete_goal(self, goal_id: str, user_id: int) -> Optional[Goal]:
        """Mark a goal as completed."""
        if user_id not in self._goals or goal_id not in self._goals[user_id]:
            return None
        
        goal = self._goals[user_id][goal_id]
        goal.status = GoalStatus.COMPLETED
        goal.completed_at = datetime.utcnow()
        goal.progress_percentage = 100.0
        
        logger.info(f"[GoalTracker] Goal completed for user {user_id}: {goal.description[:30]}...")
        
        return goal
    
    async def archive_goal(self, goal_id: str, user_id: int) -> Optional[Goal]:
        """Move a goal to archive status."""
        if user_id not in self._goals or goal_id not in self._goals[user_id]:
            return None
            
        goal = self._goals[user_id][goal_id]
        goal.status = GoalStatus.ARCHIVED
        goal.updated_at = datetime.utcnow()
        
        logger.info(f"[GoalTracker] Goal archived for user {user_id}: {goal.description[:30]}...")
        
        return goal
    
    async def detect_completion(
        self, 
        user_id: int, 
        message: str
    ) -> Optional[Goal]:
        """
        Detect if a message indicates goal completion.
        
        Returns:
            Completed Goal if detected, None otherwise
        """
        message_lower = message.lower()
        
        for pattern in self.COMPLETION_PATTERNS:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                completed_item = match.group(1).strip()
                
                # Find matching goal
                if user_id in self._goals:
                    for goal in self._goals[user_id].values():
                        if goal.status == GoalStatus.ACTIVE:
                            # Check if completed item matches goal
                            goal_lower = goal.description.lower()
                            if (completed_item in goal_lower or 
                                goal_lower in completed_item or
                                self._fuzzy_match(completed_item, goal_lower)):
                                return await self.complete_goal(goal.id, user_id)
        
        return None
    
    def _fuzzy_match(self, text1: str, text2: str, threshold: float = 0.6) -> bool:
        """Simple fuzzy matching based on word overlap."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return False
        
        overlap = len(words1 & words2)
        min_len = min(len(words1), len(words2))
        
        return overlap / min_len >= threshold if min_len > 0 else False
    
    async def get_goal_by_entity(
        self, 
        user_id: int, 
        entity: str
    ) -> List[Goal]:
        """Find goals related to an entity."""
        if user_id not in self._goals:
            return []
        
        entity_lower = entity.lower()
        matching = []
        
        for goal in self._goals[user_id].values():
            if goal.status != GoalStatus.ACTIVE:
                continue
            
            # Check related entities
            if any(entity_lower in e.lower() for e in goal.related_entities):
                matching.append(goal)
                continue
            
            # Check if entity mentioned in description
            if entity_lower in goal.description.lower():
                matching.append(goal)
        
        return matching
    
    def get_overdue_goals(self, user_id: int) -> List[Goal]:
        """Get all overdue goals for a user."""
        if user_id not in self._goals:
            return []
        
        return [
            g for g in self._goals[user_id].values()
            if g.is_overdue()
        ]
    
    def get_stats(self, user_id: int) -> Dict[str, Any]:
        """Get goal statistics for a user."""
        if user_id not in self._goals:
            return {"total": 0, "active": 0, "completed": 0, "overdue": 0}
        
        goals = list(self._goals[user_id].values())
        
        return {
            "total": len(goals),
            "active": sum(1 for g in goals if g.status == GoalStatus.ACTIVE),
            "completed": sum(1 for g in goals if g.status == GoalStatus.COMPLETED),
            "overdue": sum(1 for g in goals if g.is_overdue())
        }


# Global instance
_goal_tracker: Optional[GoalTracker] = None


def get_goal_tracker() -> Optional[GoalTracker]:
    """Get the global GoalTracker instance."""
    return _goal_tracker


def init_goal_tracker(
    db: Optional[Any] = None,
    llm: Optional[Any] = None
) -> GoalTracker:
    """Initialize the global GoalTracker."""
    global _goal_tracker
    _goal_tracker = GoalTracker(db=db, llm=llm)
    return _goal_tracker
