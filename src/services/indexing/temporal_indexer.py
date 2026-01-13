"""
Temporal Indexer Service

Maintains TimeBlock nodes in the knowledge graph and links events to their
corresponding time periods. This enables temporal queries like:
- "What happened last week?"
- "Show me my activity for December"
- "What was I working on before the holidays?"

TimeBlock Structure:
- Granularity levels: hour, day, week, month, quarter, year
- Each TimeBlock has start_time, end_time, granularity, and optional label
- Events are linked via OCCURRED_DURING relationship
- Calendar events additionally use SCHEDULED_FOR

Version: 1.0.0
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import asyncio

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.indexing.graph.schema_constants import (
    TIME_GRANULARITIES,
    DEFAULT_TIME_GRANULARITY,
    TIMEBLOCK_ID_PREFIX,
    MAX_TIMEBLOCKS_PER_BATCH,
)

logger = setup_logger(__name__)


class TimeGranularity(str, Enum):
    """Time granularity levels for TimeBlock nodes."""
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class TemporalIndexer:
    """
    Service for creating and managing TimeBlock nodes in the knowledge graph.
    Now supports "Episode Detection" to find significant clusters of activity.
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager, rag_engine: Optional[Any] = None):
        self.config = config
        self.graph = graph_manager
        self.rag_engine = rag_engine
        
    async def detect_episodes(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Scan for high-activity periods and create Episode nodes.
        
        Logic:
        1. Aggregate event counts by day
        2. Find consecutive days with high activity OR shared topics
        3. Identify main Topics during that period
        4. Create Episode node if significant
        """
        # 1. Get daily activity
        timeline = await self.get_timeline(user_id, start_date, end_date, granularity="day")
        if not timeline:
            return []
            
        episodes = []
        current_episode = []
        current_topic = None
        
        # We process days sequentially
        for day in timeline:
            day_count = day.get("event_count", 0)
            
            # Find dominant topic for this day
            day_topic = await self._get_day_dominant_topic(user_id, day.get("start_time"))
            
            # Start new episode if:
            # - No current episode
            # - Topic changed significantly
            # - Gap in activity (> 2 days)
            
            is_gap = False
            if current_episode:
                last_day = datetime.fromisoformat(current_episode[-1]["start_time"])
                this_day = datetime.fromisoformat(day["start_time"])
                if (this_day - last_day).days > 2:
                    is_gap = True
            
            topic_match = False
            if current_topic and day_topic:
                 topic_match = (current_topic == day_topic) or (self.rag_engine and await self._are_topics_similar(current_topic, day_topic))
                 
            should_continue = topic_match and not is_gap
            
            if current_episode and not should_continue:
                # Close valid episode
                if len(current_episode) >= 3 or (len(current_episode) >= 1 and sum(d.get("event_count", 0) for d in current_episode) > 20):
                     episode = await self._create_episode(user_id, current_episode)
                     if episode:
                         episodes.append(episode)
                current_episode = []
                current_topic = None
                
            if day_count > 0:
                if not current_episode:
                    current_topic = day_topic
                current_episode.append(day)
                
        # Handle trailing
        if current_episode:
             if len(current_episode) >= 3 or (len(current_episode) >= 1 and sum(d.get("event_count", 0) for d in current_episode) > 20):
                 episode = await self._create_episode(user_id, current_episode)
                 if episode:
                     episodes.append(episode)
                     
        return episodes

    async def _get_day_dominant_topic(self, user_id: int, start_time: str) -> Optional[str]:
        """Get the name of the most discussed topic for a day."""
        query = """
        FOR tb IN TimeBlock
            FILTER tb.start_time == @start_time
            FOR edge IN OCCURRED_DURING
                FILTER edge._to == tb._id
                LET e = DOCUMENT(edge._from)
                FOR tedge IN DISCUSSES
                    FILTER tedge._from == e._id
                    LET t = DOCUMENT(tedge._to)
                    COLLECT topic_name = t.name WITH COUNT INTO cnt
                    SORT cnt DESC
                    LIMIT 1
                    RETURN { name: topic_name, count: cnt }
        """
        try:
            result = await self.graph.execute_query(query, {"start_time": start_time})
            if result:
                return result[0]["name"]
        except Exception:
            pass
        return None
        
    async def _are_topics_similar(self, topic1: str, topic2: str) -> bool:
        """Check if two topics are semantically similar using RAG."""
        if not self.rag_engine:
            return topic1 == topic2
        # Simple placeholder for RAG similarity check
        # In real impl, we'd cache embeddings or use a lightweight comparison
        return topic1 == topic2  # Fallback for now to avoid heavy RAG calls in loop

    async def _create_episode(self, user_id: int, days: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Create an Episode node from a list of high-activity days."""
        if not days:
            return None
            
        start_time = days[0]["start_time"]
        end_time = days[-1]["start_time"]  # Should be end_time of last day, but simplified
        
        # Identify dominant topics in this range
        query = """
        FOR tb IN TimeBlock
            FILTER tb.start_time >= @start AND tb.start_time <= @end AND tb.user_id == @user_id
            FOR edge IN OCCURRED_DURING
                FILTER edge._to == tb._id
                LET e = DOCUMENT(edge._from)
                FOR tedge IN DISCUSSES
                    FILTER tedge._from == e._id
                    LET t = DOCUMENT(tedge._to)
                    COLLECT topic_id = t.id, topic_name = t.name WITH COUNT INTO strength
                    SORT strength DESC
                    LIMIT 3
                    RETURN { id: topic_id, name: topic_name, strength: strength }
        """
        topics = await self.graph.execute_query(query, {
            "start": start_time,
            "end": end_time,
            "user_id": user_id
        })
        
        if not topics:
            return None
            
        main_topic = topics[0]["name"]
        
        episode_name = f"Episode: {main_topic}"
        description = f"High activity period focused on {main_topic}"
        
        # Create Episode Node
        try:
            episode_id = f"episode:{user_id}:{start_time}"
            properties = {
                "name": episode_name,
                "description": description,
                "start_time": start_time,
                "end_time": end_time,
                "significance": 0.8,
                "user_id": user_id,
                "event_count": sum(d.get("event_count", 0) for d in days),
                "created_at": datetime.utcnow().isoformat()
            }
            
            await self.graph.create_node(NodeType.EPISODE, properties)
            
            # Link to Topics
            for topic in topics:
                await self.graph.create_relationship(
                    from_id=topic["id"],
                    to_id=episode_id,
                    relation_type=RelationType.ACTIVE_DURING,
                    properties={"weight": topic["strength"]}
                )
                
            logger.info(f"[TemporalIndexer] Created Episode: {episode_name}")
            return properties
            
        except Exception as e:
            logger.error(f"[TemporalIndexer] Failed to create episode: {e}")
            return None
        
    async def ensure_timeblock_exists(
        self,
        timestamp: datetime,
        granularity: str = DEFAULT_TIME_GRANULARITY,
        user_id: Optional[int] = None
    ) -> str:
        """
        Ensure a TimeBlock exists for the given timestamp and granularity.
        Creates the TimeBlock if it doesn't exist.
        
        Args:
            timestamp: The datetime to create a TimeBlock for
            granularity: hour, day, week, month, quarter, year
            user_id: Optional user ID for user-specific TimeBlocks
            
        Returns:
            The TimeBlock node ID
        """
        start_time, end_time = self._calculate_bounds(timestamp, granularity)
        timeblock_id = self._generate_timeblock_id(start_time, granularity, user_id)
        
        # Check if TimeBlock already exists
        query = f"""
        FOR tb IN TimeBlock
            FILTER tb.id == @id
            RETURN {{ id: tb.id }}
        """
        
        try:
            result = await self.graph.execute_query(query, {"id": timeblock_id})
            if result and len(result) > 0:
                return timeblock_id
        except Exception:
            pass  # TimeBlock doesn't exist, create it
        
        # Create new TimeBlock
        label = self._generate_label(start_time, granularity)
        properties = {
            "id": timeblock_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "granularity": granularity,
            "label": label,
            "created_at": datetime.utcnow().isoformat(),
        }
        
        if user_id:
            properties["user_id"] = user_id
            
        await self.graph.create_node(NodeType.TIME_BLOCK, properties)
        logger.debug(f"[TemporalIndexer] Created TimeBlock: {label} ({granularity})")
        
        # Create temporal relationships with adjacent TimeBlocks
        await self._link_adjacent_timeblocks(timeblock_id, start_time, granularity, user_id)
        
        return timeblock_id
    
    async def link_event_to_timeblock(
        self,
        event_id: str,
        timestamp: datetime,
        granularity: str = DEFAULT_TIME_GRANULARITY,
        user_id: Optional[int] = None,
        relationship_type: RelationType = RelationType.OCCURRED_DURING
    ) -> bool:
        """
        Link an event node to its corresponding TimeBlock.
        
        Args:
            event_id: The ID of the event node (email, message, etc.)
            timestamp: When the event occurred
            granularity: TimeBlock granularity to link to
            user_id: Optional user ID
            relationship_type: OCCURRED_DURING or SCHEDULED_FOR
            
        Returns:
            True if link created successfully
        """
        try:
            timeblock_id = await self.ensure_timeblock_exists(timestamp, granularity, user_id)
            
            await self.graph.create_relationship(
                from_id=event_id,
                to_id=timeblock_id,
                relation_type=relationship_type,
                properties={
                    "linked_at": datetime.utcnow().isoformat(),
                    "event_timestamp": timestamp.isoformat(),
                }
            )
            return True
            
        except Exception as e:
            logger.error(f"[TemporalIndexer] Failed to link event {event_id} to TimeBlock: {e}")
            return False
    
    async def get_events_in_timeblock(
        self,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        granularity: str = DEFAULT_TIME_GRANULARITY,
        event_types: Optional[List[NodeType]] = None,
        user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all events that occurred within a time range.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range (default: end of the granularity period)
            granularity: TimeBlock granularity
            event_types: Filter by event types (Email, Message, CalendarEvent, etc.)
            user_id: Filter by user
            
        Returns:
            List of event nodes with their properties
        """
        if end_time is None:
            _, end_time = self._calculate_bounds(start_time, granularity)
        
        # Build type filter
        type_filter = ""
        if event_types:
            type_labels = " OR ".join([f"e:{et.value}" for et in event_types])
            type_filter = f"AND ({type_labels})"
        
        user_filter = ""
        if user_id:
            user_filter = f"AND tb.user_id == {user_id}"
        
        query = f"""
        FOR tb IN TimeBlock
            FILTER tb.start_time >= @start_time
               AND tb.end_time <= @end_time
               AND tb.granularity == @granularity
               {user_filter}
            FOR edge IN UNION(
                (FOR e IN OCCURRED_DURING FILTER e._to == tb._id RETURN e),
                (FOR e IN SCHEDULED_FOR FILTER e._to == tb._id RETURN e)
            )
                LET e = DOCUMENT(edge._from)
                SORT e.timestamp DESC
                LIMIT 100
                RETURN {{
                    id: e.id,
                    types: [e.node_type],
                    props: e,
                    timeblock: tb.label
                }}
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "granularity": granularity,
            })
            return results or []
        except Exception as e:
            logger.error(f"[TemporalIndexer] Failed to get events: {e}")
            return []
    
    async def get_timeline(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        granularity: str = "day"
    ) -> List[Dict[str, Any]]:
        """
        Get a timeline of activity for a user.
        
        Returns TimeBlocks with event counts and summaries.
        """
        query = """
        FOR tb IN TimeBlock
            FILTER tb.user_id == @user_id
               AND tb.granularity == @granularity
               AND tb.start_time >= @start_date
               AND tb.end_time <= @end_date
            
            LET events = (
                FOR edge IN OCCURRED_DURING
                    FILTER edge._to == tb._id
                    LET e = DOCUMENT(edge._from)
                    RETURN e
            )
            
            SORT tb.start_time
            RETURN {
                id: tb.id,
                label: tb.label,
                start_time: tb.start_time,
                event_count: LENGTH(events),
                event_types: SLICE((FOR ev IN events RETURN ev.node_type), 0, 5)
            }
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "user_id": user_id,
                "granularity": granularity,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            })
            return results or []
        except Exception as e:
            logger.error(f"[TemporalIndexer] Timeline query failed: {e}")
            return []
    
    async def backfill_timeblocks(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: str = "day",
        user_id: Optional[int] = None
    ) -> int:
        """
        Create TimeBlock nodes for a date range (backfill historical data).
        
        Returns:
            Number of TimeBlocks created
        """
        count = 0
        current = start_date
        
        while current <= end_date and count < MAX_TIMEBLOCKS_PER_BATCH:
            await self.ensure_timeblock_exists(current, granularity, user_id)
            current = self._advance_time(current, granularity)
            count += 1
            
        logger.info(f"[TemporalIndexer] Backfilled {count} TimeBlocks ({granularity})")
        return count
    
    def _calculate_bounds(
        self, 
        timestamp: datetime, 
        granularity: str
    ) -> Tuple[datetime, datetime]:
        """Calculate start and end times for a TimeBlock."""
        if granularity == "hour":
            start = timestamp.replace(minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
        elif granularity == "day":
            start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif granularity == "week":
            # Start of week (Monday)
            start = timestamp - timedelta(days=timestamp.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(weeks=1)
        elif granularity == "month":
            start = timestamp.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # End of month
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
        elif granularity == "quarter":
            quarter = (timestamp.month - 1) // 3
            start = timestamp.replace(month=quarter * 3 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_month = (quarter + 1) * 3 + 1
            if end_month > 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=end_month)
        elif granularity == "year":
            start = timestamp.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(year=start.year + 1)
        else:
            raise ValueError(f"Unknown granularity: {granularity}")
            
        return start, end
    
    def _generate_timeblock_id(
        self,
        start_time: datetime,
        granularity: str,
        user_id: Optional[int] = None
    ) -> str:
        """Generate a unique ID for a TimeBlock."""
        if granularity == "hour":
            time_part = start_time.strftime("%Y-%m-%dT%H")
        elif granularity == "day":
            time_part = start_time.strftime("%Y-%m-%d")
        elif granularity == "week":
            time_part = f"{start_time.year}-W{start_time.isocalendar()[1]:02d}"
        elif granularity == "month":
            time_part = start_time.strftime("%Y-%m")
        elif granularity == "quarter":
            quarter = (start_time.month - 1) // 3 + 1
            time_part = f"{start_time.year}-Q{quarter}"
        elif granularity == "year":
            time_part = str(start_time.year)
        else:
            time_part = start_time.isoformat()
        
        base_id = f"{TIMEBLOCK_ID_PREFIX}:{granularity}:{time_part}"
        if user_id:
            base_id = f"{base_id}:user_{user_id}"
        return base_id
    
    def _generate_label(self, start_time: datetime, granularity: str) -> str:
        """Generate a human-readable label for a TimeBlock."""
        if granularity == "hour":
            return start_time.strftime("%B %d, %Y at %I %p")
        elif granularity == "day":
            return start_time.strftime("%A, %B %d, %Y")
        elif granularity == "week":
            week_num = start_time.isocalendar()[1]
            return f"Week {week_num} of {start_time.year}"
        elif granularity == "month":
            return start_time.strftime("%B %Y")
        elif granularity == "quarter":
            quarter = (start_time.month - 1) // 3 + 1
            return f"Q{quarter} {start_time.year}"
        elif granularity == "year":
            return str(start_time.year)
        return start_time.isoformat()
    
    def _advance_time(self, timestamp: datetime, granularity: str) -> datetime:
        """Advance a timestamp by one granularity unit."""
        if granularity == "hour":
            return timestamp + timedelta(hours=1)
        elif granularity == "day":
            return timestamp + timedelta(days=1)
        elif granularity == "week":
            return timestamp + timedelta(weeks=1)
        elif granularity == "month":
            if timestamp.month == 12:
                return timestamp.replace(year=timestamp.year + 1, month=1)
            return timestamp.replace(month=timestamp.month + 1)
        elif granularity == "quarter":
            new_month = timestamp.month + 3
            if new_month > 12:
                return timestamp.replace(year=timestamp.year + 1, month=new_month - 12)
            return timestamp.replace(month=new_month)
        elif granularity == "year":
            return timestamp.replace(year=timestamp.year + 1)
        return timestamp + timedelta(days=1)
    
    async def _link_adjacent_timeblocks(
        self,
        timeblock_id: str,
        start_time: datetime,
        granularity: str,
        user_id: Optional[int] = None
    ) -> None:
        """
        Create PRECEDED/FOLLOWS relationships with adjacent TimeBlocks.
        """
        # Calculate previous TimeBlock
        prev_end = start_time
        if granularity == "hour":
            prev_start = prev_end - timedelta(hours=1)
        elif granularity == "day":
            prev_start = prev_end - timedelta(days=1)
        elif granularity == "week":
            prev_start = prev_end - timedelta(weeks=1)
        elif granularity == "month":
            if start_time.month == 1:
                prev_start = start_time.replace(year=start_time.year - 1, month=12)
            else:
                prev_start = start_time.replace(month=start_time.month - 1)
        else:
            return  # Skip for quarter/year to reduce complexity
        
        prev_id = self._generate_timeblock_id(prev_start, granularity, user_id)
        
        # Check if previous TimeBlock exists and link
        try:
            query = """
            LET prev = FIRST(FOR tb IN TimeBlock FILTER tb.id == @prev_id RETURN tb)
            LET curr = FIRST(FOR tb IN TimeBlock FILTER tb.id == @curr_id RETURN tb)
            
            FILTER prev != null AND curr != null
            
            LET existing = (FOR e IN PRECEDED FILTER e._from == prev._id AND e._to == curr._id RETURN 1)
            FILTER LENGTH(existing) == 0
            
            INSERT { _from: prev._id, _to: curr._id, created_at: @now } INTO PRECEDED
            INSERT { _from: curr._id, _to: prev._id, created_at: @now } INTO FOLLOWS
            
            RETURN true
            """
            await self.graph.execute_query(query, {
                "prev_id": prev_id,
                "curr_id": timeblock_id,
                "now": datetime.utcnow().isoformat(),
            })
        except Exception:
            pass  # Previous TimeBlock may not exist yet
            
    # =========================================================================
    # Enhanced Intelligence Methods
    # =========================================================================
    
    async def get_user_activity_heatmap(
        self, 
        user_id: int, 
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Generate an activity heatmap for the user.
        
        Returns activity counts bucketed by:
        - Day of week (0=Mon, 6=Sun)
        - Hour of day (0-23)
        
        This enables visualizations like GitHub's contribution graph
        and insights like "You're most active on Tuesdays at 10 AM".
        """
        start_date = datetime.utcnow() - timedelta(days=days)
        
        query = """
        FOR n IN UNION(
            (FOR e IN Email FILTER e.user_id == @user_id AND e.created_at != null AND e.created_at >= @start_date RETURN { timestamp: e.created_at, type: 'Email' }),
            (FOR m IN Message FILTER m.user_id == @user_id AND m.created_at != null AND m.created_at >= @start_date RETURN { timestamp: m.created_at, type: 'Message' }),
            (FOR c IN CalendarEvent FILTER c.user_id == @user_id AND c.created_at != null AND c.created_at >= @start_date RETURN { timestamp: c.created_at, type: 'CalendarEvent' }),
            (FOR a IN ActionItem FILTER a.user_id == @user_id AND a.created_at != null AND a.created_at >= @start_date RETURN { timestamp: a.created_at, type: 'ActionItem' }),
            (FOR d IN Document FILTER d.user_id == @user_id AND d.created_at != null AND d.created_at >= @start_date RETURN { timestamp: d.created_at, type: 'Document' })
        )
            RETURN { timestamp: n.timestamp, type: n.type }
        """
        
        heatmap = {
            "by_day": {str(i): 0 for i in range(7)},  # Mon-Sun
            "by_hour": {str(i): 0 for i in range(24)},  # 0-23
            "by_day_hour": {},  # Combined: "2-10" = Tuesday 10 AM
            "total_events": 0,
            "days_analyzed": days,
            "peak_day": None,
            "peak_hour": None,
            "by_type": {}
        }
        
        try:
            results = await self.graph.execute_query(query, {
                "user_id": user_id,
                "start_date": start_date.isoformat()
            })
            
            for record in results or []:
                timestamp_str = record.get('timestamp')
                event_type = record.get('type', 'Unknown')
                
                if not timestamp_str:
                    continue
                    
                try:
                    if isinstance(timestamp_str, str):
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    else:
                        timestamp = timestamp_str
                        
                    day = str(timestamp.weekday())
                    hour = str(timestamp.hour)
                    day_hour = f"{day}-{hour}"
                    
                    heatmap["by_day"][day] = heatmap["by_day"].get(day, 0) + 1
                    heatmap["by_hour"][hour] = heatmap["by_hour"].get(hour, 0) + 1
                    heatmap["by_day_hour"][day_hour] = heatmap["by_day_hour"].get(day_hour, 0) + 1
                    heatmap["by_type"][event_type] = heatmap["by_type"].get(event_type, 0) + 1
                    heatmap["total_events"] += 1
                    
                except (ValueError, AttributeError):
                    continue
                    
            # Find peaks
            if heatmap["by_day"]:
                peak_day = max(heatmap["by_day"].items(), key=lambda x: x[1])
                DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                heatmap["peak_day"] = {"day": DAYS[int(peak_day[0])], "count": peak_day[1]}
                
            if heatmap["by_hour"]:
                peak_hour = max(heatmap["by_hour"].items(), key=lambda x: x[1])
                heatmap["peak_hour"] = {"hour": int(peak_hour[0]), "count": peak_hour[1]}
                
        except Exception as e:
            logger.error(f"[TemporalIndexer] Heatmap generation failed: {e}")
            
        return heatmap
        
    def calculate_episode_importance(self, episode: Dict[str, Any]) -> float:
        """
        Calculate the importance score of an episode.
        
        Factors:
        - Event count (more events = more significant)
        - Duration (longer episodes may be more significant projects)
        - Topic diversity (focused episodes may be more important)
        - Recency (recent episodes weighted higher)
        """
        importance = 0.0
        
        # Event count factor (0-0.3)
        event_count = episode.get("event_count", 0)
        event_score = min(0.3, event_count / 100)  # Max at 100 events
        importance += event_score
        
        # Duration factor (0-0.2)
        start_str = episode.get("start_time")
        end_str = episode.get("end_time")
        if start_str and end_str:
            try:
                start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                duration_days = (end - start).days
                duration_score = min(0.2, duration_days / 30)  # Max at 30 days
                importance += duration_score
            except (ValueError, AttributeError):
                pass
                
        # Recency factor (0-0.3)
        if end_str:
            try:
                end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                days_ago = (datetime.utcnow() - end).days
                recency_score = max(0, 0.3 - (days_ago / 100))  # Decays over 100 days
                importance += recency_score
            except (ValueError, AttributeError):
                pass
                
        # Base significance from episode (0-0.2)
        base_sig = episode.get("significance", 0.5)
        importance += base_sig * 0.2
        
        return min(1.0, importance)
        
    async def find_similar_episodes(
        self, 
        user_id: int,
        episode_id: str, 
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find episodes similar to a given episode.
        
        Similarity based on:
        - Shared topics
        - Similar time patterns
        - Similar event types
        """
        similar_episodes = []
        
        # Get the source episode's topics
        topic_query = """
        FOR t IN Topic
            FOR edge IN ACTIVE_DURING
                FILTER edge._to == @episode_id AND edge._from == t._id
                RETURN { topic: t.name }
        """
        
        try:
            topics = await self.graph.execute_query(topic_query, {"episode_id": episode_id})
            topic_names = [t["topic"] for t in (topics or [])]
            
            if not topic_names:
                return []
                
            # Find other episodes with similar topics
            similar_query = """
            FOR t IN Topic
                FILTER t.name IN @topics
                FOR edge IN ACTIVE_DURING
                    FILTER edge._from == t._id
                    LET e = DOCUMENT(edge._to)
                    FILTER e.id != @episode_id AND e.user_id == @user_id
                    COLLECT episode_id = e.id, episode_name = e.name, 
                            start = e.start_time, end = e.end_time, count = e.event_count
                            WITH COUNT INTO shared
                    SORT shared DESC
                    LIMIT @limit
                    RETURN {
                        id: episode_id,
                        name: episode_name,
                        start_time: start,
                        end_time: end,
                        event_count: count,
                        shared_topics: shared
                    }
            """
            
            results = await self.graph.execute_query(similar_query, {
                "topics": topic_names,
                "episode_id": episode_id,
                "user_id": user_id,
                "limit": limit
            })
            
            for record in results or []:
                similar_episodes.append({
                    "id": record.get("id"),
                    "name": record.get("name"),
                    "start_time": record.get("start_time"),
                    "end_time": record.get("end_time"),
                    "event_count": record.get("event_count"),
                    "shared_topics": record.get("shared_topics"),
                    "similarity_score": min(1.0, record.get("shared_topics", 0) / len(topic_names))
                })
                
        except Exception as e:
            logger.error(f"[TemporalIndexer] Similar episode search failed: {e}")
            
        return similar_episodes

