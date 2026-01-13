"""
Temporal Intelligence for Semantic Memory

Provides time-aware fact management:
- Track fact validity over time (valid_from, valid_until)
- Query facts at specific points in time
- Temporal decay of fact confidence
- Timeline generation
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import re

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class TemporalScope(str, Enum):
    """Time scope for facts."""
    PERMANENT = "permanent"      # Always valid
    SNAPSHOT = "snapshot"        # Valid at specific point
    RANGE = "range"              # Valid for a date range
    DECAYING = "decaying"        # Confidence decreases over time


@dataclass
class TemporalFact:
    """A fact with temporal metadata."""
    fact_id: int
    content: str
    confidence: float
    
    # Temporal bounds
    learned_at: datetime = field(default_factory=datetime.utcnow)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    
    # Decay settings
    scope: TemporalScope = TemporalScope.PERMANENT
    decay_rate: float = 0.0  # Confidence decay per day (e.g., 0.01 = 1% per day)
    
    # Refresh tracking
    last_reinforced: Optional[datetime] = None
    reinforcement_count: int = 0
    needs_refresh: bool = False
    
    def is_valid_at(self, point_in_time: datetime) -> bool:
        """Check if fact was valid at a specific time."""
        if self.scope == TemporalScope.PERMANENT:
            return True
        
        if self.valid_from and point_in_time < self.valid_from:
            return False
        
        if self.valid_until and point_in_time > self.valid_until:
            return False
        
        return True
    
    def is_currently_valid(self) -> bool:
        """Check if fact is currently valid."""
        return self.is_valid_at(datetime.utcnow())
    
    def get_decayed_confidence(self, at_time: Optional[datetime] = None) -> float:
        """Calculate confidence with temporal decay applied."""
        if self.scope != TemporalScope.DECAYING or self.decay_rate == 0:
            return self.confidence
        
        at_time = at_time or datetime.utcnow()
        reference_time = self.last_reinforced or self.learned_at
        
        days_elapsed = (at_time - reference_time).days
        if days_elapsed <= 0:
            return self.confidence
        
        # Exponential decay
        decayed = self.confidence * ((1 - self.decay_rate) ** days_elapsed)
        return max(0.1, decayed)  # Floor at 0.1
    
    def reinforce(self, boost: float = 0.1) -> float:
        """Reinforce the fact (reset decay, boost confidence)."""
        self.last_reinforced = datetime.utcnow()
        self.reinforcement_count += 1
        self.confidence = min(1.0, self.confidence + boost)
        self.needs_refresh = False
        return self.confidence
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "content": self.content,
            "confidence": self.confidence,
            "decayed_confidence": self.get_decayed_confidence(),
            "scope": self.scope.value,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "learned_at": self.learned_at.isoformat(),
            "reinforcement_count": self.reinforcement_count,
            "needs_refresh": self.needs_refresh
        }


@dataclass
class TimelineEvent:
    """An event in the user's fact timeline."""
    timestamp: datetime
    event_type: str  # learned, updated, expired, reinforced
    fact_id: int
    fact_content: str
    details: str = ""


