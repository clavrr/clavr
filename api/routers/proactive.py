"""
Proactive Insights API

Endpoints for proactive intelligence delivery:
- On login: Show urgent insights (conflicts, OOO notifications, important updates)
- Before meetings: Surface attendee context (recent interactions, topics discussed)

Now properly integrates with:
- ContextService: Data gathering and context building
- BriefingGenerator: LLM-powered narratives
- PerceptionAgent: Event filtering and signal detection
"""
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.dependencies import get_current_user_required, get_db, get_config
from src.database.models import User
from src.utils.logger import setup_logger
from sqlalchemy.orm import Session

logger = setup_logger(__name__)

router = APIRouter(prefix="/proactive", tags=["proactive"])


# ==================== Response Models ====================

class AttendeeContext(BaseModel):
    email: str
    name: str
    recent_interactions: List[Dict[str, Any]] = []
    topics_discussed: List[str] = []
    is_ooo: bool = False
    relationship_strength: float = 0.0
    last_interaction: Optional[str] = None


class MeetingPrepContext(BaseModel):
    meeting_id: str
    meeting_title: str
    start_time: str
    attendees: List[AttendeeContext] = []
    related_documents: List[Dict[str, Any]] = []
    suggested_topics: List[str] = []
    narrative: Optional[str] = None  # LLM-generated summary


class InsightResponse(BaseModel):
    id: str
    type: str
    title: str
    description: str
    urgency: str
    confidence: float
    timestamp: str
    source_node_id: Optional[str] = None


class TopicContextResponse(BaseModel):
    """360° cross-stack context for a topic/project - Semantic Sync."""
    topic: str
    summary: str
    key_facts: List[str] = []
    sources: Dict[str, Any] = {}
    people_involved: List[str] = []
    action_items: List[Dict[str, Any]] = []
    upcoming_events: List[Dict[str, Any]] = []
    generated_at: str


class ProactiveInsightsResponse(BaseModel):
    urgent: List[InsightResponse] = []
    meeting_prep: List[MeetingPrepContext] = []
    connections: List[Dict[str, Any]] = []
    suggestions: List[Dict[str, Any]] = []
    briefing_narrative: Optional[str] = None
    timestamp: str


# ==================== Service Factory ====================

class ProactiveServiceFactory:
    """Factory for lazily loading proactive services."""
    
    _context_service = None
    _briefing_generator = None
    _meeting_brief_generator = None
    
    @classmethod
    def get_context_service(cls, config, db=None):
        """Get or create ContextService singleton."""
        if cls._context_service is None:
            from src.services.proactive.context_service import ContextService
            cls._context_service = ContextService(config, db)
        return cls._context_service
    
    @classmethod
    def get_briefing_generator(cls, config):
        """Get or create BriefingGenerator singleton."""
        if cls._briefing_generator is None:
            try:
                from src.ai.autonomy import BriefingGenerator
                cls._briefing_generator = BriefingGenerator(config)
            except Exception as e:
                logger.warning(f"[Proactive] Could not init BriefingGenerator: {e}")
        return cls._briefing_generator
    
    @classmethod
    def get_meeting_brief_generator(cls, config):
        """Get or create MeetingBriefGenerator singleton."""
        if cls._meeting_brief_generator is None:
            try:
                from src.ai.autonomy import MeetingBriefGenerator
                cls._meeting_brief_generator = MeetingBriefGenerator(config)
            except Exception as e:
                logger.warning(f"[Proactive] Could not init MeetingBriefGenerator: {e}")
        return cls._meeting_brief_generator


# ==================== API Endpoints ====================

@router.get("/insights", response_model=ProactiveInsightsResponse)
async def get_proactive_insights(
    hours_ahead: int = 4,
    include_narrative: bool = False,
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config),
    db: Session = Depends(get_db)
):
    """
    Get proactive insights for the current user.
    
    Args:
        hours_ahead: Hours to look ahead for meetings
        include_narrative: Generate LLM briefing narrative
    
    Returns:
        - urgent: High-priority insights (conflicts, OOO, etc.)
        - meeting_prep: Context for upcoming meetings
        - connections: Notable connections to explore
        - suggestions: Actionable suggestions
        - briefing_narrative: LLM-generated morning briefing (optional)
    """
    user_id = current_user.id
    
    response = ProactiveInsightsResponse(
        urgent=[],
        meeting_prep=[],
        connections=[],
        suggestions=[],
        timestamp=datetime.utcnow().isoformat()
    )
    
    try:
        context_service = ProactiveServiceFactory.get_context_service(config, db)
        
        # 1. Get urgent insights from InsightService
        await _gather_urgent_insights(response, user_id)
        
        # 2. Get meeting preparation context via ContextService
        meeting_preps = await _gather_meeting_prep(
            context_service, user_id, hours_ahead, config, db, current_user
        )
        response.meeting_prep = meeting_preps
        
        # 3. Get notable connections via ContextService
        response.connections = await _gather_connections(context_service, user_id)
        
        # 4. Get suggestions via ContextService
        response.suggestions = await _gather_suggestions(context_service, user_id)
        
        # 5. Optional: Generate LLM narrative
        if include_narrative:
            response.briefing_narrative = await _generate_briefing_narrative(
                config, user_id, db, current_user
            )
        
    except Exception as e:
        logger.error(f"[Proactive] Failed to get insights for user {user_id}: {e}")
    
    return response


