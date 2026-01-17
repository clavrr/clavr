"""
Weekly Planning Workflow

Generates a comprehensive weekly planning overview with:
- This week's schedule
- Tasks due this week
- Last week review (optional)
- Recommendations for the week
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ..base.workflow import Workflow, WorkflowContext
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class WeeklyPlanningWorkflow(Workflow):
    """
    Weekly planning workflow.
    
    Provides a comprehensive view of the upcoming week
    with calendar, tasks, and actionable recommendations.
    """
    
    name = "weekly_planning"
    description = "Generate weekly planning overview with schedule, tasks, and recommendations"
    version = "2.0.0"
    
    def __init__(
        self,
        calendar_service: Any,
        task_service: Any
    ):
        """
        Initialize with required services.
        
        Args:
            calendar_service: Calendar service instance
            task_service: Task service instance
        """
        self.calendar_service = calendar_service
        self.task_service = task_service
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_last_week": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include last week's review"
                },
                "week_offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "Week offset from current (0=this week, 1=next week)"
                }
            }
        }
    
    async def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute the weekly planning workflow"""
        params = context.params
        include_last_week = params.get('include_last_week', True)
        week_offset = params.get('week_offset', 0)
        
        # Calculate week boundaries
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_start = week_start + timedelta(weeks=week_offset)
        week_end = week_start + timedelta(days=7)
        
        # Fetch data in parallel
        tasks = [
            self._get_week_calendar(week_start, week_end),
            self._get_week_tasks(week_start, week_end)
        ]
        
        if include_last_week:
            last_week_start = week_start - timedelta(days=7)
            last_week_end = week_start
            tasks.append(self._get_last_week_stats(last_week_start, last_week_end))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        calendar_data = results[0] if not isinstance(results[0], Exception) else {"events": [], "error": str(results[0])}
        tasks_data = results[1] if not isinstance(results[1], Exception) else {"tasks": [], "error": str(results[1])}
        last_week = results[2] if len(results) > 2 and not isinstance(results[2], Exception) else {}
        
        # Generate recommendations
        recommendations = self._generate_recommendations(calendar_data, tasks_data)
        
        # Calculate workload distribution
        workload = self._calculate_workload(calendar_data, tasks_data)
        
        result = {
            "generated_at": datetime.now().isoformat(),
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "calendar": calendar_data,
            "tasks": tasks_data,
            "last_week": last_week,
            "recommendations": recommendations,
            "workload": workload,
            "summary": self._generate_summary(calendar_data, tasks_data, last_week)
        }
        
        return result
    
    async def _get_week_calendar(self, week_start, week_end) -> Dict[str, Any]:
        """Fetch calendar events for the week"""
        events = await asyncio.to_thread(
            self.calendar_service.list_events,
            start_date=week_start.isoformat(),
            end_date=week_end.isoformat()
        )
        
        # Group events by day
        events_by_day = {}
        for day_offset in range(7):
            day = (week_start + timedelta(days=day_offset)).isoformat()
            events_by_day[day] = []
        
        for event in events:
            event_date = event.get('start', {}).get('dateTime', '')[:10]
            if not event_date:
                event_date = event.get('start', {}).get('date', '')
            if event_date in events_by_day:
                events_by_day[event_date].append(event)
        
        # Calculate daily stats
        day_stats = {}
        for day, day_events in events_by_day.items():
            total_minutes = 0
            for event in day_events:
                # Estimate duration
                start = event.get('start', {}).get('dateTime', '')
                end = event.get('end', {}).get('dateTime', '')
                if start and end:
                    try:
                        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                        total_minutes += (end_dt - start_dt).total_seconds() / 60
                    except Exception as e:
                        logger.debug(f"[WeeklyPlanning] Failed to parse event time: {e}")
            
            day_stats[day] = {
                "event_count": len(day_events),
                "meeting_hours": round(total_minutes / 60, 1),
                "is_busy": len(day_events) >= 4
            }
        
        # Find busiest day
        busiest_day = max(
            events_by_day.items(),
            key=lambda x: len(x[1]),
            default=(None, [])
        )
        
        return {
            "total_events": len(events),
            "events_by_day": events_by_day,
            "day_stats": day_stats,
            "busiest_day": busiest_day[0],
            "busiest_day_count": len(busiest_day[1]),
            "total_meeting_hours": sum(s['meeting_hours'] for s in day_stats.values())
        }
    
    async def _get_week_tasks(self, week_start, week_end) -> Dict[str, Any]:
        """Fetch tasks for the week"""
        all_tasks = await asyncio.to_thread(
            self.task_service.list_tasks,
            status='active',
            limit=200
        )
        
        # Filter to week's tasks
        week_tasks = [
            t for t in all_tasks
            if t.get('due_date') and 
               week_start.isoformat() <= t['due_date'] <= week_end.isoformat()
        ]
        
        # Group by priority
        by_priority = {
            'urgent': [],
            'high': [],
            'medium': [],
            'low': []
        }
        
        for task in week_tasks:
            priority = task.get('priority', 'medium')
            if priority in by_priority:
                by_priority[priority].append(task)
        
        # Group by day
        tasks_by_day = {}
        for day_offset in range(7):
            day = (week_start + timedelta(days=day_offset)).isoformat()
            tasks_by_day[day] = [
                t for t in week_tasks
                if t.get('due_date') == day
            ]
        
        return {
            "total_tasks": len(week_tasks),
            "by_priority": {k: len(v) for k, v in by_priority.items()},
            "urgent_tasks": by_priority['urgent'],
            "high_priority_tasks": by_priority['high'],
            "tasks_by_day": tasks_by_day,
            "total_blocked": len([t for t in week_tasks if t.get('status') == 'blocked'])
        }
    
    async def _get_last_week_stats(self, last_week_start, last_week_end) -> Dict[str, Any]:
        """Get last week's completion stats"""
        try:
            # Get completed tasks
            completed_tasks = await asyncio.to_thread(
                self.task_service.list_tasks,
                status='completed',
                limit=200
            )
            
            # Filter to last week
            last_week_completed = [
                t for t in completed_tasks
                if t.get('completed_date') and
                   last_week_start.isoformat() <= t['completed_date'] < last_week_end.isoformat()
            ]
            
            # Get events
            last_week_events = await asyncio.to_thread(
                self.calendar_service.list_events,
                start_date=last_week_start.isoformat(),
                end_date=last_week_end.isoformat()
            )
            
            # Calculate productivity score (simple heuristic)
            base_score = min(100, len(last_week_completed) * 10)
            meeting_penalty = max(0, (len(last_week_events) - 20) * 2)
            productivity_score = max(0, base_score - meeting_penalty)
            
            return {
                "tasks_completed": len(last_week_completed),
                "meetings_attended": len(last_week_events),
                "productivity_score": productivity_score,
                "high_priority_completed": len([
                    t for t in last_week_completed
                    if t.get('priority') in ['urgent', 'high']
                ])
            }
        except Exception as e:
            logger.error(f"Failed to get last week stats: {e}")
            return {}
    
    def _generate_recommendations(
        self,
        calendar: Dict,
        tasks: Dict
    ) -> List[Dict[str, str]]:
        """Generate recommendations for the week"""
        recommendations = []
        
        # Check for overloaded days
        events_by_day = calendar.get('events_by_day', {})
        day_stats = calendar.get('day_stats', {})
        
        for day, stats in day_stats.items():
            if stats.get('event_count', 0) >= 6:
                day_name = datetime.fromisoformat(day).strftime('%A')
                recommendations.append({
                    "type": "overloaded_day",
                    "priority": "high",
                    "icon": "⚠️",
                    "message": f"{day_name} has {stats['event_count']} meetings ({stats['meeting_hours']}h). Consider rescheduling some.",
                    "day": day
                })
        
        # Check for urgent tasks
        urgent_count = tasks.get('by_priority', {}).get('urgent', 0)
        if urgent_count > 0:
            recommendations.append({
                "type": "urgent_tasks",
                "priority": "high",
                "icon": "🔴",
                "message": f"You have {urgent_count} urgent tasks this week. Schedule dedicated time to complete them."
            })
        
        # Check for light days (opportunities)
        free_days = []
        for day, events in events_by_day.items():
            day_of_week = datetime.fromisoformat(day).weekday()
            if day_of_week < 5 and len(events) <= 1:  # Weekday with ≤1 meeting
                day_name = datetime.fromisoformat(day).strftime('%A')
                free_days.append(day_name)
        
        if free_days:
            recommendations.append({
                "type": "focus_days",
                "priority": "info",
                "icon": "💡",
                "message": f"Light meeting days: {', '.join(free_days)}. Great for deep work!"
            })
        
        # Meeting hours warning
        total_hours = calendar.get('total_meeting_hours', 0)
        if total_hours > 25:
            recommendations.append({
                "type": "meeting_overload",
                "priority": "medium",
                "icon": "⏰",
                "message": f"You have {total_hours:.1f} hours of meetings this week. Consider protecting some focus time."
            })
        
        # Task distribution
        tasks_by_day = tasks.get('tasks_by_day', {})
        max_day_tasks = max((len(t) for t in tasks_by_day.values()), default=0)
        if max_day_tasks > 5:
            recommendations.append({
                "type": "task_clustering",
                "priority": "medium",
                "icon": "📋",
                "message": f"Some days have many tasks due. Consider spreading them out."
            })
        
        return recommendations
    
    def _calculate_workload(
        self,
        calendar: Dict,
        tasks: Dict
    ) -> Dict[str, Any]:
        """Calculate daily workload distribution"""
        day_stats = calendar.get('day_stats', {})
        tasks_by_day = tasks.get('tasks_by_day', {})
        
        workload = {}
        for day in day_stats.keys():
            meeting_hours = day_stats.get(day, {}).get('meeting_hours', 0)
            task_count = len(tasks_by_day.get(day, []))
            
            # Simple workload score (max 10)
            meeting_score = min(5, meeting_hours / 2)
            task_score = min(5, task_count)
            total_score = meeting_score + task_score
            
            workload[day] = {
                "meeting_hours": meeting_hours,
                "task_count": task_count,
                "score": round(total_score, 1),
                "level": (
                    "light" if total_score < 3 else
                    "moderate" if total_score < 6 else
                    "heavy" if total_score < 8 else
                    "overloaded"
                )
            }
        
        return workload
    
    def _generate_summary(
        self,
        calendar: Dict,
        tasks: Dict,
        last_week: Dict
    ) -> Dict[str, Any]:
        """Generate summary statistics"""
        return {
            "total_events": calendar.get('total_events', 0),
            "total_meeting_hours": calendar.get('total_meeting_hours', 0),
            "total_tasks": tasks.get('total_tasks', 0),
            "urgent_tasks": tasks.get('by_priority', {}).get('urgent', 0),
            "busiest_day": calendar.get('busiest_day'),
            "last_week_productivity": last_week.get('productivity_score'),
            "last_week_completed": last_week.get('tasks_completed')
        }
