"""
Task Tool - Task management capabilities
"""
import asyncio
from typing import Optional, Any, Type
from langchain.tools import BaseTool
from pydantic import Field, BaseModel

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)


class TaskInput(BaseModel):
    """Input for TaskTool."""
    action: str = Field(description="Action to perform (create, list, complete, search, etc.)")
    query: Optional[str] = Field(default="", description="Query or details for the action.")
    status: Optional[str] = Field(default="pending", description="Task status filter (pending, completed, all)")
    limit: Optional[int] = Field(default=100, description="Limit result count")
    search_terms: Optional[str] = Field(default=None, description="Terms to search for")
    task_description: Optional[str] = Field(default=None, description="Description of the task to create/complete")
    title: Optional[str] = Field(default=None, description="Title of the task to create")
    notes: Optional[str] = Field(default="", description="Notes for the task")
    due_date: Optional[str] = Field(default=None, description="Due date (YYYY-MM-DD)")
    due: Optional[str] = Field(default=None, description="Alias for due_date")
    priority: Optional[str] = Field(default="medium", description="Priority (low, medium, high)")
    category: Optional[str] = Field(default=None, description="Task category")
    tags: Optional[Any] = Field(default=None, description="List of tags")
    project: Optional[str] = Field(default=None, description="Project name")
    reminder_days: Optional[int] = Field(default=None, description="Reminder days")
    estimated_hours: Optional[float] = Field(default=None, description="Estimated hours")
    template_name: Optional[str] = Field(default=None, description="Name of the template")
    name: Optional[str] = Field(default=None, description="Alias for template_name or title")
    description: Optional[str] = Field(default=None, description="Alias for task_description")
    subtasks: Optional[Any] = Field(default=None, description="List of subtasks")
    recurrence: Optional[str] = Field(default=None, description="Recurrence rule")
    variables: Optional[dict] = Field(default=None, description="Template variables")

from ..base import WorkflowEventMixin


