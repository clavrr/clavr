"""
Task Utilities Module

Contains hybrid metadata search and other helper functions.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import pytz

from ...utils.logger import setup_logger
from ..constants import ToolLimits
from .constants import DEFAULT_PRIORITY

logger = setup_logger(__name__)


class TaskUtils:
    """Utility functions for task operations"""

    def __init__(self, task_tool):
        """
        Initialize task utilities

        Args:
            task_tool: Reference to parent TaskTool instance
        """
        self.task_tool = task_tool

    def hybrid_metadata_search(
        self,
        query: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        assigned_to: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        due_after: Optional[str] = None,
        due_before: Optional[str] = None,
        has_reminders: Optional[bool] = None,
        linked_email_id: Optional[str] = None,
        linked_event_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        limit: int = ToolLimits.DEFAULT_TASK_LIST_LIMIT
    ) -> str:
        """
        Advanced hybrid search combining multiple criteria

        Searches tasks across all metadata fields with flexible filtering.
        Works with both Google Tasks and local task manager.

        Args:
            query: Text search in title/notes
            priority: Priority level (high/medium/low)
            status: Task status (pending/completed/cancelled)
            category: Task category
            tags: List of tags to match
            assigned_to: Assignee filter
            created_after: Created after date (YYYY-MM-DD)
            created_before: Created before date (YYYY-MM-DD)
            due_after: Due after date (YYYY-MM-DD)
            due_before: Due before date (YYYY-MM-DD)
            has_reminders: Filter tasks with reminders
            linked_email_id: Filter by linked email
            linked_event_id: Filter by linked calendar event
            parent_task_id: Filter by parent task (for subtasks)
            limit: Maximum results

        Returns:
            Formatted search results
        """
        try:
            # Get all tasks from appropriate source
            all_tasks = self._get_all_tasks_for_search()

            # Apply filters
            filtered_tasks = self._apply_filters(
                all_tasks,
                query=query,
                priority=priority,
                status=status,
                category=category,
                tags=tags,
                assigned_to=assigned_to,
                created_after=created_after,
                created_before=created_before,
                due_after=due_after,
                due_before=due_before,
                has_reminders=has_reminders,
                linked_email_id=linked_email_id,
                linked_event_id=linked_event_id,
                parent_task_id=parent_task_id
            )

            # Limit results
            filtered_tasks = filtered_tasks[:limit]

            # Format output
            return self._format_search_results(
                filtered_tasks,
                total=len(all_tasks),
                matched=len(filtered_tasks)
            )

        except Exception as e:
            logger.error(f"Error in hybrid metadata search: {e}")
            return f"[ERROR] Search failed: {str(e)}"

    def _get_all_tasks_for_search(self) -> List[Dict[str, Any]]:
        """Get all tasks from Google Tasks or local manager"""
        try:
            if self.task_tool.google_tasks_service:
                # Get from Google Tasks
                results = self.task_tool.google_tasks_service.tasks().list(
                    tasklist='@default',
                    showCompleted=True,
                    showHidden=True,
                    maxResults=ToolLimits.MAX_GOOGLE_RESULTS
                ).execute()
                tasks = results.get('items', [])
                
                # Convert to standard format
                return [self._convert_google_task(task) for task in tasks]
            else:
                # Get from local manager
                return self.task_tool.local_task_manager.tasks.copy()
        except Exception as e:
            logger.error(f"Error getting tasks for search: {e}")
            return []

    def _convert_google_task(self, google_task: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Google Task to standard format"""
        return {
            'id': google_task.get('id'),
            'title': google_task.get('title'),
            'notes': google_task.get('notes', ''),
            'status': 'completed' if google_task.get('status') == 'completed' else 'pending',
            'due': google_task.get('due'),
            'completed': google_task.get('completed'),
            'updated': google_task.get('updated'),
            # Default values for fields not in Google Tasks
            'priority': DEFAULT_PRIORITY,
            'category': None,
            'tags': [],
            'assigned_to': None,
            'created_at': google_task.get('updated'),
            'reminders': [],
            'linked_email_id': None,
            'linked_event_id': None,
            'parent_task_id': google_task.get('parent')
        }

    def _apply_filters(
        self,
        tasks: List[Dict[str, Any]],
        **filters
    ) -> List[Dict[str, Any]]:
        """Apply all filters to task list"""
        filtered = tasks

        # Text query filter
        if filters.get('query'):
            query = filters['query'].lower()
            filtered = [
                t for t in filtered
                if query in t.get('title', '').lower() or
                   query in t.get('notes', '').lower()
            ]

        # Priority filter
        if filters.get('priority'):
            filtered = [t for t in filtered if t.get('priority') == filters['priority']]

        # Status filter
        if filters.get('status'):
            filtered = [t for t in filtered if t.get('status') == filters['status']]

        # Category filter
        if filters.get('category'):
            filtered = [t for t in filtered if t.get('category') == filters['category']]

        # Tags filter
        if filters.get('tags'):
            tag_set = set(filters['tags'])
            filtered = [
                t for t in filtered
                if tag_set.issubset(set(t.get('tags', [])))
            ]

        # Assigned to filter
        if filters.get('assigned_to'):
            filtered = [t for t in filtered if t.get('assigned_to') == filters['assigned_to']]

        # Date filters
        filtered = self._apply_date_filters(filtered, filters)

        # Boolean filters
        if filters.get('has_reminders') is not None:
            if filters['has_reminders']:
                filtered = [t for t in filtered if t.get('reminders')]
            else:
                filtered = [t for t in filtered if not t.get('reminders')]

        # Link filters
        if filters.get('linked_email_id'):
            filtered = [t for t in filtered if t.get('linked_email_id') == filters['linked_email_id']]

        if filters.get('linked_event_id'):
            filtered = [t for t in filtered if t.get('linked_event_id') == filters['linked_event_id']]

        if filters.get('parent_task_id'):
            filtered = [t for t in filtered if t.get('parent_task_id') == filters['parent_task_id']]

        return filtered

    def _apply_date_filters(
        self,
        tasks: List[Dict[str, Any]],
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Apply date-based filters"""
        filtered = tasks

        try:
            # Created date filters
            if filters.get('created_after'):
                created_after = datetime.fromisoformat(filters['created_after'])
                filtered = [
                    t for t in filtered
                    if t.get('created_at') and
                       datetime.fromisoformat(t['created_at']) >= created_after
                ]

            if filters.get('created_before'):
                created_before = datetime.fromisoformat(filters['created_before'])
                filtered = [
                    t for t in filtered
                    if t.get('created_at') and
                       datetime.fromisoformat(t['created_at']) <= created_before
                ]

            # Due date filters
            if filters.get('due_after'):
                due_after = datetime.fromisoformat(filters['due_after'])
                filtered = [
                    t for t in filtered
                    if t.get('due') and
                       datetime.fromisoformat(t['due']) >= due_after
                ]

            if filters.get('due_before'):
                due_before = datetime.fromisoformat(filters['due_before'])
                filtered = [
                    t for t in filtered
                    if t.get('due') and
                       datetime.fromisoformat(t['due']) <= due_before
                ]

        except (ValueError, TypeError) as e:
            logger.warning(f"Error parsing date filter: {e}")

        return filtered

    def _format_search_results(
        self,
        tasks: List[Dict[str, Any]],
        total: int,
        matched: int
    ) -> str:
        """Format search results for display"""
        if not tasks:
            return f"No tasks found matching criteria (searched {total} tasks)"

        from .constants import PRIORITY_MARKERS, STATUS_MARKERS

        output = [f"**Search Results: {matched} of {total} tasks**\n"]

        for task in tasks:
            priority = task.get('priority', DEFAULT_PRIORITY)
            status = task.get('status', 'pending')
            
            priority_marker = PRIORITY_MARKERS.get(priority, '')
            status_marker = STATUS_MARKERS.get(status, '')

            output.append(f"{priority_marker}{status_marker} **{task.get('title')}**")
            output.append(f"  ID: `{task.get('id')}`")

            if task.get('category'):
                output.append(f"  Category: {task['category']}")

            if task.get('tags'):
                output.append(f"  Tags: {', '.join(task['tags'])}")

            if task.get('due'):
                output.append(f"  Due: {task['due']}")

            if task.get('assigned_to'):
                output.append(f"  Assigned: {task['assigned_to']}")

            if task.get('linked_email_id'):
                output.append(f"  Linked Email: {task['linked_email_id']}")

            if task.get('linked_event_id'):
                output.append(f"  Linked Event: {task['linked_event_id']}")

            if task.get('parent_task_id'):
                output.append(f"  Subtask of: {task['parent_task_id']}")

            output.append("")

        return "\n".join(output)
    
    @staticmethod
    def get_user_timezone(config=None):
        """
        Get user timezone as pytz timezone object.
        
        Args:
            config: Optional config object
            
        Returns:
            pytz timezone object
        """
        from ...core.calendar.utils import get_user_timezone as get_tz_str
        user_tz_str = get_tz_str(config)
        try:
            return pytz.timezone(user_tz_str)
        except Exception:
            return pytz.UTC
    
    @staticmethod
    def parse_task_due_date(due_date, user_tz=None):
        """
        Parse task due date from various formats to datetime in user timezone.
        
        Args:
            due_date: Due date (can be ISO string, datetime, or None)
            user_tz: User timezone (pytz timezone object). If None, will be fetched.
            
        Returns:
            Tuple of (parsed_date, success) where success is True if parsing succeeded
        """
        if not due_date:
            return None, False
        
        if user_tz is None:
            user_tz = TaskUtils.get_user_timezone()
        
        today = datetime.now(user_tz).date()
        
        try:
            if isinstance(due_date, str):
                # Parse as UTC first, then convert to user timezone
                task_due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                if task_due_dt.tzinfo is None:
                    task_due_dt = pytz.UTC.localize(task_due_dt)
                # Convert to user timezone and get date
                task_due = task_due_dt.astimezone(user_tz).date()
            else:
                # If it's already a datetime object
                if hasattr(due_date, 'date'):
                    if hasattr(due_date, 'tzinfo') and due_date.tzinfo:
                        task_due = due_date.astimezone(user_tz).date()
                    else:
                        task_due = due_date.date()
                else:
                    task_due = today
            
            return task_due, True
        except Exception as e:
            logger.debug(f"Could not parse due date: {e}")
            return None, False
    
    @staticmethod
    def filter_tasks_by_today(tasks, user_tz=None, include_no_due_date=True):
        """
        Filter tasks to only those due today.
        
        Args:
            tasks: List of task dictionaries
            user_tz: User timezone (pytz timezone object). If None, will be fetched.
            include_no_due_date: Whether to include tasks without due dates
            
        Returns:
            List of tasks due today
        """
        if user_tz is None:
            user_tz = TaskUtils.get_user_timezone()
        
        today = datetime.now(user_tz).date()
        today_tasks = []
        
        for task in tasks:
            due_date = task.get('due') or task.get('due_date')
            if due_date:
                task_due, success = TaskUtils.parse_task_due_date(due_date, user_tz)
                if success and task_due == today:
                    today_tasks.append(task)
                elif not success:
                    # If we can't parse the due date, include it to be safe
                    today_tasks.append(task)
            elif include_no_due_date:
                # If no due date, include it in "today" list
                today_tasks.append(task)
        
        return today_tasks
