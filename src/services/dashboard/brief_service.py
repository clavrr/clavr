"""
Brief Service.

Aggregates data for the "Briefs" dashboard:
- Emails: Important & Unread (with summaries)
- Todos: From Google Tasks, Notion, and internally extracted ActionableItems
- Meetings: Today's schedule
- Reminders: Bills and Appointments (from ActionableItems)
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import asyncio
import pytz

from src.utils.logger import setup_logger
from src.utils.config import Config, get_timezone
from src.database import get_db_context
from src.database.models import ActionableItem, User
from sqlalchemy import select, and_, or_

# Integrations
from src.integrations.gmail.service import EmailService
from src.integrations.google_tasks.service import TaskService
from src.integrations.google_calendar.service import CalendarService
from src.integrations.google_drive.service import GoogleDriveService
from src.services.extraction.actionable_item_extractor import ActionableItemExtractor

logger = setup_logger(__name__)

class BriefService:
    """Aggregator service for the Briefs dashboard."""
    
    def __init__(self, config: Config, 
                 email_service: Optional[EmailService] = None,
                 task_service: Optional[TaskService] = None,
                 calendar_service: Optional[CalendarService] = None,
                 drive_service: Optional[GoogleDriveService] = None,
                 brief_extractor: Optional[ActionableItemExtractor] = None):
        self.config = config
        self.email_service = email_service
        self.task_service = task_service
        self.calendar_service = calendar_service
        self.drive_service = drive_service
        self.extractor = brief_extractor

    async def get_dashboard_briefs(self, user_id: int, user_name: str = "there", fast_mode: bool = False) -> Dict[str, Any]:
        """
        Get all briefs components in parallel.
        Reminders are generated as an intelligent summary of emails, todos, meetings, and documents.
        """
        # First: Fetch emails, todos, meetings, documents in parallel
        # Optimization: Skip slow document fetching in fast_mode (voice)
        tasks = [
            self._get_emails(user_id, fast_mode=fast_mode),
            self._get_todos(user_id, fast_mode=fast_mode),
            self._get_meetings(user_id)
        ]
        if not fast_mode:
            tasks.append(self._get_documents(user_id))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Unpack results handling errors
        emails, todos, meetings, documents = [], [], [], []
        
        if len(results) > 0 and isinstance(results[0], list): emails = results[0]
        else: logger.error(f"[BriefService] Emails failed: {results[0] if len(results) > 0 else 'N/A'}")
            
        if len(results) > 1 and isinstance(results[1], list): todos = results[1]
        else: logger.error(f"[BriefService] Todos failed: {results[1] if len(results) > 1 else 'N/A'}")
            
        if len(results) > 2 and isinstance(results[2], list): meetings = results[2]
        else: logger.error(f"[BriefService] Meetings failed: {results[2] if len(results) > 2 else 'N/A'}")

        if not fast_mode and len(results) > 3:
            if isinstance(results[3], list): documents = results[3]
            else: logger.error(f"[BriefService] Documents failed: {results[3]}")
        
        # 2. Skip slow LLM-based summarization in fast_mode (voice optimization)
        # _generate_smart_reminders takes ~6-8s, which is too slow for voice (~1s limit)
        if fast_mode:
            logger.info("[BriefService] fast_mode enabled: skipping slow LLM-based smart reminders")
            # Create a simple summary based on item counts
            summary_parts = []
            if emails: summary_parts.append(f"{len(emails)} unread emails")
            if todos: summary_parts.append(f"{len(todos)} tasks")
            if meetings: summary_parts.append(f"{len(meetings)} meetings")
            
            simple_summary = "Here are your items: " + ", ".join(summary_parts) if summary_parts else "You're all caught up!"
            
            reminders = {
                "summary": simple_summary,
                "items": []
            }
            # Convert raw items to the format expected by the tool
            for e in emails[:3]:
                reminders["items"].append({"title": f"Email: {e['subject']}", "subtitle": e['from']})
            for t in todos[:3]:
                reminders["items"].append({"title": f"Task: {t['title']}", "subtitle": t.get('due_date') or "no due date"})
            for m in meetings[:3]:
                reminders["items"].append({"title": f"Meeting: {m['title']}", "subtitle": m['start_time']})
        else:
            # Generate smart reminders from aggregated data using LLM
            reminders = await self._generate_smart_reminders(
                user_id=user_id,
                user_name=user_name,
                emails=emails,
                todos=todos,
                meetings=meetings,
                documents=documents
            )

        return {
            "emails": emails,
            "todos": todos,
            "meetings": meetings,
            "documents": documents,
            "reminders": reminders
        }

    async def _get_emails(self, user_id: int, fast_mode: bool = False) -> List[Dict]:
        """Fetch important unread emails using Gmail's IMPORTANT label."""
        if not self.email_service:
            logger.warning("[BriefService] No email service available")
            return []
            
        try:
            # Use Gmail's IMPORTANT label - this matches what user sees in Gmail's "Important" tab
            # label:IMPORTANT is the system label that Gmail auto-applies
            query = "is:unread label:IMPORTANT"
            
            logger.info(f"[BriefService] Searching emails with query: {query}")
            
            # Explicitly disable RAG in fast_mode to avoid hitting timeouts (>1s)
            allow_rag = not fast_mode
            
            messages = await asyncio.to_thread(
                self.email_service.search_emails, 
                query=query, 
                limit=15,  # Fetch slightly fewer for speed
                allow_rag=allow_rag
            ) 
            
            logger.info(f"[BriefService] Found {len(messages)} emails")
            
            # Promotional sender patterns to exclude (be specific to avoid over-filtering)
            promo_patterns = [
                # Newsletter platforms (most reliable to filter)
                '@substack.com', '@beehiiv.com',
                '@convertkit.com', '@ghost.io',
                '@interviewcake.com', 
                # Social media notifications
                '@facebookmail.com', 
                # E-commerce / Streaming notifications
                '@primevideo.com', '@email.amazon.com', '@netflix.com',
                '@spotify.com', '@doordash.com', 
                # Explicit marketing only
                'newsletter@', 'marketing@',
            ]
            
            brief_emails = []
            for msg in messages:
                sender = msg.get('sender', '').lower()
                logger.info(f"[BriefService] Checking email from: {sender}")
                
                # Skip promotional emails (TEMPORARILY DISABLED for debugging)
                # is_promo = any(pattern in sender for pattern in promo_patterns)
                is_promo = False
                
                if is_promo:
                    logger.info(f"[BriefService] Skipping promotional email from: {sender}")
                    continue
                
                # Snippet is the Gmail preview text
                summary = msg.get('snippet', '')
                
                # Fallback if snippet is empty
                if not summary:
                    summary = "No preview available"
                
                brief_emails.append({
                    "id": msg.get('id'),
                    "subject": msg.get('subject', 'No Subject'),
                    "from": msg.get('sender', 'Unknown'),
                    "summary": summary,
                    "received_at": msg.get('date'),
                    "thread_id": msg.get('threadId')
                })
                
                # Limit to 10 filtered emails
                if len(brief_emails) >= 10:
                    break
                    
            logger.info(f"[BriefService] Filtered to {len(brief_emails)} non-promotional emails")
            return brief_emails
            
        except Exception as e:
            logger.error(f"[BriefService] Error fetching emails: {e}", exc_info=True)
            return []

    async def _get_todos(self, user_id: int, fast_mode: bool = False) -> List[Dict]:
        """
        Aggregate tasks from:
        1. ActionableItems (type='task')
        2. Google Tasks
        """
        all_todos = []
        
        # Helper for internal tasks
        def fetch_internal_tasks(uid):
            try:
                with get_db_context() as session:
                    query = select(ActionableItem).where(
                        and_(
                            ActionableItem.user_id == uid,
                            ActionableItem.status == 'pending',
                            ActionableItem.item_type == 'task'
                        )
                    ).limit(10)
                    items = session.execute(query).scalars().all()
                    return [{
                        "id": t.id,
                        "title": t.title,
                        "due_date": t.due_date.isoformat() if t.due_date else None,
                        "source": "extracted",
                        "urgency": t.urgency
                    } for t in items]
            except Exception as e:
                logger.error(f"[BriefService] Internal tasks error: {e}")
                return []

        # Optimization: Parallelize internal DB and external API calls
        internal_future = asyncio.to_thread(fetch_internal_tasks, user_id)
        
        external_tasks = []
        if self.task_service:
            try:
                # OPTIMIZATION: Call list_tasks ONCE.
                # It already fetches everything from @default in fast_mode.
                limit = 10 if fast_mode else 30
                gt_tasks = await asyncio.to_thread(
                    self.task_service.list_tasks, 
                    status='pending', 
                    limit=limit, 
                    fast_mode=fast_mode
                ) or []
                
                now = datetime.now()
                for t in gt_tasks:
                    # Determine urgency client-side to avoid extra API calls
                    is_overdue = False
                    due_str = t.get('due_date') or t.get('due')
                    if due_str:
                        try:
                            # Parse with TZ awareness
                            dt = datetime.fromisoformat(due_str.replace('Z', '+00:00'))
                            if dt.tzinfo and now.tzinfo:
                                is_overdue = dt < now
                            else:
                                is_overdue = dt < now.replace(tzinfo=None)
                        except Exception: pass

                    external_tasks.append({
                        "id": t['id'],
                        "title": t['title'],
                        "due_date": due_str,
                        "source": "google_tasks",
                        "urgency": "high" if is_overdue else "medium"
                    })
            except Exception as e:
                logger.error(f"[BriefService] External tasks error: {e}")

        # Wait for internal tasks
        internal_tasks = await internal_future
        all_todos.extend(internal_tasks)
        all_todos.extend(external_tasks)
        
        # Sort by due date (nulls last)
        all_todos.sort(key=lambda x: x.get('due_date') or '9999-12-31')
        
        return all_todos[:20]

    async def _get_meetings(self, user_id: int) -> List[Dict]:
        """Get today's meetings (Timezone Aware)."""
        if not self.calendar_service:
            logger.warning("[BriefService] Calendar service IS NONE")
            return []
            
        try:
            # Use User's Timezone for "Today"
            user_tz_name = get_timezone(self.config)
            user_tz = pytz.timezone(user_tz_name)
            now_local = datetime.now(user_tz)
            
            # Start of today (00:00:00 local)
            today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            # End of today (23:59:59 local)
            today_end = today_start + timedelta(days=1) - timedelta(seconds=1)
            
            # Convert to ISO format for API
            start_iso = today_start.isoformat()
            end_iso = today_end.isoformat()
            
            # Call list_events directly with explicit range
            events = await asyncio.to_thread(
                self.calendar_service.list_events,
                start_date=start_iso,
                end_date=end_iso
            )
            
            todays_events = []
            for evt in events:
                try:
                    # Validate event structure
                    if not isinstance(evt, dict):
                        logger.warning(f"[BriefService] Skipping malformed event (not a dict): {type(evt)}")
                        continue

                    # Handle both dateTime (timed) and date (all-day)
                    # Note: Client might return parsed datetime objects or raw dicts
                    start_obj = evt.get('start', {})
                    end_obj = evt.get('end', {})
                    
                    # Ensure start/end are dicts or objects before processing
                    if isinstance(start_obj, str):
                        logger.warning(f"[BriefService] Skipping malformed start time (str): {start_obj}")
                        continue
                        
                    start_str = None
                    end_str = None
                    is_all_day = False

                    if isinstance(start_obj, datetime):
                        start_str = start_obj.isoformat()
                    elif isinstance(start_obj, dict):
                        start_str = start_obj.get('dateTime') or start_obj.get('date')
                        is_all_day = 'date' in start_obj
                    else:
                        # Fallback for unexpected types
                        logger.warning(f"[BriefService] Unexpected start_obj type: {type(start_obj)}")
                        continue

                    if isinstance(end_obj, datetime):
                        end_str = end_obj.isoformat()
                    elif isinstance(end_obj, dict):
                        end_str = end_obj.get('dateTime') or end_obj.get('date')
                    
                    # Validate we extracted a valid start time
                    if not start_str: 
                        continue

                    todays_events.append({
                        "id": evt.get('id'),
                        "title": evt.get('summary', 'No Title'),
                        "start_time": start_str,
                        "end_time": end_str,
                        "location": evt.get('location'),
                        "attendees": evt.get('attendees', []),
                        "is_all_day": is_all_day
                    })
                except Exception as e:
                    logger.error(f"[BriefService] Event parsing error: {e}")
                    continue
            
            logger.info(f"[BriefService] Returning {len(todays_events)} processed events")
                
            return todays_events
            
        except Exception as e:
            logger.error(f"[BriefService] Calendar error: {e}", exc_info=True)
            return []

    async def _get_documents(self, user_id: int) -> List[Dict]:
        """Get recent/important documents from Drive."""
        if not self.drive_service:
            return []
            
        try:
            # Get combined list of recent and starred, prioritizing starred
            documents = []
            
            # Run in thread
            starred = await asyncio.to_thread(self.drive_service.list_starred_files, limit=5)
            recent = await asyncio.to_thread(self.drive_service.list_recent_files, limit=5)
            
            # Combine and dedupe
            seen = set()
            for doc in starred + recent:
                if doc['id'] not in seen:
                    documents.append({
                        "id": doc['id'],
                        "title": doc.get('name'),
                        "type": "document",
                        "mime_type": doc.get('mimeType'),
                        "updated_at": doc.get('modifiedTime'),
                        "link": doc.get('webViewLink'),
                        "starred": doc.get('starred', False)
                    })
                    seen.add(doc['id'])
            
            return documents[:10]
        except Exception as e:
            logger.error(f"[BriefService] Drive documents error: {e}")
            return []

    async def _get_reminders(self, user_id: int) -> List[Dict]:
        """
        Get proactive reminders:
        - Bills, Appointments, Deadlines from ActionableItems
        - Fallback: Upcoming calendar events (next 7 days)
        """
        reminders = []
        
        # 1. First, check ActionableItems database
        try:
            with get_db_context() as session:
                query = select(ActionableItem).where(
                    and_(
                        ActionableItem.user_id == user_id,
                        ActionableItem.status == 'pending',
                        # Exclude basic 'tasks' which go to Todo list
                        ActionableItem.item_type.in_(['bill', 'appointment', 'deadline'])
                    )
                ).order_by(ActionableItem.due_date.asc()).limit(20)
                
                items = session.execute(query).scalars().all()
                
                for item in items:
                    reminders.append({
                        "id": item.id,
                        "title": item.title,
                        "type": item.item_type,
                        "due_date": item.due_date.isoformat() if item.due_date else None,
                        "amount": item.amount,
                        "urgency": item.urgency,
                        "action": item.suggested_action
                    })
                    
        except Exception as e:
            logger.error(f"[BriefService] Reminders DB error: {e}")
        
        # 2. If no ActionableItems, fallback to upcoming calendar events
        logger.info(f"[BriefService] Reminders from DB: {len(reminders)}, calendar_service available: {self.calendar_service is not None}")
        if not reminders and self.calendar_service:
            try:
                user_tz_name = get_timezone(self.config)
                user_tz = pytz.timezone(user_tz_name)
                now = datetime.now(user_tz)
                end = now + timedelta(days=7)
                
                # Get events for next 7 days - use correct parameter names
                # Wrap sync call in asyncio.to_thread
                events = await asyncio.to_thread(
                    self.calendar_service.list_events,
                    start_date=now.isoformat(),
                    end_date=end.isoformat(),
                    max_results=10
                )
                
                for evt in events:
                    start_obj = evt.get('start', {})
                    
                    # Handle both datetime objects and dict formats
                    if isinstance(start_obj, datetime):
                        start_time = start_obj.isoformat()
                    elif isinstance(start_obj, dict):
                        start_time = start_obj.get('dateTime') or start_obj.get('date')
                    else:
                        start_time = str(start_obj) if start_obj else None
                    
                    if not start_time:
                        continue
                    
                    reminders.append({
                        "id": evt.get('id'),
                        "title": evt.get('summary', 'Untitled Event'),
                        "type": "appointment",
                        "due_date": start_time,
                        "amount": None,
                        "urgency": "medium",
                        "action": f"📅 {evt.get('summary', 'Event')}"
                    })
                
                # Debug: Log the exact date format being sent
                if reminders:
                    logger.info(f"[BriefService] Sample reminder dates: {[(r['title'], r['due_date']) for r in reminders[:3]]}")
                    
                logger.info(f"[BriefService] Found {len(reminders)} upcoming calendar events as reminders")
                    
            except Exception as e:
                logger.error(f"[BriefService] Calendar fallback error: {e}")
        
        return reminders

    async def _generate_smart_reminders(
        self,
        user_id: int,
        user_name: str,
        emails: List[Dict],
        todos: List[Dict],
        meetings: List[Dict],
        documents: List[Dict] = []
    ) -> Dict[str, Any]:
        """
        Generate intelligent reminders by aggregating emails, todos, and meetings.
        Uses LLM to create a personalized greeting summary.
        
        Returns:
            {
                "summary": "Hey Maniko! Here are your key action items...",
                "items": [{"title": ..., "type": ..., "urgency": ..., "due_date": ...}, ...]
            }
        """
        items = []
        
        # 1. Add urgent emails (first 3)
        for email in emails[:3]:
            items.append({
                "title": f"Reply to: {email.get('subject', 'Email')}",
                "subtitle": f"From {email.get('from', 'Unknown')}",
                "type": "email",
                "urgency": "high",
                "due_date": email.get('received_at'),
                "id": email.get('id')
            })
        
        # 2. Add pending todos (first 5)
        for todo in todos[:5]:
            items.append({
                "title": todo.get('title', 'Task'),
                "subtitle": todo.get('source', 'task'),
                "type": "todo",
                "urgency": todo.get('urgency', 'medium'),
                "due_date": todo.get('due_date'),
                "id": todo.get('id')
            })
        
        # 3. Add upcoming meetings (all for today/tomorrow)
        for meeting in meetings:
            items.append({
                "title": meeting.get('title', 'Meeting'),
                "subtitle": meeting.get('location') or 'No location',
                "type": "meeting",
                "urgency": "high" if self._is_soon(meeting.get('start_time')) else "medium",
                "due_date": meeting.get('start_time'),
                "id": meeting.get('id')
            })
            
        # 3b. Add important documents (Starred only)
        for doc in documents:
            if doc.get('starred'):
                items.append({
                    "title": doc.get('title'),
                    "subtitle": "Starred Document",
                    "type": "document",
                    "urgency": "medium",
                    "due_date": doc.get('updated_at'),
                    "id": doc.get('id'),
                    "link": doc.get('link')
                })
        
        # 4. Also check ActionableItems (bills, deadlines) from database
        try:
            with get_db_context() as session:
                query = select(ActionableItem).where(
                    and_(
                        ActionableItem.user_id == user_id,
                        ActionableItem.status == 'pending',
                        ActionableItem.item_type.in_(['bill', 'appointment', 'deadline'])
                    )
                ).order_by(ActionableItem.due_date.asc()).limit(5)
                
                db_items = session.execute(query).scalars().all()
                
                for item in db_items:
                    items.append({
                        "title": item.title,
                        "subtitle": item.suggested_action or item.item_type,
                        "type": item.item_type,
                        "urgency": item.urgency or "medium",
                        "due_date": item.due_date.isoformat() if item.due_date else None,
                        "id": str(item.id)
                    })
        except Exception as e:
            logger.error(f"[BriefService] Error fetching ActionableItems: {e}")
        
        # Sort by urgency (high first) then by due_date
        urgency_order = {"high": 0, "medium": 1, "low": 2}
        items.sort(key=lambda x: (urgency_order.get(x.get('urgency', 'medium'), 1), x.get('due_date') or '9999'))
        
        # Limit to 15 items
        items = items[:15]
        
        # 5. Generate personalized summary using LLM
        summary = await self._generate_greeting(user_name, items)
        
        logger.info(f"[BriefService] Generated {len(items)} smart reminders for {user_name}")
        
        return {
            "summary": summary,
            "items": items
        }
    
    def _is_soon(self, start_time: Optional[str]) -> bool:
        """Check if a meeting is within the next 2 hours."""
        if not start_time:
            return False
        try:
            # Parse the datetime
            if 'T' in str(start_time):
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            else:
                return False
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            return (dt - now).total_seconds() < 7200  # 2 hours
        except:
            return False
    
    async def _generate_greeting(self, user_name: str, items: List[Dict]) -> str:
        """Generate a personalized greeting using LLM."""
        if not items:
            return f"Hey {user_name}! You're all caught up - no urgent actions needed right now. 🎉"
        
        try:
            from src.ai.llm_factory import LLMFactory
            
            # Build context for LLM
            item_summary = []
            for item in items[:6]:
                item_summary.append(f"- {item['type'].upper()}: {item['title']}")
            
            prompt = f"""Generate a friendly, concise greeting for a user named {user_name}.
They have key items to be aware of:
{chr(10).join(item_summary)}

Write a single sentence greeting that:
1. Addresses them by name
2. Summarizes what needs attention today (prioritizing meetings/emails)
3. Is encouraging but urgent if needed
4. Maximum 20 words

Example: "Hey Maniko! You have 3 meetings today and 2 emails that need replies - let's tackle them!"

Generate ONLY the greeting, nothing else:"""

            llm = LLMFactory.get_llm_for_provider(self.config)
            response = await asyncio.to_thread(llm.invoke, prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Clean up response
            greeting = content.strip().strip('"').strip("'")
            
            # Fallback if response is too long or weird
            if len(greeting) > 150 or len(greeting) < 10:
                raise ValueError("Invalid LLM response length")
                
            return greeting
            
        except Exception as e:
            logger.error(f"[BriefService] LLM greeting failed: {e}")
            return f"Hey {user_name}! You have {len(items)} items needing attention today."

    async def get_critical_reminder(self, user_id: int) -> Optional[str]:
        """
        Get a single most critical reminder string for proactive voice greeting.
        Prioritizes:
        1. Meetings starting within 30 minutes.
        2. Overdue tasks.
        3. High-priority unread emails (sent within last 24h).
        """
        try:
            # 1. Check Meetings (Upcoming in next 30 mins)
            if self.calendar_service:
                meetings = await self._get_meetings(user_id)
                now = datetime.now(pytz.UTC)
                for m in meetings:
                    start_str = m.get('start_time')
                    if start_str and 'T' in start_str:
                        start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                        # If starting within 30 mins and not in the past
                        diff = (start_dt - now).total_seconds()
                        if 0 < diff < 1800:
                            mins = int(diff / 60)
                            return f"your meeting '{m.get('title')}' starts in {mins} minutes"

            # 2. Check Overdue Tasks
            if self.task_service:
                overdue = await asyncio.to_thread(self.task_service.get_overdue_tasks, limit=1)
                if overdue:
                    return f"you have an overdue task: {overdue[0].get('title')}"

            # 3. Check Database ActionableItems (Bills/Deadlines due today)
            try:
                with get_db_context() as session:
                    today = datetime.now().date()
                    query = select(ActionableItem).where(
                        and_(
                            ActionableItem.user_id == user_id,
                            ActionableItem.status == 'pending',
                            ActionableItem.due_date <= today
                        )
                    ).limit(1)
                    item = session.execute(query).scalar_one_or_none()
                    if item:
                        return f"your {item.item_type} '{item.title}' is due today"
            except Exception:
                pass

            return None
        except Exception as e:
            logger.error(f"[BriefService] Critical reminder failed: {e}")
            return None
