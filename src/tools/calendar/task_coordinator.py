"""
Calendar-Task Coordination Module

Automatically creates preparation and follow-up tasks for calendar events.
Helps users stay organized with intelligent task suggestions for meetings.

Features:
- Create prep tasks before meetings
- Create follow-up tasks after meetings
- AI-powered task suggestions based on meeting type
- Schedule dedicated prep time in calendar
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from ...core.calendar.utils import DEFAULT_DURATION_MINUTES, DEFAULT_DAYS_AHEAD
from ..constants import TaskTimingConfig
from ..tasks.constants import DEFAULT_PRIORITY

logger = setup_logger(__name__)

# Constants for task coordinator
DEFAULT_PREP_HOURS_BEFORE = 24
DEFAULT_FOLLOWUP_DAYS_AFTER = 1
LARGE_MEETING_ATTENDEE_THRESHOLD = 5
MULTIPLE_ATTENDEES_THRESHOLD = 1
MAX_PREP_TASKS = 3
MAX_FOLLOWUP_TASKS = 2
PREP_TIME_BUFFER_HOURS = 1
MAX_PREP_TIME_SUGGESTIONS = 1
DEFAULT_TASK_CATEGORY = 'work'  # Default category for meeting-related tasks


class CalendarTaskCoordinator:
    """Coordinate calendar events with automatic task creation"""
    
    def __init__(self, calendar_service: Any, task_service: Any):
        """
        Initialize coordinator with services
        
        Args:
            calendar_service: CalendarService instance
            task_service: TaskService instance
        """
        self.calendar_service = calendar_service
        self.task_service = task_service
        logger.info("[CAL_TASK] CalendarTaskCoordinator initialized")
    
    def create_prep_tasks(
        self,
        event_id: str,
        event_data: Dict[str, Any],
        prep_hours_before: int = DEFAULT_PREP_HOURS_BEFORE,
        auto_suggestions: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Create preparation tasks before a meeting
        
        Args:
            event_id: Calendar event ID
            event_data: Event details (title, start_time, description, attendees)
            prep_hours_before: Hours before meeting to set task due date
            auto_suggestions: Use AI to suggest additional prep tasks
            
        Returns:
            List of created tasks
        """
        logger.info(f"[CAL_TASK] Creating prep tasks for event: {event_data.get('summary', 'Untitled')}")
        
        title = event_data.get('summary', event_data.get('title', 'Untitled Event'))
        start_time_str = event_data.get('start_time', event_data.get('start', {}).get('dateTime'))
        description = event_data.get('description', '')
        attendees = event_data.get('attendees', [])
        
        # Calculate prep task due date (before the meeting)
        if start_time_str:
            try:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                prep_due = start_time - timedelta(hours=prep_hours_before)
                prep_due_str = prep_due.date().isoformat()
            except:
                prep_due_str = None
        else:
            prep_due_str = None
        
        created_tasks = []
        
        # Standard prep tasks based on meeting type
        prep_tasks = self._generate_standard_prep_tasks(title, description, attendees)
        
        # Create each prep task
        for task_data in prep_tasks:
            try:
                task = self.task_service.create_task(
                    title=task_data['title'],
                    due_date=prep_due_str,
                    priority=task_data.get('priority', DEFAULT_PRIORITY),
                    category=DEFAULT_TASK_CATEGORY,
                    notes=f"Preparation for: {title}\nEvent ID: {event_id}",
                    tags=['meeting-prep', 'calendar']
                )
                created_tasks.append(task)
                logger.info(f"[CAL_TASK] Created prep task: {task_data['title']}")
            except Exception as e:
                logger.error(f"[CAL_TASK] Failed to create prep task: {e}")
        
        logger.info(f"[CAL_TASK] Created {len(created_tasks)} prep tasks")
        return created_tasks
    
    def _generate_standard_prep_tasks(
        self,
        title: str,
        description: str,
        attendees: List[Any]
    ) -> List[Dict[str, str]]:
        """
        Generate standard prep tasks based on meeting characteristics
        
        Returns:
            List of task data dictionaries
        """
        tasks = []
        title_lower = title.lower()
        desc_lower = description.lower() if description else ''
        
        # Always suggest agenda review
        tasks.append({
            'title': f"Review agenda for '{title}'",
            'priority': 'high'
        })
        
        # Presentation-related meetings
        if any(word in title_lower for word in ['presentation', 'demo', 'showcase', 'pitch']):
            tasks.append({
                'title': f"Prepare slides for '{title}'",
                'priority': 'high'
            })
            tasks.append({
                'title': f"Test presentation setup for '{title}'",
                'priority': 'medium'
            })
        
        # Review meetings
        if any(word in title_lower for word in ['review', 'retrospective', 'post-mortem']):
            tasks.append({
                'title': f"Gather feedback for '{title}'",
                'priority': 'medium'
            })
            tasks.append({
                'title': f"Prepare discussion points for '{title}'",
                'priority': 'medium'
            })
        
        # Planning meetings
        if any(word in title_lower for word in ['planning', 'roadmap', 'strategy']):
            tasks.append({
                'title': f"Research topics for '{title}'",
                'priority': 'medium'
            })
            tasks.append({
                'title': f"Draft proposal for '{title}'",
                'priority': 'medium'
            })
        
        # Interview meetings
        if any(word in title_lower for word in ['interview', 'candidate']):
            tasks.append({
                'title': f"Review resume/background",
                'priority': 'high'
            })
            tasks.append({
                'title': f"Prepare interview questions",
                'priority': 'high'
            })
        
        # Client/External meetings
        if any(word in title_lower for word in ['client', 'customer', 'vendor', 'partner']):
            tasks.append({
                'title': f"Review account history",
                'priority': 'high'
            })
        
        # Large meetings (threshold+ attendees)
        if len(attendees) >= LARGE_MEETING_ATTENDEE_THRESHOLD:
            tasks.append({
                'title': f"Send pre-read materials to attendees",
                'priority': 'medium'
            })
        
        # Limit to top MAX_PREP_TASKS most relevant tasks
        return tasks[:MAX_PREP_TASKS]
    
    def create_followup_tasks(
        self,
        event_id: str,
        event_data: Dict[str, Any],
        followup_days_after: int = DEFAULT_FOLLOWUP_DAYS_AFTER
    ) -> List[Dict[str, Any]]:
        """
        Create follow-up tasks after a meeting
        
        Args:
            event_id: Calendar event ID
            event_data: Event details
            followup_days_after: Days after meeting to set task due date
            
        Returns:
            List of created tasks
        """
        logger.info(f"[CAL_TASK] Creating follow-up tasks for event: {event_data.get('summary', 'Untitled')}")
        
        title = event_data.get('summary', event_data.get('title', 'Untitled Event'))
        start_time_str = event_data.get('start_time', event_data.get('start', {}).get('dateTime'))
        attendees = event_data.get('attendees', [])
        
        # Calculate follow-up task due date (after the meeting)
        if start_time_str:
            try:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                followup_due = start_time + timedelta(days=followup_days_after)
                followup_due_str = followup_due.date().isoformat()
            except:
                followup_due_str = None
        else:
            followup_due_str = None
        
        created_tasks = []
        
        # Standard follow-up tasks
        followup_tasks = self._generate_standard_followup_tasks(title, attendees)
        
        # Create each follow-up task
        for task_data in followup_tasks:
            try:
                task = self.task_service.create_task(
                    title=task_data['title'],
                    due_date=followup_due_str,
                    priority=task_data.get('priority', DEFAULT_PRIORITY),
                    category=DEFAULT_TASK_CATEGORY,
                    notes=f"Follow-up for: {title}\nEvent ID: {event_id}",
                    tags=['meeting-followup', 'calendar']
                )
                created_tasks.append(task)
                logger.info(f"[CAL_TASK] Created follow-up task: {task_data['title']}")
            except Exception as e:
                logger.error(f"[CAL_TASK] Failed to create follow-up task: {e}")
        
        logger.info(f"[CAL_TASK] Created {len(created_tasks)} follow-up tasks")
        return created_tasks
    
    def _generate_standard_followup_tasks(
        self,
        title: str,
        attendees: List[Any]
    ) -> List[Dict[str, str]]:
        """Generate standard follow-up tasks based on meeting type"""
        tasks = []
        title_lower = title.lower()
        
        # Always suggest sending notes/summary
        if len(attendees) > MULTIPLE_ATTENDEES_THRESHOLD:
            tasks.append({
                'title': f"Send meeting notes for '{title}'",
                'priority': 'high'
            })
        
        # Action items follow-up
        tasks.append({
            'title': f"Follow up on action items from '{title}'",
            'priority': 'high'
        })
        
        # Decision meetings
        if any(word in title_lower for word in ['decision', 'approval', 'review']):
            tasks.append({
                'title': f"Document decisions from '{title}'",
                'priority': 'high'
            })
        
        # Planning/Strategy meetings
        if any(word in title_lower for word in ['planning', 'strategy', 'roadmap']):
            tasks.append({
                'title': f"Update project plan based on '{title}'",
                'priority': 'medium'
            })
        
        return tasks[:MAX_FOLLOWUP_TASKS]  # Limit to top MAX_FOLLOWUP_TASKS follow-up tasks
    
    def create_event_with_tasks(
        self,
        title: str,
        start_time: str,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
        attendees: Optional[List[str]] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        create_prep: bool = True,
        create_followup: bool = True
    ) -> Dict[str, Any]:
        """
        Create calendar event with automatic prep and follow-up tasks
        
        Args:
            title: Event title
            start_time: Event start time (ISO format)
            duration_minutes: Event duration
            attendees: List of attendee emails
            description: Event description
            location: Event location
            create_prep: Create preparation tasks
            create_followup: Create follow-up tasks
            
        Returns:
            Dictionary with event and created tasks
        """
        logger.info(f"[CAL_TASK] Creating event with tasks: {title}")
        
        # Create calendar event
        event = self.calendar_service.create_event(
            title=title,
            start_time=start_time,
            duration_minutes=duration_minutes,
            attendees=attendees,
            description=description,
            location=location
        )
        
        event_id = event.get('id')
        result = {
            'event': event,
            'prep_tasks': [],
            'followup_tasks': []
        }
        
        # Create prep tasks
        if create_prep and event_id:
            prep_tasks = self.create_prep_tasks(event_id, event)
            result['prep_tasks'] = prep_tasks
        
        # Create follow-up tasks
        if create_followup and event_id:
            followup_tasks = self.create_followup_tasks(event_id, event)
            result['followup_tasks'] = followup_tasks
        
        logger.info(f"[CAL_TASK] Created event + {len(result['prep_tasks'])} prep + {len(result['followup_tasks'])} followup tasks")
        return result
    
    def schedule_prep_time(
        self,
        event_id: str,
        event_data: Dict[str, Any],
        prep_duration_minutes: int = DEFAULT_DURATION_MINUTES,
        hours_before: int = DEFAULT_PREP_HOURS_BEFORE
    ) -> Optional[Dict[str, Any]]:
        """
        Schedule dedicated prep time before a meeting
        
        Args:
            event_id: Calendar event ID
            event_data: Event details
            prep_duration_minutes: Duration for prep work
            hours_before: Schedule prep time this many hours before meeting
            
        Returns:
            Created prep time event or None if no suitable slot
        """
        logger.info(f"[CAL_TASK] Scheduling prep time for event: {event_data.get('summary', 'Untitled')}")
        
        title = event_data.get('summary', event_data.get('title', 'Untitled Event'))
        start_time_str = event_data.get('start_time', event_data.get('start', {}).get('dateTime'))
        
        if not start_time_str:
            logger.warning("[CAL_TASK] No start time found, cannot schedule prep time")
            return None
        
        try:
            # Parse event start time
            event_start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            
            # Calculate prep time window
            prep_window_end = event_start - timedelta(hours=PREP_TIME_BUFFER_HOURS)  # Buffer before meeting
            prep_window_start = event_start - timedelta(hours=hours_before)
            
            # Find free slots in the prep window
            free_slots = self.calendar_service.find_free_time(
                duration_minutes=prep_duration_minutes,
                start_date=prep_window_start.isoformat(),
                end_date=prep_window_end.isoformat(),
                working_hours_only=True,
                max_suggestions=MAX_PREP_TIME_SUGGESTIONS
            )
            
            if not free_slots:
                logger.warning("[CAL_TASK] No free slots found for prep time")
                return None
            
            # Use first available slot
            prep_slot = free_slots[0]
            
            # Create prep time event
            prep_event = self.calendar_service.create_event(
                title=f"Prep: {title}",
                start_time=prep_slot['start'],
                end_time=prep_slot['end'],
                description=f"Preparation time for: {title}\nOriginal Event ID: {event_id}",
                location="Focus Time"
            )
            
            logger.info(f"[CAL_TASK] Scheduled prep time at {prep_slot['start']}")
            return prep_event
            
        except Exception as e:
            logger.error(f"[CAL_TASK] Failed to schedule prep time: {e}")
            return None
    
    def analyze_upcoming_meetings(
        self,
        days_ahead: int = DEFAULT_DAYS_AHEAD
    ) -> Dict[str, Any]:
        """
        Analyze upcoming meetings and suggest prep tasks
        
        Args:
            days_ahead: Number of days to look ahead
            
        Returns:
            Analysis with suggested tasks
        """
        logger.info(f"[CAL_TASK] Analyzing meetings for next {days_ahead} days")
        
        # Get upcoming events
        from datetime import datetime, timedelta
        start_date = datetime.now().isoformat()
        end_date = (datetime.now() + timedelta(days=days_ahead)).isoformat()
        
        events = self.calendar_service.list_events(
            start_date=start_date,
            end_date=end_date
        )
        
        analysis = {
            'total_meetings': len(events),
            'needs_prep': [],
            'needs_followup': [],
            'prep_time_suggestions': []
        }
        
        for event in events:
            title = event.get('summary', 'Untitled')
            event_id = event.get('id')
            
            # Check if meeting likely needs prep
            if self._needs_preparation(event):
                analysis['needs_prep'].append({
                    'event_id': event_id,
                    'title': title,
                    'start_time': event.get('start', {}).get('dateTime')
                })
            
            # Check if meeting will need follow-up
            if len(event.get('attendees', [])) > MULTIPLE_ATTENDEES_THRESHOLD:
                analysis['needs_followup'].append({
                    'event_id': event_id,
                    'title': title
                })
        
        logger.info(f"[CAL_TASK] Analysis: {len(analysis['needs_prep'])} need prep, {len(analysis['needs_followup'])} need followup")
        return analysis
    
    def _needs_preparation(self, event: Dict[str, Any]) -> bool:
        """Determine if meeting likely needs preparation"""
        title = event.get('summary', '').lower()
        attendees = event.get('attendees', [])
        
        # Meetings that typically need prep
        prep_keywords = [
            'presentation', 'demo', 'review', 'interview',
            'pitch', 'proposal', 'planning', 'strategy',
            'client', 'customer', 'board', 'executive'
        ]
        
        # Check title
        if any(keyword in title for keyword in prep_keywords):
            return True
        
        # Large meetings often need prep
        if len(attendees) >= LARGE_MEETING_ATTENDEE_THRESHOLD:
            return True
        
        return False
