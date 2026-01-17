"""
Episode Narrative Service

Converts detected episodes from TemporalIndexer into human-readable narratives.
Enables users to understand "what happened" during significant activity periods.

Features:
- Single episode summaries with participants and outcomes
- Period summaries (weekly/monthly "life stories")
- Key participant extraction
- Outcome detection (decisions, tasks created)
- Follow-up identification
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

# Configuration
MAX_EVENTS_FOR_SUMMARY = 50
MAX_PARTICIPANTS = 5
MAX_OUTCOMES = 5
MAX_FOLLOWUPS = 3


@dataclass
class EpisodeNarrative:
    """Human-readable episode summary."""
    episode_id: str
    title: str
    summary: str
    time_range: str
    duration_days: int
    key_participants: List[Dict[str, Any]]
    key_outcomes: List[Dict[str, Any]]
    follow_ups: List[Dict[str, Any]]
    event_count: int
    main_topics: List[str]
    generated_at: datetime = field(default_factory=datetime.utcnow)


class EpisodeNarrativeService:
    """
    Converts detected episodes into engaging narratives.
    
    Takes the Episode nodes created by TemporalIndexer and generates
    human-readable summaries that tell the story of what happened.
    """
    
    def __init__(
        self,
        config: Config,
        graph_manager: KnowledgeGraphManager,
        llm_factory: Optional[Any] = None
    ):
        self.config = config
        self.graph = graph_manager
        self.llm_factory = llm_factory
        
        # LLM client for narrative synthesis (lazy loaded)
        self._llm = None
    
    async def generate_episode_summary(
        self,
        episode_id: str
    ) -> Optional[EpisodeNarrative]:
        """
        Generate a narrative summary for a single episode.
        
        Args:
            episode_id: Episode node ID
            
        Returns:
            EpisodeNarrative with full summary and details
        """
        try:
            # Get episode node
            episode = await self._get_episode(episode_id)
            if not episode:
                return None
            
            # Gather all episode data
            events = await self._get_episode_events(episode_id)
            participants = await self._get_episode_participants(episode_id)
            outcomes = await self._get_episode_outcomes(episode_id, events)
            follow_ups = await self._get_episode_followups(episode_id, events)
            topics = await self._get_episode_topics(episode_id)
            
            # Calculate time range
            start_time = episode.get("start_time", "")
            end_time = episode.get("end_time", "")
            time_range = self._format_time_range(start_time, end_time)
            duration_days = self._calculate_duration_days(start_time, end_time)
            
            # Generate summary
            summary = await self._llm_synthesize(
                episode=episode,
                events=events,
                participants=participants,
                topics=topics
            )
            
            return EpisodeNarrative(
                episode_id=episode_id,
                title=episode.get("name", "Untitled Episode"),
                summary=summary,
                time_range=time_range,
                duration_days=duration_days,
                key_participants=participants[:MAX_PARTICIPANTS],
                key_outcomes=outcomes[:MAX_OUTCOMES],
                follow_ups=follow_ups[:MAX_FOLLOWUPS],
                event_count=len(events),
                main_topics=topics[:5]
            )
            
        except Exception as e:
            logger.error(f"[EpisodeNarrative] Summary generation failed: {e}")
            return None
    
    async def get_user_life_story(
        self,
        user_id: int,
        period: str = "week"  # week, month
    ) -> str:
        """
        Generate a "life story" summary for a time period.
        
        Returns a narrative like:
        "This week you focused on 3 main areas:
        1. Project Launch (12 emails, 2 meetings with Marketing)
        2. Team Hiring (4 interviews, 2 offers extended)
        3. Budget Planning (collaborated with Finance on Q1 forecast)
        
        Key wins: Hired 2 engineers, finalized launch date.
        Open items: Follow up with Sarah on budget approval."
        """
        try:
            # Calculate date range
            now = datetime.utcnow()
            if period == "week":
                start_date = now - timedelta(days=7)
                period_label = "this week"
            elif period == "month":
                start_date = now - timedelta(days=30)
                period_label = "this month"
            else:
                start_date = now - timedelta(days=7)
                period_label = "this week"
            
            # Get episodes in this period
            episodes = await self._get_episodes_in_range(
                user_id, 
                start_date.isoformat(), 
                now.isoformat()
            )
            
            if not episodes:
                # Fallback to activity summary without episodes
                return await self._generate_period_activity_summary(
                    user_id, start_date, now, period_label
                )
            
            # Generate life story from episodes
            story_parts = [f"**{period_label.title()} Summary**\n"]
            
            # Main focus areas (episodes)
            if episodes:
                story_parts.append(f"You focused on {len(episodes)} main areas:\n")
                for i, episode in enumerate(episodes[:5], 1):
                    name = episode.get("name", "Unnamed activity").replace("Episode: ", "")
                    event_count = episode.get("event_count", 0)
                    story_parts.append(f"{i}. **{name}** ({event_count} events)")
            
            story_parts.append("")
            
            # Get key outcomes across all episodes
            all_outcomes = []
            all_followups = []
            
            for episode in episodes[:3]:
                episode_id = episode.get("id")
                if episode_id:
                    events = await self._get_episode_events(episode_id)
                    outcomes = await self._get_episode_outcomes(episode_id, events)
                    followups = await self._get_episode_followups(episode_id, events)
                    all_outcomes.extend(outcomes)
                    all_followups.extend(followups)
            
            # Key wins
            if all_outcomes:
                story_parts.append("**Key accomplishments:**")
                for outcome in all_outcomes[:3]:
                    story_parts.append(f"- {outcome.get('description', outcome.get('title', 'Completed item'))}")
                story_parts.append("")
            
            # Open items
            if all_followups:
                story_parts.append("**Open items:**")
                for followup in all_followups[:3]:
                    story_parts.append(f"- {followup.get('description', followup.get('title', 'Pending item'))}")
            
            return "\n".join(story_parts)
            
        except Exception as e:
            logger.error(f"[EpisodeNarrative] Life story generation failed: {e}")
            return f"Unable to generate {period} summary."
    
    async def _get_episode(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Get episode node data."""
        try:
            query = """
            FOR e IN Episode
                FILTER e.id == @id
                RETURN {
                    id: e.id,
                    name: e.name,
                    description: e.description,
                    start_time: e.start_time,
                    end_time: e.end_time,
                    event_count: e.event_count,
                    significance: e.significance
                }
            """
            result = await self.graph.execute_query(query, {"id": episode_id})
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Episode lookup failed: {e}")
            return None
    
    async def _get_episode_events(
        self,
        episode_id: str
    ) -> List[Dict[str, Any]]:
        """Get all events that occurred during an episode."""
        try:
            # Get episode time range
            episode = await self._get_episode(episode_id)
            if not episode:
                return []
            
            start_time = episode.get("start_time", "")
            end_time = episode.get("end_time", "")
            
            query = """
            FOR tb IN TimeBlock
                FILTER tb.start_time >= @start AND tb.start_time <= @end
                FOR e IN INBOUND tb OCCURRED_DURING
                    SORT e.timestamp
                    LIMIT @limit
                    RETURN {
                        id: e.id,
                        type: e.node_type,
                        title: NOT_NULL(e.subject, e.title, e.text),
                        timestamp: e.timestamp,
                        source: e.source
                    }
            """
            
            result = await self.graph.execute_query(query, {
                "start": start_time,
                "end": end_time,
                "limit": MAX_EVENTS_FOR_SUMMARY
            })
            
            return result or []
            
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Events query failed: {e}")
            return []
    
    async def _get_episode_participants(
        self,
        episode_id: str
    ) -> List[Dict[str, Any]]:
        """Get key people involved in an episode."""
        try:
            episode = await self._get_episode(episode_id)
            if not episode:
                return []
            
            start_time = episode.get("start_time", "")
            end_time = episode.get("end_time", "")
            
            query = """
            FOR tb IN TimeBlock
                FILTER tb.start_time >= @start AND tb.start_time <= @end
                FOR e IN INBOUND tb OCCURRED_DURING
                    FOR p IN ANY e FROM, TO, CC, HAS_ATTENDEE, ASSIGNED_TO, MENTIONS
                        COLLECT name = p.name, email = p.email, id = p.id WITH COUNT INTO interaction_count
                        SORT interaction_count DESC
                        LIMIT @limit
                        RETURN { name, email, id, interaction_count }
            """
            
            result = await self.graph.execute_query(query, {
                "start": start_time,
                "end": end_time,
                "limit": MAX_PARTICIPANTS
            })
            
            return result or []
            
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Participants query failed: {e}")
            return []
    
    async def _get_episode_outcomes(
        self,
        episode_id: str,
        events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Identify outcomes from an episode.
        
        Outcomes include:
        - Tasks completed during the episode
        - Decisions made (inferred from keywords)
        - Documents created
        """
        outcomes = []
        
        try:
            episode = await self._get_episode(episode_id)
            if not episode:
                return []
            
            start_time = episode.get("start_time", "")
            end_time = episode.get("end_time", "")
            
            # Find completed tasks
            task_query = """
            FOR t IN ActionItem
                FILTER t.completed_at >= @start AND t.completed_at <= @end
                LIMIT 5
                RETURN { id: t.id, title: t.title, type: 'task_completed' }
            """
            
            tasks = await self.graph.execute_query(task_query, {
                "start": start_time,
                "end": end_time
            })
            
            for task in tasks or []:
                outcomes.append({
                    "type": "task_completed",
                    "title": task.get("title", "Task"),
                    "description": f"Completed: {task.get('title', 'Task')}"
                })
            
            # Find documents created
            doc_query = """
            FOR d IN Document
                FILTER d.created_at >= @start AND d.created_at <= @end
                LIMIT 3
                RETURN { id: d.id, title: d.title, type: 'document_created' }
            """
            
            docs = await self.graph.execute_query(doc_query, {
                "start": start_time,
                "end": end_time
            })
            
            for doc in docs or []:
                outcomes.append({
                    "type": "document_created",
                    "title": doc.get("title", "Document"),
                    "description": f"Created: {doc.get('title', 'Document')}"
                })
            
            # Infer decisions from event content (simple keyword matching)
            decision_keywords = ["decided", "agreed", "approved", "confirmed", "finalized"]
            for event in events[:20]:
                title = event.get("title", "").lower()
                if any(kw in title for kw in decision_keywords):
                    outcomes.append({
                        "type": "decision",
                        "title": event.get("title", "Decision"),
                        "description": f"Decision: {event.get('title', '')}"
                    })
            
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Outcomes detection failed: {e}")
        
        return outcomes[:MAX_OUTCOMES]
    
    async def _get_episode_followups(
        self,
        episode_id: str,
        events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Identify pending follow-ups from an episode.
        
        Follow-ups include:
        - Tasks created but not completed
        - Commitments mentioned in communications
        - Open questions
        """
        followups = []
        
        try:
            episode = await self._get_episode(episode_id)
            if not episode:
                return []
            
            start_time = episode.get("start_time", "")
            end_time = episode.get("end_time", "")
            
            # Find pending tasks created during episode
            task_query = """
            FOR t IN ActionItem
                FILTER t.created_at >= @start AND t.created_at <= @end
                  AND (t.status == null OR t.status IN ['pending', 'in_progress'])
                LIMIT 5
                RETURN { id: t.id, title: t.title, due_date: t.due_date }
            """
            
            tasks = await self.graph.execute_query(task_query, {
                "start": start_time,
                "end": end_time
            })
            
            for task in tasks or []:
                followups.append({
                    "type": "pending_task",
                    "title": task.get("title", "Task"),
                    "description": f"Follow up: {task.get('title', 'Pending task')}",
                    "due_date": task.get("due_date")
                })
            
            # Infer follow-ups from event content
            followup_keywords = ["follow up", "next steps", "action item", "to do", "will send"]
            for event in events[:20]:
                title = event.get("title", "").lower()
                if any(kw in title for kw in followup_keywords):
                    followups.append({
                        "type": "inferred",
                        "title": event.get("title", "Follow-up"),
                        "description": f"Follow up from: {event.get('title', '')[:50]}"
                    })
            
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Followups detection failed: {e}")
        
        return followups[:MAX_FOLLOWUPS]
    
    async def _get_episode_topics(self, episode_id: str) -> List[str]:
        """Get topics associated with an episode."""
        try:
            query = """
            FOR e IN Episode
                FILTER e.id == @id
                FOR t IN INBOUND e ACTIVE_DURING
                    # Wait, check schema. Is it Topic -> Episode or Episode -> Topic?
                    # The original was (t:Topic)-[:ACTIVE_DURING]->(e:Episode)
                    RETURN t.name
            """
            
            # Re-verifying schema for Topics: (Topic)-[:ACTIVE_DURING]->(Episode)
            query = """
            FOR t IN Topic
                FOR e IN OUTBOUND t ACTIVE_DURING
                    FILTER e.id == @id
                    RETURN t.name
            """
            
            result = await self.graph.execute_query(query, {"id": episode_id})
            return [r.get("name") for r in result or [] if r.get("name")]
            
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Topics query failed: {e}")
            return []
    
    async def _get_episodes_in_range(
        self,
        user_id: int,
        start_time: str,
        end_time: str
    ) -> List[Dict[str, Any]]:
        """Get episodes in a date range."""
        try:
            query = """
            FOR e IN Episode
                FILTER e.user_id == @user_id
                  AND e.start_time >= @start
                  AND e.start_time <= @end
                SORT e.event_count DESC
                RETURN {
                    id: e.id,
                    name: e.name,
                    event_count: e.event_count,
                    start_time: e.start_time,
                    end_time: e.end_time
                }
            """
            
            result = await self.graph.execute_query(query, {
                "user_id": user_id,
                "start": start_time,
                "end": end_time
            })
            
            return result or []
            
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Episodes query failed: {e}")
            return []
    
    async def _generate_period_activity_summary(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        period_label: str
    ) -> str:
        """Generate activity summary when no episodes are available."""
        try:
            # Get activity counts by type
            query = """
            FOR tb IN TimeBlock
                FILTER tb.user_id == @user_id
                  AND tb.start_time >= @start
                  AND tb.start_time <= @end
                FOR e IN INBOUND tb OCCURRED_DURING
                    COLLECT type = e.node_type WITH COUNT INTO count
                    SORT count DESC
                    RETURN { type, count }
            """
            
            result = await self.graph.execute_query(query, {
                "user_id": user_id,
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            })
            
            if not result:
                return f"No significant activity recorded {period_label}."
            
            parts = [f"**{period_label.title()} Activity:**\n"]
            
            for row in result:
                content_type = row.get("type", "item")
                count = row.get("count", 0)
                type_name = {
                    "Email": "emails",
                    "Message": "messages",
                    "CalendarEvent": "meetings",
                    "Task": "tasks",
                    "Document": "documents"
                }.get(content_type, f"{content_type}s")
                parts.append(f"- {count} {type_name}")
            
            return "\n".join(parts)
            
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Activity summary failed: {e}")
            return f"Unable to generate activity summary for {period_label}."
    
    async def _llm_synthesize(
        self,
        episode: Dict[str, Any],
        events: List[Dict[str, Any]],
        participants: List[Dict[str, Any]],
        topics: List[str]
    ) -> str:
        """
        Use LLM to synthesize a narrative summary.
        
        Falls back to template-based summary if LLM is not available.
        """
        # Prepare context for LLM
        name = episode.get("name", "").replace("Episode: ", "")
        event_count = len(events)
        participant_names = [p.get("name", "Unknown") for p in participants[:3]]
        topic_list = ", ".join(topics[:3]) if topics else "various topics"
        
        # Calculate event type breakdown
        type_counts: Dict[str, int] = {}
        for event in events:
            event_type = event.get("type", "event")
            type_counts[event_type] = type_counts.get(event_type, 0) + 1
        
        type_summary = ", ".join(
            f"{count} {t.lower()}s" 
            for t, count in sorted(type_counts.items(), key=lambda x: -x[1])[:3]
        )
        
        # If we have an LLM, use it for synthesis
        if self.llm_factory:
            try:
                from src.ai.llm_factory import LLMFactory
                if self._llm is None:
                    self._llm = LLMFactory.create_llm(self.config, model_tier="fast")
                
                prompt = f"""Summarize this work episode in 2-3 sentences:
                
Topic: {name}
Duration: {episode.get('start_time', '')} to {episode.get('end_time', '')}
Events: {event_count} total ({type_summary})
Key People: {', '.join(participant_names) if participant_names else 'Various collaborators'}
Topics: {topic_list}

Write a brief, natural summary of what happened during this period."""

                response = await self._llm.ainvoke(prompt)
                return response.content if hasattr(response, 'content') else str(response)
                
            except Exception as e:
                logger.debug(f"[EpisodeNarrative] LLM synthesis failed: {e}")
        
        # Fallback to template-based summary
        participants_str = (
            f"Key participants: {', '.join(participant_names)}. " 
            if participant_names else ""
        )
        
        return (
            f"This episode focused on {name}, with {event_count} events "
            f"({type_summary}). {participants_str}"
            f"Main topics discussed: {topic_list}."
        )
    
    def _format_time_range(self, start_time: str, end_time: str) -> str:
        """Format time range for display."""
        try:
            start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            
            if start.date() == end.date():
                return start.strftime("%B %d, %Y")
            else:
                return f"{start.strftime('%B %d')} - {end.strftime('%B %d, %Y')}"
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Failed to format time range: {e}")
            return f"{start_time} to {end_time}"
    
    def _calculate_duration_days(self, start_time: str, end_time: str) -> int:
        """Calculate episode duration in days."""
        try:
            start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            return max(1, (end - start).days)
        except Exception as e:
            logger.debug(f"[EpisodeNarrative] Failed to calculate duration: {e}")
            return 1


# Global instance management
_episode_narrative: Optional[EpisodeNarrativeService] = None


def get_episode_narrative() -> Optional[EpisodeNarrativeService]:
    """Get the global episode narrative service."""
    return _episode_narrative


def init_episode_narrative(
    config: Config,
    graph_manager: KnowledgeGraphManager,
    llm_factory: Optional[Any] = None
) -> EpisodeNarrativeService:
    """Initialize and return the global episode narrative service."""
    global _episode_narrative
    _episode_narrative = EpisodeNarrativeService(config, graph_manager, llm_factory)
    logger.info("[EpisodeNarrativeService] Initialized")
    return _episode_narrative