@router.get("/meeting-prep/{meeting_id}")
async def get_meeting_preparation(
    meeting_id: str,
    include_narrative: bool = True,
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config),
    db: Session = Depends(get_db)
):
    """
    Get detailed preparation context for a specific meeting.
    
    Uses:
    - ContextService for data gathering
    - MeetingBriefGenerator for LLM narrative
    """
    user_id = current_user.id
    
    try:
        from src.core.async_credential_provider import AsyncCredentialFactory
        
        factory = AsyncCredentialFactory(config, db, current_user)
        calendar_service = await factory.get_calendar_service()
        
        if not calendar_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Calendar service unavailable"
            )
        
        # Get the specific event
        event = await calendar_service.get_event(meeting_id)
        
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting not found"
            )
        
        # Build context via ContextService
        context_service = ProactiveServiceFactory.get_context_service(config, db)
        raw_context = await context_service.build_meeting_context(event, user_id)
        
        # Convert to response model
        attendees = [
            AttendeeContext(
                email=a.get('email', ''),
                name=a.get('name', ''),
                recent_interactions=a.get('history', []),
                topics_discussed=a.get('topics', []),
                is_ooo=a.get('is_ooo', False),
                relationship_strength=a.get('strength', 0.0),
                last_interaction=a.get('last_interaction')
            )
            for a in raw_context.get('attendees', [])
        ]
        
        result = MeetingPrepContext(
            meeting_id=meeting_id,
            meeting_title=event.get('summary', 'Untitled'),
            start_time=event.get('start', {}).get('dateTime', ''),
            attendees=attendees,
            related_documents=raw_context.get('related_documents', []),
            suggested_topics=raw_context.get('suggested_topics', [])
        )
        
        # Generate LLM narrative if requested
        if include_narrative:
            brief_generator = ProactiveServiceFactory.get_meeting_brief_generator(config)
            if brief_generator:
                try:
                    email_service = await factory.get_email_service()
                    from src.ai.memory.semantic_memory import SemanticMemory
                    semantic_memory = SemanticMemory(config)
                    
                    brief = await brief_generator.generate_brief(
                        user_id=user_id,
                        event_id=meeting_id,
                        calendar_service=calendar_service,
                        email_service=email_service,
                        semantic_memory=semantic_memory
                    )
                    result.narrative = brief.get('narrative') if isinstance(brief, dict) else str(brief)
                except Exception as e:
                    logger.warning(f"[Proactive] Narrative generation failed: {e}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Proactive] Meeting prep failed for {meeting_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare meeting context"
        )


@router.get("/briefing")
async def get_morning_briefing(
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config),
    db: Session = Depends(get_db)
):
    """
    Get a full morning briefing with LLM-generated narrative.
    
    Uses BriefingGenerator from src.ai.autonomy.
    """
    user_id = current_user.id
    
    try:
        from src.core.async_credential_provider import AsyncCredentialFactory
        
        factory = AsyncCredentialFactory(config, db, current_user)
        calendar_service = await factory.get_calendar_service()
        email_service = await factory.get_email_service()
        task_service = await factory.get_task_service()
        
        brief_generator = ProactiveServiceFactory.get_briefing_generator(config)
        
        if brief_generator:
            briefing = await brief_generator.generate_briefing(
                user_id=user_id,
                calendar_service=calendar_service,
                email_service=email_service,
                task_service=task_service,
                fast_mode=False
            )
            return briefing
        
        # Fallback to basic briefing via ContextService
        context_service = ProactiveServiceFactory.get_context_service(config, db)
        return await context_service.get_briefing_summary(user_id)
        
    except Exception as e:
        logger.error(f"[Proactive] Briefing generation failed for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate briefing"
        )


