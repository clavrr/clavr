"""
Proactive Insights API

Endpoints for proactive intelligence delivery:
- On login: Show urgent insights (conflicts, OOO notifications, important updates)
- Before meetings: Surface attendee context (recent interactions, topics discussed)
- Periodic: Highlight important connections and suggestions

"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel

from api.dependencies import get_config
from api.auth import get_current_user_required
from src.database import get_db
from src.database.models import User
from src.utils.logger import setup_logger
from sqlalchemy.orm import Session

logger = setup_logger(__name__)

router = APIRouter(prefix="/proactive", tags=["proactive"])


# Response Models
class AttendeeContext(BaseModel):
    email: str
    name: str
    recent_interactions: List[Dict[str, Any]] = []
    topics_discussed: List[str] = []
    is_ooo: bool = False
    relationship_strength: float = 0.0


class MeetingPrepContext(BaseModel):
    meeting_id: str
    meeting_title: str
    start_time: str
    attendees: List[AttendeeContext] = []
    related_documents: List[Dict[str, Any]] = []
    suggested_topics: List[str] = []


class InsightResponse(BaseModel):
    id: str
    type: str
    title: str
    description: str
    urgency: str
    confidence: float
    timestamp: str
    source_node_id: Optional[str] = None


class ProactiveInsightsResponse(BaseModel):
    urgent: List[InsightResponse] = []
    meeting_prep: List[MeetingPrepContext] = []
    connections: List[Dict[str, Any]] = []
    suggestions: List[Dict[str, Any]] = []
    timestamp: str


@router.get("/insights", response_model=ProactiveInsightsResponse)
async def get_proactive_insights(
    hours_ahead: int = 4,
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config),
    db: Session = Depends(get_db)
):
    """
    Get proactive insights for the current user.
    
    Returns:
    - urgent: High-priority insights (conflicts, OOO, etc.)
    - meeting_prep: Context for upcoming meetings
    - connections: Notable connections to explore
    - suggestions: Actionable suggestions
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
        # 1. Get urgent insights from InsightService
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
        
        # 2. Get meeting preparation context
        meeting_preps = await _get_meeting_prep_context(
            user_id=user_id,
            hours_ahead=hours_ahead,
            config=config,
            db=db
        )
        response.meeting_prep = meeting_preps
        
        # 3. Get notable connections
        connections = await _get_notable_connections(user_id, config)
        response.connections = connections[:5]
        
        # 4. Get suggestions based on recent activity
        suggestions = await _get_actionable_suggestions(user_id, config)
        response.suggestions = suggestions[:3]
        
    except Exception as e:
        logger.error(f"[Proactive] Failed to get insights for user {user_id}: {e}")
    
    return response


@router.get("/meeting-prep/{meeting_id}")
async def get_meeting_preparation(
    meeting_id: str,
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config),
    db: Session = Depends(get_db)
):
    """
    Get detailed preparation context for a specific meeting.
    
    Returns comprehensive context including:
    - Attendee relationship history
    - Related documents and emails
    - Topics discussed with attendees
    - Suggested talking points
    """
    user_id = current_user.id
    
    try:
        # Get the meeting details
        from api.dependencies import AppState
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
        
        # Build detailed context
        context = await _build_detailed_meeting_context(
            event=event,
            user_id=user_id,
            config=config
        )
        
        return context
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Proactive] Meeting prep failed for {meeting_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare meeting context"
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


# Helper Functions

async def _get_meeting_prep_context(
    user_id: int,
    hours_ahead: int,
    config,
    db: Session
) -> List[MeetingPrepContext]:
    """Get meeting preparation context for upcoming meetings."""
    preps = []
    
    try:
        from api.dependencies import AppState
        from src.database.models import User, Session as DBSession
        from src.core.async_credential_provider import AsyncCredentialFactory
        
        # Get user for credential factory
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return []
        
        factory = AsyncCredentialFactory(config, db, user)
        calendar_service = await factory.get_calendar_service()
        
        if not calendar_service:
            return []
        
        # Get upcoming events
        upcoming = await calendar_service.get_upcoming_events(limit=5)
        
        # Filter to events within hours_ahead
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours_ahead)
        
        for event in upcoming or []:
            start_str = event.get('start', {}).get('dateTime', '')
            if not start_str:
                continue
            
            try:
                start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                if start_time.replace(tzinfo=None) > cutoff:
                    continue
            except:
                continue
            
            # Build context for this meeting
            attendee_contexts = await _build_attendee_contexts(
                attendees=event.get('attendees', []),
                user_id=user_id,
                config=config
            )
            
            # Get related documents
            related_docs = await _find_related_documents(
                meeting_title=event.get('summary', ''),
                attendee_emails=[a.get('email', '') for a in event.get('attendees', [])],
                user_id=user_id,
                config=config
            )
            
            prep = MeetingPrepContext(
                meeting_id=event.get('id', ''),
                meeting_title=event.get('summary', 'Untitled Meeting'),
                start_time=start_str,
                attendees=attendee_contexts,
                related_documents=related_docs[:5],
                suggested_topics=_extract_suggested_topics(attendee_contexts)
            )
            
            preps.append(prep)
        
    except Exception as e:
        logger.warning(f"[Proactive] Failed to get meeting prep: {e}")
    
    return preps


