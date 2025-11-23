"""
Calendar Integration Module for Task Tool

Handles all calendar-related task operations including:
- Creating tasks from calendar events
- Scheduling task work time in calendar
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from ..constants import TaskTimingConfig
from .constants import DEFAULT_DURATION_MINUTES, DEFAULT_PRIORITY

logger = setup_logger(__name__)


class CalendarIntegration:
    """Handles calendar-related task operations"""
    
    def __init__(self, task_tool):
        """
        Initialize calendar integration
        
        Args:
            task_tool: Reference to parent TaskTool instance
        """
        self.task_tool = task_tool
    
    def create_task_from_event(
        self,
        event_id: str,
        event_data: Dict[str, Any],
        task_type: str = "preparation"
    ) -> str:
        """
        Create task from calendar event (preparation or follow-up)
        
        Args:
            event_id: Calendar event ID
            event_data: Event details (title, start, end, description)
            task_type: "preparation" (before event) or "follow-up" (after event)
            
        Returns:
            Success message with task ID
        """
        try:
            title = event_data.get('title', 'Event Task')
            start_time = event_data.get('start', '')
            description = event_data.get('description', '')
            
            if task_type == "preparation":
                task_desc, due_date, notes = self._create_prep_task_data(
                    title, start_time, description
                )
            else:  # follow-up
                task_desc, due_date, notes = self._create_followup_task_data(
                    title, start_time, description
                )
            
            # Create task
            result = self.task_tool._create_task(
                description=task_desc,
                due_date=due_date,
                priority=DEFAULT_PRIORITY,
                tags=['calendar', task_type],
                notes=notes,
                category='meeting'
            )
            
            logger.info(f"[CALENDAR->TASK] Created {task_type} task for event {event_id}: {task_desc}")
            return result
            
        except Exception as e:
            return self.task_tool._handle_error(e, "creating task from calendar event")
    
    def schedule_task_time(
        self,
        task_id: str,
        preferred_time: Optional[str] = None,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
        calendar_tool: Optional[Any] = None
    ) -> str:
        """
        Schedule time in calendar for working on task
        
        Args:
            task_id: Task ID
            preferred_time: Preferred time slot (ISO or natural language)
            duration_minutes: Duration to block
            calendar_tool: CalendarTool instance (for integration)
            
        Returns:
            Success message or instructions
        """
        try:
            # Get task details
            task = self._get_task(task_id)
            
            if not task:
                return f"[ERROR] Task {task_id} not found"
            
            task_desc = task.get('description', 'Task')
            
            # If no calendar_tool provided, return instructions
            if not calendar_tool:
                return f"""[INFO] To schedule time for this task, use:
calendar_tool.create_event(
    title="Work on: {task_desc}",
    start_time="{preferred_time or 'your preferred time'}",
    duration_minutes={duration_minutes}
)"""
            
            # Create calendar event via CalendarTool
            event_title = f"Work on: {task_desc}"
            event_desc = f"Focused time for task: {task_desc}\nTask ID: {task_id}"
            
            result = calendar_tool.create_event(
                title=event_title,
                start_time=preferred_time,
                duration_minutes=duration_minutes,
                description=event_desc
            )
            
            logger.info(f"[TASK->CALENDAR] Scheduled {duration_minutes}min for task {task_id}")
            return self.task_tool._format_success(
                f"Scheduled {duration_minutes}-minute work session for '{task_desc}'\n\n{result}"
            )
            
        except Exception as e:
            return self.task_tool._handle_error(e, "scheduling task time in calendar")
    
    def _create_prep_task_data(
        self,
        title: str,
        start_time: str,
        description: str
    ) -> tuple:
        """Create preparation task data"""
        task_desc = f"Prepare for {title}"
        
        # Due configured hours before event
        due_date = None
        if start_time:
            try:
                event_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                due_dt = event_dt - timedelta(hours=TaskTimingConfig.PREP_TASK_HOURS_BEFORE_EVENT)
                due_date = due_dt.isoformat()
            except:
                due_date = start_time
        
        notes = f"Preparation for event: {title}\nTime: {start_time}\n{description}"
        
        return task_desc, due_date, notes
    
    def _create_followup_task_data(
        self,
        title: str,
        start_time: str,
        description: str
    ) -> tuple:
        """Create follow-up task data"""
        task_desc = f"Follow up on {title}"
        
        # Due configured days after event
        due_date = None
        if start_time:
            try:
                event_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                due_dt = event_dt + timedelta(days=TaskTimingConfig.FOLLOWUP_TASK_DAYS_AFTER_EVENT)
                due_date = due_dt.isoformat()
            except:
                due_date = None
        
        notes = f"Follow-up for event: {title}\nCompleted: {start_time}\n{description}"
        
        return task_desc, due_date, notes
    
    def _get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task from Google Tasks or local manager"""
        if self.task_tool.google_client and self.task_tool.google_client.is_available():
            return self.task_tool.google_client.get_task(task_id)
        elif self.task_tool.manager:
            return self.task_tool.manager.get_task(task_id)
        return None