class TemporalQueryEngine:
    """
    Enables time-based queries on facts.
    
    Examples:
    - "What did user prefer in 2022?"
    - "Facts learned in the last week"
    - "What was true before [event]?"
    """
    
    def __init__(self):
        self._temporal_facts: Dict[int, Dict[int, TemporalFact]] = {}  # user_id -> fact_id -> TemporalFact
        self._timelines: Dict[int, List[TimelineEvent]] = {}  # user_id -> events
    
    def add_fact(
        self,
        user_id: int,
        fact_id: int,
        content: str,
        confidence: float,
        scope: TemporalScope = TemporalScope.PERMANENT,
        valid_from: Optional[datetime] = None,
        valid_until: Optional[datetime] = None,
        decay_rate: float = 0.0
    ) -> TemporalFact:
        """Add a fact with temporal metadata."""
        if user_id not in self._temporal_facts:
            self._temporal_facts[user_id] = {}
            self._timelines[user_id] = []
        
        temporal_fact = TemporalFact(
            fact_id=fact_id,
            content=content,
            confidence=confidence,
            scope=scope,
            valid_from=valid_from,
            valid_until=valid_until,
            decay_rate=decay_rate
        )
        
        self._temporal_facts[user_id][fact_id] = temporal_fact
        
        # Add to timeline
        self._timelines[user_id].append(TimelineEvent(
            timestamp=temporal_fact.learned_at,
            event_type="learned",
            fact_id=fact_id,
            fact_content=content[:50] + "..." if len(content) > 50 else content
        ))
        
        return temporal_fact
    
    def query_at_time(
        self,
        user_id: int,
        point_in_time: datetime,
        min_confidence: float = 0.0
    ) -> List[TemporalFact]:
        """
        Get facts that were valid at a specific point in time.
        
        Args:
            user_id: User ID
            point_in_time: The point in time to query
            min_confidence: Minimum confidence threshold
        """
        user_facts = self._temporal_facts.get(user_id, {})
        
        valid_facts = []
        for fact in user_facts.values():
            if fact.is_valid_at(point_in_time):
                decayed_conf = fact.get_decayed_confidence(point_in_time)
                if decayed_conf >= min_confidence:
                    valid_facts.append(fact)
        
        return valid_facts
    
    def query_time_range(
        self,
        user_id: int,
        start_time: datetime,
        end_time: datetime,
        include_partial: bool = True
    ) -> List[TemporalFact]:
        """
        Get facts valid during a time range.
        
        Args:
            user_id: User ID
            start_time: Range start
            end_time: Range end
            include_partial: Include facts that overlap partially
        """
        user_facts = self._temporal_facts.get(user_id, {})
        
        matching_facts = []
        for fact in user_facts.values():
            # Check overlap with range
            fact_start = fact.valid_from or datetime.min
            fact_end = fact.valid_until or datetime.max
            
            if include_partial:
                # Any overlap
                if fact_start <= end_time and fact_end >= start_time:
                    matching_facts.append(fact)
            else:
                # Must be fully within range
                if fact_start >= start_time and fact_end <= end_time:
                    matching_facts.append(fact)
        
        return matching_facts
    
    def query_learned_since(
        self,
        user_id: int,
        since: datetime
    ) -> List[TemporalFact]:
        """Get facts learned after a specific time."""
        user_facts = self._temporal_facts.get(user_id, {})
        
        return [
            fact for fact in user_facts.values()
            if fact.learned_at >= since
        ]
    
    def query_expiring_soon(
        self,
        user_id: int,
        days: int = 7
    ) -> List[TemporalFact]:
        """Get facts that will expire soon or have low decayed confidence."""
        user_facts = self._temporal_facts.get(user_id, {})
        cutoff = datetime.utcnow() + timedelta(days=days)
        
        expiring = []
        for fact in user_facts.values():
            # Check explicit expiration
            if fact.valid_until and fact.valid_until <= cutoff:
                expiring.append(fact)
            # Check confidence decay
            elif fact.scope == TemporalScope.DECAYING:
                if fact.get_decayed_confidence() < 0.3:
                    fact.needs_refresh = True
                    expiring.append(fact)
        
        return expiring
    
    def query_needs_refresh(self, user_id: int) -> List[TemporalFact]:
        """Get facts marked as needing refresh."""
        user_facts = self._temporal_facts.get(user_id, {})
        return [f for f in user_facts.values() if f.needs_refresh]
    
    def reinforce_fact(self, user_id: int, fact_id: int, boost: float = 0.1) -> Optional[float]:
        """Reinforce a fact (reset decay, boost confidence)."""
        user_facts = self._temporal_facts.get(user_id, {})
        fact = user_facts.get(fact_id)
        
        if fact:
            new_conf = fact.reinforce(boost)
            
            # Add to timeline
            self._timelines[user_id].append(TimelineEvent(
                timestamp=datetime.utcnow(),
                event_type="reinforced",
                fact_id=fact_id,
                fact_content=fact.content[:50],
                details=f"Confidence: {new_conf:.2f}"
            ))
            
            return new_conf
        return None
    
    def get_timeline(
        self,
        user_id: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_types: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[TimelineEvent]:
        """
        Get the fact timeline for a user.
        
        Returns chronologically ordered events.
        """
        events = self._timelines.get(user_id, [])
        
        # Filter by time
        if start_time:
            events = [e for e in events if e.timestamp >= start_time]
        if end_time:
            events = [e for e in events if e.timestamp <= end_time]
        
        # Filter by type
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        
        # Sort and limit
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]
    
    def parse_temporal_query(self, query: str) -> Dict[str, Any]:
        """
        Parse natural language temporal query.
        
        Examples:
        - "in 2022" → {"year": 2022}
        - "last week" → {"range": (7 days ago, now)}
        - "before January" → {"before": January 1}
        """
        query_lower = query.lower()
        result = {"type": "current"}
        
        # Year patterns
        year_match = re.search(r'\b(20\d{2})\b', query)
        if year_match:
            year = int(year_match.group(1))
            result = {
                "type": "year",
                "year": year,
                "start": datetime(year, 1, 1),
                "end": datetime(year, 12, 31, 23, 59, 59)
            }
            return result
        
        # Relative patterns
        if "last week" in query_lower:
            result = {
                "type": "relative",
                "start": datetime.utcnow() - timedelta(days=7),
                "end": datetime.utcnow()
            }
        elif "last month" in query_lower:
            result = {
                "type": "relative",
                "start": datetime.utcnow() - timedelta(days=30),
                "end": datetime.utcnow()
            }
        elif "yesterday" in query_lower:
            yesterday = datetime.utcnow() - timedelta(days=1)
            result = {
                "type": "day",
                "start": yesterday.replace(hour=0, minute=0, second=0),
                "end": yesterday.replace(hour=23, minute=59, second=59)
            }
        elif "today" in query_lower:
            today = datetime.utcnow()
            result = {
                "type": "day",
                "start": today.replace(hour=0, minute=0, second=0),
                "end": today
            }
        elif "recently" in query_lower:
            result = {
                "type": "relative",
                "start": datetime.utcnow() - timedelta(days=3),
                "end": datetime.utcnow()
            }
        
        return result
    
    def get_stats(self, user_id: int) -> Dict[str, Any]:
        """Get temporal statistics for a user."""
        user_facts = self._temporal_facts.get(user_id, {})
        timeline = self._timelines.get(user_id, [])
        
        permanent = sum(1 for f in user_facts.values() if f.scope == TemporalScope.PERMANENT)
        decaying = sum(1 for f in user_facts.values() if f.scope == TemporalScope.DECAYING)
        expired = sum(1 for f in user_facts.values() if not f.is_currently_valid())
        needs_refresh = sum(1 for f in user_facts.values() if f.needs_refresh)
        
        return {
            "total_facts": len(user_facts),
            "permanent_facts": permanent,
            "decaying_facts": decaying,
            "expired_facts": expired,
            "needs_refresh": needs_refresh,
            "timeline_events": len(timeline)
        }


# Global instance
_temporal_engine: Optional[TemporalQueryEngine] = None


def get_temporal_engine() -> Optional[TemporalQueryEngine]:
    """Get the global TemporalQueryEngine instance."""
    return _temporal_engine


def init_temporal_engine() -> TemporalQueryEngine:
    """Initialize the global TemporalQueryEngine."""
    global _temporal_engine
    _temporal_engine = TemporalQueryEngine()
    logger.info("[TemporalQueryEngine] Global instance initialized")
    return _temporal_engine