async def _build_attendee_contexts(
    attendees: List[Dict[str, Any]],
    user_id: int,
    config
) -> List[AttendeeContext]:
    """Build context for each meeting attendee."""
    contexts = []
    
    try:
        from api.dependencies import AppState
        from src.ai.memory.person_unification import PersonUnificationService
        
        graph_manager = AppState.get_graph_manager()
        if not graph_manager:
            return contexts
        
        person_service = PersonUnificationService(config, graph_manager)
        
        for attendee in attendees[:10]:  # Limit to 10 attendees
            email = attendee.get('email', '').lower()
            name = attendee.get('displayName', email.split('@')[0])
            
            ctx = AttendeeContext(
                email=email,
                name=name,
                recent_interactions=[],
                topics_discussed=[],
                is_ooo=False,
                relationship_strength=0.0
            )
            
            try:
                # Find person in graph
                person_ids = await person_service.find_all_identities(email=email)
                
                if person_ids:
                    person_id = person_ids[0].get('node', {}).get('id')
                    
                    if person_id:
                        # Get relationship summary
                        summary = await person_service.get_relationship_summary(
                            user_id=user_id,
                            person_id=person_id
                        )
                        
                        ctx.recent_interactions = summary.get('recent_interactions', [])[:3]
                        ctx.topics_discussed = summary.get('common_topics', [])[:5]
                        ctx.relationship_strength = summary.get('relationship_strength', 0.0)
                        
                        # Check OOO status
                        ctx.is_ooo = await _check_ooo_status(email, graph_manager)
                
            except Exception as e:
                logger.debug(f"[Proactive] Failed to get context for {email}: {e}")
            
            contexts.append(ctx)
    
    except Exception as e:
        logger.warning(f"[Proactive] Failed to build attendee contexts: {e}")
    
    return contexts


async def _check_ooo_status(email: str, graph_manager) -> bool:
    """Check if a person is out of office."""
    try:
        query = """
        MATCH (p:Person {email: $email})
        RETURN p.is_ooo as is_ooo
        """
        result = await graph_manager.execute_query(query, {'email': email.lower()})
        if result and len(result) > 0:
            return result[0].get('is_ooo', False)
    except:
        pass
    return False


async def _find_related_documents(
    meeting_title: str,
    attendee_emails: List[str],
    user_id: int,
    config
) -> List[Dict[str, Any]]:
    """Find documents/emails related to the meeting."""
    documents = []
    
    try:
        from api.dependencies import AppState
        
        rag_engine = AppState.get_rag_engine()
        if not rag_engine:
            return []
        
        # Search for content related to meeting title
        results = await rag_engine.search(
            query=meeting_title,
            filters={'user_id': str(user_id)},
            top_k=5
        )
        
        for result in results or []:
            documents.append({
                'id': result.get('id'),
                'type': result.get('node_type', 'Document'),
                'title': result.get('title') or result.get('subject', 'Untitled'),
                'source': result.get('source', 'unknown'),
                'timestamp': result.get('timestamp'),
                'relevance_score': result.get('score', 0.0)
            })
        
    except Exception as e:
        logger.debug(f"[Proactive] Document search failed: {e}")
    
    return documents


