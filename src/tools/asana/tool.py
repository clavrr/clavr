"""
Asana Tool - LangChain tool for Asana task management

Provides task management capabilities through the AsanaService.
"""
import asyncio
import os
from langchain.tools import BaseTool
from pydantic import Field, BaseModel
from typing import Optional, Any, Type

from src.utils.logger import setup_logger
from src.utils.config import Config, load_config

logger = setup_logger(__name__)


class AsanaInput(BaseModel):
    """Input for AsanaTool."""
    action: str = Field(description="Action to perform (create, list, complete, search, delete, overdue, projects, create_project)")
    query: Optional[str] = Field(default="", description="Query or details for the action.")
    title: Optional[str] = Field(default=None, description="Task title")
    due_date: Optional[str] = Field(default=None, description="Due date (YYYY-MM-DD)")
    notes: Optional[str] = Field(default=None, description="Task notes")
    project_id: Optional[str] = Field(default=None, description="Asana project ID")
    project_name: Optional[str] = Field(default=None, description="Asana project name")
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
        if config:
            kwargs['config'] = config
        kwargs['user_id'] = user_id
        super().__init__(**kwargs)
        self.config = config or load_config()
        self.user_id = user_id
        self._access_token = access_token
        self._workspace_id = workspace_id
    
    @property
    def asana_service(self):
        """Lazy initialization of Asana service with user-specific OAuth token."""
        if self._service is None:
            try:
                from src.integrations.asana import AsanaService
                from src.core.integration_tokens import get_integration_token
                
                # Get user-specific token from UserIntegration
                access_token = self._access_token or get_integration_token(self.user_id, 'asana')
                if not access_token:
                    logger.debug(f"[AsanaTool] No Asana token for user {self.user_id}")
                    return None
                
                self._service = AsanaService(
                    config=self.config,
                    access_token=access_token,
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
        service = self.asana_service

        if not service:
            return "[INTEGRATION_REQUIRED] Asana permission not granted. Please enable Asana integration in Settings."

        if not service.is_available:
            unavailable_reason = getattr(service, "unavailable_reason", None)
            if unavailable_reason == "sdk_missing":
                return (
                    "[SYSTEM_CONFIG_REQUIRED] Asana isn't available on this backend yet. "
                    "Install backend dependency: pip install asana"
                )
            return "[INTEGRATION_REQUIRED] Asana permission not granted. Please enable Asana integration in Settings."
        
        try:
            if action == "list" and "project" in (query or "").lower() and "task" not in (query or "").lower():
                action = "projects"

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
            elif action == "create_project":
                return self._handle_create_project(query, **kwargs)
            else:
                return f"Unknown action: {action}. Supported: create, list, complete, search, delete, projects, create_project"
                
        except Exception as e:
            err_str = str(e)
            if "401" in err_str or "403" in err_str or "unauthorized" in err_str.lower():
                logger.warning(f"[AsanaTool] Auth error for user {self.user_id}, attempting token refresh: {e}")
                refreshed = self._refresh_asana_token()
                if refreshed:
                    self._service = None
                    return "[RETRY] Asana token refreshed. Please resend your message."
                else:
                    self._mark_asana_inactive()
                    return "[INTEGRATION_REQUIRED] Asana access expired. Please reconnect Asana in Settings."
            logger.error(f"Asana tool error: {e}", exc_info=True)
            return f"Error executing Asana action: {str(e)}"
    
    def _refresh_asana_token(self) -> bool:
        """Attempt to refresh the Asana access token using stored refresh_token."""
        try:
            from src.database import get_db_context
            from src.database.models import UserIntegration
            import requests as req_lib
            from datetime import datetime, timedelta

            with get_db_context() as db:
                row = db.query(UserIntegration).filter(
                    UserIntegration.user_id == self.user_id,
                    UserIntegration.provider == "asana"
                ).first()
                if not row or not row.refresh_token:
                    logger.warning("[AsanaTool] No refresh_token stored for Asana")
                    return False

                client_id = None
                client_secret = None
                try:
                    client_id = self.config.oauth.providers["asana"].client_id
                    client_secret = self.config.oauth.providers["asana"].client_secret
                except Exception:
                    pass
                client_id = client_id or os.getenv("ASANA_CLIENT_ID")
                client_secret = client_secret or os.getenv("ASANA_CLIENT_SECRET")

                if not client_id or not client_secret:
                    logger.warning("[AsanaTool] Asana client_id/secret not configured, cannot refresh")
                    return False

                resp = req_lib.post(
                    "https://app.asana.com/-/oauth_token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": row.refresh_token,
                    },
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.error(f"[AsanaTool] Refresh failed: {resp.status_code} {resp.text[:200]}")
                    return False

                data = resp.json()
                row.access_token = data["access_token"]
                if data.get("refresh_token"):
                    row.refresh_token = data["refresh_token"]
                if data.get("expires_in"):
                    row.expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])
                row.is_active = True
                logger.info(f"[AsanaTool] Refreshed Asana token for user {self.user_id}")
                return True
        except Exception as ex:
            logger.error(f"[AsanaTool] Exception during token refresh: {ex}")
            return False

    def _mark_asana_inactive(self) -> None:
        """Mark Asana integration inactive after unrecoverable auth failure."""
        try:
            from src.database import get_db_context
            from src.database.models import UserIntegration
            with get_db_context() as db:
                row = db.query(UserIntegration).filter(
                    UserIntegration.user_id == self.user_id,
                    UserIntegration.provider == "asana"
                ).first()
                if row:
                    row.is_active = False
                    logger.info(f"[AsanaTool] Marked asana inactive for user {self.user_id}")
        except Exception as ex:
            logger.warning(f"[AsanaTool] Could not mark asana inactive: {ex}")

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
            project_name=kwargs.get("project_name"),
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

    def _handle_create_project(self, query: str, **kwargs) -> str:
        """Handle Asana project creation."""
        project_name = kwargs.get("project_name") or query
        if not project_name:
            return "Please provide a project name."

        project = self.asana_service.create_project(
            name=project_name,
            notes=kwargs.get("notes")
        )
        return f"✅ Created Asana project: **{project['name']}**"
    
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
