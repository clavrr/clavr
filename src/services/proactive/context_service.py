"""
Context Service (Proactive Intelligence)

Centralizes logic for gathering context about people, meetings, and topics.
Used by:
- API (Proactive Router)
- Ghost Agents (Meeting Prepper)
- CLI (clavr brief)
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database.models import User

logger = setup_logger(__name__)


class ProactiveContextService:
    """
    Production-quality context service with proper dependency injection.
    
    Can be initialized with dependencies (for testing/API) or will
    lazily initialize them (for Celery workers).
    """
    
    # Class-level cache for expensive services
    _graph_manager_instance = None
    _rag_engine_instance = None
    
    def __init__(
        self, 
        config: Config, 
        db_session=None,
        graph_manager=None,
        rag_engine=None,
        person_service=None
    ):
        """
        Initialize context service.
        
        Args:
            config: Application configuration
            db_session: Optional database session
            graph_manager: Optional KnowledgeGraphManager (injected for testing/API)
            rag_engine: Optional RAGEngine (injected for testing/API)
            person_service: Optional PersonUnificationService
        """
        self.config = config
        self.db = db_session
        
        # Accept injected dependencies or use lazy loading
        self._graph_manager = graph_manager
        self._rag_engine = rag_engine
        self._person_service = person_service
    
    @property
    def graph_manager(self):
        """Lazy-load graph manager with singleton pattern."""
        if self._graph_manager is not None:
            return self._graph_manager
        
        # Check class-level cache first
        if ProactiveContextService._graph_manager_instance is not None:
            return ProactiveContextService._graph_manager_instance
        
        # Initialize (expensive operation, done once)
        try:
            from src.services.indexing.graph import KnowledgeGraphManager
            ProactiveContextService._graph_manager_instance = KnowledgeGraphManager(
                backend="arangodb",
                config=self.config
            )
            logger.info("[ProactiveContextService] Initialized KnowledgeGraphManager (ArangoDB)")
            return ProactiveContextService._graph_manager_instance
        except Exception as e:
            logger.warning(f"[ProactiveContextService] Failed to init graph manager: {e}")
            return None

            return None
    
    @property
    def rag_engine(self):
        """Lazy-load RAG engine with singleton pattern."""
        if self._rag_engine is not None:
            return self._rag_engine
        
        if ProactiveContextService._rag_engine_instance is not None:
            return ProactiveContextService._rag_engine_instance
        
        try:
            from src.ai.rag import RAGEngine
            ProactiveContextService._rag_engine_instance = RAGEngine(self.config)
            logger.info("[ProactiveContextService] Initialized RAGEngine")
            return ProactiveContextService._rag_engine_instance
        except Exception as e:
            logger.warning(f"[ProactiveContextService] Failed to init RAG engine: {e}")
            return None
    
    @property
    def person_service(self):
        """Lazy-load person unification service."""
        if self._person_service is not None:
            return self._person_service
        
        if self.graph_manager is None:
            return None
        
        try:
            from src.ai.memory.person_unification import PersonUnificationService
            self._person_service = PersonUnificationService(self.config, self.graph_manager)
            return self._person_service
        except Exception as e:
            logger.warning(f"[ContextService] Failed to init person service: {e}")
            return None
        
    async def build_meeting_context(self, event: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """
        Build a comprehensive context dossier for a meeting.
        
        Args:
            event: Calendar event data
            user_id: User ID
            
        Returns:
            Rich context object with attendees, documents, topics
        """
        if not event:
            return {}
            
        summary = event.get('summary', 'Untitled')
        attendees = event.get('attendees', [])
        
        # Run context gathering concurrently for performance
        attendee_task = self.build_attendee_contexts(attendees, user_id)
        
        emails = [a.get('email') for a in attendees if a.get('email')]
        docs_task = self.find_related_documents(summary, emails, user_id)
        
        # Await both concurrently
        attendee_ctx, related_docs = await asyncio.gather(
            attendee_task, docs_task, return_exceptions=True
        )
        
        # Handle exceptions
        if isinstance(attendee_ctx, Exception):
            logger.error(f"[ContextService] Attendee context failed: {attendee_ctx}")
            attendee_ctx = []
        if isinstance(related_docs, Exception):
            logger.error(f"[ContextService] Document search failed: {related_docs}")
            related_docs = []
        
        # Extract topics from attendee context
        topics = self._extract_suggested_topics(attendee_ctx)
        
        return {
            'meeting_id': event.get('id'),
            'title': summary,
            'start_time': event.get('start', {}).get('dateTime'),
            'attendees': attendee_ctx,
            'related_documents': related_docs,
            'suggested_topics': topics,
            'generated_at': datetime.utcnow().isoformat()
        }

    async def build_attendee_contexts(self, attendees: List[Dict], user_id: int) -> List[Dict]:
        """
        Get rich context for each attendee from the Knowledge Graph.
        
        Uses ArangoDB queries for production performance.
        """
        contexts = []
        
        if not self.graph_manager:
            logger.warning("[ContextService] No graph manager available, returning basic context")
            return [
                {
                    'email': a.get('email', ''),
                    'name': a.get('displayName', a.get('email', '').split('@')[0]),
                    'history': [],
                    'topics': [],
                    'strength': 0.0,
                    'is_ooo': False
                }
                for a in attendees if a.get('email')
            ]
        
        for att in attendees:
            email = att.get('email', '').lower()
            if not email:
                continue
            
            ctx = {
                'email': email,
                'name': att.get('displayName', email.split('@')[0]),
                'history': [],
                'topics': [],
                'strength': 0.0,
                'is_ooo': False,
                'last_interaction': None
            }
            
            try:
                # AQL query for person and relationship data
                query = """
                LET person = FIRST(
                    FOR p IN Person
                        FILTER LOWER(p.email) == @email
                        RETURN p
                )
                
                LET relationship = person != null ? FIRST(
                    FOR u IN User
                        FILTER u.id == @user_id
                        FOR r IN COMMUNICATES_WITH
                            FILTER r._from == u._id AND r._to == person._id
                            RETURN r
                ) : null
                
                LET recent_emails = person != null ? (
                    FOR e IN Email
                        FILTER e.user_id == @user_id
                           AND (e.from_email == @email OR @email IN e.to_emails)
                        SORT e.date DESC
                        LIMIT 3
                        RETURN { subject: e.subject, date: e.date }
                ) : []
                
                RETURN {
                    person: person,
                    relationship: relationship,
                    recent_emails: recent_emails
                }
                """
                
                result = await self.graph_manager.execute_query(query, {
                    "email": email,
                    "user_id": user_id
                })
                
                if result and len(result) > 0:
                    data = result[0]
                    person = data.get("person") or {}
                    relationship = data.get("relationship") or {}
                    recent = data.get("recent_emails") or []
                    
                    if person:
                        ctx['name'] = person.get('name') or ctx['name']
                    
                    if relationship:
                        ctx['strength'] = relationship.get('strength', 0.0)
                        ctx['last_interaction'] = relationship.get('last_interaction')
                    
                    ctx['history'] = [
                        {'subject': e.get('subject'), 'date': e.get('date')}
                        for e in recent
                    ]
                
                # Check OOO status
                ctx['is_ooo'] = await self._check_ooo_status(email, user_id)
                
            except Exception as e:
                logger.debug(f"[ContextService] Graph lookup failed for {email}: {e}")
            
            contexts.append(ctx)
        
        return contexts
    
    async def _check_ooo_status(self, email: str, user_id: int) -> bool:
        """Check if person is marked as Out of Office."""
        if not self.graph_manager:
            return False
        
        try:
            query = """
            FOR p IN Person
                FILTER LOWER(p.email) == @email
                FOR s IN HAS_STATUS
                    FILTER s._from == p._id
                    FOR status IN Status
                        FILTER status._id == s._to
                           AND status.type IN ['OOO', 'out_of_office', 'vacation']
                           AND (status.end_date == null OR status.end_date >= DATE_NOW())
                        RETURN true
            """
            result = await self.graph_manager.execute_query(query, {"email": email.lower()})
            return len(result) > 0
        except Exception as e:
            logger.debug(f"OOO status check failed for {email}: {e}")
            return False

    async def find_related_documents(self, topic: str, emails: List[str], user_id: int) -> List[Dict]:
        """
        Find related documents using RAG semantic search.
        """
        if not self.rag_engine:
            logger.debug("[ContextService] No RAG engine available")
            return []
        
        docs = []
        try:
            # Construct query combining topic and key contacts
            query_parts = [topic]
            if emails:
                query_parts.extend(emails[:3])
            query = " ".join(query_parts)
            
            results = await self.rag_engine.search(
                query, 
                filters={'user_id': str(user_id)}, 
                top_k=5
            )
            
            for r in results or []:
                docs.append({
                    'title': r.get('title', 'Untitled'),
                    'type': r.get('node_type') or r.get('source', 'Document'),
                    'snippet': (r.get('text', '') or '')[:200],
                    'url': r.get('url') or r.get('source', ''),
                    'relevance': r.get('score', 0.0)
                })
                
        except Exception as e:
            logger.debug(f"[ContextService] Document search failed: {e}")
            
        return docs

    def _extract_suggested_topics(self, attendees: List[Dict]) -> List[str]:
        """Extract common topics from attendee context, ranked by frequency."""
        topics = {}
        for a in attendees:
            for t in a.get('topics', []):
                topics[t] = topics.get(t, 0) + 1
        return sorted(topics.keys(), key=lambda k: topics[k], reverse=True)[:5]
    
    async def generate_proactive_insight(self, user_id: int) -> Dict[str, Any]:
        """
        Use LLM to synthesize disparate data points into actionable insights.
        
        Example: "You haven't replied to Sarah's urgent email about Project X, 
        and you have a meeting with her boss in 2 hours."
        """
        now = datetime.utcnow()
        
        # 1. Gather raw context data (already have methods for this)
        briefing_data = await self.get_briefing_summary(user_id)
        
        # 2. Add extra signals (Recent unread high-signal items)
        # This could be more sophisticated, but we'll use a summary of unread emails for now
        unread_emails = []
        if self.graph_manager:
            try:
                query = """
                FOR e IN Email
                    FILTER e.user_id == @user_id 
                       AND e.is_read == false
                       AND e.date >= @since
                    SORT e.date DESC
                    LIMIT 5
                    RETURN { subject: e.subject, from: e.from_email, date: e.date }
                """
                since = (now - timedelta(days=3)).isoformat()
                unread_emails = await self.graph_manager.execute_query(query, {
                    "user_id": user_id,
                    "since": since
                })
            except Exception as e:
                logger.debug(f"Unread email query failed: {e}")
        
        # 3. LLM Synthesis
        try:
            from src.ai.llm_factory import LLMFactory
            from langchain_core.messages import SystemMessage, HumanMessage
            
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.5)
            
            system_prompt = (
                "You are an Executive Assistant synthesizing data into high-value proactive insights. "
                "Look for connections between unread emails, upcoming meetings, and overdue tasks. "
                "Output a single, concise 'Proactive Insight' that is most relevant right now. "
                "Keep it under 40 words."
            )
            
            context_str = f"Meetings Today: {briefing_data.get('meetings_today')}\n"
            context_str += f"Pending Tasks: {briefing_data.get('action_items')}\n"
            context_str += f"Recent Unread: {unread_emails}\n"
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Synthesize this context for user {user_id}:\n{context_str}")
            ]
            
            response = await asyncio.to_thread(llm.invoke, messages)
            insight = response.content.strip()
            
            return {
                "insight": insight,
                "data_points": {
                    "meetings_count": len(briefing_data.get('meetings_today', [])),
                    "tasks_count": len(briefing_data.get('action_items', [])),
                    "unread_count": len(unread_emails)
                },
                "generated_at": now.isoformat()
            }
            
        except Exception as e:
            logger.error(f"[ContextService] Insight generation failed: {e}")
            return {"insight": "Focus on your upcoming meetings and pending tasks.", "error": str(e)}

    async def get_briefing_summary(self, user_id: int) -> Dict[str, Any]:
        """
        Generate a morning briefing summary for a user.
        
        Returns:
            Briefing with calendar, tasks, insights
        """
        now = datetime.utcnow()
        today_end = now.replace(hour=23, minute=59, second=59)
        
        briefing = {
            "date": now.date().isoformat(),
            "meetings_today": [],
            "action_items": [],
            "insights": [],
            "generated_at": now.isoformat()
        }
        
        if not self.graph_manager:
            return briefing
        
        try:
            # Today's meetings (AQL)
            meeting_query = """
            FOR e IN CalendarEvent
                FILTER e.user_id == @user_id
                   AND e.start_time >= @day_start
                   AND e.start_time <= @day_end
                SORT e.start_time ASC
                RETURN {
                    id: e.id,
                    title: e.title,
                    start: e.start_time,
                    end: e.end_time,
                    attendees: LENGTH(e.attendees)
                }
            """
            meetings = await self.graph_manager.execute_query(meeting_query, {
                "user_id": user_id,
                "day_start": now.isoformat(),
                "day_end": today_end.isoformat()
            })
            briefing["meetings_today"] = meetings or []
            
            # High priority action items (AQL)
            task_query = """
            FOR t IN ActionItem
                FILTER t.user_id == @user_id
                   AND t.status != 'completed'
                   AND (t.priority == 'high' OR t.due_date <= @tomorrow)
                SORT t.priority, t.due_date ASC
                LIMIT 5
                RETURN {
                    id: t.id,
                    title: t.title,
                    due: t.due_date,
                    priority: t.priority
                }
            """
            tomorrow = (now + timedelta(days=1)).isoformat()
            tasks = await self.graph_manager.execute_query(task_query, {
                "user_id": user_id,
                "tomorrow": tomorrow
            })
            briefing["action_items"] = tasks or []
            
        except Exception as e:
            logger.error(f"[ContextService] Briefing generation failed: {e}")
        
        return briefing
