"""
Task Query Handlers

Handles task query operations: list, search, analytics, and other query operations.
This module centralizes query handling logic to keep the main TaskTool class clean.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from .constants import DEFAULT_STATUS, MAX_COMPLETED_TASKS_FOR_CONTEXT
from .utils import TaskUtils

logger = setup_logger(__name__)


class TaskQueryHandlers:
    """
    Handles task query operations.
    
    This class centralizes list, search, and other query operations
    to improve maintainability and keep the main TaskTool class focused.
    """
    
    def __init__(self, task_tool):
        """
        Initialize query handlers.
        
        Args:
            task_tool: Parent TaskTool instance for accessing services, config, etc.
        """
        self.task_tool = task_tool
        self.config = task_tool.config if hasattr(task_tool, 'config') else None
    
    def handle_list(
        self,
        status: Optional[str],
        priority: Optional[str],
        category: Optional[str],
        tags: Optional[List[str]],
        project: Optional[str],
        description: Optional[str],
        due_date: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle task listing.
        
        Args:
            status: Task status filter
            priority: Task priority filter
            category: Task category filter
            tags: Task tags filter
            project: Project filter
            description: Task description (for create conversion)
            due_date: Due date (for create conversion)
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Formatted task list string
        """
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for listing tasks
        if workflow_emitter:
            self.task_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr checking your tasks...",
                data={'action': 'list'}
            )
        
        # Check if this is actually a create query that was misclassified
        query_lower = (query or "").lower()
        if ("create" in query_lower or "add" in query_lower) and ("task" in query_lower or "tasks" in query_lower):
            # This is actually a create query, not a list query
            logger.info(f"[TASKS] Converting 'list' action to 'create' for query: {query}")
            # Extract description from query
            if not description:
                # Try to extract task description from query
                description = query or ""
                for prefix in ['please create a task about', 'please create a task', 'please create a tasks about', 'please create a tasks', 
                              'create a task about', 'create a task', 'create a tasks about', 'create a tasks',
                              'create task about', 'create task', 'create tasks about', 'create tasks',
                              'add a task about', 'add a task', 'add a tasks about', 'add a tasks',
                              'add task about', 'add task', 'add tasks about', 'add tasks']:
                    if query_lower.startswith(prefix):
                        description = (query or "")[len(prefix):].strip()
                        break
                # If still no description, use the whole query minus action words
                if description == query:
                    # Remove action words
                    words_to_remove = ['please', 'add', 'a', 'task', 'tasks', 'about', 'create', 'new', 'make']
                    words = [w for w in description.split() if w.lower() not in words_to_remove]
                    description = ' '.join(words) if words else query
            
            # Now create the task using action handler
            return self.task_tool.action_handlers.handle_create(
                description=description,
                due_date=due_date,
                priority=kwargs.get('priority'),
                category=kwargs.get('category'),
                tags=kwargs.get('tags'),
                project=project,
                parent_id=kwargs.get('parent_id'),
                notes=kwargs.get('notes'),
                recurrence=kwargs.get('recurrence'),
                reminder_days=kwargs.get('reminder_days'),
                estimated_hours=kwargs.get('estimated_hours'),
                subtasks=kwargs.get('subtasks'),
                query=query,
                **kwargs
            )
        
        # Ensure status defaults to "pending" for list action
        # This is critical - users asking "what tasks do I have" want pending tasks, not completed
        list_status = status if status and status != DEFAULT_STATUS else "pending"
        
        # Check if query contains "today" - interpret as "what I need to do today"
        # For "today" queries, show ALL pending tasks (not just tasks due today)
        # because "today" means "what's on my plate today" not "what's due today"
        query_lower = (query or "").lower()
        filter_today = "today" in query_lower
        
        # Get pending tasks (default)
        tasks = self.task_tool.task_service.list_tasks(
            status=list_status,  # Explicitly set to pending for list queries
            priority=priority,
            category=category,
            tags=tags,
            project=project
        )
        
        # For "today" queries, show ALL pending tasks (user wants to see what they need to do today)
        # Only filter by due date if explicitly requested (e.g., "tasks due today")
        if filter_today and "due" in query_lower:
            # User explicitly asked for "tasks due today" - filter by due date
            original_count = len(tasks)
            tasks = TaskUtils.filter_tasks_by_today(tasks, include_no_due_date=True)
            logger.info(f"[TASKS] Filtered to {len(tasks)} tasks due today (from {original_count} total pending)")
        elif filter_today:
            # User asked "what is on my tasks today?" - show ALL pending tasks
            # This is the common interpretation: "what do I need to do today?"
            logger.info(f"[TASKS] 'Today' query detected - showing ALL {len(tasks)} pending tasks (interpreted as 'what I need to do today')")
        
        logger.info(f"[TASKS] List action: status={list_status}, found {len(tasks)} tasks")
        
        # Also get completed count for context if showing pending tasks
        title = f"Tasks ({list_status})"
        if list_status == "pending" and len(tasks) > 0:
            # Get completed count for better context
            try:
                completed_tasks = self.task_tool.task_service.list_tasks(
                    status="completed", 
                    show_completed=True, 
                    limit=MAX_COMPLETED_TASKS_FOR_CONTEXT
                )
                completed_count = len(completed_tasks)
                if completed_count > 0:
                    title = f"Your Tasks ({len(tasks)} pending, {completed_count} completed)"
            except Exception as e:
                logger.debug(f"Could not get completed count: {e}")
        
        return self.task_tool.formatting_handlers.format_task_list(tasks, title, query or "")
    
    def handle_search(
        self,
        query: str,
        description: Optional[str],
        tags: Optional[List[str]],
        category: Optional[str],
        priority: Optional[str],
        status: Optional[str],
        due_date: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle task search.
        
        Args:
            query: Search query string
            description: Task description (for create conversion)
            tags: Task tags filter
            category: Task category filter
            priority: Task priority filter
            status: Task status filter
            due_date: Due date (for create conversion)
            **kwargs: Additional arguments
            
        Returns:
            Formatted search results string
        """
        query_lower = (query or "").lower()
        
        # Check for bulk_complete keywords first (highest priority)
        if any(phrase in query_lower for phrase in [
            "mark all", "complete all", "finish all", "clear all", 
            "mark all tasks", "complete all tasks", "all done", "all tasks done",
            "mark everything", "clear everything"
        ]):
            # This is actually a bulk_complete query, not a search query
            logger.info(f"[TASKS] Converting 'search' action to 'bulk_complete' for query: {query}")
            # Get all pending tasks
            all_pending_tasks = self.task_tool.task_service.list_tasks(
                status="pending", 
                show_completed=False, 
                limit=MAX_COMPLETED_TASKS_FOR_CONTEXT
            )
            task_ids = [task_id for task in all_pending_tasks if (task_id := task.get('id')) is not None]
            
            if not task_ids:
                return "You don't have any pending tasks to complete."
            
            result = self.task_tool.task_service.bulk_complete(task_ids)
            success_count = result.get('success', result.get('success_count', 0))
            total_count = result.get('total', result.get('total_count', len(task_ids)))
            failed_count = result.get('failed', 0)
            
            if success_count == total_count:
                return f"Successfully completed all {success_count} task{'s' if success_count != 1 else ''}!"
            elif success_count > 0:
                return f"Completed {success_count} out of {total_count} tasks. {failed_count} task{'s' if failed_count != 1 else ''} failed."
            else:
                return f"[ERROR] Failed to complete any tasks. {result.get('error', 'Unknown error')}"
        
        # Check for create keywords second
        if any(keyword in query_lower for keyword in ['add', 'create', 'new', 'make', 'schedule']) and 'task' in query_lower:
            # This is actually a create query, not a search query
            logger.info(f"[TASKS] Converting 'search' action to 'create' for query: {query}")
            # Extract description from query
            if not description:
                # Try to extract task description from query
                # Remove common prefixes like "please add a task about", "add task", etc.
                description = query or ""
                for prefix in ['please add a task about', 'please add a task', 'add a task about', 'add a task', 'add task about', 'add task', 'create a task about', 'create a task', 'create task about', 'create task']:
                    if query_lower.startswith(prefix):
                        description = (query or "")[len(prefix):].strip()
                        break
                # If still no description, use the whole query minus action words
                if description == query:
                    # Remove action words
                    words_to_remove = ['please', 'add', 'a', 'task', 'about', 'create', 'new', 'make']
                    words = [w for w in description.split() if w.lower() not in words_to_remove]
                    description = ' '.join(words) if words else query
            
            # Now create the task using action handler
            return self.task_tool.action_handlers.handle_create(
                description=description,
                due_date=due_date,
                priority=priority,
                category=category,
                tags=tags,
                project=kwargs.get('project'),
                parent_id=kwargs.get('parent_id'),
                notes=kwargs.get('notes'),
                recurrence=kwargs.get('recurrence'),
                reminder_days=kwargs.get('reminder_days'),
                estimated_hours=kwargs.get('estimated_hours'),
                subtasks=kwargs.get('subtasks'),
                query=query,
                **kwargs
            )
        
        # Check for list keywords
        if any(keyword in query_lower for keyword in ['what', 'show', 'list', 'have', 'my', 'today', 'tasks', 'todo']):
            # This is actually a list query, not a search query
            logger.info(f"[TASKS] Converting 'search' action to 'list' for query: {query}")
            # Fall through to list action
            list_status = status if status and status != DEFAULT_STATUS else "pending"
            tasks = self.task_tool.task_service.list_tasks(
                status=list_status,
                priority=priority,
                category=category,
                tags=tags,
                project=kwargs.get('project')
            )
            
            # Filter by "today" if requested
            if "today" in query_lower:
                original_count = len(tasks)
                tasks = TaskUtils.filter_tasks_by_today(tasks, include_no_due_date=True)
                logger.info(f"[TASKS] Filtered to {len(tasks)} tasks due today (from {original_count} total pending, search conversion)")
            
            logger.info(f"[TASKS] List action (from search): status={list_status}, found {len(tasks)} tasks")
            title = f"Your Tasks ({list_status})"
            if list_status == "pending" and len(tasks) > 0:
                try:
                    completed_tasks = self.task_tool.task_service.list_tasks(
                        status="completed", 
                        show_completed=True, 
                        limit=MAX_COMPLETED_TASKS_FOR_CONTEXT
                    )
                    completed_count = len(completed_tasks)
                    if completed_count > 0:
                        title = f"Your Tasks ({len(tasks)} pending, {completed_count} completed)"
                except Exception as e:
                    logger.debug(f"Could not get completed count: {e}")
            return self.task_tool.formatting_handlers.format_task_list(tasks, title, query or "")
        
        # Actual search query
        tasks = self.task_tool.task_service.search_tasks(
            query=query,
            tags=tags,
            category=category,
            priority=priority
        )
        return self.task_tool.formatting_handlers.format_task_list(tasks, f"Search results for '{query}'", query)
    
    def handle_analytics(self, days: int, **kwargs) -> str:
        """
        Handle task analytics.
        
        Args:
            days: Number of days for analytics
            **kwargs: Additional arguments
            
        Returns:
            Formatted analytics string
        """
        analytics = self.task_tool.task_service.get_analytics(days=days)
        return self.task_tool.formatting_handlers.format_analytics(analytics)
    
    def handle_get_overdue(self, query: Optional[str], **kwargs) -> str:
        """
        Handle getting overdue tasks.
        
        Args:
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Formatted overdue tasks string
        """
        tasks = self.task_tool.task_service.get_overdue_tasks()
        return self.task_tool.formatting_handlers.format_task_list(tasks, "Overdue Tasks", query or "")
    
    def handle_get_due_today(self, query: Optional[str], **kwargs) -> str:
        """
        Handle getting tasks due today.
        
        Args:
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Formatted tasks due today string
        """
        # Get all pending tasks and filter for those due today
        all_tasks = self.task_tool.task_service.list_tasks(status="pending", show_completed=False)
        
        # Filter tasks due today using utility method
        today_tasks = TaskUtils.filter_tasks_by_today(all_tasks, include_no_due_date=True)
        
        return self.task_tool.formatting_handlers.format_task_list(today_tasks, "Tasks Due Today", query or "")
    
    def handle_get_completed(self, query: Optional[str], **kwargs) -> str:
        """
        Handle getting completed tasks.
        
        Args:
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Formatted completed tasks string
        """
        # Get completed tasks
        tasks = self.task_tool.task_service.list_tasks(status="completed", show_completed=True)
        return self.task_tool.formatting_handlers.format_task_list(tasks, "Completed Tasks", query or "")
    
    def handle_get_by_priority(
        self,
        priority: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle getting tasks by priority.
        
        Args:
            priority: Priority filter
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Formatted priority-filtered tasks string
        """
        # Get tasks filtered by priority
        priority_filter = priority or kwargs.get('priority', 'high')
        all_tasks = self.task_tool.task_service.list_tasks(status="pending", show_completed=False)
        filtered_tasks = [
            t for t in all_tasks 
            if t.get('priority', 'medium').lower() == priority_filter.lower()
        ]
        return self.task_tool.formatting_handlers.format_task_list(
            filtered_tasks,
            f"{priority_filter.title()} Priority Tasks",
            query or ""
        )


