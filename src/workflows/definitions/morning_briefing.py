"""
Morning Briefing Workflow

Generates a comprehensive morning briefing with:
- Today's calendar events
- Urgent and overdue tasks
- Important unread emails
- Summary and recommendations
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ..base.workflow import Workflow, WorkflowContext
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class MorningBriefingWorkflow(Workflow):
    """
    Morning briefing workflow.
    
    Gathers information from calendar, tasks, and email to provide
    a comprehensive start-of-day overview.
    """
    
    name = "morning_briefing"
    description = "Generate comprehensive morning briefing with today's schedule, tasks, and important emails"
    version = "2.0.0"
    
    def __init__(
        self,
        calendar_service: Any,
        task_service: Any,
        email_service: Any,
        email_ai_analyzer: Optional[Any] = None
    ):
        """
        Initialize with required services.
        
        Args:
            calendar_service: Calendar service instance
            task_service: Task service instance
            email_service: Email service instance
            email_ai_analyzer: Optional AI analyzer for email prioritization
        """
        self.calendar_service = calendar_service
        self.task_service = task_service
        self.email_service = email_service
        self.email_ai_analyzer = email_ai_analyzer
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_emails": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum unread emails to include"
                },
                "max_tasks": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum tasks per category"
                },
                "include_recommendations": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include AI-generated recommendations"
                }
            }
        }
    
    async def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute the morning briefing workflow"""
        params = context.params
        max_emails = params.get('max_emails', 10)
        max_tasks = params.get('max_tasks', 10)
        include_recommendations = params.get('include_recommendations', True)
        
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        
        # Execute data gathering in parallel
        calendar_task = self._get_calendar_data(today, tomorrow)
        tasks_task = self._get_tasks_data(today, max_tasks)
        emails_task = self._get_emails_data(max_emails)
        
        calendar_data, tasks_data, emails_data = await asyncio.gather(
            calendar_task,
            tasks_task,
            emails_task,
            return_exceptions=True
        )
        
        # Handle any errors from parallel execution
        if isinstance(calendar_data, Exception):
            logger.error(f"Calendar data fetch failed: {calendar_data}")
            calendar_data = {"events": [], "total_events": 0, "error": str(calendar_data)}
        
        if isinstance(tasks_data, Exception):
            logger.error(f"Tasks data fetch failed: {tasks_data}")
            tasks_data = {"urgent": [], "overdue": [], "due_today": [], "error": str(tasks_data)}
        
        if isinstance(emails_data, Exception):
            logger.error(f"Emails data fetch failed: {emails_data}")
            emails_data = {"important_emails": [], "total_unread": 0, "error": str(emails_data)}
        
        # Store intermediate results
        context.state['calendar'] = calendar_data
        context.state['tasks'] = tasks_data
        context.state['emails'] = emails_data
        
        # Generate summary
        summary = self._generate_summary(calendar_data, tasks_data, emails_data)
        
        # Generate recommendations if requested
        recommendations = []
        if include_recommendations:
            recommendations = self._generate_recommendations(
                calendar_data, tasks_data, emails_data
            )
        
        result = {
            "generated_at": datetime.now().isoformat(),
            "date": today.isoformat(),
            "calendar": calendar_data,
            "tasks": tasks_data,
            "emails": emails_data,
            "summary": summary,
            "recommendations": recommendations
        }
        
        # Add text summary for easy display
        result["text_summary"] = self._format_text_summary(result)
        
        return result
    
    async def _get_calendar_data(self, today, tomorrow) -> Dict[str, Any]:
        """Fetch today's calendar events"""
        events = await asyncio.to_thread(
            self.calendar_service.list_events,
            start_date=today.isoformat(),
            end_date=tomorrow.isoformat()
        )
        
        # Sort by start time
        events = sorted(
            events,
            key=lambda e: e.get('start', {}).get('dateTime', '00:00')
        )
        
        return {
            "events": events[:10],
            "total_events": len(events),
            "next_event": events[0] if events else None,
            "all_day_events": [
                e for e in events
                if e.get('start', {}).get('date')  # All-day events have 'date' not 'dateTime'
            ]
        }
    
    async def _get_tasks_data(self, today, max_tasks: int) -> Dict[str, Any]:
        """Fetch urgent and due tasks"""
        all_tasks = await asyncio.to_thread(
            self.task_service.list_tasks,
            status='active',
            limit=200
        )
        
        # Categorize tasks
        overdue = []
        due_today = []
        urgent = []
        high_priority = []
        
        for task in all_tasks:
            due_date = task.get('due_date')
            priority = task.get('priority', 'medium')
            
            if due_date:
                if due_date < today.isoformat():
                    overdue.append(task)
                elif due_date == today.isoformat():
                    due_today.append(task)
            
            if priority == 'urgent':
                urgent.append(task)
            elif priority == 'high':
                high_priority.append(task)
        
        return {
            "total_active": len(all_tasks),
            "overdue": overdue[:max_tasks],
            "overdue_count": len(overdue),
            "due_today": due_today[:max_tasks],
            "due_today_count": len(due_today),
            "urgent": urgent[:max_tasks],
            "urgent_count": len(urgent),
            "high_priority": high_priority[:max_tasks],
            "high_priority_count": len(high_priority)
        }
    
    async def _get_emails_data(self, max_emails: int) -> Dict[str, Any]:
        """Fetch important unread emails"""
        unread_emails = await asyncio.to_thread(
            self.email_service.list_emails,
            max_results=max_emails * 2,  # Fetch more to filter
            query='is:unread'
        )
        
        important_emails = []
        
        if self.email_ai_analyzer:
            # Use AI to prioritize emails
            for email in unread_emails[:max_emails]:
                try:
                    urgency = await asyncio.to_thread(
                        self.email_ai_analyzer.classify_urgency,
                        email
                    )
                    if urgency in ['urgent', 'high']:
                        important_emails.append({
                            **email,
                            'urgency': urgency
                        })
                except Exception as e:
                    logger.debug(f"AI urgency classification failed: {e}")
        else:
            # Fallback: use email labels/flags
            important_emails = [
                e for e in unread_emails
                if e.get('priority') == 'high' or 
                   'IMPORTANT' in e.get('labels', []) or
                   e.get('starred', False)
            ]
        
        return {
            "total_unread": len(unread_emails),
            "important_emails": important_emails[:max_emails],
            "important_count": len(important_emails),
            "has_urgent": any(
                e.get('urgency') == 'urgent'
                for e in important_emails
            )
        }
    
    def _generate_summary(
        self,
        calendar: Dict,
        tasks: Dict,
        emails: Dict
    ) -> Dict[str, Any]:
        """Generate a high-level summary"""
        next_event = calendar.get('next_event')
        
        return {
            "total_events": calendar.get('total_events', 0),
            "next_meeting": next_event.get('summary', 'No meetings') if next_event else 'No meetings today',
            "next_meeting_time": next_event.get('start', {}).get('dateTime', '') if next_event else '',
            "overdue_count": tasks.get('overdue_count', 0),
            "due_today_count": tasks.get('due_today_count', 0),
            "urgent_count": tasks.get('urgent_count', 0),
            "unread_count": emails.get('total_unread', 0),
            "important_email_count": emails.get('important_count', 0),
            "needs_attention": (
                tasks.get('overdue_count', 0) > 0 or
                emails.get('has_urgent', False)
            ),
            "busy_day": calendar.get('total_events', 0) >= 5
        }
    
    def _generate_recommendations(
        self,
        calendar: Dict,
        tasks: Dict,
        emails: Dict
    ) -> List[Dict[str, str]]:
        """Generate actionable recommendations"""
        recommendations = []
        
        # Overdue tasks
        if tasks.get('overdue_count', 0) > 0:
            recommendations.append({
                "type": "overdue_tasks",
                "priority": "high",
                "icon": "⚠️",
                "message": f"You have {tasks['overdue_count']} overdue tasks. Consider rescheduling or completing them today."
            })
        
        # Busy calendar
        if calendar.get('total_events', 0) >= 6:
            recommendations.append({
                "type": "busy_day",
                "priority": "medium",
                "icon": "📅",
                "message": f"Busy day ahead with {calendar['total_events']} meetings. Consider blocking focus time."
            })
        
        # Urgent emails
        if emails.get('has_urgent', False):
            recommendations.append({
                "type": "urgent_emails",
                "priority": "high",
                "icon": "📧",
                "message": "You have urgent emails that need attention before your first meeting."
            })
        
        # Light day opportunity
        if calendar.get('total_events', 0) <= 2 and tasks.get('urgent_count', 0) > 0:
            recommendations.append({
                "type": "focus_opportunity",
                "priority": "info",
                "icon": "💡",
                "message": f"Light meeting day! Great opportunity to tackle your {tasks['urgent_count']} urgent tasks."
            })
        
        # Early start needed
        next_event = calendar.get('next_event')
        if next_event:
            start_time = next_event.get('start', {}).get('dateTime', '')
            if start_time and 'T08' in start_time or 'T07' in start_time:
                recommendations.append({
                    "type": "early_meeting",
                    "priority": "info",
                    "icon": "🌅",
                    "message": f"Early meeting at {start_time[11:16]}. Plan your prep time accordingly."
                })
        
        return recommendations
    
    def _format_text_summary(self, result: Dict) -> str:
        """Format briefing as readable text"""
        lines = []
        lines.append("☀️ MORNING BRIEFING")
        lines.append("=" * 50)
        lines.append("")
        
        summary = result.get('summary', {})
        
        # Summary section
        lines.append("📊 OVERVIEW")
        lines.append(f"• Next Meeting: {summary.get('next_meeting', 'None')}")
        if summary.get('next_meeting_time'):
            lines.append(f"  Time: {summary['next_meeting_time'][11:16]}")
        lines.append(f"• Total Meetings: {summary.get('total_events', 0)}")
        lines.append(f"• Urgent Tasks: {summary.get('urgent_count', 0)}")
        lines.append(f"• Overdue Tasks: {summary.get('overdue_count', 0)}")
        lines.append(f"• Important Emails: {summary.get('important_email_count', 0)}")
        lines.append("")
        
        # Recommendations
        recommendations = result.get('recommendations', [])
        if recommendations:
            lines.append("💡 RECOMMENDATIONS")
            for rec in recommendations:
                lines.append(f"{rec.get('icon', '•')} {rec.get('message', '')}")
            lines.append("")
        
        # Tasks
        tasks = result.get('tasks', {})
        if tasks.get('overdue'):
            lines.append("⚠️ OVERDUE TASKS")
            for task in tasks['overdue'][:5]:
                lines.append(f"• [{task.get('priority', 'N/A').upper()}] {task.get('title', 'Untitled')}")
            lines.append("")
        
        if tasks.get('due_today'):
            lines.append("📝 DUE TODAY")
            for task in tasks['due_today'][:5]:
                lines.append(f"• {task.get('title', 'Untitled')}")
            lines.append("")
        
        # Calendar
        calendar = result.get('calendar', {})
        if calendar.get('events'):
            lines.append("🗓️ TODAY'S SCHEDULE")
            for event in calendar['events'][:6]:
                time = event.get('start', {}).get('dateTime', '')
                time_str = time[11:16] if time else "All day"
                lines.append(f"• {time_str} - {event.get('summary', 'Untitled')}")
            lines.append("")
        
        return "\n".join(lines)
