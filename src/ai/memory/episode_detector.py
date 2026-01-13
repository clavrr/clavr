"""
Episode Detection for Active Project Prioritization

Clusters high-activity periods in the knowledge graph to detect "active projects"
and prioritize retrieval from those specific nodes.

Part of the Advanced RAG architecture for temporal awareness.
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class EpisodeType(Enum):
    """Types of detected episodes."""
    PROJECT = "project"       # Sustained work on a project
    CONVERSATION = "conversation"  # Active email/message thread
    DEADLINE = "deadline"     # Upcoming deadline cluster
    MEETING_SERIES = "meeting_series"  # Related meetings
    RESEARCH = "research"     # Research/learning activity


@dataclass
class Episode:
    """A detected episode of activity."""
    episode_id: str
    type: EpisodeType
    title: str              # Human-readable episode name
    start_time: datetime
    end_time: datetime
    node_ids: List[str]     # Graph nodes in this episode
    activity_score: float   # 0-1 score based on activity level
    recency_score: float    # Decay based on time since last activity
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodeContext:
    """Context from detected episodes for RAG boost."""
    active_episodes: List[Episode]
    boost_node_ids: List[str]   # Node IDs to boost in retrieval
    boost_factor: float         # How much to boost (1.0-2.0)
    context_summary: str        # Summary for prompt injection


class EpisodeDetector:
    """
    Detects active episodes for retrieval prioritization.
    
    Uses graph activity patterns to identify:
    - Active projects (sustained activity over time)
    - Hot threads (recent email/message clusters)
    - Upcoming deadlines (events with approaching dates)
    
    Features:
    - Time-window based clustering
    - Activity frequency scoring
    - Recency decay for prioritization
    """
    
    # Configuration
    DEFAULT_WINDOW_HOURS = 48       # Look back window
    MIN_ACTIVITY_COUNT = 3          # Minimum nodes for episode
    RECENCY_HALF_LIFE_HOURS = 24    # Half-life for recency decay
    
    def __init__(
        self,
        graph_manager: Optional[Any] = None,
        window_hours: int = 48,
        min_activity: int = 3
    ):
        """
        Initialize episode detector.
        
        Args:
            graph_manager: Knowledge graph manager
            window_hours: Hours to look back for activity
            min_activity: Minimum activities to form episode
        """
        self.graph = graph_manager
        self.window_hours = window_hours
        self.min_activity = min_activity
        
        # Cache for detected episodes
        self._episode_cache: Dict[int, Tuple[datetime, List[Episode]]] = {}
        self._cache_ttl = timedelta(minutes=15)
        
        logger.info(f"EpisodeDetector initialized (window={window_hours}h, min_activity={min_activity})")
    
    async def detect_episodes(
        self,
        user_id: int,
        force_refresh: bool = False
    ) -> List[Episode]:
        """
        Detect active episodes for a user.
        
        Args:
            user_id: The user's ID
            force_refresh: Bypass cache and recompute
            
        Returns:
            List of detected episodes sorted by relevance
        """
        # Check cache
        if not force_refresh and user_id in self._episode_cache:
            cached_time, cached_episodes = self._episode_cache[user_id]
            if datetime.utcnow() - cached_time < self._cache_ttl:
                return cached_episodes
        
        episodes = []
        
        # Detect different episode types
        project_episodes = await self._detect_project_episodes(user_id)
        episodes.extend(project_episodes)
        
        thread_episodes = await self._detect_conversation_episodes(user_id)
        episodes.extend(thread_episodes)
        
        deadline_episodes = await self._detect_deadline_episodes(user_id)
        episodes.extend(deadline_episodes)
        
        # Sort by combined relevance (activity * recency)
        episodes.sort(
            key=lambda e: e.activity_score * e.recency_score,
            reverse=True
        )
        
        # Update cache
        self._episode_cache[user_id] = (datetime.utcnow(), episodes)
        
        return episodes
    
    async def get_retrieval_context(
        self,
        user_id: int,
        query: Optional[str] = None,
        max_episodes: int = 3
    ) -> EpisodeContext:
        """
        Get episode context for RAG retrieval boosting.
        
        Args:
            user_id: User ID
            query: Optional query for relevance filtering
            max_episodes: Max episodes to include
            
        Returns:
            EpisodeContext with boost information
        """
        episodes = await self.detect_episodes(user_id)
        
        # Filter to most relevant episodes
        if query:
            # Score episodes by query relevance
            query_lower = query.lower()
            for ep in episodes:
                title_match = sum(1 for word in query_lower.split() 
                                 if word in ep.title.lower())
                ep.metadata['query_relevance'] = title_match / max(1, len(query_lower.split()))
            
            # Re-sort with query relevance
            episodes.sort(
                key=lambda e: (
                    e.activity_score * e.recency_score * 
                    (1 + e.metadata.get('query_relevance', 0))
                ),
                reverse=True
            )
        
        active = episodes[:max_episodes]
        
        # Collect node IDs to boost
        boost_ids = []
        for ep in active:
            boost_ids.extend(ep.node_ids[:10])  # Limit per episode
        
        # Calculate boost factor based on episode strength
        if active:
            avg_relevance = sum(
                e.activity_score * e.recency_score for e in active
            ) / len(active)
            boost_factor = 1.0 + min(0.5, avg_relevance)  # 1.0-1.5x boost
        else:
            boost_factor = 1.0
        
        # Generate context summary
        if active:
            titles = [e.title for e in active[:3]]
            summary = f"Active focus: {', '.join(titles)}"
        else:
            summary = ""
        
        return EpisodeContext(
            active_episodes=active,
            boost_node_ids=boost_ids,
            boost_factor=boost_factor,
            context_summary=summary
        )
    
    async def _detect_project_episodes(self, user_id: int) -> List[Episode]:
        """Detect project-related episodes from task/document activity."""
        episodes = []
        
        if not self.graph:
            return episodes
        
        try:
            from src.services.indexing.graph.schema import NodeType, RelationType
            
            now = datetime.utcnow()
            window_start = now - timedelta(hours=self.window_hours)
            
            # Query for recent activity on projects
            # Group by project node and count activity
            query = f"""
                FOR doc IN Document
                    FILTER doc.user_id == @user_id
                    FILTER doc.updated_at >= @window_start OR doc.created_at >= @window_start
                    COLLECT project = doc.project_id INTO docs
                    LET activity_count = LENGTH(docs)
                    FILTER activity_count >= @min_activity
                    SORT activity_count DESC
                    LIMIT 20
                    RETURN {{
                        project_id: project,
                        activity_count: activity_count,
                        doc_ids: docs[*].doc._id
                    }}
            """
            
            results = await self.graph.execute_query(
                query,
                {
                    'user_id': str(user_id),
                    'window_start': window_start.isoformat(),
                    'min_activity': self.min_activity
                }
            )
            
            for result in results:
                project_id = result.get('project_id')
                if not project_id:
                    continue
                
                activity = result.get('activity_count', 0)
                doc_ids = result.get('doc_ids', [])
                
                # Get project name
                project_node = await self.graph.get_node(project_id)
                title = project_node.get('name', project_id) if project_node else project_id
                
                episode = Episode(
                    episode_id=f"project_{project_id}",
                    type=EpisodeType.PROJECT,
                    title=f"Project: {title}",
                    start_time=window_start,
                    end_time=now,
                    node_ids=doc_ids,
                    activity_score=min(1.0, activity / 10.0),
                    recency_score=1.0,  # Recent by definition
                    metadata={'project_id': project_id}
                )
                episodes.append(episode)
                
        except Exception as e:
            logger.debug(f"Project episode detection failed: {e}")
        
        return episodes
    
    async def _detect_conversation_episodes(self, user_id: int) -> List[Episode]:
        """Detect active email/message threads."""
        episodes = []
        
        if not self.graph:
            return episodes
        
        try:
            from src.services.indexing.graph.schema import NodeType
            
            now = datetime.utcnow()
            window_start = now - timedelta(hours=self.window_hours)
            
            # Query for active threads
            query = """
                FOR email IN Email
                    FILTER email.user_id == @user_id
                    FILTER email.timestamp >= @window_start
                    COLLECT thread_id = email.thread_id INTO emails
                    LET msg_count = LENGTH(emails)
                    FILTER msg_count >= @min_activity
                    SORT msg_count DESC
                    LIMIT 20
                    RETURN {
                        thread_id: thread_id,
                        msg_count: msg_count,
                        subject: FIRST(emails).email.subject,
                        email_ids: emails[*].email._id
                    }
            """
            
            results = await self.graph.execute_query(
                query,
                {
                    'user_id': str(user_id),
                    'window_start': window_start.isoformat(),
                    'min_activity': self.min_activity
                }
            )
            
            for result in results:
                thread_id = result.get('thread_id')
                if not thread_id:
                    continue
                
                msg_count = result.get('msg_count', 0)
                subject = result.get('subject', 'Thread')
                email_ids = result.get('email_ids', [])
                
                episode = Episode(
                    episode_id=f"thread_{thread_id}",
                    type=EpisodeType.CONVERSATION,
                    title=f"Thread: {subject[:50]}",
                    start_time=window_start,
                    end_time=now,
                    node_ids=email_ids,
                    activity_score=min(1.0, msg_count / 5.0),
                    recency_score=1.0,
                    metadata={'thread_id': thread_id, 'subject': subject}
                )
                episodes.append(episode)
                
        except Exception as e:
            logger.debug(f"Conversation episode detection failed: {e}")
        
        return episodes
    
    async def _detect_deadline_episodes(self, user_id: int) -> List[Episode]:
        """Detect upcoming deadline clusters."""
        episodes = []
        
        if not self.graph:
            return episodes
        
        try:
            now = datetime.utcnow()
            future_window = now + timedelta(hours=self.window_hours * 2)
            
            # Query for upcoming deadlines/events
            query = """
                FOR item IN ActionItem
                    FILTER item.user_id == @user_id
                    FILTER item.due_date != null
                    FILTER item.due_date >= @now AND item.due_date <= @future
                    FILTER item.status != 'completed'
                    SORT item.due_date ASC
                    LIMIT 10
                    RETURN {
                        id: item._id,
                        title: item.title,
                        due_date: item.due_date
                    }
            """
            
            results = await self.graph.execute_query(
                query,
                {
                    'user_id': str(user_id),
                    'now': now.isoformat(),
                    'future': future_window.isoformat()
                }
            )
            
            if results:
                # Group by day for clustering
                by_day = defaultdict(list)
                for item in results:
                    due = item.get('due_date', '')
                    day = due[:10] if due else 'unknown'
                    by_day[day].append(item)
                
                for day, items in by_day.items():
                    if len(items) >= 2:  # At least 2 items due same day
                        episode = Episode(
                            episode_id=f"deadline_{day}",
                            type=EpisodeType.DEADLINE,
                            title=f"Deadlines on {day}",
                            start_time=now,
                            end_time=future_window,
                            node_ids=[i['id'] for i in items],
                            activity_score=min(1.0, len(items) / 3.0),
                            recency_score=0.8,  # Slightly lower for future
                            metadata={'due_date': day, 'items': [i['title'] for i in items]}
                        )
                        episodes.append(episode)
                        
        except Exception as e:
            logger.debug(f"Deadline episode detection failed: {e}")
        
        return episodes
    
    def calculate_recency_decay(self, last_activity: datetime) -> float:
        """
        Calculate recency decay score.
        
        Uses exponential decay with configurable half-life.
        """
        now = datetime.utcnow()
        hours_ago = (now - last_activity).total_seconds() / 3600
        
        # Exponential decay: score = 0.5^(hours/half_life)
        half_life = self.RECENCY_HALF_LIFE_HOURS
        decay = 0.5 ** (hours_ago / half_life)
        
        return decay
