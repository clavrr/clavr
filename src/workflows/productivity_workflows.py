"""
Productivity Workflows Module

Automated workflows that combine Email, Calendar, and Task tools
to create intelligent productivity assistance.

Features:
- Morning briefing workflow
- Email-to-action workflow
- Weekly planning workflow
- End-of-day review workflow
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class ProductivityWorkflows:
    """Automated productivity workflows combining multiple tools"""
    
    def __init__(
        self,
        email_service: Any,
        calendar_service: Any,
        task_service: Any,
        email_ai_analyzer: Optional[Any] = None
    ):
        """
        Initialize workflows with required services
        
        Args:
            email_service: EmailService instance
            calendar_service: CalendarService instance
            task_service: TaskService instance
            email_ai_analyzer: Optional EmailAIAnalyzer for AI features
        """
        self.email_service = email_service
        self.calendar_service = calendar_service
        self.task_service = task_service
        self.email_ai_analyzer = email_ai_analyzer
        logger.info("[WORKFLOWS] ProductivityWorkflows initialized")
    
    def morning_briefing(
        self,
        include_weather: bool = False,
        max_emails: int = 10,
        max_tasks: int = 10
    ) -> Dict[str, Any]:
        """
        Generate comprehensive morning briefing
        
        Provides:
        - Today's calendar events
        - Urgent/high-priority tasks
        - Unread important emails
        - Optional weather forecast
        
        Args:
            include_weather: Include weather forecast
            max_emails: Maximum unread emails to show
            max_tasks: Maximum tasks to show
            
        Returns:
            Dictionary with briefing data
        """
        logger.info("[WORKFLOWS] Generating morning briefing")
        
        briefing = {
            'generated_at': datetime.now().isoformat(),
            'calendar': {},
            'tasks': {},
            'emails': {},
            'summary': {}
        }
        
        try:
            # === TODAY'S CALENDAR ===
            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)
            
            events = self.calendar_service.list_events(
                start_date=today.isoformat(),
                end_date=tomorrow.isoformat()
            )
            
            briefing['calendar'] = {
                'total_events': len(events),
                'events': events[:10],  # Top 10 events
                'next_event': events[0] if events else None
            }
            
            # === URGENT & HIGH-PRIORITY TASKS ===
            all_tasks = self.task_service.list_tasks(
                status='active',
                limit=100
            )
            
            # Filter urgent and high-priority tasks
            urgent_tasks = [
                t for t in all_tasks
                if t.get('priority') in ['urgent', 'high']
            ]
            
            # Sort by due date and priority
            urgent_tasks.sort(
                key=lambda t: (
                    t.get('due_date', '9999-99-99'),
                    0 if t.get('priority') == 'urgent' else 1
                )
            )
            
            # Separate overdue tasks
            overdue_tasks = [
                t for t in urgent_tasks
                if t.get('due_date') and t['due_date'] < today.isoformat()
            ]
            
            # Today's tasks
            today_tasks = [
                t for t in urgent_tasks
                if t.get('due_date') == today.isoformat()
            ]
            
            briefing['tasks'] = {
                'total_active': len(all_tasks),
                'total_urgent': len(urgent_tasks),
                'overdue': overdue_tasks[:max_tasks],
                'due_today': today_tasks[:max_tasks],
                'high_priority': urgent_tasks[:max_tasks]
            }
            
            # === UNREAD IMPORTANT EMAILS ===
            unread_emails = self.email_service.list_emails(
                max_results=max_emails,
                query='is:unread'
            )
            
            # Filter important emails (AI-based if available)
            important_emails = []
            if self.email_ai_analyzer:
                for email in unread_emails:
                    urgency = self.email_ai_analyzer.classify_urgency(email)
                    if urgency in ['urgent', 'high']:
                        important_emails.append({
                            **email,
                            'urgency': urgency
                        })
            else:
                # Fallback: use email importance markers
                important_emails = [
                    e for e in unread_emails
                    if e.get('priority') == 'high' or 'IMPORTANT' in e.get('labels', [])
                ]
            
            briefing['emails'] = {
                'total_unread': len(unread_emails),
                'important_count': len(important_emails),
                'important_emails': important_emails[:max_emails]
            }
            
            # === SUMMARY ===
            briefing['summary'] = {
                'total_events_today': len(events),
                'next_meeting': events[0].get('summary', 'No meetings') if events else 'No meetings today',
                'next_meeting_time': events[0].get('start', {}).get('dateTime', '') if events else '',
                'urgent_tasks_count': len(urgent_tasks),
                'overdue_tasks_count': len(overdue_tasks),
                'unread_important_count': len(important_emails),
                'needs_attention': len(overdue_tasks) > 0 or len(important_emails) > 0
            }
            
            logger.info(
                f"[WORKFLOWS] Briefing generated: {len(events)} events, "
                f"{len(urgent_tasks)} urgent tasks, {len(important_emails)} important emails"
            )
            
        except Exception as e:
            logger.error(f"[WORKFLOWS] Error generating briefing: {e}")
            briefing['error'] = str(e)
        
        return briefing
    
    def email_to_action_workflow(
        self,
        email_id: str,
        auto_create_tasks: bool = True,
        auto_create_events: bool = True,
        auto_archive: bool = False
    ) -> Dict[str, Any]:
        """
        Comprehensive email processing workflow
        
        Automatically:
        1. Extract action items → create tasks
        2. Detect meeting requests → create calendar events
        3. Classify and categorize email
        4. Optionally archive after processing
        
        Args:
            email_id: Email message ID
            auto_create_tasks: Automatically create extracted tasks
            auto_create_events: Automatically create detected events
            auto_archive: Archive email after processing
            
        Returns:
            Dictionary with processing results
        """
        logger.info(f"[WORKFLOWS] Processing email {email_id} with automation")
        
        result = {
            'email_id': email_id,
            'tasks_created': [],
            'events_created': [],
            'email_classification': {},
            'archived': False
        }
        
        try:
            # Get email
            email = self.email_service.get_email(email_id)
            
            if not self.email_ai_analyzer:
                result['error'] = 'AI analyzer not available'
                return result
            
            # === EXTRACT TASKS ===
            action_items = self.email_ai_analyzer.extract_action_items(
                email_data=email,
                context={},
                auto_categorize=True
            )
            
            if auto_create_tasks and action_items:
                for task_data in action_items:
                    try:
                        task = self.task_service.create_task(
                            title=task_data['title'],
                            due_date=task_data.get('due_date'),
                            priority=task_data.get('priority', 'medium'),
                            category=task_data.get('category', 'work'),
                            notes=f"From email: {email.get('subject', 'No subject')}\nEmail ID: {email_id}",
                            tags=['email', 'auto-created']
                        )
                        result['tasks_created'].append(task)
                        logger.info(f"[WORKFLOWS] Created task: {task_data['title']}")
                    except Exception as e:
                        logger.error(f"[WORKFLOWS] Failed to create task: {e}")
            
            # === DETECT CALENDAR EVENTS ===
            event_suggestions = self.email_ai_analyzer.suggest_calendar_events(email)
            
            if auto_create_events and event_suggestions:
                for event_data in event_suggestions:
                    try:
                        event = self.calendar_service.create_event(
                            title=event_data['title'],
                            start_time=event_data['start_time'],
                            duration_minutes=event_data.get('duration_minutes', 60),
                            description=f"From email: {email.get('subject', '')}\nEmail ID: {email_id}",
                            attendees=event_data.get('attendees', [])
                        )
                        result['events_created'].append(event)
                        logger.info(f"[WORKFLOWS] Created event: {event_data['title']}")
                    except Exception as e:
                        logger.error(f"[WORKFLOWS] Failed to create event: {e}")
            
            # === CLASSIFY EMAIL ===
            urgency = self.email_ai_analyzer.classify_urgency(email)
            category = self.email_ai_analyzer.suggest_email_category(email)
            
            result['email_classification'] = {
                'urgency': urgency,
                'category': category,
                'action_items_found': len(action_items),
                'events_suggested': len(event_suggestions)
            }
            
            # === ARCHIVE IF REQUESTED ===
            if auto_archive:
                try:
                    self.email_service.archive_email(email_id)
                    result['archived'] = True
                    logger.info(f"[WORKFLOWS] Archived email {email_id}")
                except Exception as e:
                    logger.error(f"[WORKFLOWS] Failed to archive: {e}")
            
            logger.info(
                f"[WORKFLOWS] Email processed: {len(result['tasks_created'])} tasks, "
                f"{len(result['events_created'])} events created"
            )
            
        except Exception as e:
            logger.error(f"[WORKFLOWS] Error in email-to-action workflow: {e}")
            result['error'] = str(e)
        
        return result
    
    def weekly_planning_workflow(
        self,
        include_last_week_review: bool = True
    ) -> Dict[str, Any]:
        """
        Generate weekly planning overview
        
        Provides:
        - Upcoming week's calendar
        - Tasks due this week
        - Optional: Last week's completion stats
        - Suggestions for scheduling
        
        Args:
            include_last_week_review: Include last week's stats
            
        Returns:
            Dictionary with planning data
        """
        logger.info("[WORKFLOWS] Generating weekly planning")
        
        planning = {
            'generated_at': datetime.now().isoformat(),
            'this_week': {},
            'last_week': {},
            'recommendations': []
        }
        
        try:
            # === THIS WEEK'S CALENDAR ===
            today = datetime.now().date()
            week_start = today - timedelta(days=today.weekday())  # Monday
            week_end = week_start + timedelta(days=7)
            
            events = self.calendar_service.list_events(
                start_date=week_start.isoformat(),
                end_date=week_end.isoformat()
            )
            
            # Group by day
            events_by_day = {}
            for event in events:
                event_date = event.get('start', {}).get('dateTime', '')[:10]
                if event_date not in events_by_day:
                    events_by_day[event_date] = []
                events_by_day[event_date].append(event)
            
            planning['this_week']['calendar'] = {
                'total_events': len(events),
                'events_by_day': events_by_day,
                'busiest_day': max(events_by_day.items(), key=lambda x: len(x[1]))[0] if events_by_day else None
            }
            
            # === THIS WEEK'S TASKS ===
            all_tasks = self.task_service.list_tasks(
                status='active',
                limit=200
            )
            
            # Filter tasks due this week
            week_tasks = [
                t for t in all_tasks
                if t.get('due_date') and week_start.isoformat() <= t['due_date'] <= week_end.isoformat()
            ]
            
            # Group by priority
            tasks_by_priority = {
                'urgent': [t for t in week_tasks if t.get('priority') == 'urgent'],
                'high': [t for t in week_tasks if t.get('priority') == 'high'],
                'medium': [t for t in week_tasks if t.get('priority') == 'medium'],
                'low': [t for t in week_tasks if t.get('priority') == 'low']
            }
            
            planning['this_week']['tasks'] = {
                'total_tasks': len(week_tasks),
                'by_priority': {
                    k: len(v) for k, v in tasks_by_priority.items()
                },
                'urgent_tasks': tasks_by_priority['urgent']
            }
            
            # === LAST WEEK REVIEW ===
            if include_last_week_review:
                last_week_start = week_start - timedelta(days=7)
                last_week_end = week_start
                
                last_week_events = self.calendar_service.list_events(
                    start_date=last_week_start.isoformat(),
                    end_date=last_week_end.isoformat()
                )
                
                # Get completed tasks from last week
                completed_tasks = self.task_service.list_tasks(
                    status='completed',
                    limit=200
                )
                
                last_week_completed = [
                    t for t in completed_tasks
                    if t.get('completed_date') and 
                    last_week_start.isoformat() <= t['completed_date'] <= last_week_end.isoformat()
                ]
                
                planning['last_week'] = {
                    'total_events': len(last_week_events),
                    'tasks_completed': len(last_week_completed),
                    'productivity_score': min(100, len(last_week_completed) * 10)  # Simple score
                }
            
            # === RECOMMENDATIONS ===
            recommendations = []
            
            # Check for overloaded days
            for day, day_events in events_by_day.items():
                if len(day_events) >= 5:
                    recommendations.append({
                        'type': 'overloaded_day',
                        'message': f'⚠️ {day} has {len(day_events)} meetings. Consider rescheduling some.',
                        'priority': 'medium'
                    })
            
            # Check for urgent tasks without calendar blocks
            if tasks_by_priority['urgent']:
                recommendations.append({
                    'type': 'schedule_work_time',
                    'message': f'💡 You have {len(tasks_by_priority["urgent"])} urgent tasks. Schedule focus time to complete them.',
                    'priority': 'high'
                })
            
            # Check for days with no events
            days_without_meetings = 0
            for i in range(5):  # Weekdays only
                day = (week_start + timedelta(days=i)).isoformat()
                if day not in events_by_day or len(events_by_day[day]) == 0:
                    days_without_meetings += 1
            
            if days_without_meetings > 0:
                recommendations.append({
                    'type': 'free_days',
                    'message': f'✨ You have {days_without_meetings} days with no meetings. Great for deep work!',
                    'priority': 'info'
                })
            
            planning['recommendations'] = recommendations
            
            logger.info(
                f"[WORKFLOWS] Weekly planning generated: {len(events)} events, "
                f"{len(week_tasks)} tasks, {len(recommendations)} recommendations"
            )
            
        except Exception as e:
            logger.error(f"[WORKFLOWS] Error generating weekly planning: {e}")
            planning['error'] = str(e)
        
        return planning
    
    def end_of_day_review(self) -> Dict[str, Any]:
        """
        Generate end-of-day review
        
        Provides:
        - Today's completed tasks
        - Events attended
        - Pending tasks for tomorrow
        - Productivity summary
        
        Returns:
            Dictionary with review data
        """
        logger.info("[WORKFLOWS] Generating end-of-day review")
        
        review = {
            'generated_at': datetime.now().isoformat(),
            'today': {},
            'tomorrow': {},
            'summary': {}
        }
        
        try:
            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)
            
            # === TODAY'S EVENTS ===
            today_events = self.calendar_service.list_events(
                start_date=today.isoformat(),
                end_date=tomorrow.isoformat()
            )
            
            # === TODAY'S COMPLETED TASKS ===
            completed_tasks = self.task_service.list_tasks(
                status='completed',
                limit=100
            )
            
            today_completed = [
                t for t in completed_tasks
                if t.get('completed_date') == today.isoformat()
            ]
            
            # === PENDING TASKS ===
            active_tasks = self.task_service.list_tasks(
                status='active',
                limit=100
            )
            
            overdue_tasks = [
                t for t in active_tasks
                if t.get('due_date') and t['due_date'] < today.isoformat()
            ]
            
            # === TOMORROW'S PREVIEW ===
            tomorrow_events = self.calendar_service.list_events(
                start_date=tomorrow.isoformat(),
                end_date=(tomorrow + timedelta(days=1)).isoformat()
            )
            
            tomorrow_tasks = [
                t for t in active_tasks
                if t.get('due_date') == tomorrow.isoformat()
            ]
            
            review['today'] = {
                'events_attended': len(today_events),
                'tasks_completed': len(today_completed),
                'completed_task_list': today_completed
            }
            
            review['tomorrow'] = {
                'scheduled_events': len(tomorrow_events),
                'tasks_due': len(tomorrow_tasks),
                'event_list': tomorrow_events[:5],
                'task_list': tomorrow_tasks[:10]
            }
            
            review['summary'] = {
                'productivity_score': min(100, len(today_completed) * 15),
                'meetings_attended': len(today_events),
                'tasks_completed': len(today_completed),
                'overdue_tasks': len(overdue_tasks),
                'tomorrow_preview': f"{len(tomorrow_events)} meetings, {len(tomorrow_tasks)} tasks"
            }
            
            logger.info(
                f"[WORKFLOWS] End-of-day review: {len(today_completed)} tasks completed, "
                f"{len(today_events)} meetings attended"
            )
            
        except Exception as e:
            logger.error(f"[WORKFLOWS] Error generating review: {e}")
            review['error'] = str(e)
        
        return review
    
    def format_briefing_text(self, briefing: Dict[str, Any]) -> str:
        """Format morning briefing as readable text"""
        lines = []
        lines.append("☀️ MORNING BRIEFING")
        lines.append("=" * 50)
        lines.append("")
        
        summary = briefing.get('summary', {})
        
        # Summary
        lines.append("📊 SUMMARY")
        lines.append(f"• Next Meeting: {summary.get('next_meeting', 'None')}")
        if summary.get('next_meeting_time'):
            lines.append(f"  Time: {summary['next_meeting_time']}")
        lines.append(f"• Total Events Today: {summary.get('total_events_today', 0)}")
        lines.append(f"• Urgent Tasks: {summary.get('urgent_tasks_count', 0)}")
        lines.append(f"• Overdue Tasks: {summary.get('overdue_tasks_count', 0)}")
        lines.append(f"• Important Unread Emails: {summary.get('unread_important_count', 0)}")
        lines.append("")
        
        # Tasks
        tasks = briefing.get('tasks', {})
        if tasks.get('overdue'):
            lines.append("⚠️ OVERDUE TASKS")
            for task in tasks['overdue'][:5]:
                lines.append(f"• [{task.get('priority', 'N/A').upper()}] {task.get('title', 'Untitled')}")
            lines.append("")
        
        if tasks.get('due_today'):
            lines.append("📅 DUE TODAY")
            for task in tasks['due_today'][:5]:
                lines.append(f"• [{task.get('priority', 'N/A').upper()}] {task.get('title', 'Untitled')}")
            lines.append("")
        
        # Calendar
        calendar = briefing.get('calendar', {})
        if calendar.get('events'):
            lines.append("🗓️ TODAY'S SCHEDULE")
            for event in calendar['events'][:5]:
                time = event.get('start', {}).get('dateTime', '')
                if time:
                    time = time[11:16]  # Extract HH:MM
                lines.append(f"• {time} - {event.get('summary', 'Untitled')}")
            lines.append("")
        
        return "\n".join(lines)