@router.get("/topic-context/{topic}", response_model=TopicContextResponse)
async def get_topic_context(
    topic: str,
    include_sources: Optional[str] = None,
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config),
    db: Session = Depends(get_db)
):
    """
    Semantic Sync: Get 360° cross-stack context for a topic/project.
    
    When a user mentions a project in Gmail, this endpoint pulls:
    - Linear: Issue status, sprint position
    - Gmail: Recent emails about this topic
    - Slack: Team discussions
    - Notion: Related documents
    - Drive: Related files
    - Calendar: Related events
    - Keep: Notes
    - Tasks: Related tasks
    
    This is the "Autonomous Glue" - not just finding data but synthesizing
    it into actionable intelligence.
    
    Args:
        topic: The topic/project to search for (e.g., "Project Alpha", "ENG-402")
        include_sources: Comma-separated list of sources (default: all)
    
    Returns:
        TopicContextResponse with synthesized 360° context
    """
    user_id = current_user.id
    
    try:
        from src.services.proactive.cross_stack_context import CrossStackContext
        from src.services.indexing.graph.manager import KnowledgeGraphManager
        from src.ai.rag.core.rag_engine import RAGEngine
        
        # Parse include_sources
        sources = None
        if include_sources:
            sources = [s.strip().lower() for s in include_sources.split(",")]
        
        # Initialize services
        graph_manager = KnowledgeGraphManager(config=config)
        rag_engine = RAGEngine(config)
        
        cross_stack = CrossStackContext(
            config=config,
            graph_manager=graph_manager,
            rag_engine=rag_engine
        )
        
        # Build topic context
        context = await cross_stack.build_topic_context(
            topic=topic,
            user_id=user_id,
            include_sources=sources
        )
        
        return TopicContextResponse(
            topic=context.get("topic", topic),
            summary=context.get("summary", ""),
            key_facts=context.get("key_facts", []),
            sources=context.get("sources", {}),
            people_involved=context.get("people_involved", []),
            action_items=context.get("action_items", []),
            upcoming_events=context.get("upcoming_events", []),
            generated_at=context.get("generated_at", datetime.utcnow().isoformat())
        )
        
    except Exception as e:
        logger.error(f"[Proactive] Topic context failed for '{topic}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build topic context: {str(e)}"
        )


@router.post("/insights/{insight_id}/dismiss")
async def dismiss_insight(
    insight_id: str,
    current_user: User = Depends(get_current_user_required)
):
    """Dismiss an insight so it won't be shown again."""
    from src.services.insights import get_insight_service
    
    insight_service = get_insight_service()
    if insight_service:
        await insight_service.dismiss_insight(insight_id, current_user.id)
    
    return {"status": "dismissed", "insight_id": insight_id}


@router.post("/insights/{insight_id}/shown")
async def mark_insight_shown(
    insight_id: str,
    current_user: User = Depends(get_current_user_required)
):
    """Mark an insight as shown (increments shown count)."""
    from src.services.insights import get_insight_service
    
    insight_service = get_insight_service()
    if insight_service:
        await insight_service.mark_insight_shown(insight_id)
    
    return {"status": "marked_shown", "insight_id": insight_id}


# ==================== Internal Helpers ====================

async def _gather_urgent_insights(response: ProactiveInsightsResponse, user_id: int):
    """Gather urgent insights from InsightService."""
    try:
        from src.services.insights import get_insight_service
        
        insight_service = get_insight_service()
        if insight_service:
            urgent_insights = await insight_service.get_urgent_insights(
                user_id=user_id,
                max_insights=5
            )
            
            for insight in urgent_insights:
                response.urgent.append(InsightResponse(
                    id=insight.get('id', ''),
                    type=insight.get('type', 'info'),
                    title=insight.get('title', 'Insight'),
                    description=insight.get('content', ''),
                    urgency=insight.get('urgency', 'medium'),
                    confidence=insight.get('confidence', 0.5),
                    timestamp=insight.get('timestamp', datetime.utcnow().isoformat()),
                    source_node_id=insight.get('source_node_id')
                ))
    except Exception as e:
        logger.warning(f"[Proactive] InsightService failed: {e}")


