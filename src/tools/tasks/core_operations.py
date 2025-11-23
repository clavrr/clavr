"""
Core Operations Module for Task Tool

Handles all core CRUD operations for tasks including:
- Creating tasks
- Listing/filtering tasks
- Updating tasks
- Completing tasks
- Deleting tasks
- Searching tasks
- Getting analytics
- Bulk operations
"""
from typing import Optional, List, Dict, Any

from .constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    DEFAULT_ANALYTICS_DAYS,
    DEFAULT_REMINDER_DAYS,
    PRIORITY_MARKERS,
    STATUS_MARKERS,
)
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class CoreOperations:
    """Handles core CRUD operations for tasks"""
    
    def __init__(self, task_tool):
        """
        Initialize core operations
        
        Args:
            task_tool: Reference to parent TaskTool instance
        """
        self.task_tool = task_tool
    
    def create_task(
        self,
        description: str,
        due_date: Optional[str] = None,
        priority: str = DEFAULT_PRIORITY,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        project: Optional[str] = None,
        parent_id: Optional[str] = None,
        subtasks: Optional[List[str]] = None,
        notes: Optional[str] = None,
        recurrence: Optional[str] = None,
        reminder_days: Optional[int] = None,
        estimated_hours: Optional[float] = None,
        **kwargs
    ) -> str:
        """Create a new task"""
        try:
            # Try Google Tasks first if available
            if self.task_tool.google_client and self.task_tool.google_client.is_available():
                return self._create_google_task(description, due_date, notes, priority)
            
            # Fallback to local manager
            return self._create_local_task(
                description, due_date, priority, category, tags, project,
                parent_id, subtasks, notes, recurrence, reminder_days, estimated_hours
            )
            
        except Exception as e:
            return self.task_tool._handle_error(e, "creating task")
    
    def list_tasks(
        self,
        status: str = DEFAULT_STATUS,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        project: Optional[str] = None,
        **kwargs
    ) -> str:
        """List tasks with filtering"""
        try:
            # Try Google Tasks first
            if self.task_tool.google_client and self.task_tool.google_client.is_available():
                return self._list_google_tasks()
            
            # Fallback to local manager
            return self._list_local_tasks(status, priority, category, tags, project)
            
        except Exception as e:
            return self.task_tool._handle_error(e, "listing tasks")
    
    def complete_task(self, task_id: str, **kwargs) -> str:
        """Mark task as complete"""
        try:
            if self.task_tool.google_client and self.task_tool.google_client.is_available():
                self.task_tool.google_client.complete_task(task_id)
                logger.info(f"[GOOGLE TASKS] Completed task: {task_id}")
                return self.task_tool._format_success("Task marked as complete")
            
            self.task_tool.manager.complete_task(task_id)
            logger.info(f"[LOCAL] Completed task: {task_id}")
            return self.task_tool._format_success("Task marked as complete")
            
        except Exception as e:
            return self.task_tool._handle_error(e, "completing task")
    
    def delete_task(self, task_id: str, **kwargs) -> str:
        """Delete a task"""
        try:
            if self.task_tool.google_client and self.task_tool.google_client.is_available():
                self.task_tool.google_client.delete_task(task_id)
                logger.info(f"[GOOGLE TASKS] Deleted task: {task_id}")
                return self.task_tool._format_success("Task deleted")
            
            self.task_tool.manager.delete_task(task_id)
            logger.info(f"[LOCAL] Deleted task: {task_id}")
            return self.task_tool._format_success("Task deleted")
            
        except Exception as e:
            return self.task_tool._handle_error(e, "deleting task")
    
    def update_task(
        self,
        task_id: str,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        status: Optional[str] = None,
        **kwargs
    ) -> str:
        """Update task properties"""
        try:
            if self.task_tool.google_client and self.task_tool.google_client.is_available():
                return self._update_google_task(task_id, description, due_date, notes, status)
            
            return self._update_local_task(
                task_id, description, due_date, priority, category, tags, notes, status
            )
            
        except Exception as e:
            return self.task_tool._handle_error(e, "updating task")
    
    def search_tasks(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        **kwargs
    ) -> str:
        """Search tasks"""
        try:
            tasks = self.task_tool.manager.search_tasks(
                query=query,
                tags=tags,
                category=category,
                priority=priority
            )
            
            if not tasks:
                return "[INFO] No tasks found matching search criteria"
            
            output = f"**Search Results ({len(tasks)} tasks)**\n\n"
            for task in tasks:
                desc = task.get('description', 'Untitled')
                due = task.get('due_date', 'No deadline')
                output += f"- **{desc}**\n  Due: {due}\n\n"
            
            return self.task_tool._format_success(output)
            
        except Exception as e:
            return self.task_tool._handle_error(e, "searching tasks")
    
    def get_analytics(self, days: int = DEFAULT_ANALYTICS_DAYS, **kwargs) -> str:
        """Get task analytics"""
        try:
            analytics = self.task_tool.manager.get_analytics(days=days)
            
            output = f"**Task Analytics (Last {days} days)**\n\n"
            output += f"Completed: {analytics.get('completed', 0)}\n"
            output += f"Pending: {analytics.get('pending', 0)}\n"
            output += f"Overdue: {analytics.get('overdue', 0)}\n"
            output += f"Completion Rate: {analytics.get('completion_rate', 0):.1%}\n"
            
            return self.task_tool._format_success(output)
            
        except Exception as e:
            return self.task_tool._handle_error(e, "getting analytics")
    
    def bulk_complete(self, task_ids: Optional[List[str]] = None, **kwargs) -> str:
        """Complete multiple tasks"""
        if not task_ids:
            return "[ERROR] No task IDs provided"
        
        try:
            completed = 0
            for task_id in task_ids:
                try:
                    self.complete_task(task_id)
                    completed += 1
                except:
                    continue
            
            return self.task_tool._format_success(f"Completed {completed}/{len(task_ids)} tasks")
            
        except Exception as e:
            return self.task_tool._handle_error(e, "bulk completing tasks")
    
    def bulk_delete(self, task_ids: Optional[List[str]] = None, **kwargs) -> str:
        """Delete multiple tasks"""
        if not task_ids:
            return "[ERROR] No task IDs provided"
        
        try:
            deleted = 0
            for task_id in task_ids:
                try:
                    self.delete_task(task_id)
                    deleted += 1
                except:
                    continue
            
            return self.task_tool._format_success(f"Deleted {deleted}/{len(task_ids)} tasks")
            
        except Exception as e:
            return self.task_tool._handle_error(e, "bulk deleting tasks")
    
    def get_overdue_tasks(self, **kwargs) -> str:
        """Get overdue tasks"""
        try:
            tasks = self.task_tool.manager.get_overdue_tasks()
            
            if not tasks:
                return "[INFO] No overdue tasks!"
            
            output = f"**Overdue Tasks ({len(tasks)} total)**\n\n"
            for task in tasks:
                desc = task.get('description', 'Untitled')
                due = task.get('due_date', 'Unknown')
                output += f"[!] **{desc}**\n  Was due: {due}\n\n"
            
            return self.task_tool._format_success(output)
            
        except Exception as e:
            return self.task_tool._handle_error(e, "getting overdue tasks")
    
    def get_subtasks(self, parent_id: Optional[str] = None, **kwargs) -> str:
        """Get subtasks of a parent task"""
        if not parent_id:
            return "[ERROR] No parent task ID provided"
        
        try:
            subtasks = self.task_tool.manager.get_subtasks(parent_id)
            
            if not subtasks:
                return "[INFO] No subtasks found"
            
            output = f"**Subtasks ({len(subtasks)} total)**\n\n"
            for task in subtasks:
                desc = task.get('description', 'Untitled')
                status_mark = "[X]" if task.get('status') == 'completed' else "[ ]"
                output += f"{status_mark} {desc}\n"
            
            return self.task_tool._format_success(output)
            
        except Exception as e:
            return self.task_tool._handle_error(e, "getting subtasks")
    
    def get_tasks_with_reminders(self, days: int = DEFAULT_REMINDER_DAYS, **kwargs) -> str:
        """Get tasks with upcoming reminders"""
        try:
            tasks = self.task_tool.manager.get_tasks_with_reminders(days=days)
            
            if not tasks:
                return f"[INFO] No tasks with reminders in the next {days} days"
            
            output = f"**Tasks with Reminders (Next {days} days)**\n\n"
            for task in tasks:
                desc = task.get('description', 'Untitled')
                reminder = task.get('reminder_date', 'Unknown')
                output += f"[!] **{desc}**\n  Reminder: {reminder}\n\n"
            
            return self.task_tool._format_success(output)
            
        except Exception as e:
            return self.task_tool._handle_error(e, "getting tasks with reminders")
    
    # Helper methods
    
    def _create_google_task(
        self,
        description: str,
        due_date: Optional[str],
        notes: Optional[str],
        priority: str
    ) -> str:
        """Create task in Google Tasks"""
        task = self.task_tool.google_client.create_task(
            title=description,
            due=due_date,
            notes=notes
        )
        task_id = task.get('id', 'unknown')
        logger.info(f"[GOOGLE TASKS] Created task: {description} (ID: {task_id})")
        return self.task_tool._format_success(
            f"**Task Created**\n\n**{description}**\nDue: {due_date or 'No deadline'}\nPriority: {priority}"
        )
    
    def _create_local_task(
        self,
        description: str,
        due_date: Optional[str],
        priority: str,
        category: Optional[str],
        tags: Optional[List[str]],
        project: Optional[str],
        parent_id: Optional[str],
        subtasks: Optional[List[str]],
        notes: Optional[str],
        recurrence: Optional[str],
        reminder_days: Optional[int],
        estimated_hours: Optional[float]
    ) -> str:
        """Create task in local manager"""
        task_id = self.task_tool.manager.create_task(
            description=description,
            due_date=due_date,
            priority=priority,
            category=category,
            tags=tags or [],
            project=project,
            parent_id=parent_id,
            notes=notes,
            recurrence=recurrence,
            reminder_days=reminder_days,
            estimated_hours=estimated_hours
        )
        
        if subtasks:
            for subtask_desc in subtasks:
                self.task_tool.manager.create_task(
                    description=subtask_desc,
                    parent_id=task_id,
                    priority=priority
                )
            logger.info(f"[LOCAL] Created task with {len(subtasks)} subtasks")
        
        logger.info(f"[LOCAL] Created task: {description} (ID: {task_id})")
        return self.task_tool._format_success(
            f"**Task Created (Local)**\n\n**{description}**\nDue: {due_date or 'No deadline'}\nPriority: {priority}"
        )
    
    def _list_google_tasks(self) -> str:
        """List tasks from Google Tasks"""
        tasks = self.task_tool.google_client.list_tasks()
        
        if not tasks:
            return "[INFO] No tasks found"
        
        output = f"**Tasks ({len(tasks)} total)**\n\n"
        for task in tasks:
            title = task.get('title', 'Untitled')
            due = task.get('due', 'No deadline')
            status_mark = "[X]" if task.get('status') == 'completed' else "[ ]"
            output += f"{status_mark} {title}\n  Due: {due}\n\n"
        
        return self.task_tool._format_success(output)
    
    def _list_local_tasks(
        self,
        status: str,
        priority: Optional[str],
        category: Optional[str],
        tags: Optional[List[str]],
        project: Optional[str]
    ) -> str:
        """List tasks from local manager"""
        tasks = self.task_tool.manager.list_tasks(
            status=status,
            priority=priority,
            category=category,
            tags=tags,
            project=project
        )
        
        if not tasks:
            return "[INFO] No tasks found"
        
        output = f"**{status.title()} Tasks ({len(tasks)} total)**\n\n"
        
        for task in tasks:
            desc = task.get('description', 'Untitled')
            due = task.get('due_date', 'No deadline')
            pri = task.get('priority', DEFAULT_PRIORITY)
            cat = task.get('category', '')
            
            pri_mark = PRIORITY_MARKERS.get(pri, '[ ]')
            
            output += f"{pri_mark} **{desc}**\n"
            output += f"  Due: {due}\n"
            if cat:
                output += f"  Category: {cat}\n"
            output += "\n"
        
        return self.task_tool._format_success(output)
    
    def _update_google_task(
        self,
        task_id: str,
        description: Optional[str],
        due_date: Optional[str],
        notes: Optional[str],
        status: Optional[str]
    ) -> str:
        """Update task in Google Tasks"""
        update_data = {}
        if description:
            update_data['title'] = description
        if due_date:
            update_data['due'] = due_date
        if notes:
            update_data['notes'] = notes
        if status:
            update_data['status'] = status
        
        self.task_tool.google_client.update_task(task_id, **update_data)
        logger.info(f"[GOOGLE TASKS] Updated task: {task_id}")
        return self.task_tool._format_success("Task updated")
    
    def _update_local_task(
        self,
        task_id: str,
        description: Optional[str],
        due_date: Optional[str],
        priority: Optional[str],
        category: Optional[str],
        tags: Optional[List[str]],
        notes: Optional[str],
        status: Optional[str]
    ) -> str:
        """Update task in local manager"""
        update_data = {}
        if description:
            update_data['description'] = description
        if due_date:
            update_data['due_date'] = due_date
        if priority:
            update_data['priority'] = priority
        if category:
            update_data['category'] = category
        if tags:
            update_data['tags'] = tags
        if notes:
            update_data['notes'] = notes
        if status:
            update_data['status'] = status
        
        self.task_tool.manager.update_task(task_id, **update_data)
        logger.info(f"[LOCAL] Updated task: {task_id}")
        return self.task_tool._format_success("Task updated")
