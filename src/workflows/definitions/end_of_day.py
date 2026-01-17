"""
End of Day Review Workflow

Generates an end-of-day summary with:
- Today's accomplishments
- Tasks completed
- Tomorrow's preview
- Productivity insights
"""
import asyncio
from typing import Dict, Any, List
from datetime import datetime, timedelta

from ..base.workflow import Workflow, WorkflowContext
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class EndOfDayReviewWorkflow(Workflow):
    """
    End of day review workflow.
    
    Summarizes the day's activities and prepares for tomorrow.
    """
    
    name = "end_of_day_review"
    description = "Generate end-of-day summary with accomplishments and tomorrow's preview"
    version = "2.0.0"
    
    def __init__(
        self,
        calendar_service: Any,
        task_service: Any,
        email_service: Any = None
    ):
        """
        Initialize with required services.
        
        Args:
            calendar_service: Calendar service instance
            task_service: Task service instance
            email_service: Optional email service for email stats
        """
        self.calendar_service = calendar_service
        self.task_service = task_service
        self.email_service = email_service
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_email_stats": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include email statistics"
                }
            }
        }
    
    async def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute the end-of-day review workflow"""
        params = context.params
        include_email_stats = params.get('include_email_stats', True)
        
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        day_after = tomorrow + timedelta(days=1)
        
        # Fetch data in parallel
        tasks = [
            self._get_today_summary(today, tomorrow),
            self._get_tasks_summary(today),
            self._get_tomorrow_preview(tomorrow, day_after)
        ]
        
        if include_email_stats and self.email_service:
            tasks.append(self._get_email_stats())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        today_data = results[0] if not isinstance(results[0], Exception) else {"error": str(results[0])}
        tasks_data = results[1] if not isinstance(results[1], Exception) else {"error": str(results[1])}
        tomorrow_data = results[2] if not isinstance(results[2], Exception) else {"error": str(results[2])}
        email_data = results[3] if len(results) > 3 and not isinstance(results[3], Exception) else {}
        
        # Calculate productivity score
        productivity = self._calculate_productivity(today_data, tasks_data)
        
        # Generate insights
        insights = self._generate_insights(today_data, tasks_data, tomorrow_data)
        
        result = {
            "generated_at": datetime.now().isoformat(),
            "date": today.isoformat(),
            "today": today_data,
            "tasks": tasks_data,
            "tomorrow": tomorrow_data,
            "email_stats": email_data,
            "productivity": productivity,
            "insights": insights,
            "text_summary": ""
        }
        
        # Generate text summary
        result["text_summary"] = self._format_text_summary(result)
        
        return result
    
    async def _get_today_summary(self, today, tomorrow) -> Dict[str, Any]:
        """Get today's calendar summary"""
        events = await asyncio.to_thread(
            self.calendar_service.list_events,
            start_date=today.isoformat(),
            end_date=tomorrow.isoformat()
        )
        
        # Calculate total meeting time
        total_minutes = 0
        for event in events:
            start = event.get('start', {}).get('dateTime', '')
            end = event.get('end', {}).get('dateTime', '')
            if start and end:
                try:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    total_minutes += (end_dt - start_dt).total_seconds() / 60
                except Exception as e:
                    logger.debug(f"[EndOfDayReview] Failed to parse event time: {e}")
        
        return {
            "events_attended": len(events),
            "total_meeting_hours": round(total_minutes / 60, 1),
            "events": events[:10],
            "had_meetings": len(events) > 0
        }
    
    async def _get_tasks_summary(self, today) -> Dict[str, Any]:
        """Get today's task summary"""
        # Get completed tasks
        completed = await asyncio.to_thread(
            self.task_service.list_tasks,
            status='completed',
            limit=100
        )
        
        # Filter to today
        today_completed = [
            t for t in completed
            if t.get('completed_date') == today.isoformat()
        ]
        
        # Get active tasks
        active = await asyncio.to_thread(
            self.task_service.list_tasks,
            status='active',
            limit=100
        )
        
        # Find overdue
        overdue = [
            t for t in active
            if t.get('due_date') and t['due_date'] < today.isoformat()
        ]
        
        # Tasks that were due today but not completed
        missed_today = [
            t for t in active
            if t.get('due_date') == today.isoformat()
        ]
        
        return {
            "completed_today": len(today_completed),
            "completed_tasks": today_completed,
            "overdue_count": len(overdue),
            "overdue_tasks": overdue[:5],
            "missed_today": len(missed_today),
            "missed_tasks": missed_today[:5],
            "total_active": len(active),
            "high_priority_completed": len([
                t for t in today_completed
                if t.get('priority') in ['urgent', 'high']
            ])
        }
    
    async def _get_tomorrow_preview(self, tomorrow, day_after) -> Dict[str, Any]:
        """Get tomorrow's preview"""
        events = await asyncio.to_thread(
            self.calendar_service.list_events,
            start_date=tomorrow.isoformat(),
            end_date=day_after.isoformat()
        )
        
        active = await asyncio.to_thread(
            self.task_service.list_tasks,
            status='active',
            limit=100
        )
        
        tomorrow_tasks = [
            t for t in active
            if t.get('due_date') == tomorrow.isoformat()
        ]
        
        # Find first event time
        first_event = None
        if events:
            sorted_events = sorted(
                events,
                key=lambda e: e.get('start', {}).get('dateTime', '99:99')
            )
            first_event = sorted_events[0]
        
        return {
            "events_scheduled": len(events),
            "events": events[:5],
            "tasks_due": len(tomorrow_tasks),
            "tasks": tomorrow_tasks[:5],
            "first_event": first_event,
            "first_event_time": first_event.get('start', {}).get('dateTime', '')[:16] if first_event else None,
            "busy_day": len(events) >= 5
        }
    
    async def _get_email_stats(self) -> Dict[str, Any]:
        """Get email statistics"""
        try:
            # Count unread
            unread = await asyncio.to_thread(
                self.email_service.list_emails,
                max_results=100,
                query='is:unread'
            )
            
            # Count sent today
            today = datetime.now().date().isoformat()
            sent = await asyncio.to_thread(
                self.email_service.list_emails,
                max_results=50,
                query=f'in:sent after:{today}'
            )
            
            return {
                "unread_count": len(unread),
                "sent_today": len(sent),
                "inbox_zero": len(unread) == 0
            }
        except Exception as e:
            logger.error(f"Failed to get email stats: {e}")
            return {}
    
    def _calculate_productivity(
        self,
        today: Dict,
        tasks: Dict
    ) -> Dict[str, Any]:
        """Calculate productivity metrics"""
        completed = tasks.get('completed_today', 0)
        high_priority = tasks.get('high_priority_completed', 0)
        meetings = today.get('events_attended', 0)
        meeting_hours = today.get('total_meeting_hours', 0)
        
        # Base score from completed tasks
        base_score = min(50, completed * 10)
        
        # Bonus for high priority
        priority_bonus = min(20, high_priority * 10)
        
        # Focus time bonus (less meetings = more focus)
        focus_bonus = max(0, 30 - (meeting_hours * 4))
        
        # Calculate total
        total_score = min(100, base_score + priority_bonus + focus_bonus)
        
        # Determine grade
        grade = (
            "A" if total_score >= 90 else
            "B" if total_score >= 75 else
            "C" if total_score >= 60 else
            "D" if total_score >= 40 else
            "F"
        )
        
        return {
            "score": total_score,
            "grade": grade,
            "breakdown": {
                "tasks_completed": base_score,
                "high_priority_bonus": priority_bonus,
                "focus_time_bonus": focus_bonus
            },
            "focus_hours": max(0, 8 - meeting_hours),
            "tasks_per_hour": round(completed / max(1, 8 - meeting_hours), 1)
        }
    
    def _generate_insights(
        self,
        today: Dict,
        tasks: Dict,
        tomorrow: Dict
    ) -> List[Dict[str, str]]:
        """Generate personalized insights"""
        insights = []
        
        # Great day
        if tasks.get('completed_today', 0) >= 5:
            insights.append({
                "type": "achievement",
                "icon": "🎉",
                "message": f"Great day! You completed {tasks['completed_today']} tasks."
            })
        
        # Focus day
        if today.get('total_meeting_hours', 0) <= 2:
            insights.append({
                "type": "focus",
                "icon": "🎯",
                "message": "Low meeting day - hope you got some deep work done!"
            })
        
        # Overdue warning
        if tasks.get('overdue_count', 0) > 0:
            insights.append({
                "type": "warning",
                "icon": "⚠️",
                "message": f"You have {tasks['overdue_count']} overdue tasks. Consider prioritizing these."
            })
        
        # Busy tomorrow
        if tomorrow.get('busy_day', False):
            insights.append({
                "type": "heads_up",
                "icon": "📅",
                "message": f"Heads up: Tomorrow has {tomorrow['events_scheduled']} meetings scheduled."
            })
        
        # Early start
        first_time = tomorrow.get('first_event_time', '')
        if first_time and ('T07' in first_time or 'T08' in first_time):
            time_str = first_time.split('T')[1][:5] if 'T' in first_time else first_time
            insights.append({
                "type": "reminder",
                "icon": "🌅",
                "message": f"Early start tomorrow: first meeting at {time_str}."
            })
        
        # Task-free tomorrow
        if tomorrow.get('tasks_due', 0) == 0 and tomorrow.get('events_scheduled', 0) <= 2:
            insights.append({
                "type": "opportunity",
                "icon": "💡",
                "message": "Light day tomorrow - great opportunity for catch-up or strategic work."
            })
        
        return insights
    
    def _format_text_summary(self, result: Dict) -> str:
        """Format as readable text"""
        lines = []
        lines.append("🌙 END OF DAY REVIEW")
        lines.append("=" * 50)
        lines.append("")
        
        # Productivity
        prod = result.get('productivity', {})
        lines.append(f"📊 PRODUCTIVITY SCORE: {prod.get('score', 0)}/100 ({prod.get('grade', 'N/A')})")
        lines.append("")
        
        # Today's accomplishments
        tasks = result.get('tasks', {})
        lines.append("✅ TODAY'S ACCOMPLISHMENTS")
        lines.append(f"• Tasks Completed: {tasks.get('completed_today', 0)}")
        lines.append(f"• High Priority: {tasks.get('high_priority_completed', 0)}")
        
        today = result.get('today', {})
        lines.append(f"• Meetings Attended: {today.get('events_attended', 0)}")
        lines.append(f"• Meeting Hours: {today.get('total_meeting_hours', 0)}")
        lines.append("")
        
        # Insights
        insights = result.get('insights', [])
        if insights:
            lines.append("💡 INSIGHTS")
            for insight in insights:
                lines.append(f"{insight.get('icon', '•')} {insight.get('message', '')}")
            lines.append("")
        
        # Tomorrow preview
        tomorrow = result.get('tomorrow', {})
        lines.append("🔮 TOMORROW")
        lines.append(f"• Meetings: {tomorrow.get('events_scheduled', 0)}")
        lines.append(f"• Tasks Due: {tomorrow.get('tasks_due', 0)}")
        if tomorrow.get('first_event'):
            lines.append(f"• First Meeting: {tomorrow['first_event'].get('summary', 'Untitled')}")
        lines.append("")
        
        return "\n".join(lines)
