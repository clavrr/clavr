"""
Person Intelligence Service

Rich person context for every interaction, enabling agents to have
deeper understanding of relationships and communication patterns.

Features:
- Recent communication summary
- Open loops detection (pending emails, tasks)
- Communication patterns (response time, preferred channel, active hours)
- Relationship health scoring
- LLM-generated talking points
"""
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

# Configuration
RECENT_DAYS_DEFAULT = 30
OPEN_LOOP_DAYS = 7
MAX_TALKING_POINTS = 5


@dataclass
class CommunicationPatterns:
    """Communication patterns for a person."""
    avg_response_time_hours: Optional[float] = None
    preferred_channel: str = "unknown"
    active_hours: Dict[str, Any] = field(default_factory=dict)
    communication_frequency: str = "unknown"  # daily, weekly, monthly, rare


@dataclass
class PersonContext:
    """Rich context for a person across all connected apps."""
    person_id: str
    name: str
    emails: List[str]
    profile: Dict[str, Any]
    recent_summary: str
    open_loops: List[Dict[str, Any]]
    shared_interests: List[str]
    patterns: CommunicationPatterns
    relationship_health: float  # 0.0 - 1.0
    health_trend: str  # improving, stable, declining
    talking_points: List[str]
    last_updated: datetime = field(default_factory=datetime.utcnow)


