"""
Summarization Service

Creates automatic Summary nodes in the knowledge graph for:
- Daily activity summaries (emails received, meetings attended, tasks completed)
- Weekly digests
- Project/Topic summaries

These Summary nodes are linked via SUMMARIZES relationships to source content,
and HIGHLIGHTS relationships to key people/topics.
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.ai.llm_factory import LLMFactory
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

SUMMARY_GENERATION_PROMPT = """You are an intelligent assistant creating a brief summary.

Analyze the provided activity data and generate a concise summary that captures:
1. Key highlights (most important items)
2. Notable people involved
3. Action items or follow-ups needed
4. Overall sentiment/tone

Return JSON:
{
    "summary": "Brief 2-3 sentence overview",
    "key_topics": ["topic1", "topic2"],
    "key_people": ["person1", "person2"],
    "action_items": ["action1", "action2"],
    "sentiment": "positive|neutral|negative"
}
"""


class SummarizationService:
    """
    Generates automatic Summary nodes in the knowledge graph.
    
    Summary Types:
    - daily: Summarizes a day's emails, meetings, and tasks
    - weekly: Week-level digest
    - project: Project/topic-specific summaries
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self.llm = None
        self.is_running = False
        self._stop_event = asyncio.Event()
        
    def _get_llm(self):
        """Lazy-load LLM."""
        if not self.llm:
            try:
                self.llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.0)
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")
        return self.llm
    
    async def start(self):
        """Start the summarization service."""
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        logger.info("[SummarizationService] Started")
        asyncio.create_task(self._run_loop())
        
    async def stop(self):
        """Stop the service."""
        self.is_running = False
        self._stop_event.set()
        logger.info("[SummarizationService] Stopped")
        
    async def _run_loop(self):
        """Main loop - generate daily summaries."""
        while self.is_running:
            try:
                await self._generate_daily_summaries()
                # Run at 6pm daily or every 6 hours
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=21600)
                except asyncio.TimeoutError:
                    pass
            except Exception as e:
                logger.error(f"[SummarizationService] Error: {e}")
                await asyncio.sleep(300)
    
    async def _generate_daily_summaries(self):
        """Generate daily summaries for all active users."""
        try:
            # Native AQL to get users
            query = "FOR u IN User RETURN u.id as user_id LIMIT 100"
            users = await self.graph.execute_query(query, {})
            
            today = datetime.utcnow().date()
            for user in users or []:
                user_id = user.get("user_id")
                if user_id:
                    await self.generate_daily_summary(user_id, today)
        except Exception as e:
            logger.error(f"[SummarizationService] Failed: {e}")
    
    async def generate_daily_summary(
        self,
        user_id: int,
        date: datetime.date = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a daily summary for a user.
        
        Creates a Summary node linked to the day's emails, meetings, etc.
        """
        if date is None:
            date = datetime.utcnow().date()
            
        summary_id = f"summary:daily:{user_id}:{date.isoformat()}"
        
        # Check if summary already exists
        existing = await self.graph.get_node(summary_id)
        if existing:
            return existing
        
        # Gather the day's activity
        activity = await self._gather_daily_activity(user_id, date)
        
        if not activity.get("has_activity"):
            return None
        
        # Generate summary using LLM
        summary_data = await self._generate_summary_content(activity)
        
        if not summary_data:
            return None
        
        # Create Summary node
        properties = {
            "content": summary_data.get("summary", ""),
            "summary_type": "daily",
            "period": date.isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "source": "auto",
            "item_count": activity.get("total_items", 0),
            "key_topics": summary_data.get("key_topics", []),
            "key_people": summary_data.get("key_people", []),
            "key_actions": summary_data.get("action_items", []),
            "sentiment_overview": summary_data.get("sentiment", "neutral"),
        }
        
        try:
            await self.graph.add_node(summary_id, NodeType.SUMMARY, properties)
            
            # Link to TimeBlock for the day
            timeblock_id = f"timeblock:day:{date.isoformat()}"
            await self.graph.add_relationship(
                summary_id,
                timeblock_id,
                RelationType.OCCURRED_DURING,
                properties={"created_at": datetime.utcnow().isoformat()}
            )
            
            # Link to source content via SUMMARIZES
            for email_id in activity.get("email_ids", [])[:20]:
                await self.graph.add_relationship(
                    summary_id,
                    email_id,
                    RelationType.SUMMARIZES,
                    properties={"created_at": datetime.utcnow().isoformat()}
                )
            
            for event_id in activity.get("event_ids", [])[:10]:
                await self.graph.add_relationship(
                    summary_id,
                    event_id,
                    RelationType.SUMMARIZES,
                    properties={"created_at": datetime.utcnow().isoformat()}
                )
            
            # Link to key people via HIGHLIGHTS using native AQL
            for person_name in summary_data.get("key_people", [])[:5]:
                person_query = """
                FOR p IN Person
                    FILTER CONTAINS(LOWER(p.name), LOWER(@name))
                    LIMIT 1
                    RETURN { id: p.id }
                """
                persons = await self.graph.execute_query(person_query, {"name": person_name})
                for p in persons or []:
                    await self.graph.add_relationship(
                        summary_id,
                        p["id"],
                        RelationType.HIGHLIGHTS,
                        properties={"created_at": datetime.utcnow().isoformat()}
                    )
            
            logger.info(f"[SummarizationService] Created daily summary for user {user_id}: {date}")
            return properties
            
        except Exception as e:
            logger.error(f"[SummarizationService] Failed to create summary: {e}")
            return None
    
    async def _gather_daily_activity(
        self,
        user_id: int,
        date: datetime.date
    ) -> Dict[str, Any]:
        """Gather all activity for a specific day."""
        activity = {
            "has_activity": False,
            "total_items": 0,
            "emails_received": [],
            "emails_sent": [],
            "email_ids": [],
            "meetings": [],
            "event_ids": [],
            "tasks_completed": [],
            "messages": [],
        }
        
        date_str = date.isoformat()
        next_date_str = (date + timedelta(days=1)).isoformat()
        
        # Get emails received - Native AQL
        email_query = """
        FOR e IN Email
            FILTER e.date >= @start AND e.date < @end
            LIMIT 50
            RETURN { id: e.id, subject: e.subject, sender: e.sender }
        """
        try:
            emails = await self.graph.execute_query(email_query, {"start": date_str, "end": next_date_str})
            for email in emails or []:
                activity["emails_received"].append({
                    "subject": email.get("subject", ""),
                    "sender": email.get("sender", "")
                })
                activity["email_ids"].append(email.get("id"))
            activity["total_items"] += len(emails or [])
        except Exception as e:
            logger.debug(f"Email query failed: {e}")
        
        # Get calendar events - Native AQL
        event_query = """
        FOR e IN CalendarEvent
            FILTER e.start_time >= @start AND e.start_time < @end
            LIMIT 20
            RETURN { id: e.id, title: e.title, attendees: e.attendees }
        """
        try:
            events = await self.graph.execute_query(event_query, {"start": date_str, "end": next_date_str})
            for event in events or []:
                activity["meetings"].append({
                    "title": event.get("title", ""),
                    "attendees": event.get("attendees", [])
                })
                activity["event_ids"].append(event.get("id"))
            activity["total_items"] += len(events or [])
        except Exception as e:
            logger.debug(f"Event query failed: {e}")
        
        # Get completed tasks - Native AQL
        # Replacing Task with ActionItem
        task_query = """
        FOR t IN ActionItem
            FILTER t.user_id == @user_id 
               AND t.status == 'completed'
               AND t.completed_at >= @start 
               AND t.completed_at < @end
            LIMIT 20
            RETURN { description: t.description }
        """
        try:
            tasks = await self.graph.execute_query(task_query, {
                "user_id": user_id,
                "start": date_str,
                "end": next_date_str
            })
            for task in tasks or []:
                activity["tasks_completed"].append(task.get("description", ""))
            activity["total_items"] += len(tasks or [])
        except Exception as e:
            logger.debug(f"Task query failed: {e}")
        
        activity["has_activity"] = activity["total_items"] > 0
        return activity
    
    async def _generate_summary_content(
        self,
        activity: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Use LLM to generate summary content."""
        llm = self._get_llm()
        if not llm:
            return self._generate_fallback_summary(activity)
        
        try:
            # Format activity data for LLM
            activity_text = f"""
            Emails Received ({len(activity.get('emails_received', []))}):
            {chr(10).join([f"- {e['subject']} (from: {e['sender']})" for e in activity.get('emails_received', [])[:10]])}
            
            Meetings ({len(activity.get('meetings', []))}):
            {chr(10).join([f"- {m['title']}" for m in activity.get('meetings', [])[:10]])}
            
            Tasks Completed ({len(activity.get('tasks_completed', []))}):
            {chr(10).join([f"- {t}" for t in activity.get('tasks_completed', [])[:10]])}
            """
            
            prompt_msgs = [
                SystemMessage(content=SUMMARY_GENERATION_PROMPT),
                HumanMessage(content=activity_text)
            ]
            
            result = await asyncio.to_thread(llm.invoke, prompt_msgs)
            response_text = result.content if hasattr(result, 'content') else str(result)
            
            # Parse JSON
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            if not clean_text.startswith("{"):
                import re
                match = re.search(r'\{.*\}', clean_text, re.DOTALL)
                if match:
                    clean_text = match.group(0)
            
            return json.loads(clean_text)
            
        except Exception as e:
            logger.warning(f"LLM summary failed: {e}")
            return self._generate_fallback_summary(activity)
    
    def _generate_fallback_summary(
        self,
        activity: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate a basic summary without LLM."""
        email_count = len(activity.get("emails_received", []))
        meeting_count = len(activity.get("meetings", []))
        task_count = len(activity.get("tasks_completed", []))
        
        summary_parts = []
        if email_count > 0:
            summary_parts.append(f"{email_count} emails received")
        if meeting_count > 0:
            summary_parts.append(f"{meeting_count} meetings")
        if task_count > 0:
            summary_parts.append(f"{task_count} tasks completed")
        
        return {
            "summary": ", ".join(summary_parts) if summary_parts else "No significant activity",
            "key_topics": [],
            "key_people": [e.get("sender", "") for e in activity.get("emails_received", [])[:3]],
            "action_items": [],
            "sentiment": "neutral"
        }
    
    async def get_user_summaries(
        self,
        user_id: int,
        summary_type: str = "daily",
        limit: int = 7
    ) -> List[Dict[str, Any]]:
        """Get recent summaries for a user."""
        query = """
        FOR s IN Summary
            FILTER s.user_id == @user_id AND s.summary_type == @summary_type
            SORT s.period DESC
            LIMIT @limit
            RETURN {
                id: s.id, content: s.content, period: s.period,
                key_topics: s.key_topics, key_people: s.key_people,
                sentiment: s.sentiment_overview
            }
        """
        try:
            results = await self.graph.execute_query(query, {
                "user_id": user_id,
                "summary_type": summary_type,
                "limit": limit
            })
            return [dict(r) for r in results or []]
        except Exception as e:
            logger.error(f"Failed to get summaries: {e}")
            return []
