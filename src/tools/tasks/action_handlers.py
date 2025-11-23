"""
Task Action Handlers

Handles core task CRUD operations: create, update, delete, complete.
This module centralizes action handling logic to keep the main TaskTool class clean.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from ...utils.logger import setup_logger
from .constants import DEFAULT_PRIORITY

logger = setup_logger(__name__)


class TaskActionHandlers:
    """
    Handles core task CRUD operations.
    
    This class centralizes create, update, delete, and complete action handling
    to improve maintainability and keep the main TaskTool class focused.
    """
    
    def __init__(self, task_tool):
        """
        Initialize action handlers.
        
        Args:
            task_tool: Parent TaskTool instance for accessing services, config, etc.
        """
        self.task_tool = task_tool
        self.config = task_tool.config if hasattr(task_tool, 'config') else None
    
    def handle_create(
        self,
        description: Optional[str],
        due_date: Optional[str],
        priority: Optional[str],
        category: Optional[str],
        tags: Optional[List[str]],
        project: Optional[str],
        parent_id: Optional[str],
        notes: Optional[str],
        recurrence: Optional[str],
        reminder_days: Optional[int],
        estimated_hours: Optional[float],
        subtasks: Optional[List[str]],
        query: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle task creation.
        
        Args:
            description: Task description/title
            due_date: Task due date
            priority: Task priority
            category: Task category
            tags: Task tags
            project: Project name
            parent_id: Parent task ID
            notes: Task notes
            recurrence: Recurrence pattern
            reminder_days: Days before due date for reminder
            estimated_hours: Estimated hours to complete
            subtasks: List of subtask descriptions
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Response string
        """
        # If description is missing, try to extract it from the query
        if not description and query:
            # Try to extract description from query using simple patterns
            query_lower = query.lower()
            # Remove common prefixes
            for prefix in ['please create a task about', 'please create a task', 'please create task about', 'please create task',
                          'create a task about', 'create a task', 'create task about', 'create task',
                          'add a task about', 'add a task', 'add task about', 'add task']:
                if query_lower.startswith(prefix):
                    description = query[len(prefix):].strip()
                    break
            
            # If still no description, try to remove action words
            if not description:
                words_to_remove = ['please', 'add', 'a', 'task', 'tasks', 'about', 'create', 'new', 'make']
                words = [w for w in query.split() if w.lower() not in words_to_remove]
                description = ' '.join(words) if words else query
            
            logger.info(f"[TASK] Extracted description from query: '{description}'")
        
        if not description:
            return "[ERROR] Please provide 'description' for create action"
        
        # Emit high-level action event
        workflow_emitter = kwargs.get('workflow_emitter')
        if workflow_emitter:
            self.task_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr creating task...",
                data={'description': description}
            )
        
        result = self.task_tool.task_service.create_task(
            title=description,  # 'description' maps to 'title' in service
            due_date=due_date,
            priority=priority,
            category=category,
            tags=tags,
            project=project,
            parent_id=parent_id,
            notes=notes,
            recurrence=recurrence,
            reminder_days=reminder_days,
            estimated_hours=estimated_hours,
            subtasks=subtasks
        )
        task_id = result.get('id', 'N/A')
        return f"Task created successfully (ID: {task_id})"
    
    def handle_complete(
        self,
        task_id: Optional[str],
        description: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle task completion.
        
        Args:
            task_id: Task ID to complete
            description: Task description for searching
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Response string
        """
        # Emit high-level action event
        workflow_emitter = kwargs.get('workflow_emitter')
        if workflow_emitter:
            self.task_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr completing task...",
                data={'task_id': task_id, 'description': description}
            )
        
        # SMART COMPLETE HANDLER: Uses context, handles follow-ups, auto-completes when obvious
        if not task_id:
            # Check if this is a follow-up query (e.g., "the first one", "the second one")
            selected_task = self.task_tool._handle_follow_up_selection(query, description)
            if selected_task:
                task_id = selected_task.get('id')
                task_title = selected_task.get('title', selected_task.get('description', 'task'))
                logger.info(f"[TASK] Resolved follow-up selection: {task_title}")
            else:
                # Extract description from query if not provided
                if not description and query:
                    description = self.task_tool._extract_task_description_from_complete_query(query)
                    logger.info(f"[TASK] Extracted description from query: '{description}'")
                
                if description:
                    # Search for tasks matching description
                    tasks = self.task_tool.task_service.search_tasks(query=description)
                    tasks = tasks[:10]
                    
                    if not tasks:
                        return f"I couldn't find any tasks matching '{description}'. Could you check the exact wording?"
                    
                    # SMART DECISION: Filter to pending tasks only (can't complete already completed)
                    pending_tasks = [t for t in tasks if t.get('status', 'pending') != 'completed']
                    completed_tasks = [t for t in tasks if t.get('status', 'pending') == 'completed']
                    
                    # If only one pending task, auto-complete it (be proactive!)
                    if len(pending_tasks) == 1:
                        task_id = pending_tasks[0].get('id')
                        task_title = pending_tasks[0].get('title', pending_tasks[0].get('description', description))
                        logger.info(f"[TASK] Auto-completing single pending task: {task_title}")
                        # Continue to completion below
                    elif len(pending_tasks) == 0:
                        if completed_tasks:
                            return f"All tasks matching '{description}' are already completed! Great job! 🎉"
                        else:
                            return f"I couldn't find any pending tasks matching '{description}'."
                    else:
                        # Multiple pending tasks - show list and store for follow-up
                        self.task_tool._last_task_list = pending_tasks
                        self.task_tool._last_task_list_query = description
                        
                        return self._format_task_selection_list(pending_tasks, "complete", description)
                else:
                    return "I need to know which task to mark as done. You can say something like 'mark task X done' or 'complete the task about Y'."
        
        # Complete the task
        if not task_id:
            return "I couldn't identify which task to complete. Please try again with more details."
        
        # Get task title for better response
        try:
            task_details = self.task_tool.task_service.get_task(task_id)
            task_title = task_details.get('title', task_details.get('description', 'task'))
        except:
            task_title = description or "task"
        
        self.task_tool.task_service.complete_task(task_id)
        # Clear the stored list since we completed a task
        self.task_tool._last_task_list = None
        self.task_tool._last_task_list_query = None
        return f"Done! I've marked '{task_title}' as complete."
    
    def handle_delete(
        self,
        task_id: Optional[str],
        description: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle task deletion.
        
        Args:
            task_id: Task ID to delete
            description: Task description for searching
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Response string
        """
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for deleting task
        if workflow_emitter:
            self.task_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr deleting task...",
                data={'action': 'delete'}
            )
        
        # SMART DELETE HANDLER: Uses context, handles follow-ups, auto-deletes when obvious
        if not task_id:
            # Check if this is a follow-up query (e.g., "the first one", "the second one")
            selected_task = self.task_tool._handle_follow_up_selection(query, description)
            if selected_task:
                task_id = selected_task.get('id')
                task_title = selected_task.get('title', selected_task.get('description', 'task'))
                logger.info(f"[TASK] Resolved follow-up selection for delete: {task_title}")
            else:
                if description:
                    # Search for tasks matching description
                    tasks = self.task_tool.task_service.search_tasks(query=description)
                    tasks = tasks[:10]
                    
                    if not tasks:
                        return f"I couldn't find any tasks matching '{description}'."
                    
                    # If only one task, auto-delete it (be proactive!)
                    if len(tasks) == 1:
                        task_id = tasks[0].get('id')
                        task_title = tasks[0].get('title', tasks[0].get('description', description))
                        logger.info(f"[TASK] Auto-deleting single matching task: {task_title}")
                    else:
                        # Multiple matches - show list and store for follow-up
                        self.task_tool._last_task_list = tasks
                        self.task_tool._last_task_list_query = description
                        
                        return self._format_task_selection_list(tasks, "delete", description)
                else:
                    return "I need to know which task to delete. You can say something like 'delete task X' or 'remove the task about Y'."
        
        # Delete the task
        if not task_id:
            return "I couldn't identify which task to delete. Please try again with more details."
        
        # Get task title for better response
        try:
            task_details = self.task_tool.task_service.get_task(task_id)
            task_title = task_details.get('title', task_details.get('description', 'task'))
        except:
            task_title = description or "task"
        
        self.task_tool.task_service.delete_task(task_id)
        # Clear the stored list since we deleted a task
        self.task_tool._last_task_list = None
        self.task_tool._last_task_list_query = None
        return f"Done! I've deleted '{task_title}'."
    
    def handle_update(
        self,
        task_id: Optional[str],
        description: Optional[str],
        due_date: Optional[str],
        priority: Optional[str],
        category: Optional[str],
        tags: Optional[List[str]],
        notes: Optional[str],
        status: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle task update.
        
        Args:
            task_id: Task ID to update
            description: New description/title
            due_date: New due date
            priority: New priority
            category: New category
            tags: New tags
            notes: New notes
            status: New status
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Response string
        """
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for updating task
        if workflow_emitter:
            self.task_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr updating task...",
                data={'action': 'update'}
            )
        
        # If task_id is not provided, try to find task by description or from query context
        if not task_id:
            # Try to extract task reference from query
            query_lower = (query or "").lower()
            
            # Check if query mentions "my task", "the task", "this task", etc.
            if any(phrase in query_lower for phrase in ["my task", "the task", "this task", "that task"]):
                # Get the user's pending tasks and use the first one if only one exists
                tasks = self.task_tool.task_service.list_tasks(status="pending", limit=10)
                if len(tasks) == 1:
                    task_id = tasks[0].get('id')
                    task_title = tasks[0].get('title', tasks[0].get('description', 'task'))
                    logger.info(f"[TASK] Found single pending task for update: {task_id}")
                elif len(tasks) > 1:
                    # Multiple tasks - try to match by description if provided
                    if description:
                        matching_tasks = [t for t in tasks if description.lower() in t.get('title', '').lower()]
                        if len(matching_tasks) == 1:
                            task_id = matching_tasks[0].get('id')
                            task_title = matching_tasks[0].get('title', matching_tasks[0].get('description', 'task'))
                            logger.info(f"[TASK] Found task by description for update: {task_id}")
                        else:
                            return f"[ERROR] You have {len(tasks)} tasks. Please specify which task to update (e.g., 'update the task about X')."
                    else:
                        return f"[ERROR] You have {len(tasks)} tasks. Please specify which task to update."
                else:
                    return "[ERROR] You don't have any pending tasks to update."
            elif description:
                # Search for task by description
                tasks = self.task_tool.task_service.search_tasks(query=description)
                tasks = tasks[:10]
                if not tasks:
                    return f"[ERROR] Could not find a task matching '{description}'"
                elif len(tasks) == 1:
                    task_id = tasks[0].get('id')
                    task_title = tasks[0].get('title', tasks[0].get('description', 'task'))
                    logger.info(f"[TASK] Found task by description for update: {task_id}")
                else:
                    task_list = "\n".join([f"{i+1}. {t.get('title', t.get('description', 'Untitled'))} (ID: {t.get('id')})" 
                                          for i, t in enumerate(tasks[:5])])
                    return f"[ERROR] Multiple tasks found matching '{description}'. Please specify which one:\n{task_list}"
            else:
                return "[ERROR] Please specify which task to update (e.g., 'add a due date to my task' or 'update task X')"
        
        # Get task title for conversational response
        if not task_id:
            return "[ERROR] Could not identify which task to update"
        
        # Get task details for better response
        try:
            task_details = self.task_tool.task_service.get_task(task_id)
            task_title = task_details.get('title', task_details.get('description', 'task'))
        except:
            task_title = description or "task"
        
        # Update the task
        result = self.task_tool.task_service.update_task(
            task_id=task_id,
            title=description if description and description != task_title else None,  # Only update title if different
            due_date=due_date,
            priority=priority,
            category=category,
            tags=tags,
            notes=notes,
            status=status
        )
        
        # Generate conversational response
        updates = []
        if due_date:
            # Format due date nicely
            try:
                if isinstance(due_date, str):
                    # Try to parse and format the date
                    try:
                        parsed_date = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                        # Format as "tonight", "tomorrow", or date
                        if "tonight" in (query or "").lower() or "this evening" in (query or "").lower():
                            updates.append("due date to tonight")
                        elif "tomorrow" in (query or "").lower():
                            updates.append("due date to tomorrow")
                        else:
                            updates.append(f"due date to {parsed_date.strftime('%B %d, %Y')}")
                    except:
                        updates.append(f"due date to {due_date}")
                else:
                    updates.append(f"due date to {due_date}")
            except:
                updates.append(f"due date to {due_date}")
        if priority and priority != DEFAULT_PRIORITY:
            updates.append(f"priority to {priority}")
        if category:
            updates.append(f"category to {category}")
        if description and description != task_title:
            updates.append(f"title to '{description}'")
        
        if updates:
            if len(updates) == 1:
                return f"Done! I've set the {updates[0]} for '{task_title}'."
            else:
                update_text = ", ".join(updates[:-1]) + f", and {updates[-1]}"
                return f"Done! I've updated '{task_title}' with {update_text}."
        else:
            return f"Done! I've updated '{task_title}'."
    
    def _format_task_selection_list(
        self,
        tasks: List[Dict[str, Any]],
        action: str,
        search_term: Optional[str] = None
    ) -> str:
        """
        Format a list of tasks for user selection.
        
        Args:
            tasks: List of task dictionaries
            action: Action being performed ("complete" or "delete")
            search_term: Optional search term used
            
        Returns:
            Formatted selection list string
        """
        task_list_parts = []
        for i, t in enumerate(tasks[:5], 1):
            task_title = t.get('title', t.get('description', 'Untitled'))
            due_date = t.get('due_date', t.get('due', None))
            status = t.get('status', 'pending')
            
            task_desc = f"{i}. **{task_title}**"
            if due_date:
                try:
                    if isinstance(due_date, str):
                        parsed_date = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                        task_desc += f" (due {parsed_date.strftime('%b %d')})"
                    else:
                        task_desc += f" (due {due_date})"
                except:
                    if due_date:
                        task_desc += f" (due {due_date})"
            if status == 'completed':
                task_desc += " [completed]"
            
            task_list_parts.append(task_desc)
        
        task_list = "\n".join(task_list_parts)
        
        if search_term:
            return f"I found {len(tasks)} tasks matching '{search_term}'. Which one should I {action}?\n\n{task_list}\n\nJust say 'the first one', 'the second one', or 'the one due [date]' and I'll {action} it!"
        else:
            return f"I found {len(tasks)} tasks. Which one should I {action}?\n\n{task_list}\n\nJust say 'the first one', 'the second one', or 'the one due [date]' and I'll {action} it!"