class TaskTool(WorkflowEventMixin, BaseTool):
    """Task management tool wrapping TaskService for Google Tasks API"""
    name: str = "tasks"
    description: str = "Task management (create, list, complete, search). Use this for task-related queries."
    args_schema: Type[BaseModel] = TaskInput
    
    storage_path: str = Field(default="./data/tasks.json")
    config: Optional[Config] = Field(default=None)
    user_id: int = Field(default=1)
    credentials: Optional[Any] = Field(default=None)
    user_first_name: Optional[str] = Field(default=None)
    _task_service: Optional[Any] = None
    
    def __init__(self, storage_path: str = "./data/tasks.json", config: Optional[Config] = None,
                 user_id: int = 1, credentials: Optional[Any] = None, user_first_name: Optional[str] = None, **kwargs):
        super().__init__(
            storage_path=storage_path,
            config=config,
            user_id=user_id,
            credentials=credentials,
            user_first_name=user_first_name,
            **kwargs
        )
        if credentials:
            logger.info(f"[TaskTool] Initialized with credentials (valid={getattr(credentials, 'valid', 'unknown')})")
        else:
            logger.warning("[TaskTool] Initialized with NO credentials")
        self._task_service = None
    
    @property
    def task_service(self) -> Optional[Any]:
        """Lazy initialization of task service for Google Tasks API access"""
        if self._task_service is None and self.credentials and self.config:
            try:
                from ...integrations.google_tasks.service import TaskService
                self._task_service = TaskService(
                    config=self.config,
                    credentials=self.credentials
                )
                logger.info("[TaskTool] TaskService initialized successfully")
            except Exception as e:
                logger.warning(f"[TaskTool] Failed to initialize TaskService: {e}")
        return self._task_service
    
    def _run(self, action: str = "create", query: str = "", **kwargs) -> str:
        """Execute task tool action - CRITICAL: Must return actual task data, not metadata"""
        logger.info(f"[TaskTool] Executing {action} with query='{query}' and kwargs={kwargs}")
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Ensure service is initialized
        if not self.task_service:
             # If action is template-related and we have DB access, we might proceed,
             # but generally we need the service or credentials.
             if action not in ["create_template", "list_templates", "delete_template"]:
                logger.warning(f"[TaskTool] TaskService not available for action {action}")
                return "[INTEGRATION_REQUIRED] Tasks permission not granted. Please enable Google integration in Settings."

        try:
            # CRITICAL FIX: For list/search actions, fetch ACTUAL tasks from Google Tasks API
            
            if action in ["list", "check"] and self.task_service:
                # Fetch actual tasks from Google Tasks API
                status = kwargs.get('status', 'pending')
                
                # VOICE OPTIMIZATION: Reduce limit for fetch
                limit = kwargs.get('limit', 5) # Default to 5 for voice brevety
                
                # VOICE OPTIMIZATION: Use fast_mode (check @default only) if limit is small
                fast_mode = False
                if limit <= 5:
                    fast_mode = True
                    logger.info("[TaskTool] VOICE FAST PATH: Enabling fast_mode (default list only)")

                logger.info(f"[TaskTool] Listing tasks with status={status}, limit={limit}, fast_mode={fast_mode}")
                tasks = self.task_service.list_tasks(status=status, limit=limit, fast_mode=fast_mode)
                logger.info(f"[TaskTool] Found {len(tasks)} tasks")
                
                if not tasks:
                    if status == 'pending':
                        return "You don't have any pending tasks right now. You're all caught up!"
                    return "No tasks found."
                
                # Format tasks for natural response
                task_lines = []
                max_tasks = 5 # Limit to 5 for voice brevety
                for i, task in enumerate(tasks[:max_tasks], 1):
                    title = task.get('title', task.get('description', 'Untitled'))
                    due = task.get('due')
                    status_str = task.get('status', 'needsAction')
                    
                    line = f"{i}. {title}"
                    if due:
                        line += f" (due: {due})"
                    if status_str == 'completed':
                        line += " [DONE]"
                    task_lines.append(line)
                
                result = f"Your tasks ({len(tasks)} total):\n" + "\n".join(task_lines)
                if len(tasks) > max_tasks:
                    result += f"\n... and {len(tasks) - max_tasks} more pending tasks."
                return result
                
            elif action == "search" and self.task_service:
                # Search tasks
                search_terms = kwargs.get('search_terms', query)
                
                # VOICE OPTIMIZATION: Reduce limit and use fast_mode if it's a small search
                limit = kwargs.get('limit', 10) # Default to 10 for search
                fast_mode = False
                if limit <= 10:
                    fast_mode = True
                    logger.info("[TaskTool] VOICE FAST PATH: Enabling fast_mode for search")
                
                tasks = self.task_service.list_tasks(status='all', limit=limit, fast_mode=fast_mode)
                
                # Filter by search terms
                search_lower = search_terms.lower()
                matching = [t for t in tasks if search_lower in t.get('title', '').lower() 
                           or search_lower in t.get('notes', '').lower()]
                
                if not matching:
                    return f"I couldn't find any tasks matching '{search_terms}'."
                
                task_lines = []
                for i, task in enumerate(matching[:10], 1):
                    title = task.get('title', 'Untitled')
                    task_lines.append(f"{i}. {title}")
                
                return f"Found {len(matching)} tasks matching '{search_terms}':\n" + "\n".join(task_lines)
            
            elif action == "get_overdue" and self.task_service:
                # Get overdue tasks (tasks with due dates in the past)
                overdue = self.task_service.get_overdue_tasks(limit=50)
                
                if not overdue:
                    return "Good news! You don't have any past due tasks. You're all caught up!"
                
                task_lines = []
                from datetime import datetime
                now = datetime.now()
                
                for i, task in enumerate(overdue[:20], 1):
                    title = task.get('title', task.get('description', 'Untitled'))
                    due = task.get('due', '')
                    
                    # Calculate days overdue
                    days_overdue = ""
                    if due:
                        try:
                            due_dt = datetime.fromisoformat(due.replace('Z', '+00:00'))
                            if due_dt.tzinfo:
                                due_dt = due_dt.replace(tzinfo=None)
                            delta = (now - due_dt).days
                            if delta == 1:
                                days_overdue = " (1 day overdue)"
                            elif delta > 1:
                                days_overdue = f" ({delta} days overdue)"
                            else:
                                days_overdue = " (due today)"
                        except:
                            pass
                    
                    task_lines.append(f"{i}. {title}{days_overdue}")
                
                if len(overdue) == 1:
                    return f"You have 1 past due task:\n" + "\n".join(task_lines)
                else:
                    result = f"You have {len(overdue)} past due tasks:\n" + "\n".join(task_lines)
                    if len(overdue) > 20:
                        result += f"\n... and {len(overdue) - 20} more overdue tasks"
                    return result
            
            elif action == "complete" and self.task_service:
                task_desc = kwargs.get('task_description', query)
                # Find and complete the task
                tasks = self.task_service.list_tasks(status='pending', limit=100)
                task_lower = task_desc.lower()
                
                task_completed = False
                for task in tasks:
                    title = task.get('title', '').lower()
                    if task_lower in title or title in task_lower:
                        task_id = task.get('id')
                        if task_id:
                            self.task_service.complete_task(task_id)
                            return f"Done! I've marked '{task.get('title')}' as complete. Great job!"
                
                return f"I couldn't find a task matching '{task_desc}' to complete."
            
            elif action == "create_template":
                # Create a task preset
                template_name = kwargs.get('template_name') or kwargs.get('name')
                task_description = kwargs.get('task_description') or kwargs.get('description') or query
                
                if not template_name:
                    return "[ERROR] Could not identify template name. Please specify a name for the template."
                
                try:
                    from ...database import get_db_context
                    from ...core.tasks.presets import TaskTemplateStorage
                    
                    with get_db_context() as db:
                        storage = TaskTemplateStorage(db, self.user_id)
                        
                        # Extract task details from query if provided
                        priority = kwargs.get('priority', 'medium')
                        category = kwargs.get('category')
                        tags = kwargs.get('tags', [])
                        subtasks = kwargs.get('subtasks', [])
                        recurrence = kwargs.get('recurrence')
                        
                        # Fallback description
                        if not task_description or task_description.strip() == "":
                             task_description = query or "New Task Template"
                        
                        result = storage.create_template(
                            name=template_name,
                            description=template_name,  # Use name as description
                            task_description=task_description,
                            priority=priority,
                            category=category,
                            tags=tags if isinstance(tags, list) else [tags] if tags else [],
                            subtasks=subtasks if isinstance(subtasks, list) else [subtasks] if subtasks else [],
                            recurrence=recurrence
                        )
                        
                        return f"Created task preset '{template_name}' successfully."
                except Exception as e:
                    logger.error(f"Failed to create task preset: {e}", exc_info=True)
                    return f"[ERROR] Failed to create task preset: {str(e)}"
            
            elif action == "use_template":
                # Use an existing task preset to create a task
                template_name = kwargs.get('template_name') or kwargs.get('name')
                
                if not template_name:
                    return "[ERROR] Could not identify template name. Please specify which preset to use."
                
                try:
                    from ...database import get_db_context
                    from ...core.tasks.presets import TaskTemplateStorage
                    
                    with get_db_context() as db:
                        storage = TaskTemplateStorage(db, self.user_id)
                        
                        # Get template
                        template = storage.get_template(template_name)
                        if not template:
                            return f"[ERROR] Task preset '{template_name}' not found."
                        
                        # Extract variables from query if provided
                        variables = kwargs.get('variables', {})
                        
                        # Expand template with variables
                        expanded = storage.expand_template(template_name, variables)
                        
                        # Create task from expanded template
                        if not self.task_service:
                            return "[ERROR] Task service not available. Cannot create task from preset."
                        
                        # Extract due_date from kwargs
                        due_date = kwargs.get('due_date') or kwargs.get('due')
                        
                        result = self.task_service.create_task(
                            title=expanded.get('description', ''),
                            notes='',
                            due_date=due_date,
                            priority=expanded.get('priority', 'medium'),
                            category=expanded.get('category'),
                            tags=expanded.get('tags', []),
                            project=kwargs.get('project'),
                            reminder_days=kwargs.get('reminder_days'),
                            estimated_hours=kwargs.get('estimated_hours')
                        )
                        
                        task_title = result.get('title', expanded.get('description', ''))
                        return f"I've created a task from preset '{template_name}': {task_title}"
                except Exception as e:
                    logger.error(f"Failed to use task preset: {e}", exc_info=True)
                    return f"[ERROR] Failed to use task preset: {str(e)}"
            
            elif action == "list_templates":
                # List all task presets
                try:
                    from ...database import get_db_context
                    from ...core.tasks.presets import TaskTemplateStorage
                    
                    with get_db_context() as db:
                        storage = TaskTemplateStorage(db, self.user_id)
                        templates = storage.list_templates()
                        
                        if not templates:
                            return "You don't have any task presets yet."
                        
                        template_lines = []
                        for i, template in enumerate(templates, 1):
                            name = template.get('name', 'Unnamed')
                            description = template.get('task_description', '')[:50]
                            if len(description) > 50:
                                description += "..."
                            template_lines.append(f"{i}. {name}" + (f" - {description}" if description else ""))
                        
                        return f"Your task presets ({len(templates)} total):\n" + "\n".join(template_lines)
                except Exception as e:
                    logger.error(f"Failed to list task presets: {e}", exc_info=True)
                    return f"[ERROR] Failed to list task presets: {str(e)}"
            
            elif action == "delete_template":
                # Delete a task preset
                template_name = kwargs.get('template_name') or kwargs.get('name')
                
                if not template_name:
                    return "[ERROR] Could not identify template name."
                
                try:
                    from ...database import get_db_context
                    from ...core.tasks.presets import TaskTemplateStorage
                    
                    with get_db_context() as db:
                        storage = TaskTemplateStorage(db, self.user_id)
                        storage.delete_template(template_name)
                        return f"Deleted task preset '{template_name}' successfully."
                except Exception as e:
                    logger.error(f"Failed to delete task preset: {e}", exc_info=True)
                    return f"[ERROR] Failed to delete task preset: {str(e)}"
            
            elif action == "create":
                # Create a task
                if not self.task_service:
                    return "[ERROR] Google Tasks service not available."
                
                # Use provided parameters or extraction fallbacks
                title = kwargs.get('title') or kwargs.get('description') or kwargs.get('task_description')
                
                # If title is missing, try to use query
                if not title or title.strip() == "":
                    # Logic to strip common action words if relying on query
                    if query:
                         cleaned = query
                         for word in ["create", "add", "make", "new", "task", "please"]:
                             cleaned = cleaned.replace(word, "", 1) # simple removal
                         title = cleaned.strip() or "New Task"
                    else:
                         title = "New Task"

                # Extract other parameters 
                notes = kwargs.get('notes', '')
                due_date = kwargs.get('due_date') or kwargs.get('due')
                priority = kwargs.get('priority', 'medium')
                category = kwargs.get('category')
                tags = kwargs.get('tags')
                project = kwargs.get('project')
                reminder_days = kwargs.get('reminder_days')
                estimated_hours = kwargs.get('estimated_hours')
                
                logger.info(f"[TaskTool] Creating task: '{title}'")
                
                try:
                    result = self.task_service.create_task(
                        title=title,
                        notes=notes,
                        due_date=due_date,
                        priority=priority,
                        category=category,
                        tags=tags,
                        project=project,
                        reminder_days=reminder_days,
                        estimated_hours=estimated_hours
                    )
                    task_title = result.get('title', title)
                    task_due = result.get('due', due_date)
                    
                except Exception as e:
                    logger.error(f"Failed to create task: {e}", exc_info=True)
                    return f"[ERROR] Failed to create task: {str(e)}"

                # Cheerful confirmation
                due_msg = f" due {task_due}" if task_due else ""
                return f"You got it! I've added '{task_title}' to your list{due_msg}. Let's get things done!"
            
            return f"Error: Unknown action '{action}'"
            
        except Exception as e:
            logger.error(f"TaskTool error: {e}", exc_info=True)
            return f"Error: {str(e)}"
    
    async def _arun(self, action: str = "create", query: str = "", **kwargs) -> str:
        """Async execution - runs blocking _run in thread pool to avoid blocking event loop"""
        return await asyncio.to_thread(self._run, action=action, query=query, **kwargs)