class PersonIntelligenceService:
    """
    Rich person context for every interaction.
    
    Enables agents to understand:
    - What you've been discussing with this person
    - What's pending between you
    - How you typically communicate
    - Whether the relationship is healthy
    - What to talk about
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
        
        # Cache for person contexts
        self._context_cache: Dict[str, PersonContext] = {}
        self._cache_ttl = timedelta(minutes=30)
        self._cache_times: Dict[str, datetime] = {}
    
    async def get_person_context(
        self,
        person_id: str,
        user_id: int,
        force_refresh: bool = False
    ) -> Optional[PersonContext]:
        """
        Get comprehensive context for a person.
        
        Args:
            person_id: Person node ID or email
            user_id: User ID for context
            force_refresh: Force cache refresh
            
        Returns:
            PersonContext with all available intelligence
        """
        cache_key = f"{user_id}:{person_id}"
        
        # Check cache
        if not force_refresh and self._is_cached(cache_key):
            return self._context_cache[cache_key]
        
        try:
            # Get base profile
            profile = await self._get_base_profile(person_id)
            if not profile:
                return None
            
            name = profile.get("name", "Unknown")
            emails = profile.get("emails", [])
            
            # Gather all context in parallel
            import asyncio
            
            results = await asyncio.gather(
                self._get_recent_communication_summary(person_id, user_id),
                self._get_open_loops(person_id, user_id),
                self._get_shared_interests(person_id, user_id),
                self._get_communication_patterns(person_id, user_id),
                self._calc_relationship_health(person_id, user_id),
                self._generate_talking_points(person_id, user_id, name),
                return_exceptions=True
            )
            
            # Unpack results with defaults for failures
            recent_summary = results[0] if not isinstance(results[0], Exception) else ""
            open_loops = results[1] if not isinstance(results[1], Exception) else []
            shared_interests = results[2] if not isinstance(results[2], Exception) else []
            patterns = results[3] if not isinstance(results[3], Exception) else CommunicationPatterns()
            health_data = results[4] if not isinstance(results[4], Exception) else {"score": 0.5, "trend": "stable"}
            talking_points = results[5] if not isinstance(results[5], Exception) else []
            
            context = PersonContext(
                person_id=person_id,
                name=name,
                emails=emails,
                profile=profile,
                recent_summary=recent_summary,
                open_loops=open_loops,
                shared_interests=shared_interests,
                patterns=patterns,
                relationship_health=health_data.get("score", 0.5),
                health_trend=health_data.get("trend", "stable"),
                talking_points=talking_points
            )
            
            # Cache it
            self._context_cache[cache_key] = context
            self._cache_times[cache_key] = datetime.utcnow()
            
            return context
            
        except Exception as e:
            logger.error(f"[PersonIntelligence] Failed to get context for {person_id}: {e}")
            return None
    
    async def _get_base_profile(self, person_id: str) -> Optional[Dict[str, Any]]:
        """Get basic person profile from graph."""
        try:
            query = """
            FOR p IN Person
                FILTER p.id == @id OR p.email == @id
                LIMIT 1
                RETURN {
                    name: p.name,
                    email: p.email,
                    emails: p.emails,
                    source: p.source,
                    company: p.company,
                    title: p.title
                }
            """
            # Also check Contact collection
            if not person_id.startswith('p:'): # Basic check if it's not already a Person ID
                query = """
                FOR p IN Contact
                    FILTER p.id == @id OR p.email == @id
                    LIMIT 1
                    RETURN {
                        name: p.name,
                        email: p.email,
                        emails: p.emails,
                        source: p.source,
                        company: p.company,
                        title: p.title
                    }
                """
            result = await self.graph.execute_query(query, {"id": person_id})
            if result:
                row = result[0]
                emails = row.get("emails") or []
                if row.get("email") and row["email"] not in emails:
                    emails.append(row["email"])
                return {
                    "name": row.get("name", "Unknown"),
                    "emails": emails,
                    "source": row.get("source"),
                    "company": row.get("company"),
                    "title": row.get("title")
                }
            return None
        except Exception as e:
            logger.debug(f"[PersonIntelligence] Profile lookup failed: {e}")
            return None
    
    async def _get_recent_communication_summary(
        self,
        person_id: str,
        user_id: int,
        days: int = RECENT_DAYS_DEFAULT
    ) -> str:
        """
        Generate a summary of recent communication.
        
        Returns a brief summary like:
        "15 emails exchanged in the last 30 days, mostly about Project Alpha.
        Last contact was 2 days ago regarding the budget review."
        """
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            
            query = """
            FOR p IN Person
                FILTER p.id == @person_id OR p.email == @person_id
                FOR content, edge IN ANY p FROM, TO, CC, HAS_ATTENDEE, ASSIGNED_TO, MENTIONS
                    FILTER content.user_id == @user_id
                       AND content.timestamp >= @cutoff
                    COLLECT type = content.node_type WITH COUNT INTO count
                    AGGREGATE last = MAX(content.timestamp)
                    SORT count DESC
                    RETURN { type, count, last }
            """
            
            result = await self.graph.execute_query(query, {
                "person_id": person_id,
                "user_id": user_id,
                "cutoff": cutoff
            })
            
            if not result:
                return f"No recent communication in the last {days} days."
            
            # Build summary
            parts = []
            total_interactions = 0
            last_contact = None
            
            for row in result:
                content_type = row.get("type", "item")
                count = row.get("count", 0)
                last = row.get("last")
                
                total_interactions += count
                if last and (not last_contact or last > last_contact):
                    last_contact = last
                
                type_name = {
                    "Email": "emails",
                    "Message": "Slack messages",
                    "CalendarEvent": "meetings"
                }.get(content_type, f"{content_type}s")
                
                parts.append(f"{count} {type_name}")
            
            summary = f"{total_interactions} interactions in the last {days} days"
            if parts:
                summary += f" ({', '.join(parts[:3])})"
            
            if last_contact:
                try:
                    last_dt = datetime.fromisoformat(last_contact.replace("Z", "+00:00"))
                    days_ago = (datetime.utcnow() - last_dt.replace(tzinfo=None)).days
                    if days_ago == 0:
                        summary += ". Last contact was today."
                    elif days_ago == 1:
                        summary += ". Last contact was yesterday."
                    else:
                        summary += f". Last contact was {days_ago} days ago."
                except:
                    pass
            
            return summary
            
        except Exception as e:
            logger.debug(f"[PersonIntelligence] Communication summary failed: {e}")
            return ""
    
    async def _get_open_loops(
        self,
        person_id: str,
        user_id: int
    ) -> List[Dict[str, Any]]:
        """
        Find open items between user and person.
        
        Open loops include:
        - Unanswered emails from this person
        - Tasks assigned to/from this person
        - Pending follow-ups mentioned in communications
        """
        loops = []
        cutoff = (datetime.utcnow() - timedelta(days=OPEN_LOOP_DAYS)).isoformat()
        
        try:
            # Unanswered emails
            email_query = """
            FOR p IN Person
                FILTER p.id == @person_id OR p.email == @person_id
                FOR e IN OUTBOUND p SENT
                    FILTER e.user_id == @user_id
                       AND e.timestamp >= @cutoff
                    # Check if any reply exists
                    LET replies = (FOR r IN INBOUND e REPLIED_TO RETURN r)
                    FILTER LENGTH(replies) == 0
                    SORT e.timestamp DESC
                    LIMIT 5
                    RETURN { id: e.id, subject: e.subject, timestamp: e.timestamp }
            """
            
            email_result = await self.graph.execute_query(email_query, {
                "person_id": person_id,
                "user_id": user_id,
                "cutoff": cutoff
            })
            
            for row in email_result or []:
                loops.append({
                    "type": "unanswered_email",
                    "id": row.get("id"),
                    "description": f"Unanswered email: {row.get('subject', 'No subject')}",
                    "timestamp": row.get("timestamp"),
                    "actionable": True
                })
            
            # Pending tasks involving this person
            task_query = """
            FOR p IN Person
                FILTER p.id == @person_id OR p.email == @person_id
                FOR t IN ANY p ASSIGNED_TO, ASSIGNED_BY
                    FILTER t.user_id == @user_id
                       AND t.status IN ['pending', 'in_progress']
                    SORT t.due_date
                    LIMIT 5
                    RETURN { id: t.id, title: t.title, due_date: t.due_date }
            """
            
            task_result = await self.graph.execute_query(task_query, {
                "person_id": person_id,
                "user_id": user_id
            })
            
            for row in task_result or []:
                loops.append({
                    "type": "pending_task",
                    "id": row.get("id"),
                    "description": f"Pending task: {row.get('title', 'Untitled')}",
                    "due_date": row.get("due_date"),
                    "actionable": True
                })
            
        except Exception as e:
            logger.debug(f"[PersonIntelligence] Open loops query failed: {e}")
        
        return loops
    
    async def _get_shared_interests(
        self,
        person_id: str,
        user_id: int
    ) -> List[str]:
        """Get topics/projects shared with this person."""
        try:
            query = """
            FOR p IN Person
                FILTER p.id == @person_id OR p.email == @person_id
                FOR entity, edge IN ANY p DISCUSSES, WORKS_ON, PARTICIPATES_IN
                    FOR content IN ANY entity DISCUSSES, WORKS_ON, PARTICIPATES_IN
                        FILTER content.user_id == @user_id
                        COLLECT name = entity.name WITH COUNT INTO strength
                        SORT strength DESC
                        LIMIT 10
                        RETURN { name, strength }
            """
            
            result = await self.graph.execute_query(query, {
                "person_id": person_id,
                "user_id": user_id
            })
            
            return [row.get("name") for row in result or [] if row.get("name")]
            
        except Exception as e:
            logger.debug(f"[PersonIntelligence] Shared interests query failed: {e}")
            return []
    
    async def _get_communication_patterns(
        self,
        person_id: str,
        user_id: int
    ) -> CommunicationPatterns:
        """Analyze communication patterns with this person."""
        patterns = CommunicationPatterns()
        
        try:
            # Get channel distribution
            channel_query = """
            FOR p IN Person
                FILTER p.id == @person_id OR p.email == @person_id
                FOR content, edge IN ANY p FROM, TO, CC, HAS_ATTENDEE, ASSIGNED_TO, MENTIONS
                    FILTER content.user_id == @user_id
                    COLLECT type = content.node_type WITH COUNT INTO count
                    SORT count DESC
                    RETURN { type, count }
            """
            
            channel_result = await self.graph.execute_query(channel_query, {
                "person_id": person_id,
                "user_id": user_id
            })
            
            if channel_result:
                top_channel = channel_result[0].get("type", "Email")
                patterns.preferred_channel = {
                    "Email": "email",
                    "Message": "slack",
                    "CalendarEvent": "meetings"
                }.get(top_channel, "email")
                
                # Calculate frequency
                total = sum(r.get("count", 0) for r in channel_result)
                if total > 100:
                    patterns.communication_frequency = "daily"
                elif total > 30:
                    patterns.communication_frequency = "weekly"
                elif total > 5:
                    patterns.communication_frequency = "monthly"
                else:
                    patterns.communication_frequency = "rare"
            
            response_query = """
            FOR e1 IN Email
                FILTER e1.sender == @person_id OR e1.user_id == @user_id
                FOR e2 IN OUTBOUND e1 REPLIED_TO
                    FILTER e1.user_id == @user_id OR e2.user_id == @user_id
                    RETURN DATE_DIFF(e2.timestamp, e1.timestamp, "h")
            """
            # Take average of returned diffs in Python if desired, or use AQL
            response_query = """
            LET diffs = (
                FOR e1 IN Email
                    FILTER e1.sender == @person_id OR e1.user_id == @user_id
                    FOR e2 IN OUTBOUND e1 REPLIED_TO
                        FILTER e1.user_id == @user_id OR e2.user_id == @user_id
                        RETURN ABS(DATE_DIFF(e2.timestamp, e1.timestamp, "h"))
            )
            RETURN LENGTH(diffs) > 0 ? AVERAGE(diffs) : null
            """
            # Note: This query is simplified and may need adjustment for actual graph structure
            
        except Exception as e:
            logger.debug(f"[PersonIntelligence] Patterns analysis failed: {e}")
        
        return patterns
    
    async def _calc_relationship_health(
        self,
        person_id: str,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Calculate relationship health based on interaction patterns.
        
        Factors:
        - Recent activity (more = healthier)
        - Response rate (replies vs no-reply)
        - Positive sentiment indicators
        - Frequency trend
        """
        try:
            # Get interaction counts by week for last 8 weeks
            query = """
            FOR p IN Person
                FILTER p.id == @person_id OR p.email == @person_id
                FOR content, edge IN ANY p FROM, TO, CC, HAS_ATTENDEE, ASSIGNED_TO, MENTIONS
                    FILTER content.user_id == @user_id
                       AND content.timestamp >= @cutoff
                    COLLECT day = DATE_FORMAT(content.timestamp, "%Y-%m-%d") WITH COUNT INTO count
                    SORT day
                    RETURN { day, count }
            """
            
            cutoff = (datetime.utcnow() - timedelta(days=56)).isoformat()  # 8 weeks
            result = await self.graph.execute_query(query, {
                "person_id": person_id,
                "user_id": user_id,
                "cutoff": cutoff
            })
            
            if not result:
                return {"score": 0.5, "trend": "unknown"}
            
            # Calculate recent vs older activity
            total = len(result)
            recent_count = sum(
                1 for r in result 
                if r.get("day") and r["day"] > (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%d")
            )
            older_count = total - recent_count
            
            # Health score based on activity
            if total == 0:
                score = 0.3
            elif recent_count > older_count:
                score = min(0.9, 0.5 + (recent_count / 10))  # Growing relationship
            elif recent_count > 0:
                score = 0.6  # Active but not growing
            else:
                score = 0.4  # Declining
            
            # Determine trend
            if recent_count > older_count * 1.5:
                trend = "improving"
            elif recent_count < older_count * 0.5:
                trend = "declining"
            else:
                trend = "stable"
            
            return {"score": score, "trend": trend}
            
        except Exception as e:
            logger.debug(f"[PersonIntelligence] Health calculation failed: {e}")
            return {"score": 0.5, "trend": "unknown"}
    
    async def _generate_talking_points(
        self,
        person_id: str,
        user_id: int,
        person_name: str
    ) -> List[str]:
        """
        Generate suggested talking points for next interaction.
        
        Based on:
        - Open loops that need attention
        - Shared topics with recent activity
        - Upcoming events involving this person
        """
        talking_points = []
        
        try:
            # Get open loops for talking points
            open_loops = await self._get_open_loops(person_id, user_id)
            for loop in open_loops[:2]:
                if loop.get("type") == "unanswered_email":
                    talking_points.append(f"Follow up on: {loop['description'].replace('Unanswered email: ', '')}")
                elif loop.get("type") == "pending_task":
                    talking_points.append(f"Discuss: {loop['description'].replace('Pending task: ', '')}")
            
            # Get recent shared topics
            shared = await self._get_shared_interests(person_id, user_id)
            if shared:
                talking_points.append(f"Recent shared topic: {shared[0]}")
            
            # Check for upcoming meetings
            upcoming_query = """
            FOR e IN CalendarEvent
                FILTER e.user_id == @user_id
                   AND e.start_time >= @now
                   AND e.start_time <= @next_week
                FOR p IN OUTBOUND e HAS_ATTENDEE
                    FILTER p.id == @person_id OR p.email == @person_id
                    LIMIT 1
                    RETURN { title: e.title, start_time: e.start_time }
            """
            
            upcoming_result = await self.graph.execute_query(upcoming_query, {
                "person_id": person_id,
                "user_id": user_id,
                "now": datetime.utcnow().isoformat(),
                "next_week": (datetime.utcnow() + timedelta(days=7)).isoformat()
            })
            
            if upcoming_result:
                meeting = upcoming_result[0]
                talking_points.append(f"Upcoming meeting: {meeting.get('title', 'Meeting')}")
            
        except Exception as e:
            logger.debug(f"[PersonIntelligence] Talking points generation failed: {e}")
        
        return talking_points[:MAX_TALKING_POINTS]
    
    def _is_cached(self, cache_key: str) -> bool:
        """Check if context is cached and still valid."""
        if cache_key not in self._context_cache:
            return False
        cache_time = self._cache_times.get(cache_key)
        if not cache_time:
            return False
        return datetime.utcnow() - cache_time < self._cache_ttl
    
    def clear_cache(self, person_id: Optional[str] = None):
        """Clear context cache."""
        if person_id:
            keys_to_remove = [k for k in self._context_cache if person_id in k]
            for key in keys_to_remove:
                self._context_cache.pop(key, None)
                self._cache_times.pop(key, None)
        else:
            self._context_cache.clear()
            self._cache_times.clear()
    
    def format_for_prompt(self, context: PersonContext) -> str:
        """Format person context for inclusion in agent prompts."""
        if not context:
            return ""
        
        parts = [f"**About {context.name}:**"]
        
        if context.recent_summary:
            parts.append(f"- {context.recent_summary}")
        
        if context.open_loops:
            loop_count = len(context.open_loops)
            parts.append(f"- {loop_count} open item(s) to address")
        
        if context.shared_interests:
            interests = ", ".join(context.shared_interests[:3])
            parts.append(f"- Shared interests: {interests}")
        
        if context.patterns.preferred_channel != "unknown":
            parts.append(f"- Usually communicates via {context.patterns.preferred_channel}")
        
        if context.relationship_health < 0.4:
            parts.append("- ⚠️ Relationship may need attention (declining activity)")
        elif context.relationship_health > 0.7:
            parts.append("- ✓ Healthy, active relationship")
        
        if context.talking_points:
            parts.append(f"- Suggested topics: {', '.join(context.talking_points[:2])}")
        
        return "\n".join(parts)


# Global instance management
_person_intelligence: Optional[PersonIntelligenceService] = None


def get_person_intelligence() -> Optional[PersonIntelligenceService]:
    """Get the global person intelligence service."""
    return _person_intelligence


def init_person_intelligence(
    config: Config,
    graph_manager: KnowledgeGraphManager,
    llm_factory: Optional[Any] = None
) -> PersonIntelligenceService:
    """Initialize and return the global person intelligence service."""
    global _person_intelligence
    _person_intelligence = PersonIntelligenceService(config, graph_manager, llm_factory)
    logger.info("[PersonIntelligenceService] Initialized")
    return _person_intelligence
