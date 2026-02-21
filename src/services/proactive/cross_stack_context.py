"""
Cross-Stack Context Service

The "Contextual Bridge" 

When a user mentions a project/topic, this service pulls context from
ALL indexed sources to provide a 360-degree summary:
- Linear: Issue status, sprint position
- Gmail: Recent emails about topic
- Slack: Team discussions
- Notion: Relevant documents
- Drive: Related files

Now includes TTL-based caching to avoid redundant cross-stack queries.
"""
from src.utils.logger import setup_logger
from src.utils.config import Config
from src.ai.llm_factory import LLMFactory
from langchain_core.messages import SystemMessage, HumanMessage
import asyncio
import hashlib
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

logger = setup_logger(__name__)

# Default cache TTL: 5 minutes
CONTEXT_CACHE_TTL_SECONDS = 300


class CrossStackContext:
    """
    Service for building 360-degree context across all data sources.
    
    Used by:
    - MeetingPrepper: Context for meeting attendees
    - Proactive API: Rich context for user queries
    - Ghost Agents: Understanding relationships between data

    Now includes TTL-based caching to avoid redundant cross-stack queries
    for the same topic within a short time window.
    """
    
    def __init__(self, config: Config, graph_manager=None, rag_engine=None):
        """
        Initialize Cross-Stack Context service.
        
        Args:
            config: Application configuration
            graph_manager: Knowledge Graph manager
            rag_engine: RAG engine for semantic search
        """
        self.config = config
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = CONTEXT_CACHE_TTL_SECONDS

    @staticmethod
    def _cache_key(topic: str, user_id: int, sources: List[str]) -> str:
        """Generate a deterministic cache key from topic + user + sources."""
        raw = f"{user_id}:{topic.strip().lower()}:{','.join(sorted(sources))}"
        return hashlib.md5(raw.encode()).hexdigest()

    def invalidate_cache(
        self, topic: Optional[str] = None, user_id: Optional[int] = None
    ) -> int:
        """
        Invalidate cached context entries.
        If topic and user_id are given, invalidate matching entries.
        If neither is given, clear the entire cache.
        Returns count of invalidated entries.
        """
        if topic is None and user_id is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        to_remove = []
        for key, entry in self._cache.items():
            if (topic and entry.get("topic", "").lower() == topic.lower() and
                    (user_id is None or entry.get("user_id") == user_id)):
                to_remove.append(key)
            elif user_id and entry.get("user_id") == user_id and topic is None:
                to_remove.append(key)

        for key in to_remove:
            del self._cache[key]
        return len(to_remove)

    async def build_topic_context(
        self,
        topic: str,
        user_id: int,
        include_sources: Optional[List[str]] = None,
        bypass_cache: bool = False,
    ) -> Dict[str, Any]:
        """
        Build comprehensive context for a topic across all sources.
        
        Args:
            topic: Topic/project to gather context for (e.g., "Project Alpha")
            user_id: User ID
            include_sources: Optional list of sources to include
                             (default: all - linear, email, slack, notion, drive)
            bypass_cache: If True, always refresh from sources
        
        Returns:
            Dict with context from each source and synthesized summary
        """
        sources = include_sources or ["linear", "email", "slack", "notion", "drive", "calendar", "keep", "tasks"]

        # Check cache first
        cache_key = self._cache_key(topic, user_id, sources)
        if not bypass_cache:
            cached = self._cache.get(cache_key)
            if cached:
                cached_at = cached.get("_cached_at", 0)
                if time.time() - cached_at < self._cache_ttl:
                    logger.debug(
                        f"[CrossStack] Cache HIT for '{topic}' "
                        f"(age: {time.time() - cached_at:.0f}s)"
                    )
                    return cached
                else:
                    # Expired, remove stale entry
                    del self._cache[cache_key]

        context = {
            "topic": topic,
            "user_id": user_id,
            "generated_at": datetime.utcnow().isoformat(),
            "sources": {},
            "summary": "",
            "key_facts": [],
            "recent_activity": [],
            "people_involved": [],
            "action_items": [],
            "upcoming_events": []
        }
        
        try:
            # Graph-first fast path (#5): Use Topic nodes to pre-populate context
            # This is 10x faster than individual API calls when data is in the graph
            if self.graph_manager:
                try:
                    graph_context = await self._gather_graph_topic_context(topic, user_id)
                    if graph_context:
                        for source_name, items in graph_context.items():
                            if items and source_name not in context["sources"]:
                                context["sources"][source_name] = items
                        logger.info(
                            f"[CrossStack] Graph fast-path populated "
                            f"{len(graph_context)} sources for '{topic}'"
                        )
                except Exception as e:
                    logger.debug(f"[CrossStack] Graph fast-path failed: {e}")
            
            # Gather remaining context from each source (fills gaps)
            if "linear" in sources and "linear" not in context["sources"]:
                context["sources"]["linear"] = await self._get_linear_context(topic, user_id)
            
            if "email" in sources and "email" not in context["sources"]:
                context["sources"]["email"] = await self._get_email_context(topic, user_id)
            
            if "slack" in sources and "slack" not in context["sources"]:
                context["sources"]["slack"] = await self._get_slack_context(topic, user_id)
            
            if "notion" in sources and "notion" not in context["sources"]:
                context["sources"]["notion"] = await self._get_notion_context(topic, user_id)
            
            if "drive" in sources and "drive" not in context["sources"]:
                context["sources"]["drive"] = await self._get_drive_context(topic, user_id)
            
            if "calendar" in sources and "calendar" not in context["sources"]:
                context["sources"]["calendar"] = await self._get_calendar_context(topic, user_id)
            
            if "keep" in sources and "keep" not in context["sources"]:
                context["sources"]["keep"] = await self._get_keep_context(topic, user_id)
            
            if "tasks" in sources and "tasks" not in context["sources"]:
                context["sources"]["tasks"] = await self._get_tasks_context(topic, user_id)
            
            # Synthesize the context
            context = self._synthesize_context(context)
            
        except Exception as e:
            logger.error(f"[CrossStack] Failed to build context for '{topic}': {e}")
            context["error"] = str(e)
        
        # 3. Enhance with LLM Narrative Synthesis (The "Clavr Difference")
        context = await self._llm_synthesize_narrative(context)

        # Store in cache
        context["_cached_at"] = time.time()
        self._cache[cache_key] = context

        # Evict old entries if cache grows too large
        if len(self._cache) > 100:
            oldest_key = min(
                self._cache, key=lambda k: self._cache[k].get("_cached_at", 0)
            )
            del self._cache[oldest_key]
        
        return context
    
    async def _gather_graph_topic_context(
        self, topic: str, user_id: int
    ) -> Dict[str, Any]:
        """
        Use knowledge graph Topic nodes to pre-populate cross-app context.
        
        Queries: Topic → DISCUSSES ← [entities from multiple apps]
        Groups results by source app for direct insertion into context.
        """
        if not self.graph_manager:
            return {}
        
        aql = """
        FOR t IN Topic
            LET exact = LOWER(t.name) == LOWER(@topic)
            LET fuzzy = CONTAINS(LOWER(t.name), LOWER(@topic))
                      OR CONTAINS(LOWER(@topic), LOWER(t.name))
            LET keyword_match = LENGTH(
                FOR kw IN (t.keywords || [])
                    FILTER CONTAINS(LOWER(@topic), LOWER(kw))
                    RETURN 1
            ) > 0
            FILTER exact OR fuzzy OR keyword_match
            SORT exact DESC, fuzzy DESC
            LIMIT 3
            LET entities = (
                FOR v, e IN 1..2 INBOUND t GRAPH 'knowledge_graph'
                    SORT v.date DESC, v.start_time DESC, v.timestamp DESC
                    LIMIT 20
                    RETURN {
                        id: v._key,
                        collection: PARSE_IDENTIFIER(v).collection,
                        title: v.subject || v.title || v.name || "",
                        date: v.date || v.start_time || v.timestamp || "",
                        snippet: LEFT(v.body || v.content || v.description || "", 200),
                        source: v.source || PARSE_IDENTIFIER(v).collection
                    }
            )
            RETURN {topic_name: t.name, entities}
        """
        
        try:
            results = await self.graph_manager.execute_query(aql, {'topic': topic})
            if not results:
                return {}
            
            # Group by source app
            source_map = {
                'Email': 'email',
                'Message': 'slack',
                'CalendarEvent': 'calendar',
                'Document': 'drive',
                'LinearIssue': 'linear',
                'GoogleTask': 'tasks',
            }
            
            grouped: Dict[str, Any] = {}
            for topic_result in results:
                for entity in topic_result.get('entities', []):
                    collection = entity.get('collection', '')
                    source_key = source_map.get(collection)
                    if source_key and source_key not in grouped:
                        grouped[source_key] = {
                            'found': True,
                            'source': 'graph',
                            'items': [],
                        }
                    if source_key:
                        grouped[source_key].setdefault('items', []).append({
                            'title': entity.get('title', ''),
                            'date': entity.get('date', ''),
                            'snippet': entity.get('snippet', ''),
                        })
            
            return grouped
            
        except Exception as e:
            logger.debug(f"[CrossStack] Graph topic context query failed: {e}")
            return {}
    
    async def _get_linear_context(self, topic: str, user_id: int) -> Dict[str, Any]:
        """Get Linear issues related to topic."""
        result = {
            "found": False,
            "issues": [],
            "active_sprint_status": None
        }
        
        try:
            if not self.graph_manager:
                return result
            
            # Search for Linear issues matching topic (AQL)
            query = """
            FOR i IN LinearIssue
                FILTER i.user_id == @user_id
                   AND (CONTAINS(LOWER(i.title), LOWER(@topic)) OR CONTAINS(LOWER(i.description), LOWER(@topic)))
                SORT i.priority ASC
                LIMIT 10
                RETURN {
                    id: i.identifier,
                    title: i.title,
                    state: i.state,
                    priority: i.priority,
                    due_date: i.dueDate,
                    url: i.url
                }
            """
            
            issues = await self.graph_manager.execute_query(query, {
                "user_id": user_id,
                "topic": topic
            })
            
            if issues:
                result["found"] = True
                result["issues"] = [dict(i) for i in issues]
                
                # Calculate status summary
                states = [i.get("state") for i in issues if i.get("state")]
                if states:
                    in_progress = sum(1 for s in states if s == "In Progress")
                    done = sum(1 for s in states if s == "Done")
                    result["active_sprint_status"] = {
                        "total": len(issues),
                        "in_progress": in_progress,
                        "done": done,
                        "remaining": len(issues) - in_progress - done
                    }
            
        except Exception as e:
            logger.debug(f"[CrossStack] Linear context failed: {e}")
        
        return result
    
    async def _get_email_context(self, topic: str, user_id: int) -> Dict[str, Any]:
        """Get emails related to topic."""
        result = {
            "found": False,
            "recent_emails": [],
            "key_people": []
        }
        
        try:
            if not self.rag_engine:
                return result
            
            # Semantic search for relevant emails
            search_results = await self.rag_engine.search(
                query=f"{topic} email",
                filters={"user_id": str(user_id), "source": "gmail"},
                top_k=10
            )
            
            for r in search_results or []:
                result["recent_emails"].append({
                    "subject": r.get("title") or r.get("subject"),
                    "from": r.get("from"),
                    "date": r.get("timestamp"),
                    "snippet": r.get("text", "")[:200]
                })
            
            if result["recent_emails"]:
                result["found"] = True
                # Extract unique people
                people = set()
                for email in result["recent_emails"]:
                    if email.get("from"):
                        people.add(email["from"])
                result["key_people"] = list(people)[:5]
            
        except Exception as e:
            logger.debug(f"[CrossStack] Email context failed: {e}")
        
        return result
    
    async def _get_slack_context(self, topic: str, user_id: int) -> Dict[str, Any]:
        """Get Slack messages related to topic."""
        result = {
            "found": False,
            "recent_messages": [],
            "channels": []
        }
        
        try:
            if not self.rag_engine:
                return result
            
            search_results = await self.rag_engine.search(
                query=topic,
                filters={"user_id": str(user_id), "source": "slack"},
                top_k=10
            )
            
            channels = set()
            for r in search_results or []:
                channel = r.get("channel", "Unknown")
                channels.add(channel)
                result["recent_messages"].append({
                    "channel": channel,
                    "text": r.get("text", "")[:200],
                    "timestamp": r.get("timestamp"),
                    "user": r.get("user")
                })
            
            if result["recent_messages"]:
                result["found"] = True
                result["channels"] = list(channels)
            
        except Exception as e:
            logger.debug(f"[CrossStack] Slack context failed: {e}")
        
        return result
    
    async def _get_notion_context(self, topic: str, user_id: int) -> Dict[str, Any]:
        """Get Notion pages related to topic."""
        result = {
            "found": False,
            "pages": []
        }
        
        try:
            if not self.rag_engine:
                return result
            
            search_results = await self.rag_engine.search(
                query=topic,
                filters={"user_id": str(user_id), "source": "notion"},
                top_k=5
            )
            
            for r in search_results or []:
                result["pages"].append({
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "snippet": r.get("text", "")[:200]
                })
            
            if result["pages"]:
                result["found"] = True
            
        except Exception as e:
            logger.debug(f"[CrossStack] Notion context failed: {e}")
        
        return result
    
    async def _get_drive_context(self, topic: str, user_id: int) -> Dict[str, Any]:
        """Get Drive files related to topic."""
        result = {
            "found": False,
            "files": []
        }
        
        try:
            if not self.rag_engine:
                return result
            
            search_results = await self.rag_engine.search(
                query=topic,
                filters={"user_id": str(user_id), "source": "google_drive"},
                top_k=5
            )
            
            for r in search_results or []:
                result["files"].append({
                    "name": r.get("title"),
                    "type": r.get("mime_type", "document"),
                    "url": r.get("url"),
                    "modified": r.get("modified_time")
                })
            
            if result["files"]:
                result["found"] = True
            
        except Exception as e:
            logger.debug(f"[CrossStack] Drive context failed: {e}")
        
        return result
    
    async def _get_calendar_context(self, topic: str, user_id: int) -> Dict[str, Any]:
        """Get calendar events related to topic."""
        result = {
            "found": False,
            "upcoming_events": [],
            "past_events": []
        }
        
        try:
            if not self.graph_manager:
                return result
            
            now = datetime.utcnow()
            week_ahead = (now + timedelta(days=7)).isoformat()
            week_ago = (now - timedelta(days=7)).isoformat()
            
            # Search for calendar events matching topic (AQL)
            query = """
            FOR e IN CalendarEvent
                FILTER e.user_id == @user_id
                   AND (CONTAINS(LOWER(e.title), LOWER(@topic)) OR CONTAINS(LOWER(e.description), LOWER(@topic)))
                   AND e.start_time >= @week_ago
                   AND e.start_time <= @week_ahead
                SORT e.start_time ASC
                LIMIT 10
                RETURN {
                    id: e.id,
                    title: e.title,
                    start: e.start_time,
                    end: e.end_time,
                    attendees: e.attendees
                }
            """
            
            events = await self.graph_manager.execute_query(query, {
                "user_id": user_id,
                "topic": topic,
                "week_ago": week_ago,
                "week_ahead": week_ahead
            })
            
            for event in events or []:
                event_data = {
                    "id": event.get("id"),
                    "title": event.get("title"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "attendees": event.get("attendees", [])
                }
                
                # Check if past or upcoming
                try:
                    start_str = event.get("start")
                    if isinstance(start_str, str):
                        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start = start_str
                    
                    if start.replace(tzinfo=None) > now:
                        result["upcoming_events"].append(event_data)
                    else:
                        result["past_events"].append(event_data)
                except (ValueError, TypeError):
                    result["upcoming_events"].append(event_data)
            
            if result["upcoming_events"] or result["past_events"]:
                result["found"] = True
            
        except Exception as e:
            logger.debug(f"[CrossStack] Calendar context failed: {e}")
        
        return result
    
    async def _get_keep_context(self, topic: str, user_id: int) -> Dict[str, Any]:
        """Get Google Keep notes related to topic."""
        result = {
            "found": False,
            "notes": []
        }
        
        try:
            if not self.rag_engine:
                return result
            
            search_results = await self.rag_engine.search(
                query=topic,
                filters={"user_id": str(user_id), "source": "google_keep"},
                top_k=5
            )
            
            for r in search_results or []:
                result["notes"].append({
                    "title": r.get("title", "Untitled Note"),
                    "snippet": r.get("text", "")[:200],
                    "color": r.get("color"),
                    "pinned": r.get("pinned", False)
                })
            
            if result["notes"]:
                result["found"] = True
            
        except Exception as e:
            logger.debug(f"[CrossStack] Keep context failed: {e}")
        
        return result
    
    async def _get_tasks_context(self, topic: str, user_id: int) -> Dict[str, Any]:
        """Get Google Tasks related to topic."""
        result = {
            "found": False,
            "tasks": [],
            "completed": 0,
            "pending": 0
        }
        
        try:
            if not self.graph_manager:
                return result
            
            # Search for tasks matching topic (AQL)
            query = """
            FOR t IN GoogleTask
                FILTER t.user_id == @user_id
                   AND (CONTAINS(LOWER(t.title), LOWER(@topic)) OR CONTAINS(LOWER(t.notes), LOWER(@topic)))
                SORT t.due ASC
                LIMIT 10
                RETURN {
                    id: t.id,
                    title: t.title,
                    due: t.due,
                    status: t.status,
                    notes: t.notes
                }
            """
            
            tasks = await self.graph_manager.execute_query(query, {
                "user_id": user_id,
                "topic": topic
            })
            
            for task in tasks or []:
                status = task.get("status", "needsAction")
                result["tasks"].append({
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "due": task.get("due"),
                    "status": status,
                    "notes": task.get("notes", "")[:100]
                })
                
                if status == "completed":
                    result["completed"] += 1
                else:
                    result["pending"] += 1
            
            if result["tasks"]:
                result["found"] = True
            
        except Exception as e:
            logger.debug(f"[CrossStack] Tasks context failed: {e}")
        
        return result
    
    def _synthesize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize gathered context into actionable summary."""
        topic = context["topic"]
        sources = context["sources"]
        
        # Build summary
        summary_parts = []
        
        # Linear status
        linear = sources.get("linear", {})
        if linear.get("found"):
            status = linear.get("active_sprint_status", {})
            summary_parts.append(
                f"Linear: {status.get('total', 0)} issues "
                f"({status.get('in_progress', 0)} in progress)"
            )
            
            # Add high priority issues to action items
            for issue in linear.get("issues", [])[:3]:
                if issue.get("priority") in [1, 2]:
                    context["action_items"].append({
                        "source": "linear",
                        "title": issue.get("title"),
                        "url": issue.get("url")
                    })
        
        # Email activity
        email = sources.get("email", {})
        if email.get("found"):
            count = len(email.get("recent_emails", []))
            summary_parts.append(f"Email: {count} recent messages")
            
            # Add key people
            for person in email.get("key_people", []):
                if person not in context["people_involved"]:
                    context["people_involved"].append(person)
        
        # Slack activity
        slack = sources.get("slack", {})
        if slack.get("found"):
            channels = slack.get("channels", [])
            summary_parts.append(f"Slack: Active in {', '.join(channels[:3])}")
        
        # Documents
        notion = sources.get("notion", {})
        drive = sources.get("drive", {})
        doc_count = len(notion.get("pages", [])) + len(drive.get("files", []))
        if doc_count > 0:
            summary_parts.append(f"Documents: {doc_count} related files")
        
        # Calendar
        calendar = sources.get("calendar", {})
        if calendar.get("found"):
            upcoming = len(calendar.get("upcoming_events", []))
            past = len(calendar.get("past_events", []))
            if upcoming > 0:
                summary_parts.append(f"Calendar: {upcoming} upcoming events")
                # Add to upcoming events
                context["upcoming_events"] = calendar.get("upcoming_events", [])
            if past > 0:
                summary_parts.append(f"(+{past} past)")
        
        # Google Keep
        keep = sources.get("keep", {})
        if keep.get("found"):
            notes_count = len(keep.get("notes", []))
            summary_parts.append(f"Keep: {notes_count} notes")
        
        # Google Tasks
        tasks = sources.get("tasks", {})
        if tasks.get("found"):
            pending = tasks.get("pending", 0)
            completed = tasks.get("completed", 0)
            if pending > 0:
                summary_parts.append(f"Tasks: {pending} pending")
                # Add pending tasks to action items
                for task in tasks.get("tasks", []):
                    if task.get("status") != "completed":
                        context["action_items"].append({
                            "source": "google_tasks",
                            "title": task.get("title"),
                            "due": task.get("due")
                        })
        
        # Build final summary
        if summary_parts:
            context["summary"] = " | ".join(summary_parts)
        else:
            context["summary"] = f"No indexed data found for '{topic}'"
        
        # Add key facts
        context["key_facts"] = [
            f"Found in {sum(1 for s in sources.values() if s.get('found'))} sources",
            f"Involves {len(context['people_involved'])} people",
            f"{len(context['action_items'])} action items identified"
        ]
        
        return context
    
    async def get_person_context(
        self,
        email_or_name: str,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Get comprehensive context about a person across all sources.
        
        Used for meeting prep and relationship management.
        """
        context = {
            "person": email_or_name,
            "user_id": user_id,
            "emails": [],
            "slack_messages": [],
            "linear_issues": [],
            "last_interaction": None,
            "common_topics": [],
            "relationship_strength": 0.0
        }
        
        try:
            if self.graph_manager:
                # Get relationship data from graph (AQL with edge traversal)
                query = """
                FOR u IN User
                    FILTER u.id == @user_id
                    FOR p, r IN 1..1 OUTBOUND u COMMUNICATES_WITH
                        FILTER CONTAINS(LOWER(p.email), LOWER(@search)) OR CONTAINS(LOWER(p.name), LOWER(@search))
                        LIMIT 1
                        RETURN {
                            email: p.email,
                            name: p.name,
                            last_interaction: r.last_interaction,
                            strength: r.strength,
                            interactions: r.interaction_count
                        }
                """
                
                result = await self.graph_manager.execute_query(query, {
                    "user_id": user_id,
                    "search": email_or_name.lower()
                })
                
                if result:
                    person = result[0]
                    context["email"] = person.get("email")
                    context["name"] = person.get("name")
                    context["last_interaction"] = person.get("last_interaction")
                    context["relationship_strength"] = person.get("strength", 0.0)
            
            # Get recent content involving this person
            if self.rag_engine:
                results = await self.rag_engine.search(
                    query=email_or_name,
                    filters={"user_id": str(user_id)},
                    top_k=20
                )
                
                for r in results or []:
                    source = r.get("source", "unknown")
                    item = {
                        "text": r.get("text", "")[:200],
                        "timestamp": r.get("timestamp")
                    }
                    
                    if source == "gmail":
                        context["emails"].append(item)
                    elif source == "slack":
                        context["slack_messages"].append(item)
            
        except Exception as e:
            logger.error(f"[CrossStack] Person context failed: {e}")
        
        return context

    async def get_active_projects(self, user_id: int, limit: int = 3) -> List[str]:
        """
        Get names of currently active projects for a user based on graph activity.
        
        Heuristic: Projects that have been recently mentioned or have recent insights
        linked to them by the GraphObserver.
        """
        if not self.graph_manager:
            return []
            
        # AQL query to find projects with most recent activity or insights
        # We look for nodes linked to the Project node via ABOUT, RELATED_TO, or PART_OF
        # and sort by the most recent creation time among those links.
        query = """
        FOR p IN Project
            FILTER p.user_id == @user_id
            LET recent_activity = (
                FOR v, e IN 1..1 ANY p ABOUT, RELATED_TO, PART_OF, CONTAINS
                    SORT v.created_at DESC
                    LIMIT 10
                    RETURN v.created_at
            )
            FILTER LENGTH(recent_activity) > 0
            SORT FIRST(recent_activity) DESC
            LIMIT @limit
            RETURN p.name
        """
        
        try:
            results = await self.graph_manager.execute_query(query, {
                "user_id": user_id,
                "limit": limit
            })
            return [str(name) for name in results if name]
        except Exception as e:
            logger.debug(f"[CrossStack] Failed to find active projects: {e}")
            return []

    async def _llm_synthesize_narrative(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Use AI to create a professional 360-degree narrative synthesis."""
        topic = context.get("topic")
        sources = context.get("sources", {})
        
        # Prepare context for LLM
        # Only include sources that found something
        available_data = {k: v for k, v in sources.items() if v.get("found")}
        
        if not available_data:
            return context
            
        system_prompt = f"""
        You are Clavr's 'Autonomous Glue', an AI that synthesizes information across multiple platforms.
        Create a professional '360-degree Perspective' on the topic: '{topic}'.
        
        Synthesize the provided data into:
        1. A 2-3 sentence Executive Summary.
        2. A list of key facts (bullet points).
        3. A 'People Involved' summary.
        4. Clear action items if any.
        
        Tone: Professional, concise, executive-level.
        """
        
        user_prompt = f"Data Sources:\n{available_data}"
        
        try:
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.2)
            response = await asyncio.to_thread(
                llm.invoke,
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
            
            # Simple parsing of narrative into context fields (in a real app, use structured output)
            content = response.content
            context["summary"] = content.split('\n\n')[0] if content else context["summary"]
            
            # Metadata for audit
            context["synthesis_engine"] = "llm-v1"
            
        except Exception as e:
            logger.warning(f"[CrossStack] LLM synthesis failed: {e}")
            
        return context