def _extract_suggested_topics(attendee_contexts: List[AttendeeContext]) -> List[str]:
    """Extract suggested discussion topics based on attendee history."""
    topic_counts = {}
    
    for ctx in attendee_contexts:
        for topic in ctx.topics_discussed:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    
    # Sort by frequency
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
    return [topic for topic, _ in sorted_topics[:5]]


async def _get_notable_connections(user_id: int, config) -> List[Dict[str, Any]]:
    """Get notable connections worth highlighting."""
    connections = []
    
    try:
        from api.dependencies import AppState
        
        graph_manager = AppState.get_graph_manager()
        if not graph_manager:
            return []
        
        # Find strong relationships that haven't been surfaced recently
        query = """
        MATCH (p1:Person)-[r:COMMUNICATES_WITH]->(p2:Person)
        WHERE p1.user_id = $user_id
          AND r.strength > 0.7
          AND (r.last_surfaced IS NULL OR r.last_surfaced < datetime() - duration('P7D'))
        RETURN p1.name as person1, p2.name as person2, 
               r.strength as strength, r.interaction_count as interactions
        ORDER BY r.strength DESC
        LIMIT 5
        """
        
        result = await graph_manager.execute_query(query, {'user_id': user_id})
        
        for row in result or []:
            connections.append({
                'type': 'strong_relationship',
                'title': f"Strong connection with {row.get('person2', 'Unknown')}",
                'description': f"You've had {row.get('interactions', 0)} interactions",
                'strength': row.get('strength', 0.5)
            })
        
    except Exception as e:
        logger.debug(f"[Proactive] Connection search failed: {e}")
    
    return connections


async def _get_actionable_suggestions(user_id: int, config) -> List[Dict[str, Any]]:
    """Get actionable suggestions based on graph analysis."""
    suggestions = []
    
    try:
        from api.dependencies import AppState
        
        graph_manager = AppState.get_graph_manager()
        if not graph_manager:
            return []
        
        # Find overdue tasks
        query = """
        MATCH (t:ActionItem)
        WHERE t.user_id = $user_id
          AND t.status = 'pending'
          AND t.due_date IS NOT NULL
          AND t.due_date < date()
        RETURN t.description as title, t.due_date as due_date, t.source as source
        ORDER BY t.due_date ASC
        LIMIT 3
        """
        
        result = await graph_manager.execute_query(query, {'user_id': user_id})
        
        for row in result or []:
            suggestions.append({
                'type': 'overdue_task',
                'title': row.get('title', 'Untitled task'),
                'description': f"This task was due on {row.get('due_date', 'Unknown')}",
                'action': 'complete_or_reschedule',
                'source': row.get('source', 'unknown')
            })
        
        # Find topics with high activity that might need attention
        query2 = """
        MATCH (t:Topic)-[:DISCUSSES]-(content)
        WHERE t.user_id = $user_id
        WITH t, count(content) as activity, max(content.timestamp) as last_activity
        WHERE activity > 5
          AND last_activity > datetime() - duration('P7D')
        RETURN t.name as topic, activity, last_activity
        ORDER BY activity DESC
        LIMIT 2
        """
        
        result2 = await graph_manager.execute_query(query2, {'user_id': user_id})
        
        for row in result2 or []:
            suggestions.append({
                'type': 'active_topic',
                'title': f"Active topic: {row.get('topic', 'Unknown')}",
                'description': f"This topic has {row.get('activity', 0)} recent mentions",
                'action': 'explore'
            })
        
    except Exception as e:
        logger.debug(f"[Proactive] Suggestion generation failed: {e}")
    
    return suggestions
