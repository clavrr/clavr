"""
Asana Tool - LangChain tool for Asana task management

Provides task management capabilities through the AsanaService.
"""
import asyncio
from langchain.tools import BaseTool
from pydantic import Field, BaseModel
from typing import Optional, Any, Type

from src.utils.logger import setup_logger
from src.utils.config import Config, load_config

logger = setup_logger(__name__)


class AsanaInput(BaseModel):
    """Input for AsanaTool."""
    action: str = Field(description="Action to perform (create, list, complete, search, delete, overdue, projects)")
    query: Optional[str] = Field(default="", description="Query or details for the action.")
    title: Optional[str] = Field(default=None, description="Task title")
    due_date: Optional[str] = Field(default=None, description="Due date (YYYY-MM-DD)")
    notes: Optional[str] = Field(default=None, description="Task notes")
    project_id: Optional[str] = Field(default=None, description="Asana project ID")
    assignee: Optional[str] = Field(default=None, description="Task assignee")
    status: Optional[str] = Field(default="pending", description="Task status filter")
    limit: Optional[int] = Field(default=10, description="Result limit")
    task_id: Optional[str] = Field(default=None, description="Asana task ID")


class AsanaTool(BaseTool):
    """
    Asana task management tool wrapping AsanaService.
    
    Actions:
    - create: Create a new task
    - list: List tasks
    - complete: Mark task as completed
    - search: Search tasks
    - delete: Delete a task
    """
    
    name: str = "asana"
    description: str = (
        "Asana task management (create, list, complete, search). "
        "Use this for Asana-specific task queries."
    )
    args_schema: Type[BaseModel] = AsanaInput
    
    config: Optional[Config] = Field(default=None, exclude=True)
    user_id: int = Field(default=1, exclude=True)
    _service: Any = None
    
    def __init__(
        self,
        config: Optional[Config] = None,
        user_id: int = 1,
        access_token: Optional[str] = None,
        workspace_id: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize Asana tool.
        
        Args:
            config: Application configuration
            user_id: User ID for the request
            access_token: Asana access token
            workspace_id: Asana workspace ID
        """
        super().__init__(**kwargs)
        self.config = config or load_config()
        self.user_id = user_id
        self._access_token = access_token
        self._workspace_id = workspace_id
    
    @property
    def asana_service(self):
        """Lazy initialization of Asana service."""
        if self._service is None:
            try:
                from src.integrations.asana import AsanaService
                self._service = AsanaService(
                    config=self.config,
                    access_token=self._access_token,
                    workspace_id=self._workspace_id
                )
            except Exception as e:
                logger.error(f"Failed to initialize AsanaService: {e}")
                self._service = None
        return self._service
    
    def _run(
        self,
        action: str = "list",
        query: str = "",
        **kwargs
    ) -> str:
        """
        Execute Asana tool action.
        
        Args:
            action: Action to perform (create, list, complete, search, delete)
            query: Query string or task title
            **kwargs: Additional parameters (title, due_date, task_id, etc.)
        """
        if not self.asana_service:
            return "[INTEGRATION_REQUIRED] Asana permission not granted. Please enable Asana integration in Settings."
        
        if not self.asana_service.is_available:
            return "[INTEGRATION_REQUIRED] Asana permission not granted. Please enable Asana integration in Settings."
        
        try:
            if action == "create":
                return self._handle_create(query, **kwargs)
            elif action == "list":
                return self._handle_list(query, **kwargs)
            elif action == "complete":
                return self._handle_complete(query, **kwargs)
            elif action == "search":
                return self._handle_search(query, **kwargs)
            elif action == "delete":
                return self._handle_delete(query, **kwargs)
            elif action == "overdue":
                return self._handle_overdue(**kwargs)
            elif action == "projects":
                return self._handle_projects(**kwargs)
            else:
                return f"Unknown action: {action}. Supported: create, list, complete, search, delete"
                
        except Exception as e:
            logger.error(f"Asana tool error: {e}", exc_info=True)
            return f"Error executing Asana action: {str(e)}"
    
    def _handle_create(self, query: str, **kwargs) -> str:
        """Handle task creation."""
        title = kwargs.get("title") or query
        if not title:
            return "Please provide a task title."
        
        task = self.asana_service.create_task(
            title=title,
            due_date=kwargs.get("due_date"),
            notes=kwargs.get("notes"),
            project_id=kwargs.get("project_id"),
            assignee=kwargs.get("assignee")
        )
        
        due_str = f" (due: {task['due_date']})" if task.get("due_date") else ""
        return f"✅ Created Asana task: **{task['title']}**{due_str}"
    
    def _handle_list(self, query: str, **kwargs) -> str:
        """Handle task listing."""
        status = kwargs.get("status", "pending")
        limit = kwargs.get("limit", 10)
        project_id = kwargs.get("project_id")
        
        tasks = self.asana_service.list_tasks(
            status=status,
            project_id=project_id,
            limit=limit
        )
        
        if not tasks:
            return "No tasks found."
        
        lines = [f"📋 **Asana Tasks** ({len(tasks)} {status}):"]
        for i, task in enumerate(tasks[:10], 1):
            status_icon = "✅" if task["status"] == "completed" else "⬜"
            due_str = f" (due: {task['due_date']})" if task.get("due_date") else ""
            lines.append(f"{i}. {status_icon} {task['title']}{due_str}")
        
        if len(tasks) > 10:
            lines.append(f"... and {len(tasks) - 10} more")
        
        return "\n".join(lines)
    
    def _handle_complete(self, query: str, **kwargs) -> str:
        """Handle task completion."""
        task_id = kwargs.get("task_id")
        
        if not task_id and query:
            # Search for task by name
            tasks = self.asana_service.search_tasks(query, limit=5)
            if not tasks:
                return f"No task found matching: {query}"
            if len(tasks) == 1:
                task_id = tasks[0]["id"]
            else:
                lines = ["Multiple tasks found. Please be more specific:"]
                for t in tasks[:5]:
                    lines.append(f"- {t['title']} (ID: {t['id']})")
                return "\n".join(lines)
        
        if not task_id:
            return "Please specify a task to complete."
        
        task = self.asana_service.complete_task(task_id)
        return f"✅ Completed: **{task['title']}**"
    
    def _handle_search(self, query: str, **kwargs) -> str:
        """Handle task search."""
        if not query:
            return "Please provide a search query."
        
        limit = kwargs.get("limit", 10)
        tasks = self.asana_service.search_tasks(query, limit=limit)
        
        if not tasks:
            return f"No tasks found matching: {query}"
        
        lines = [f"🔍 **Search results for '{query}'** ({len(tasks)} found):"]
        for i, task in enumerate(tasks[:10], 1):
            status_icon = "✅" if task["status"] == "completed" else "⬜"
            lines.append(f"{i}. {status_icon} {task['title']}")
        
        return "\n".join(lines)
    
    def _handle_delete(self, query: str, **kwargs) -> str:
        """Handle task deletion."""
        task_id = kwargs.get("task_id")
        
        if not task_id:
            return "Please provide a task ID to delete."
        
        result = self.asana_service.delete_task(task_id)
        return f"🗑️ Task deleted successfully."
    
    def _handle_overdue(self, **kwargs) -> str:
        """Handle overdue tasks listing."""
        limit = kwargs.get("limit", 10)
        tasks = self.asana_service.get_overdue_tasks(limit=limit)
        
        if not tasks:
            return "🎉 No overdue tasks!"
        
        lines = [f"⚠️ **Overdue Tasks** ({len(tasks)}):"]
        for i, task in enumerate(tasks[:10], 1):
            lines.append(f"{i}. ⬜ {task['title']} (was due: {task['due_date']})")
        
        return "\n".join(lines)
    
    def _handle_projects(self, **kwargs) -> str:
        """Handle project listing."""
        projects = self.asana_service.list_projects()
        
        if not projects:
            return "No projects found."
        
        lines = [f"📁 **Asana Projects** ({len(projects)}):"]
        for p in projects[:20]:
            archived = " (archived)" if p.get("archived") else ""
            lines.append(f"- {p['name']}{archived}")
        
        return "\n".join(lines)
    
    async def _arun(
        self,
        action: str = "list",
        query: str = "",
        **kwargs
    ) -> str:
        """Async execution - runs blocking _run in thread pool."""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._run(action=action, query=query, **kwargs)
        )
