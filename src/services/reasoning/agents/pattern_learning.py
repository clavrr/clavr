"""
Pattern Learning Agent

Analyzes the knowledge graph to find recurring patterns in user behavior.

Pattern Types Detected:
1. Sequence Patterns: "User checks Email before creating Tasks"
2. Time-of-Day Patterns: "User has meetings at 9 AM daily"
3. Day-of-Week Patterns: "User meets with Bob every Tuesday"
4. Periodic Patterns: "User reviews reports every month-end"
5. Co-occurrence Patterns: "User mentions Project X with Contact Y"
6. Duration Patterns: "User's standup meetings average 25 minutes"

Outputs: GraphPattern nodes
"""
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.reasoning.interfaces import ReasoningAgent, ReasoningResult

logger = setup_logger(__name__)


class PatternType(str, Enum):
    """Types of behavioral patterns."""
    SEQUENCE = "sequence"
    TIME_OF_DAY = "time_of_day"
    DAY_OF_WEEK = "day_of_week"
    PERIODIC = "periodic"
    COOCCURRENCE = "cooccurrence"
    DURATION = "duration"


@dataclass
class DetectedPattern:
    """A detected behavioral pattern."""
    pattern_type: PatternType
    description: str
    confidence: float
    frequency: int
    details: Dict[str, Any]
    

