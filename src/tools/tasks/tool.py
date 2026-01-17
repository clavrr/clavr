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
    user_id: int = Field(description="User ID - required for multi-tenancy")
    credentials: Optional[Any] = Field(default=None)
    user_first_name: Optional[str] = Field(default=None)
    _task_service: Optional[Any] = None
    
    def __init__(self, storage_path: str = "./data/tasks.json", config: Optional[Config] = None,
                 user_id: int = None, credentials: Optional[Any] = None, user_first_name: Optional[str] = None, **kwargs):
        if user_id is None:
            raise ValueError("user_id is required for TaskTool - cannot default to 1 for multi-tenancy")
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
        """Execute task tool action dispatcher"""
        logger.info(f"[TaskTool] Executing {action} with query='{query}' and kwargs={kwargs}")
        
        # Ensure service is initialized for Google Tasks actions
        if not self.task_service:
            if action not in ["create_template", "list_templates", "delete_template"]:
                logger.warning(f"[TaskTool] TaskService not available for action {action}")
                return "[INTEGRATION_REQUIRED] Tasks permission not granted. Please enable Google integration in Settings."

        try:
            if action in ["list", "check"]:
                return self._handle_list_tasks(**kwargs)
            elif action == "search":
                return self._handle_search_tasks(query, **kwargs)
            elif action == "get_overdue":
                return self._handle_get_overdue()
            elif action == "complete":
                return self._handle_complete_task(query, **kwargs)
            elif action in ["create_template", "use_template", "list_templates", "delete_template"]:
                return self._handle_template_actions(action, query, **kwargs)
            elif action == "create":
                return self._handle_create_task(query, **kwargs)
            
            return f"Error: Unknown action '{action}'"
            
        except Exception as e:
            logger.error(f"TaskTool error: {e}", exc_info=True)
            return f"Error: {str(e)}"

    def _handle_list_tasks(self, **kwargs) -> str:
        """Fetch and format tasks list"""
        status = kwargs.get('status', 'pending')
        limit = kwargs.get('limit', 5)
        fast_mode = limit <= 5
        
        tasks = self.task_service.list_tasks(status=status, limit=limit, fast_mode=fast_mode)
        if not tasks:
            return "You don't have any pending tasks right now." if status == 'pending' else "No tasks found."
        
        task_lines = []
        for i, task in enumerate(tasks[:5], 1):
            title = task.get('title', 'Untitled')
            due = task.get('due')
            line = f"{i}. {title}" + (f" (due: {due})" if due else "")
            if task.get('status') == 'completed': line += " [DONE]"
            task_lines.append(line)
        
        result = f"Your tasks ({len(tasks)} total):\n" + "\n".join(task_lines)
        if len(tasks) > 5: result += f"\n... and {len(tasks) - 5} more."
        return result

    def _handle_search_tasks(self, query: str, **kwargs) -> str:
        """Search tasks by keywords"""
        search_terms = kwargs.get('search_terms', query)
        tasks = self.task_service.list_tasks(status='all', limit=20, fast_mode=True)
        
        search_lower = search_terms.lower()
        matching = [t for t in tasks if search_lower in t.get('title', '').lower() 
                   or search_lower in t.get('notes', '').lower()]
        
        if not matching:
            return f"I couldn't find any tasks matching '{search_terms}'."
        
        task_lines = [f"{i}. {t.get('title', 'Untitled')}" for i, t in enumerate(matching[:10], 1)]
        return f"Found {len(matching)} tasks matching '{search_terms}':\n" + "\n".join(task_lines)

    def _handle_get_overdue(self) -> str:
        """Get list of past due tasks"""
        overdue = self.task_service.get_overdue_tasks(limit=50)
        if not overdue:
            return "Good news! You don't have any past due tasks."
        
        from datetime import datetime
        now = datetime.now()
        task_lines = []
        for i, task in enumerate(overdue[:10], 1):
            due = task.get('due', '')
            days_msg = ""
            if due:
                try:
                    due_dt = datetime.fromisoformat(due.replace('Z', '+00:00')).replace(tzinfo=None)
                    delta = (now - due_dt).days
                    days_msg = f" ({delta} days overdue)" if delta > 0 else " (due today)"
                except Exception as e:
                    logger.debug(f"[TaskTool] Date parsing failed: {e}")
            task_lines.append(f"{i}. {task.get('title', 'Untitled')}{days_msg}")
            
        return f"You have {len(overdue)} past due tasks:\n" + "\n".join(task_lines)

    def _handle_complete_task(self, query: str, **kwargs) -> str:
        """Find and mark a task as complete with ambiguity handling"""
        task_desc = kwargs.get('task_description', query)
        tasks = self.task_service.list_tasks(status='pending', limit=100)
        task_lower = task_desc.lower()
        
        matches = []
        for t in tasks:
            title = t.get('title', '').lower()
            if task_lower == title: # Exact match prioritization
                matches = [t]
                break
            if task_lower in title or title in task_lower:
                matches.append(t)
        
        if not matches:
            return f"I couldn't find a task matching '{task_desc}' to complete."
        if len(matches) > 1:
            match_list = "\n".join([f"- {m.get('title')}" for m in matches[:3]])
            return f"Found multiple matches for '{task_desc}'. Which one did you mean?\n{match_list}"
            
        task = matches[0]
        self.task_service.complete_task(task.get('id'))
        return f"Done! I've marked '{task.get('title')}' as complete. Great job!"

    def _handle_template_actions(self, action: str, query: str, **kwargs) -> str:
        """Handle task template related operations"""
        from ...database import get_db_context
        from ...core.tasks.presets import TaskTemplateStorage
        
        with get_db_context() as db:
            storage = TaskTemplateStorage(db, self.user_id)
            name = kwargs.get('template_name') or kwargs.get('name')
            
            if action == "create_template":
                desc = kwargs.get('task_description') or kwargs.get('description') or query
                if not name: return "[ERROR] Template name required."
                storage.create_template(name=name, description=name, task_description=desc or "New Template",
                                     priority=kwargs.get('priority', 'medium'), category=kwargs.get('category'))
                return f"Created task preset '{name}' successfully."
                
            elif action == "use_template":
                if not name: return "[ERROR] Template name required."
                expanded = storage.expand_template(name, kwargs.get('variables', {}))
                result = self.task_service.create_task(title=expanded.get('description', ''),
                                                    due_date=kwargs.get('due_date') or kwargs.get('due'))
                return f"Created task from preset '{name}': {result.get('title')}"
                
            elif action == "list_templates":
                templates = storage.list_templates()
                if not templates: return "No task presets found."
                lines = [f"{i}. {t.get('name')}" for i, t in enumerate(templates, 1)]
                return "Your task presets:\n" + "\n".join(lines)
                
            elif action == "delete_template":
                if not name: return "[ERROR] Template name required."
                storage.delete_template(name)
                return f"Deleted task preset '{name}'."
        return "Unknown template action"

    def _handle_create_task(self, query: str, **kwargs) -> str:
        """Create a new task"""
        title = kwargs.get('title') or kwargs.get('description') or kwargs.get('task_description')
        if not title:
            cleaned = query
            for word in ["create", "add", "make", "new", "task", "please"]:
                cleaned = cleaned.replace(word, "", 1)
            title = cleaned.strip() or "New Task"
            
        result = self.task_service.create_task(
            title=title, notes=kwargs.get('notes', ''),
            due_date=kwargs.get('due_date') or kwargs.get('due'),
            priority=kwargs.get('priority', 'medium'),
            category=kwargs.get('category')
        )
        due_msg = f" due {result.get('due')}" if result.get('due') else ""
        return f"You got it! I've added '{result.get('title')}' to your list{due_msg}."

    
    async def _arun(self, action: str = "create", query: str = "", **kwargs) -> str:
        """Async execution - runs blocking _run in thread pool to avoid blocking event loop"""
        return await asyncio.to_thread(self._run, action=action, query=query, **kwargs)