async def _gather_meeting_prep(
    context_service, 
    user_id: int, 
    hours_ahead: int, 
    config, 
    db: Session,
    current_user: User
) -> List[MeetingPrepContext]:
    """Gather meeting prep using ContextService."""
    preps = []
    
    try:
        from src.core.async_credential_provider import AsyncCredentialFactory
        
        factory = AsyncCredentialFactory(config, db, current_user)
        calendar_service = await factory.get_calendar_service()
        
        if not calendar_service:
            return preps
        
        # Get upcoming events
        now = datetime.utcnow()
        end_time = now + timedelta(hours=hours_ahead)
        
        events = await calendar_service.get_events(
            time_min=now.isoformat() + 'Z',
            time_max=end_time.isoformat() + 'Z',
            max_results=5
        )
        
        for event in (events or []):
            # Use ContextService for rich context
            ctx = await context_service.build_meeting_context(event, user_id)
            
            attendees = [
                AttendeeContext(
                    email=a.get('email', ''),
                    name=a.get('name', ''),
                    recent_interactions=a.get('history', []),
                    topics_discussed=a.get('topics', []),
                    is_ooo=a.get('is_ooo', False),
                    relationship_strength=a.get('strength', 0.0)
                )
                for a in ctx.get('attendees', [])
            ]
            
            prep = MeetingPrepContext(
                meeting_id=event.get('id', ''),
                meeting_title=event.get('summary', 'Untitled'),
                start_time=event.get('start', {}).get('dateTime', ''),
                attendees=attendees,
                related_documents=ctx.get('related_documents', []),
                suggested_topics=ctx.get('suggested_topics', [])
            )
            preps.append(prep)
            
    except Exception as e:
        logger.warning(f"[Proactive] Meeting prep failed: {e}")
    
    return preps


async def _gather_connections(context_service, user_id: int) -> List[Dict[str, Any]]:
    """Gather notable connections using graph queries (AQL)."""
    connections = []
    
    try:
        if not context_service.graph_manager:
            return []
        
        # AQL query for strong relationships
        query = """
        FOR r IN COMMUNICATES_WITH
            LET from_user = DOCUMENT(r._from)
            LET to_person = DOCUMENT(r._to)
            FILTER from_user.id == @user_id
               AND r.strength > 0.7
               AND (r.last_surfaced == null OR DATE_DIFF(r.last_surfaced, DATE_NOW(), 'd') > 7)
            SORT r.strength DESC
            LIMIT 5
            RETURN {
                person: to_person.name,
                email: to_person.email,
                strength: r.strength,
                interactions: r.interaction_count
            }
        """
        
        result = await context_service.graph_manager.execute_query(query, {'user_id': user_id})
        
        for row in result or []:
            connections.append({
                'type': 'strong_relationship',
                'title': f"Strong connection with {row.get('person', 'Unknown')}",
                'email': row.get('email'),
                'description': f"You've had {row.get('interactions', 0)} interactions",
                'strength': row.get('strength', 0.5)
            })
            
    except Exception as e:
        logger.debug(f"[Proactive] Connection search failed: {e}")
    
    return connections


async def _gather_suggestions(context_service, user_id: int) -> List[Dict[str, Any]]:
    """Gather actionable suggestions using graph queries (AQL)."""
    suggestions = []
    
    try:
        if not context_service.graph_manager:
            return []
        
        # AQL: Find overdue tasks
        overdue_query = """
        FOR t IN ActionItem
            FILTER t.user_id == @user_id
               AND t.status == 'pending'
               AND t.due_date != null
               AND t.due_date < DATE_ISO8601(DATE_NOW())
            SORT t.due_date ASC
            LIMIT 3
            RETURN {
                title: t.description,
                due_date: t.due_date,
                source: t.source
            }
        """
        
        result = await context_service.graph_manager.execute_query(overdue_query, {'user_id': user_id})
        
        for row in result or []:
            suggestions.append({
                'type': 'overdue_task',
                'title': row.get('title', 'Untitled task'),
                'description': f"This task was due on {row.get('due_date', 'Unknown')}",
                'action': 'complete_or_reschedule',
                'source': row.get('source', 'unknown')
            })
            
    except Exception as e:
        logger.debug(f"[Proactive] Suggestion generation failed: {e}")
    
    return suggestions


async def _generate_briefing_narrative(config, user_id: int, db: Session, current_user: User) -> Optional[str]:
    """Generate LLM briefing narrative using BriefingGenerator."""
    try:
        from src.core.async_credential_provider import AsyncCredentialFactory
        
        factory = AsyncCredentialFactory(config, db, current_user)
        calendar_service = await factory.get_calendar_service()
        email_service = await factory.get_email_service()
        task_service = await factory.get_task_service()
        
        brief_generator = ProactiveServiceFactory.get_briefing_generator(config)
        
        if brief_generator:
            result = await brief_generator.generate_briefing(
                user_id=user_id,
                calendar_service=calendar_service,
                email_service=email_service,
                task_service=task_service,
                fast_mode=True  # Fast mode for inline narrative
            )
            return result.get('narrative') if isinstance(result, dict) else str(result)
    except Exception as e:
        logger.warning(f"[Proactive] Briefing narrative failed: {e}")
    
    return None
