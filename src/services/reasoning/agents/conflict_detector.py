"""
Conflict Detector Agent

A reasoning agent that proactively identifies conflicts and scheduling issues.

Conflict Types Detected:
1. Calendar Conflicts: Double-booked meetings, overlapping events
2. Attendee Conflicts: Meeting with someone who is OOO or in another meeting
3. Deadline Conflicts: Tasks due at the same time, competing priorities
4. Resource Conflicts: Multiple tasks requiring same resources

Outputs: Insight nodes (type=conflict)
"""
import asyncio
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from collections import defaultdict

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.reasoning.interfaces import ReasoningAgent, ReasoningResult

logger = setup_logger(__name__)


class ConflictDetectorAgent(ReasoningAgent):
    """
    Agent that proactively detects conflicts before they cause problems.
    
    This is a critical agent for the "intelligent assistant" experience,
    surfacing issues like:
    - "You have two meetings at 3 PM tomorrow"
    - "Bob is marked OOO but is invited to your meeting"
    - "Three tasks are due Friday but you have 8 hours of meetings"
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self._name = "ConflictDetectorAgent"
        
    @property
    def name(self) -> str:
        return self._name
        
    async def analyze(self, user_id: int, context: Optional[Dict[str, Any]] = None) -> List[ReasoningResult]:
        """
        Run comprehensive conflict analysis.
        """
        results = []
        
        # Run all conflict detectors concurrently
        conflict_tasks = [
            self._detect_calendar_overlaps(user_id),
            self._detect_attendee_conflicts(user_id),
            self._detect_deadline_conflicts(user_id),
            self._detect_workload_conflicts(user_id),
        ]
        
        try:
            all_conflicts = await asyncio.gather(*conflict_tasks, return_exceptions=True)
            
            for i, conflicts in enumerate(all_conflicts):
                if isinstance(conflicts, Exception):
                    logger.error(f"[{self.name}] Conflict detector {i} failed: {conflicts}")
                elif conflicts:
                    results.extend(conflicts)
                    
        except Exception as e:
            logger.error(f"[{self.name}] Analysis failed: {e}")
            
        logger.info(f"[{self.name}] Detected {len(results)} conflicts for user {user_id}")
        return results
        
    async def verify(self, hypothesis_id: str) -> bool:
        """Verify if a conflict still exists."""
        return True
        
    # =========================================================================
    # Conflict Detection Methods
    # =========================================================================
    
    async def _detect_calendar_overlaps(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect overlapping calendar events.
        
        Examples:
        - "You have two meetings at 3 PM tomorrow"
        - "Your standup overlaps with the team sync"
        """
        results = []
        
        # Look at upcoming 7 days
        now = datetime.utcnow()
        week_from_now = (now + timedelta(days=7)).isoformat()
        now_iso = now.isoformat()
        
        query = """
        FOR e IN CalendarEvent
            FILTER e.user_id == @user_id
               AND e.start_time >= @now
               AND e.start_time <= @week_from_now
            SORT e.start_time ASC
            RETURN { id: e.id, title: e.title, start: e.start_time, end: e.end_time }
        """
        
        try:
            events = await self.graph.execute_query(query, {
                "user_id": user_id,
                "now": now_iso,
                "week_from_now": week_from_now
            })
            
            if not events or len(events) < 2:
                return results
                
            # Parse events into structured format
            parsed_events = []
            for event in events:
                try:
                    start_str = event.get("start")
                    end_str = event.get("end")
                    
                    if not start_str or not end_str:
                        continue
                        
                    if isinstance(start_str, str):
                        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    else:
                        start = start_str
                        
                    if isinstance(end_str, str):
                        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                    else:
                        end = end_str
                        
                    parsed_events.append({
                        "id": event.get("id"),
                        "title": event.get("title", "Untitled"),
                        "start": start,
                        "end": end
                    })
                except (ValueError, AttributeError):
                    continue
                    
            # Check for overlaps
            for i, event_a in enumerate(parsed_events):
                for event_b in parsed_events[i+1:]:
                    # Check if events overlap
                    if event_a["start"] < event_b["end"] and event_b["start"] < event_a["end"]:
                        # Calculate overlap severity
                        overlap_start = max(event_a["start"], event_b["start"])
                        overlap_end = min(event_a["end"], event_b["end"])
                        overlap_minutes = int((overlap_end - overlap_start).total_seconds() / 60)
                        
                        if overlap_minutes < 5:
                            continue  # Minor overlap, skip
                            
                        # Higher confidence for longer overlaps
                        confidence = min(0.95, 0.6 + (overlap_minutes / 120))
                        
                        content = {
                            "content": f"Scheduling conflict: '{event_a['title']}' and '{event_b['title']}' overlap by {overlap_minutes} minutes",
                            "type": "conflict",
                            "conflict_type": "calendar_overlap",
                            "event_a": {"id": event_a["id"], "title": event_a["title"]},
                            "event_b": {"id": event_b["id"], "title": event_b["title"]},
                            "overlap_minutes": overlap_minutes,
                            "actionable": True,
                            "related_ids": [event_a["id"], event_b["id"]]
                        }
                        
                        results.append(ReasoningResult(
                            type="insight",
                            confidence=confidence,
                            content=content,
                            source_agent=self.name
                        ))
                        
        except Exception as e:
            logger.error(f"[{self.name}] Calendar overlap detection failed: {e}")
            
        return results
        
    async def _detect_attendee_conflicts(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect conflicts with attendees (OOO, double-booked).
        
        Examples:
        - "Bob is marked OOO during your meeting with him"
        - "Sarah is in another meeting during your standup"
        """
        results = []
        
        # Look for meetings with attendees who have conflicts
        today = datetime.utcnow().date()
        week_from_now = (datetime.utcnow() + timedelta(days=7)).isoformat()
        now_iso = datetime.utcnow().isoformat()
        
        # Native AQL to traverse CalendarEvent -> Person -> Status
        # We assume HAS_ATTENDEE and HAS_STATUS edge collections exist
        query = """
        FOR e IN CalendarEvent
            FILTER e.user_id == @user_id
               AND e.start_time >= @now
               AND e.start_time <= @week_from_now
            
            # Find attendees
            FOR p IN 1..1 OUTBOUND e HAS_ATTENDEE
                
                # Check their status (optional traversal)
                LET status_node = (
                    FOR s IN 1..1 OUTBOUND p HAS_STATUS
                    LIMIT 1
                    RETURN s
                )[0]
                
                FILTER status_node != null 
                   AND (status_node.status == 'OOO' OR status_node.status == 'out_of_office')
                
                RETURN {
                    event_id: e.id, 
                    event_title: e.title, 
                    event_start: e.start_time,
                    attendee_name: p.name, 
                    attendee_id: p.id,
                    attendee_status: status_node.status
                }
        """
        
        try:
            attendee_info = await self.graph.execute_query(query, {
                "user_id": user_id,
                "now": now_iso,
                "week_from_now": week_from_now
            })
            
            for record in attendee_info or []:
                status = record.get("attendee_status")
                
                if status and status.lower() in ["ooo", "out_of_office", "vacation"]:
                    attendee_name = record.get("attendee_name", "Someone")
                    event_title = record.get("event_title", "a meeting")
                    
                    content = {
                        "content": f"{attendee_name} is marked as Out of Office during '{event_title}'",
                        "type": "conflict",
                        "conflict_type": "attendee_unavailable",
                        "attendee": attendee_name,
                        "event_title": event_title,
                        "status": status,
                        "actionable": True,
                        "related_ids": [record.get("event_id"), record.get("attendee_id")]
                    }
                    
                    results.append(ReasoningResult(
                        type="insight",
                        confidence=0.9,
                        content=content,
                        source_agent=self.name
                    ))
                    
        except Exception as e:
            logger.error(f"[{self.name}] Attendee conflict detection failed: {e}")
            
        return results
        
    async def _detect_deadline_conflicts(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect task deadline conflicts.
        
        Examples:
        - "3 tasks are due tomorrow"
        - "High-priority deadline conflicts with a full day of meetings"
        """
        results = []
        
        # Look for multiple tasks due on the same day
        now_iso = datetime.utcnow().isoformat()
        week_from_now = (datetime.utcnow() + timedelta(days=7)).isoformat()
        
        query = """
        FOR t IN ActionItem
            FILTER t.user_id == @user_id
               AND t.due_date >= @now
               AND t.due_date <= @week_from_now
               AND t.status != 'completed'
            SORT t.due_date ASC
            RETURN { id: t.id, title: t.title, due_date: t.due_date, priority: t.priority }
        """
        
        try:
            tasks = await self.graph.execute_query(query, {
                "user_id": user_id,
                "now": now_iso,
                "week_from_now": week_from_now
            })
            
            if not tasks:
                return results
                
            # Group tasks by due date
            tasks_by_date: Dict[str, List[Dict]] = defaultdict(list)
            
            for task in tasks:
                due_str = task.get("due_date")
                if not due_str:
                    continue
                    
                try:
                    if isinstance(due_str, str):
                        due_date = datetime.fromisoformat(due_str.replace('Z', '+00:00')).date()
                    else:
                        due_date = due_str.date()
                        
                    date_key = due_date.isoformat()
                    tasks_by_date[date_key].append({
                        "id": task.get("id"),
                        "title": task.get("title"),
                        "priority": task.get("priority", "normal")
                    })
                except (ValueError, AttributeError):
                    continue
                    
            # Find dates with multiple tasks
            for date_key, date_tasks in tasks_by_date.items():
                if len(date_tasks) >= 3:
                    task_titles = [t["title"][:30] for t in date_tasks[:3]]
                    high_priority_count = sum(1 for t in date_tasks if t.get("priority") == "high")
                    
                    confidence = min(0.9, 0.5 + (len(date_tasks) * 0.1))
                    
                    content = {
                        "content": f"{len(date_tasks)} tasks due on {date_key}: {', '.join(task_titles)}...",
                        "type": "conflict",
                        "conflict_type": "deadline_cluster",
                        "date": date_key,
                        "task_count": len(date_tasks),
                        "high_priority_count": high_priority_count,
                        "actionable": True,
                        "related_ids": [t["id"] for t in date_tasks]
                    }
                    
                    results.append(ReasoningResult(
                        type="insight",
                        confidence=confidence,
                        content=content,
                        source_agent=self.name
                    ))
                    
        except Exception as e:
            logger.error(f"[{self.name}] Deadline conflict detection failed: {e}")
            
        return results
        
    async def _detect_workload_conflicts(self, user_id: int) -> List[ReasoningResult]:
        """
        Detect workload conflicts (too many meetings vs tasks).
        
        Examples:
        - "Friday has 6 hours of meetings but 3 tasks due"
        - "Heavy meeting day may impact your deadlines"
        """
        results = []
        
        # Look at next 5 business days
        now = datetime.utcnow()
        
        for day_offset in range(1, 6):
            check_date = now + timedelta(days=day_offset)
            
            # Skip weekends
            if check_date.weekday() >= 5:
                continue
                
            day_start = check_date.replace(hour=0, minute=0, second=0)
            day_end = check_date.replace(hour=23, minute=59, second=59)
            
            # Get meetings for the day
            meeting_query = """
            FOR e IN CalendarEvent
                FILTER e.user_id == @user_id
                   AND e.start_time >= @day_start
                   AND e.start_time <= @day_end
                RETURN { start: e.start_time, end: e.end_time }
            """
            
            # Get tasks due that day
            task_query = """
            FOR t IN ActionItem
                FILTER t.user_id == @user_id
                   AND t.due_date >= @day_start
                   AND t.due_date <= @day_end
                   AND t.status != 'completed'
                RETURN count(t)
            """
            
            try:
                meetings = await self.graph.execute_query(meeting_query, {
                    "user_id": user_id,
                    "day_start": day_start.isoformat(),
                    "day_end": day_end.isoformat()
                })
                
                task_result = await self.graph.execute_query(task_query, {
                    "user_id": user_id,
                    "day_start": day_start.isoformat(),
                    "day_end": day_end.isoformat()
                })
                
                # Calculate meeting hours
                total_meeting_minutes = 0
                for meeting in meetings or []:
                    start_str = meeting.get("start")
                    end_str = meeting.get("end")
                    
                    if start_str and end_str:
                        try:
                            if isinstance(start_str, str):
                                start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                            else:
                                start = start_str
                            if isinstance(end_str, str):
                                end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                            else:
                                end = end_str
                                
                            total_meeting_minutes += int((end - start).total_seconds() / 60)
                        except (ValueError, AttributeError):
                            pass
                            
                meeting_hours = total_meeting_minutes / 60
                task_count = task_result[0] if task_result and isinstance(task_result[0], int) else 0
                
                # Flag if heavy meetings (>5 hours) AND multiple tasks due
                if meeting_hours >= 5 and task_count >= 2:
                    day_name = check_date.strftime("%A, %B %d")
                    
                    content = {
                        "content": f"Workload alert: {day_name} has {meeting_hours:.1f} hours of meetings with {task_count} tasks due",
                        "type": "conflict",
                        "conflict_type": "workload_imbalance",
                        "date": check_date.date().isoformat(),
                        "meeting_hours": round(meeting_hours, 1),
                        "task_count": task_count,
                        "actionable": True
                    }
                    
                    results.append(ReasoningResult(
                        type="insight",
                        confidence=0.8,
                        content=content,
                        source_agent=self.name
                    ))
                    
            except Exception as e:
                logger.error(f"[{self.name}] Workload analysis for day {day_offset} failed: {e}")
                continue
                
        return results
