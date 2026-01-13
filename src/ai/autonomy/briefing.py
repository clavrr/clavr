"""
Daily Briefing Generator

Aggregates context from Calendar, Email, and Tasks to generate a concise
narrative briefing for the user using an LLM.

Phase 3 of Ambient Autonomy.
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

from ...utils.logger import setup_logger
from ...utils.config import Config
from ..llm_factory import LLMFactory
from langchain_core.messages import SystemMessage, HumanMessage

from ..prompts.autonomy_prompts import (
    MORNING_BRIEFING_SYSTEM_PROMPT,
    MEETING_BRIEFING_SYSTEM_PROMPT
)

logger = setup_logger(__name__)

class BriefingGenerator:
    """
    Generates daily briefings by aggregating context triggers.
    """
    
    def __init__(self, config: Config):
        self.config = config
        
    async def generate_briefing(self, 
                                user_id: int,
                                calendar_service: Any,
                                email_service: Any,
                                task_service: Any,
                                fast_mode: bool = False) -> str:
        """
        Gather context and generate briefing narrative.
        """
        try:
            # 1. Gather Context
            context = await self._gather_context(
                user_id, 
                calendar_service, 
                email_service, 
                task_service,
                fast_mode=fast_mode
            )
            
            # 2. Generate Narrative via LLM
            narrative = await self._generate_narrative(context)
            
            return narrative
            
        except Exception as e:
            logger.error(f"Failed to generate briefing for user {user_id}: {e}")
            return "I apologize, but I couldn't generate your briefing due to a system error. Please check your dashboard."

    async def _gather_context(self, 
                              user_id: int, 
                              calendar_service: Any, 
                              email_service: Any, 
                              task_service: Any,
                              fast_mode: bool = False) -> Dict[str, Any]:
        """
        Fetch fresh data from all services safely.
        """
        logger.info(f"Gathering briefing context for user {user_id}...")
        
        now_utc = datetime.now(timezone.utc)
        
        # --- 1. Calendar: Events for Next 24 Hours ---
        events = []
        if calendar_service:
            try:
                # Use list_events with explicit time range instead of get_upcoming_events(limit=X)
                # to be more precise about "Today/Tomorrow"
                start_str = now_utc.isoformat()
                end_str = (now_utc + timedelta(hours=24)).isoformat()
                
                # Wrap sync call
                events = await asyncio.to_thread(
                    calendar_service.list_events,
                    start_date=start_str,
                    end_date=end_str,
                    max_results=15
                ) or []
            except Exception as e:
                logger.warning(f"Briefing context - Calendar failed: {e}")
            
        # --- 2. Tasks: Overdue + Pending High Priority ---
        tasks = []
        if task_service:
            try:
                # Wrap sync calls
                overdue_future = asyncio.to_thread(task_service.get_overdue_tasks, limit=5, fast_mode=fast_mode)
                # TODO: add pending high priority if API supports it
                # For now just overdue is critical
                overdue = await overdue_future or []
                tasks.extend(overdue)
            except Exception as e:
                logger.warning(f"Briefing context - Tasks failed: {e}")

        # --- 3. Emails: Unread Priority ---
        emails = []
        if email_service:
            try:
                # Search for unread high priority
                query = "is:unread label:important"
                results = await asyncio.to_thread(
                    email_service.search_emails, 
                    query=query, 
                    limit=5, # Changed from max_results to limit for consistency
                    allow_rag=not fast_mode
                )
                emails = results if results else []
            except Exception as e:
                logger.warning(f"Briefing context - Emails failed: {e}")
            
        return {
            "datetime": now_utc.isoformat(), # Use UTC in context
            "events": events,
            "tasks": tasks,
            "emails": emails
        }
        
    async def _generate_narrative(self, context: Dict[str, Any]) -> str:
        """
        Call LLM to generate text.
        """
        try:
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.7)
            
            # Helper to format events legibly
            def fmt_event(e):
                start_obj = e.get('start', {})
                if isinstance(start_obj, datetime):
                    dt = start_obj.isoformat()
                elif isinstance(start_obj, dict):
                    dt = start_obj.get('dateTime') or start_obj.get('date') or "All Day"
                else:
                    dt = "Unknown"
                    
                if 'T' in dt:
                    # Naive truncation of seconds/offset for brevity in prompt
                    dt = dt.split('+')[0].replace('T', ' ')[:16] 
                return f"- {dt}: {e.get('summary', 'Untitled')}"

            events_msg = "\n".join([fmt_event(e) for e in context.get('events', [])]) or "No upcoming events in next 24h."
            tasks_msg = "\n".join([f"- {t.get('title', 'No Title')} (Due: {t.get('due') or t.get('due_date') or 'No Date'})" for t in context.get('tasks', []) if isinstance(t, dict)]) or "No urgent tasks."
            emails_msg = "\n".join([f"- {e.get('subject', 'No Subject')} (From: {e.get('from', 'Unknown')})" for e in context.get('emails', []) if isinstance(e, dict)]) or "No unread priority emails."
            
            user_context = f"""
            Current Time (UTC): {context.get('datetime')}
            
            CALENDAR (Next 24h):
            {events_msg}
            
            TASKS (Overdue/Urgent):
            {tasks_msg}
            
            EMAILS (Unread Important):
            {emails_msg}
            """
            
            # Use centralized Prompt
            prompt_content = MORNING_BRIEFING_SYSTEM_PROMPT.format(user_context=user_context)

            # Construct messages list (Gemini requires HumanMessage to trigger 'contents')
            messages = [
                SystemMessage(content=prompt_content),
                HumanMessage(content="Please generate my morning briefing now based on the above context.")
            ]
            
            result = await asyncio.to_thread(llm.invoke, messages)
            return result.content
            
        except Exception as e:
            logger.error(f"Briefing LLM generation failed: {e}")
            return "Good morning. I encountered an error compiling your briefing. Please check your dashboard."

class MeetingBriefGenerator:
    """
    Generates targeted briefs for specific meetings.
    """
    def __init__(self, config: Config):
        self.config = config
        
    async def generate_brief(self,
                             user_id: int,
                             event_id: str,
                             calendar_service: Any,
                             email_service: Any,
                             semantic_memory: Any) -> str:
        """
        Generate a dossier for a specific meeting.
        """
        try:
            context = await self._gather_context(user_id, event_id, calendar_service, email_service, semantic_memory)
            
            if not context:
                return f"Could not find details for meeting {event_id}."
            
            return await self._generate_narrative(context)
            
        except Exception as e:
            logger.error(f"Failed to generate meeting brief for {event_id}: {e}")
            return "Unable to generate meeting brief due to system error."
            
    async def _gather_context(self,
                              user_id: int,
                              event_id: str,
                              calendar_service: Any,
                              email_service: Any,
                              semantic_memory: Any) -> Optional[Dict[str, Any]]:
        
        # 1. Fetch Event Details (Sync Call Wrapped)
        event = None
        if calendar_service:
            try:
                event = await asyncio.to_thread(calendar_service.get_event, event_id)
            except Exception as e:
                logger.warning(f"Meeting brief - Get event failed: {e}")
                return None
             
        if not event:
            return None
            
        attendees = event.get('attendees', [])
        subject = event.get('summary', 'No Title')
        description = event.get('description', '')
        
        # 2. Context Search (Email + Memory)
        attendee_context = {}
        
        # Limit to first 5 attendees to avoid blowing up context window
        for att in attendees[:5]:
            email = att.get('email')
            # Skip self if possible (naive check)
            if not email or 'self' in att or att.get('responseStatus') == 'declined': 
                continue
            
            # A. Search Memory (Async)
            facts = []
            if semantic_memory:
                 try:
                     # Inefficient scan for MVP; ideally vector search
                     user_facts = await semantic_memory.get_facts(user_id, limit=50)
                     facts = [f['content'] for f in user_facts if email in f['content'] or att.get('displayName', '') in f['content']]
                 except Exception:
                     pass
            
            # B. Search Emails (Sync Call Wrapped)
            recent_emails = []
            if email_service:
                try:
                    res = await asyncio.to_thread(
                        email_service.search_emails,
                        query=f"from:{email}",
                        max_results=2
                    )
                    if res:
                        recent_emails = [e.get('subject', 'No Subject') for e in res]
                except Exception:
                    pass
                    
            attendee_context[email] = {
                "name": att.get('displayName', email),
                "facts": facts,
                "recent_emails": recent_emails
            }
            
        return {
            "subject": subject,
            "description": description,
            "start": event.get('start'),
            "attendees": attendee_context
        }

    async def _generate_narrative(self, context: Dict[str, Any]) -> str:
        try:
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.5)
            
            # Format context
            attendees_str = ""
            for email, data in context.get('attendees', {}).items():
                attendees_str += f"- {data['name']} ({email})\n"
                if data['facts']:
                    attendees_str += f"  - FACTS: {'; '.join(data['facts'][:3])}\n"
                if data['recent_emails']:
                    attendees_str += f"  - RECENT EMAILS: {'; '.join(data['recent_emails'])}\n"
            
            if not attendees_str:
                attendees_str = "No specific attendee context found."

            # Format time handle datetime objects or dicts
            start_obj = context.get('start', {})
            if isinstance(start_obj, datetime):
                time_str = start_obj.isoformat()
            elif isinstance(start_obj, dict):
                time_str = start_obj.get('dateTime') or start_obj.get('date') or "Unknown"
            else:
                time_str = "Unknown"

            user_context = f"""
            MEETING: {context.get('subject', 'Untitled')}
            TIME: {time_str}
            DESCRIPTION: {context.get('description', 'None')}
            
            ATTENDEES & CONTEXT:
            {attendees_str}
            """
            
            prompt_content = MEETING_BRIEFING_SYSTEM_PROMPT.format(user_context=user_context)

            # Construct messages list
            messages = [
                SystemMessage(content=prompt_content),
                HumanMessage(content="Please generate the meeting brief now based on the above dossier context.")
            ]
            
            result = await asyncio.to_thread(llm.invoke, messages)
            return result.content
            
        except Exception as e:
            logger.error(f"Meeting brief LLM generation failed: {e}")
            return f"Meeting Brief for {context.get('subject')}: Unable to generate details."
