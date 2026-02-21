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
import pytz
import re
from email.utils import parsedate_to_datetime

from src.utils.logger import setup_logger
from src.utils.config import Config, get_timezone, ConfigDefaults
from src.database import get_db_context
from src.database.models import ActionableItem, User, GhostDraft
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

    IMPACT_KEYWORDS = [
        'urgent', 'asap', 'response needed', 'action required', 'immediate', 
        'due', 'deadline', 'payment', 'invoice', 'bill', 'receipt',
        'contract', 'sign', 'offer', 'investment', 'raise', 'funding', 'equity', 
        '50k', '100k', '10k', '25k', 'money', 'transfer', 'invest', 'investor',
        'keep me posted', 'interested', 'believe in you', 'put in', 'round'
    ]

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
            self._get_meetings(user_id),
        ]
        if not fast_mode:
            tasks.append(self._get_documents(user_id))
            
        # Always fetch Ghost drafts (internal and fast)
        tasks.append(self._get_ghost_drafts(user_id))
        
        # People CRM data (fast — graph queries only)
        tasks.append(self._get_people(user_id))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # We must fetch recent important emails SEQUENTIALLY after _get_emails 
        # because google-api-python-client's httplib2 is NOT thread-safe for parallel calls on the same client.
        urgent_read_emails = []
        try:
            urgent_read_emails = await self._get_recent_important_emails(user_id)
        except Exception as e:
            logger.error(f"[BriefService] Sequential fetch of urgent emails failed: {e}")
        
        emails = results[0] if isinstance(results[0], list) else []
        todos = results[1] if isinstance(results[1], list) else []
        meetings = results[2] if isinstance(results[2], list) else []
        
        idx = 3
        documents = []
        if not fast_mode:
            documents = results[idx] if isinstance(results[idx], list) else []
            idx += 1
            
        ghost_drafts = results[idx] if isinstance(results[idx], list) else []
        idx += 1
        
        people = results[idx] if isinstance(results[idx], dict) else {}

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
                emails=emails, # Unread
                urgent_emails=urgent_read_emails, # New param
                todos=todos,
                meetings=meetings,
                documents=documents,
                ghost_drafts=ghost_drafts
            )

        return {
            "emails": emails,
            "todos": todos,
            "meetings": meetings,
            "documents": documents,
            "ghost_drafts": ghost_drafts,
            "people": people,
            "reminders": reminders
        }

    async def _get_emails(self, user_id: int, fast_mode: bool = False) -> List[Dict]:
        """Fetch important unread emails using Gmail's IMPORTANT label."""
        if not self.email_service:
            logger.warning("[BriefService] No email service available")
            return []
            
        try:
            # Use structured parameters — search_emails builds its own Gmail query internally.
            # Do NOT pass raw Gmail syntax (e.g. "in:inbox newer_than:2d") as the query arg
            # because the search service strips/mangles it via junk-word removal.
            recent_cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y/%m/%d")
            
            logger.info(f"[BriefService] Searching recent inbox emails since {recent_cutoff}")
            
            # Explicitly disable RAG in fast_mode to avoid hitting timeouts (>1s)
            allow_rag = not fast_mode
            
            messages = await asyncio.to_thread(
                self.email_service.search_emails,
                query=None,           # No free-text query — just structural filters
                folder="inbox",       # Inbox only
                after_date=recent_cutoff,  # Last 7 days
                is_unread=None,       # Both read AND unread
                limit=25,             # Fetch more to survive promotional filtering
                allow_rag=allow_rag
            ) 
            
            logger.info(f"[BriefService] Found {len(messages)} emails")
            
            # Promotional sender patterns to exclude (be specific to avoid over-filtering)
            # Promotional sender patterns to exclude
            promo_patterns = ConfigDefaults.EMAIL_PROMO_PATTERNS
            
            brief_emails = []
            for msg in messages:
                sender = msg.get('sender', '').lower()
                logger.info(f"[BriefService] Checking email from: {sender}")
                
                # Skip promotional emails
                is_promo = any(pattern in sender for pattern in promo_patterns)
                
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

        except Exception as e:
            logger.error(f"[BriefService] Error fetching emails: {e}", exc_info=True)
            return []

    async def _get_recent_important_emails(self, user_id: int) -> List[Dict]:
        """
        Fetch recent emails (read or unread) that match high-impact keywords.
        Used specifically for Reminders to capture things like 'Investment offer' even if opened.
        """
        if not self.email_service:
            return []
            
        try:
            # Construct OR query with keywords
            # "newer_than:2d (urgent OR asap OR ...)"
            keywords_or = " OR ".join(f'"{kw}"' for kw in self.IMPACT_KEYWORDS)
            query = f"newer_than:2d ({keywords_or})"
            
            logger.info(f"[BriefService] Searching recent important emails: {query[:50]}...")
            
            # Fetch with strict limit since this is expensive/specific
            messages = await asyncio.to_thread(
                self.email_service.search_emails, 
                query=query, 
                limit=50, 
                allow_rag=False # pure keyword search
            )
            
            cleaned = []
            now = datetime.now()
            
            for msg in messages:
                # Double check 48h (API usually handles it but good to be safe)
                # And re-verify regex match to avoid partial word matches if API is loose
                
                # Check 48h logic verified earlier
                received_at = msg.get('date')
                # ... (date parsing logic similar to before, strictly enforcing 48h)
                # For brevity, trusting API 'newer_than:2d' mostly, but we can do a quick pass
                
                cleaned.append({
                    "id": msg.get('id'),
                    "subject": msg.get('subject', 'No Subject'),
                    "from": msg.get('sender', 'Unknown'),
                    "summary": msg.get('snippet', ''),
                    "received_at": msg.get('date'),
                    "thread_id": msg.get('threadId')
                })
            
            logger.info(f"[BriefService] Found {len(cleaned)} high-impact recent emails")
            return cleaned
            
        except Exception as e:
            logger.error(f"[BriefService] Error fetching important emails: {e}")
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
                        except Exception as e:
                            logger.warning(f"[BriefService] Date parsing failed for task {t.get('id')}: {e}")
                            # urgency defaults to medium if date parse fails
                            pass

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
            
            logger.info(f"[BriefService] Raw events before dedup: {len(todays_events)}")
            
            # Deduplicate by start_time at source level
            seen_times = set()
            deduped_events = []
            for evt in todays_events:
                st = evt.get('start_time')
                if st in seen_times:
                    logger.info(f"[BriefService] Deduping meeting at source: {evt.get('title')}")
                    continue
                seen_times.add(st)
                deduped_events.append(evt)
            
            logger.info(f"[BriefService] Returning {len(deduped_events)} deduplicated events")
                
            return deduped_events
            
        except Exception as e:
            logger.error(f"[BriefService] Calendar error: {e}", exc_info=True)
            return []

    async def _get_ghost_drafts(self, user_id: int) -> List[Dict]:
        """Fetch pending Ghost drafts."""
        def fetch_drafts():
            try:
                with get_db_context() as session:
                    query = select(GhostDraft).where(
                        and_(
                            GhostDraft.user_id == user_id,
                            GhostDraft.status == 'draft'
                        )
                    ).order_by(GhostDraft.created_at.desc()).limit(5)
                    
                    drafts = session.execute(query).scalars().all()
                    return [{
                        "id": d.id,
                        "title": d.title,
                        "type": "draft",
                        "integration": d.integration_type,
                        "confidence": d.confidence
                    } for d in drafts]
            except Exception as e:
                logger.error(f"[BriefService] Ghost drafts error: {e}")
                return []
                
        return await asyncio.to_thread(fetch_drafts)

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
    
    async def _get_people(self, user_id: int) -> Dict[str, Any]:
        """Get People CRM data: inner circle + fading contacts."""
        try:
            from src.services.crm.personal_crm import get_personal_crm
            crm = get_personal_crm()
            if not crm:
                return {}
            
            from dataclasses import asdict
            
            # Fetch inner circle (top 5) and fading contacts (up to 3) in parallel
            inner_circle_task = crm.get_inner_circle(user_id=user_id, limit=5)
            fading_task = crm.get_fading_contacts(user_id=user_id, limit=3)
            
            inner_circle, fading = await asyncio.gather(
                inner_circle_task, fading_task,
                return_exceptions=True
            )
            
            inner = [asdict(c) for c in inner_circle] if isinstance(inner_circle, list) else []
            fade = [asdict(c) for c in fading] if isinstance(fading, list) else []
            
            # Build nudge messages for fading contacts
            nudges = []
            for contact in fade:
                name = contact.get('name', 'Someone')
                last = contact.get('last_interaction', '')
                nudges.append(f"You haven't connected with {name} recently")
            
            return {
                "inner_circle": inner,
                "fading_contacts": fade,
                "nudges": nudges,
                "total_inner_circle": len(inner),
                "total_fading": len(fade)
            }
        except Exception as e:
            logger.debug(f"[BriefService] People CRM fetch error: {e}")
            return {}

    async def _get_reminders(self, user_id: int) -> List[Dict]:
        """
        Get proactive reminders:
        - Bills, Appointments, Deadlines from ActionableItems
        - Fallback: Upcoming calendar events (next 7 days)
        """
        reminders = []
        
        # 1. First, check ActionableItems database
        try:
            def fetch_db_reminders():
                reminders_list = []
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
                            reminders_list.append({
                                "id": item.id,
                                "title": item.title,
                                "type": item.item_type,
                                "due_date": item.due_date.isoformat() if item.due_date else None,
                                "amount": item.amount,
                                "urgency": item.urgency,
                                "action": item.suggested_action
                            })
                except Exception as e:
                    logger.error(f"[BriefService] Reminders DB error inner: {e}")
                return reminders_list
                
            reminders = await asyncio.to_thread(fetch_db_reminders)
                    
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

    async def _get_llm_classified_reminders(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Fetch LLM-classified reminders from the database.
        
        These are pre-processed by the background classification task
        and represent messages that Gemini determined need user attention.
        """
        from src.database.models import MessageClassification
        
        cutoff = datetime.now() - timedelta(hours=48)
        reminders = []
        
        try:
            with get_db_context() as session:
                results = session.query(MessageClassification).filter(
                    and_(
                        MessageClassification.user_id == user_id,
                        MessageClassification.needs_response == True,
                        MessageClassification.is_dismissed == False,
                        MessageClassification.classified_at >= cutoff
                    )
                ).order_by(
                    # High urgency first (alphabetically: 'high' < 'low' < 'medium')
                    MessageClassification.urgency.asc(),
                    MessageClassification.classified_at.desc()
                ).limit(10).all()
                
                for r in results:
                    reminders.append({
                        "title": r.title,
                        "subtitle": f"from {r.sender}" if r.sender else r.classification_reason,
                        "type": r.source_type,
                        "urgency": r.urgency,
                        "due_date": r.source_date.isoformat() if r.source_date else None,
                        "id": f"llm_{r.id}",
                        "source_id": r.source_id,  # Original message ID for deduplication
                        "suggested_action": r.suggested_action,
                        "reason": r.classification_reason,
                        "is_llm_classified": True  # Flag for UI
                    })
                    
        except Exception as e:
            logger.error(f"[BriefService] Error fetching LLM classifications: {e}")
        
        return reminders

    async def _generate_smart_reminders(
        self,
        user_id: int,
        user_name: str,
        emails: List[Dict],
        todos: List[Dict],
        meetings: List[Dict],
        urgent_emails: List[Dict] = [], # New
        documents: List[Dict] = [],
        ghost_drafts: List[Dict] = []
    ) -> Dict[str, Any]:
        """
        Generate intelligent reminders.
        
        Uses LLM classifications from database as primary source.
        Falls back to keyword matching for emails not yet classified.
        """
        items = []
        
        # PRIORITY 1: LLM-Classified Reminders (from background task)
        # These are pre-analyzed by Gemini for intelligent prioritization
        try:
            llm_reminders = await self._get_llm_classified_reminders(user_id)
            if llm_reminders:
                logger.info(f"[BriefService][Reminders] Found {len(llm_reminders)} LLM-classified reminders")
                items.extend(llm_reminders)
        except Exception as e:
            logger.warning(f"[BriefService] LLM classification fetch failed: {e}")
        
        # Track which email IDs are already in LLM reminders (to avoid duplicates)
        llm_email_ids = set()
        for item in items:
            if item.get('type') == 'email' and item.get('source_id'):
                llm_email_ids.add(item.get('source_id'))
        
        # FALLBACK: Keyword-based Email Matching (for unclassified emails)
        
        # 1. Process Emails for Reminders
        # Combine unread 'emails' and 'urgent_emails' (which might be read)
        # Deduplicate by ID
        all_candidate_emails = {e['id']: e for e in emails}
        for e in urgent_emails:
            all_candidate_emails[e['id']] = e # urgent_emails take precedence or are just added
            
        candidate_list = list(all_candidate_emails.values())
        
        logger.info(f"[BriefService][Reminders] Total email candidates: {len(candidate_list)} (unread={len(emails)}, urgent={len(urgent_emails)})")
        for c in candidate_list:
            logger.info(f"  -> Candidate: {c.get('subject', 'N/A')[:50]}")
        
        # Filter: Last 48h AND High Impact
        impact_keywords = self.IMPACT_KEYWORDS
        
        now = datetime.now()
        email_reminders_added = 0
        
        for email in candidate_list:
            # 1. Check Date (Last 48 hours)
            received_at = email.get('received_at')
            if not received_at:
                continue
                
            try:
                # Handle ISO format variations (often returned by Gmail/Graph)
                # Ensure we handle Z or +00:00
                email_dt = None
                if isinstance(received_at, str):
                    try:
                        # Try RFC 2822 first (standard for email)
                        email_dt = parsedate_to_datetime(received_at)
                    except Exception:
                        # Fallback to ISO
                        try:
                            email_dt = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
                        except ValueError:
                             pass
                elif isinstance(received_at, datetime):
                    email_dt = received_at
                
                if not email_dt:
                    continue
                    
                # Normalize timezones for comparison
                if email_dt.tzinfo and now.tzinfo:
                    diff = now - email_dt
                elif not email_dt.tzinfo and not now.tzinfo:
                    diff = now - email_dt
                elif email_dt.tzinfo:
                     diff = now.replace(tzinfo=email_dt.tzinfo) - email_dt
                else:
                     diff = now - email_dt.replace(tzinfo=None)

                if diff > timedelta(hours=48):
                    continue
            except Exception as e:
                logger.warning(f"[BriefService] Date parse failed for reminder check: {e}")
                continue

            # 2. Check Keywords (Title or Summary)
            subject = email.get('subject', '').lower()
            summary = email.get('summary', '').lower()
            snippet = email.get('snippet', '').lower()
            
            content_to_check = f"{subject} {summary} {snippet}"
            
            # Use regex for word boundary matching
            is_high_impact = any(
                re.search(r'\b' + re.escape(kw) + r'\b', content_to_check) 
                for kw in impact_keywords
            )
            
            if is_high_impact:
                # Clean up subject for natural display (remove "Re:", "Fwd:", etc.)
                raw_subject = email.get('subject', 'Email')
                clean_subject = raw_subject
                for prefix in ['Re: ', 'RE: ', 'Fwd: ', 'FWD: ', 'Fw: ']:
                    if clean_subject.startswith(prefix):
                        clean_subject = clean_subject[len(prefix):]
                
                logger.info(f"[BriefService][Reminders] ✓ Adding email reminder: {clean_subject[:50]}")
                items.append({
                    "title": clean_subject,  # Just the subject, natural
                    "subtitle": f"from {email.get('from', 'Unknown').split('<')[0].strip()}",  # "from John Doe"
                    "type": "email",
                    "urgency": "high",
                    "due_date": received_at,
                    "id": email.get('id')
                })
                email_reminders_added += 1
                # Limit to 5 max email reminders
                if email_reminders_added >= 5:
                    break
            else:
                logger.info(f"[BriefService][Reminders] ✗ Skipping (no keyword match): {email.get('subject', 'N/A')[:50]}")
        
        # 2. Add pending todos (recent only - last 48h, max 5)
        # Filter out:
        # - Items older than 48h to keep reminders fresh
        # - Placeholder/test items
        placeholder_patterns = ['task 1', 'task 2', 'task 3', 'test task', 'placeholder', 'review overdue']
        todos_added = 0
        
        for todo in todos:
            if todos_added >= 5:
                break
                
            title = todo.get('title', '').lower()
            
            # Skip obvious test/placeholder items
            if any(p in title for p in placeholder_patterns):
                logger.info(f"[BriefService][Reminders] Skipping placeholder todo: {title}")
                continue
                
            # Check due date - only include items from last 48h or upcoming
            due_date = todo.get('due_date')
            if due_date:
                try:
                    if isinstance(due_date, str):
                        due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                    else:
                        due_dt = due_date
                    
                    # Calculate difference
                    if due_dt.tzinfo:
                        diff = now.replace(tzinfo=due_dt.tzinfo) - due_dt
                    else:
                        diff = now - due_dt.replace(tzinfo=None)
                    
                    # Skip if older than 48h (overdue by more than 2 days)
                    if diff > timedelta(hours=48):
                        logger.info(f"[BriefService][Reminders] Skipping old todo (>48h): {title}")
                        continue
                except Exception:
                    pass  # If can't parse, include it
            
            items.append({
                "title": todo.get('title', 'Task'),
                "subtitle": todo.get('source', 'task'),
                "type": "todo",
                "urgency": todo.get('urgency', 'medium'),
                "due_date": due_date,
                "id": todo.get('id')
            })
            todos_added += 1
        
        # 3. Add meetings within next 48 hours only (deduplicated by time)
        seen_start_times = set()  # Deduplicate by start time only - same time = same event
        
        for meeting in meetings:
            start_time = meeting.get('start_time')
            
            # Simple deduplication: Skip if we already have a meeting at this exact time
            if start_time in seen_start_times:
                continue
            
            # Filter: Only meetings within 48h window
            if start_time:
                try:
                    if isinstance(start_time, str):
                        meeting_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    else:
                        meeting_dt = start_time
                    
                    # Calculate how far in past/future
                    if meeting_dt.tzinfo:
                        diff = meeting_dt - now.replace(tzinfo=meeting_dt.tzinfo)
                    else:
                        diff = meeting_dt.replace(tzinfo=None) - now
                    
                    # Skip if meeting is more than 48h away or more than 24h in past
                    if diff > timedelta(hours=48) or diff < timedelta(hours=-24):
                        continue
                except Exception:
                    pass  # If can't parse, include it
            
            seen_start_times.add(start_time)
            title = meeting.get('title', 'Meeting')
                    
            items.append({
                "title": title,
                "subtitle": meeting.get('location') or 'No location',
                "type": "meeting",
                "urgency": "high" if self._is_soon(start_time) else "medium",
                "due_date": start_time,
                "id": meeting.get('id')
            })
            
        # 3b. Add important documents (Starred and updated within 48h only)
        for doc in documents:
            if doc.get('starred'):
                # Filter: Only docs updated within 48h
                updated_at = doc.get('updated_at')
                if updated_at:
                    try:
                        if isinstance(updated_at, str):
                            doc_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        else:
                            doc_dt = updated_at
                        
                        if doc_dt.tzinfo:
                            diff = now.replace(tzinfo=doc_dt.tzinfo) - doc_dt
                        else:
                            diff = now - doc_dt.replace(tzinfo=None)
                        
                        if diff > timedelta(hours=48):
                            continue  # Skip old docs
                    except Exception:
                        pass
                        
                items.append({
                    "title": doc.get('title'),
                    "subtitle": "Starred Document",
                    "type": "document",
                    "urgency": "medium",
                    "due_date": updated_at,
                    "id": doc.get('id'),
                    "link": doc.get('link')
                })
        
        # 3c. Add Ghost Drafts (High confidence ones)
        for draft in ghost_drafts:
            # We only add clearly high-confidence drafts to the primary reminders list
            # to avoid cluttering with low-confidence "ghost noise"
            if draft.get('confidence', 0) > 0.7:
                items.append({
                    "title": f"Review {draft.get('integration', 'Linear')} Draft: {draft.get('title')}",
                    "subtitle": "Proactive Ghost Suggestion",
                    "type": "ghost_draft",
                    "urgency": "high" if draft.get('confidence', 0) > 0.9 else "medium",
                    "due_date": datetime.now().isoformat(), # Suggestions are always "for now"
                    "id": f"ghost_{draft.get('id')}"
                })
    
        # 4. Also check ActionableItems (bills, deadlines) from database - only within 48h
        try:
            # Calculate 48h cutoff
            cutoff_past = now - timedelta(hours=48)
            cutoff_future = now + timedelta(hours=48)
            
            with get_db_context() as session:
                query = select(ActionableItem).where(
                    and_(
                        ActionableItem.user_id == user_id,
                        ActionableItem.status == 'pending',
                        ActionableItem.item_type.in_(['bill', 'appointment', 'deadline']),
                        # Only items due within 48h window (past or future)
                        or_(
                            ActionableItem.due_date.is_(None),  # No due date = include
                            and_(
                                ActionableItem.due_date >= cutoff_past,
                                ActionableItem.due_date <= cutoff_future
                            )
                        )
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
        
        # COMPREHENSIVE DEDUPLICATION - By normalized title
        # This catches duplicates even if they have different IDs
        logger.info(f"[BriefService] Items BEFORE final dedup: {len(items)}")
        for i in items:
            logger.info(f"  -> [{i.get('type')}] {i.get('title')} @ {i.get('due_date')}")
        
        # Pre-sort: Prefer non-midnight times over midnight (all-day events)
        # This ensures we keep the meeting with a specific time, not the all-day marker
        def time_preference(item):
            due = item.get('due_date', '')
            if not due:
                return 1  # No date = low priority
            # Check if time is midnight (00:00) - likely all-day event
            if isinstance(due, str) and ('T00:00:00' in due or 'T00:00' in due.split('+')[0].split('-')[0]):
                return 1  # Midnight = low priority (all-day event)
            return 0  # Specific time = high priority
        
        items.sort(key=time_preference)
        
        seen_titles = set()
        deduped_items = []
        for item in items:
            # Build key from significant words only
            raw_title = item.get('title', '').lower()
            item_type = item.get('type', 'unknown')
            
            # Tokenize and filter stop words
            stop_words = {'zoom', 'interview', 'call', 'meeting', 'with', 'the', 'for', 'and', 
                          'reply', 'fwd', 're', 'to', "maniko's", 'maniko'}
            words = raw_title.replace("'s", '').replace(":", '').split()
            significant_words = [w for w in words if len(w) > 1 and w not in stop_words][:3]
            title_key = ' '.join(sorted(significant_words))
            
            # If key is empty (all stop words), use first 10 chars of title
            if not title_key:
                title_key = raw_title[:10]
            
            # Include type in key to avoid cross-type deduplication
            dedup_key = f"{item_type}:{title_key}"
            
            if dedup_key in seen_titles:
                logger.info(f"[BriefService] Final dedup - removing: {raw_title} (key: {dedup_key})")
                continue
            
            seen_titles.add(dedup_key)
            deduped_items.append(item)
        
        logger.info(f"[BriefService] Items AFTER final dedup: {len(deduped_items)}")
        items = deduped_items
        
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
        except (ValueError, TypeError, AttributeError):
            # Datetime parsing failed
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
            # 0. Check Ghost Drafts (High confidence ones)
            ghost_drafts = await self._get_ghost_drafts(user_id)
            for draft in ghost_drafts:
                if draft.get('confidence', 0) > 0.8:
                    return f"I've drafted a {draft.get('integration')} issue for you: '{draft.get('title')}'"

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
            # 3. Check Database ActionableItems (Bills/Deadlines due today)
            try:
                def check_db_urgent():
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
                    except Exception as e:
                         logger.error(f"[BriefService] ActionableItem reminder query failed: {e}")
                    return None
                
                db_result = await asyncio.to_thread(check_db_urgent)
                if db_result:
                    return db_result
            except Exception as e:
                logger.error(f"[BriefService] ActionableItem wrapper failed: {e}")
                pass

            return None
        except Exception as e:
            logger.error(f"[BriefService] Critical reminder failed: {e}")
            return None