class PatternLearningAgent(ReasoningAgent):
    """
    Agent that detects temporal and behavioral patterns in user activity.
    
    This is a sophisticated pattern detector that identifies:
    - When users do things (time patterns)
    - What users do together (co-occurrence)
    - How long things take (duration patterns)
    - Recurring sequences (action chains)
    """
    
    # Minimum occurrences to consider a pattern valid
    MIN_PATTERN_FREQUENCY = 3
    
    # Confidence thresholds
    HIGH_CONFIDENCE = 0.8
    MEDIUM_CONFIDENCE = 0.6
    LOW_CONFIDENCE = 0.4
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self._name = "PatternLearningAgent"
        
    @property
    def name(self) -> str:
        return self._name
        
    async def analyze(self, user_id: int, context: Optional[Dict[str, Any]] = None) -> List[ReasoningResult]:
        """
        Run comprehensive pattern analysis across all pattern types.
        """
        results = []
        
        # Run all pattern detectors concurrently
        pattern_tasks = [
            self._detect_sequence_patterns(user_id),
            self._detect_time_of_day_patterns(user_id),
            self._detect_day_of_week_patterns(user_id),
            self._detect_periodic_patterns(user_id),
            self._detect_cooccurrence_patterns(user_id),
            self._detect_duration_patterns(user_id),
        ]
        
        try:
            all_patterns = await asyncio.gather(*pattern_tasks, return_exceptions=True)
            
            for i, patterns in enumerate(all_patterns):
                if isinstance(patterns, Exception):
                    logger.error(f"[{self.name}] Pattern detector {i} failed: {patterns}")
                elif patterns:
                    results.extend(patterns)
                    
        except Exception as e:
            logger.error(f"[{self.name}] Analysis failed: {e}")
            
        logger.info(f"[{self.name}] Detected {len(results)} patterns for user {user_id}")
        return results
        
    async def verify(self, hypothesis_id: str) -> bool:
        """Verify if a pattern still holds."""
        # Check if pattern has been observed recently
        return True
        
    # =========================================================================
    # Pattern Detection Methods
    # =========================================================================
    
    async def _detect_sequence_patterns(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect action sequences: "A frequently precedes B"
        """
        results = []
        
        # Native AQL to find sequence patterns using PRECEDED edge
        # We iterate potential start nodes (Email, Message, ActionItem) and follow PRECEDED
        query = """
        FOR a IN UNION(
            (FOR x IN Email FILTER x.user_id == @user_id RETURN x),
            (FOR x IN Message FILTER x.user_id == @user_id RETURN x),
            (FOR x IN ActionItem FILTER x.user_id == @user_id RETURN x)
        )
            FOR b IN 1..1 OUTBOUND a PRECEDED
                COLLECT type_a = a.node_type, type_b = b.node_type WITH COUNT INTO freq
                SORT freq DESC
                LIMIT 10
                RETURN { type_a: type_a, type_b: type_b, freq: freq }
        """
        
        try:
            pattern_stats = await self.graph.execute_query(query, {"user_id": user_id})
            
            for row in pattern_stats or []:
                type_a = row["type_a"]
                type_b = row["type_b"]
                freq = row["freq"]
                
                if freq < self.MIN_PATTERN_FREQUENCY:
                    continue
                    
                # Calculate confidence based on frequency
                confidence = min(0.9, 0.3 + (freq * 0.05))
                
                content = {
                    "description": f"Frequently transitions from {type_a} to {type_b}",
                    "pattern_type": PatternType.SEQUENCE.value,
                    "trigger": type_a,
                    "action": type_b,
                    "frequency": freq,
                    "count": freq
                }
                
                results.append(ReasoningResult(
                    type="pattern",
                    confidence=confidence,
                    content=content,
                    source_agent=self.name
                ))
                
        except Exception as e:
            logger.error(f"[{self.name}] Sequence pattern detection failed: {e}")
            
        return results
        
    async def _detect_time_of_day_patterns(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect time-of-day patterns: "User does X at Y o'clock"
        """
        results = []
        
        # Query events with timestamps and bucket by hour
        # Unioning relevant types
        query = """
        FOR n IN UNION(
            (FOR x IN Email FILTER x.user_id == @user_id RETURN x),
            (FOR x IN Message FILTER x.user_id == @user_id RETURN x),
            (FOR x IN CalendarEvent FILTER x.user_id == @user_id RETURN x),
            (FOR x IN ActionItem FILTER x.user_id == @user_id RETURN x)
        )
            FILTER n.created_at != null
            LIMIT 500
            RETURN { type: n.node_type, timestamp: n.created_at }
        """
        
        try:
            events = await self.graph.execute_query(query, {"user_id": user_id})
            
            if not events:
                return results
                
            # Bucket events by hour and type
            hour_buckets: Dict[Tuple[str, int], int] = defaultdict(int)
            
            for event in events:
                event_type = event["type"]
                timestamp_str = event.get("timestamp")
                
                if not timestamp_str:
                    continue
                    
                try:
                    # Parse ISO timestamp
                    if isinstance(timestamp_str, str):
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    else:
                        timestamp = timestamp_str
                        
                    hour = timestamp.hour
                    hour_buckets[(event_type, hour)] += 1
                except (ValueError, AttributeError):
                    continue
                    
            # Find significant patterns (events concentrated at specific hours)
            for (event_type, hour), count in hour_buckets.items():
                if count < self.MIN_PATTERN_FREQUENCY:
                    continue
                    
                # Calculate what percentage of this event type happens at this hour
                total_of_type = sum(c for (t, _), c in hour_buckets.items() if t == event_type)
                concentration = count / total_of_type if total_of_type > 0 else 0
                
                # If more than 25% happens at this hour, it's a pattern
                if concentration >= 0.25:
                    confidence = min(0.9, 0.4 + concentration)
                    
                    # Format hour nicely
                    hour_str = f"{hour}:00" if hour < 12 else f"{hour}:00"
                    period = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
                    
                    content = {
                        "description": f"User typically has {event_type} activity at {hour_str} ({period})",
                        "pattern_type": PatternType.TIME_OF_DAY.value,
                        "event_type": event_type,
                        "hour": hour,
                        "period": period,
                        "frequency": count,
                        "concentration": round(concentration, 2)
                    }
                    
                    results.append(ReasoningResult(
                        type="pattern",
                        confidence=confidence,
                        content=content,
                        source_agent=self.name
                    ))
                    
        except Exception as e:
            logger.error(f"[{self.name}] Time-of-day pattern detection failed: {e}")
            
        return results
        
    async def _detect_day_of_week_patterns(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect day-of-week patterns: "User does X every Tuesday"
        """
        results = []
        
        # Query events and bucket by day of week
        query = """
        FOR n IN UNION(
            (FOR x IN CalendarEvent FILTER x.user_id == @user_id RETURN x),
            (FOR x IN ActionItem FILTER x.user_id == @user_id RETURN x)
        )
            FILTER n.created_at != null
            LIMIT 500
            RETURN { type: n.node_type, title: n.title, timestamp: n.created_at }
        """
        
        DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        try:
            events = await self.graph.execute_query(query, {"user_id": user_id})
            
            if not events:
                return results
                
            # Track recurring events by title and day
            recurring: Dict[Tuple[str, int], int] = defaultdict(int)
            
            for event in events:
                title = event.get("title", "")
                timestamp_str = event.get("timestamp")
                
                if not timestamp_str or not title:
                    continue
                    
                try:
                    if isinstance(timestamp_str, str):
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    else:
                        timestamp = timestamp_str
                        
                    day_of_week = timestamp.weekday()
                    
                    # Normalize title (lowercase, first 50 chars)
                    title_key = title.lower()[:50]
                    recurring[(title_key, day_of_week)] += 1
                except (ValueError, AttributeError):
                    continue
                    
            # Find patterns (same title on same day multiple times)
            for (title, day), count in recurring.items():
                if count < self.MIN_PATTERN_FREQUENCY:
                    continue
                    
                confidence = min(0.9, 0.3 + (count * 0.1))
                
                content = {
                    "description": f"'{title[:30]}...' occurs every {DAYS[day]}",
                    "pattern_type": PatternType.DAY_OF_WEEK.value,
                    "event_title": title[:50],
                    "day_of_week": DAYS[day],
                    "day_number": day,
                    "frequency": count
                }
                
                results.append(ReasoningResult(
                    type="pattern",
                    confidence=confidence,
                    content=content,
                    source_agent=self.name
                ))
                    
        except Exception as e:
            logger.error(f"[{self.name}] Day-of-week pattern detection failed: {e}")
            
        return results
        
    async def _detect_periodic_patterns(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect periodic patterns: "User does X every week/month"
        """
        results = []
        
        # Query events with timestamps
        query = """
        FOR n IN UNION(
            (FOR x IN CalendarEvent FILTER x.user_id == @user_id RETURN x),
            (FOR x IN ActionItem FILTER x.user_id == @user_id RETURN x),
            (FOR x IN Document FILTER x.user_id == @user_id RETURN x)
        )
            FILTER n.created_at != null
            SORT n.created_at ASC
            LIMIT 300
            RETURN { type: n.node_type, title: n.title, timestamp: n.created_at }
        """
        
        try:
            events = await self.graph.execute_query(query, {"user_id": user_id})
            
            if not events or len(events) < 6:
                return results
                
            # Group events by similar titles
            title_groups: Dict[str, List[datetime]] = defaultdict(list)
            
            for event in events:
                title = event.get("title", "")
                timestamp_str = event.get("timestamp")
                
                if not timestamp_str or not title or len(title) < 5:
                    continue
                    
                try:
                    if isinstance(timestamp_str, str):
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    else:
                        timestamp = timestamp_str
                    
                    # Normalize title
                    title_key = title.lower()[:50]
                    title_groups[title_key].append(timestamp)
                except (ValueError, AttributeError):
                    continue
                    
            # Analyze for periodic patterns
            for title, timestamps in title_groups.items():
                if len(timestamps) < 3:
                    continue
                    
                # Sort timestamps
                timestamps.sort()
                
                # Calculate intervals between occurrences
                intervals = []
                for i in range(1, len(timestamps)):
                    interval = (timestamps[i] - timestamps[i-1]).days
                    if interval > 0:
                        intervals.append(interval)
                        
                if len(intervals) < 2:
                    continue
                    
                # Calculate average interval
                avg_interval = sum(intervals) / len(intervals)
                
                # Check if intervals are consistent (low variance)
                variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
                std_dev = variance ** 0.5
                
                # If standard deviation is less than 30% of average, it's periodic
                if avg_interval > 0 and (std_dev / avg_interval) < 0.3:
                    # Classify the period
                    if 5 <= avg_interval <= 9:
                        period = "weekly"
                    elif 25 <= avg_interval <= 35:
                        period = "monthly"
                    elif 80 <= avg_interval <= 100:
                        period = "quarterly"
                    elif avg_interval >= 350:
                        period = "yearly"
                    else:
                        period = f"every ~{int(avg_interval)} days"
                        
                    confidence = min(0.9, 0.5 + (1 - std_dev / avg_interval) * 0.4)
                    
                    content = {
                        "description": f"'{title[:30]}...' occurs {period}",
                        "pattern_type": PatternType.PERIODIC.value,
                        "event_title": title[:50],
                        "period": period,
                        "avg_interval_days": round(avg_interval, 1),
                        "consistency": round(1 - std_dev / avg_interval, 2),
                        "occurrences": len(timestamps)
                    }
                    
                    results.append(ReasoningResult(
                        type="pattern",
                        confidence=confidence,
                        content=content,
                        source_agent=self.name
                    ))
                    
        except Exception as e:
            logger.error(f"[{self.name}] Periodic pattern detection failed: {e}")
            
        return results
        
    async def _detect_cooccurrence_patterns(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect co-occurrence patterns: "X always mentioned with Y"
        """
        results = []
        
        # Explicitly list all relation collections for traversal
        rel_types = [r.value for r in RelationType]
        rel_str = ", ".join(rel_types)
        
        # Query for entities that appear together using AQL traversal
        # We start from Person, Project, Topic nodes
        query = f"""
        FOR a IN UNION(
            (FOR x IN Person FILTER x.user_id == @user_id RETURN x),
            (FOR x IN Project FILTER x.user_id == @user_id RETURN x),
            (FOR x IN Topic FILTER x.user_id == @user_id RETURN x)
        )
            # Find connected nodes via ANY relationship
            FOR b, e IN 1..1 ANY a {rel_str}
                # Filter target node type
                FILTER (b.node_type == 'Person' OR b.node_type == 'Project' OR b.node_type == 'Topic')
                   AND a._id < b._id  # Avoid duplicates and self-loops
                   
                COLLECT type_a = a.node_type, name_a = a.name, 
                        type_b = b.node_type, name_b = b.name
                        WITH COUNT INTO cooccurrence
                
                FILTER cooccurrence >= @min_freq
                SORT cooccurrence DESC
                LIMIT 10
                RETURN {{ type_a: type_a, name_a: name_a, type_b: type_b, name_b: name_b, cooccurrence: cooccurrence }}
        """
        
        try:
            patterns = await self.graph.execute_query(query, {
                "user_id": user_id,
                "min_freq": self.MIN_PATTERN_FREQUENCY
            })
            
            for pattern in patterns or []:
                name_a = pattern.get("name_a", "Unknown")
                name_b = pattern.get("name_b", "Unknown")
                type_a = pattern.get("type_a", "Item")
                type_b = pattern.get("type_b", "Item")
                count = pattern.get("cooccurrence", 0)
                
                confidence = min(0.9, 0.4 + (count * 0.05))
                
                content = {
                    "description": f"{type_a} '{name_a}' frequently appears with {type_b} '{name_b}'",
                    "pattern_type": PatternType.COOCCURRENCE.value,
                    "entity_a": {"type": type_a, "name": name_a},
                    "entity_b": {"type": type_b, "name": name_b},
                    "frequency": count
                }
                
                results.append(ReasoningResult(
                    type="pattern",
                    confidence=confidence,
                    content=content,
                    source_agent=self.name
                ))
                    
        except Exception as e:
            logger.error(f"[{self.name}] Co-occurrence pattern detection failed: {e}")
            
        return results
        
    async def _detect_duration_patterns(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect duration patterns: "X typically takes Y minutes"
        """
        results = []
        
        # Query calendar events with duration info
        query = """
        FOR e IN CalendarEvent
            FILTER e.user_id == @user_id
               AND e.start_time != null
               AND e.end_time != null
            LIMIT 300
            RETURN { title: e.title, start: e.start_time, end: e.end_time }
        """
        
        try:
            events = await self.graph.execute_query(query, {"user_id": user_id})
            
            if not events:
                return results
                
            # Group events by title and calculate durations
            duration_groups: Dict[str, List[int]] = defaultdict(list)
            
            for event in events:
                title = event.get("title", "")
                start_str = event.get("start")
                end_str = event.get("end")
                
                if not start_str or not end_str or not title:
                    continue
                    
                try:
                    if isinstance(start_str, str):
                        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start = start_str
                        
                    if isinstance(end_str, str):
                        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                    else:
                        end = end_str
                        
                    duration_minutes = int((end - start).total_seconds() / 60)
                    
                    if 5 <= duration_minutes <= 480:  # 5 min to 8 hours
                        title_key = title.lower()[:50]
                        duration_groups[title_key].append(duration_minutes)
                except (ValueError, AttributeError):
                    continue
                    
            # Find patterns (consistent durations)
            for title, durations in duration_groups.items():
                if len(durations) < self.MIN_PATTERN_FREQUENCY:
                    continue
                    
                avg_duration = sum(durations) / len(durations)
                variance = sum((d - avg_duration) ** 2 for d in durations) / len(durations)
                std_dev = variance ** 0.5
                
                # If duration is consistent (low variance)
                if avg_duration > 0 and (std_dev / avg_duration) < 0.3:
                    confidence = min(0.9, 0.5 + (1 - std_dev / avg_duration) * 0.4)
                    
                    content = {
                        "description": f"'{title[:30]}...' typically lasts {int(avg_duration)} minutes",
                        "pattern_type": PatternType.DURATION.value,
                        "event_title": title[:50],
                        "avg_duration_minutes": int(avg_duration),
                        "consistency": round(1 - std_dev / avg_duration, 2),
                        "sample_size": len(durations)
                    }
                    
                    results.append(ReasoningResult(
                        type="pattern",
                        confidence=confidence,
                        content=content,
                        source_agent=self.name
                    ))
                    
        except Exception as e:
            logger.error(f"[{self.name}] Duration pattern detection failed: {e}")
            
        return results
