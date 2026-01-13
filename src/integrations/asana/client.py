"""
Asana API Client

Low-level wrapper for Asana Python SDK.
Handles authentication and API calls.
"""
import os
from typing import Optional, Dict, Any, List

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)

# Optional Asana SDK import
try:
    import asana
    from asana.rest import ApiException
    HAS_ASANA = True
except ImportError:
    HAS_ASANA = False
    asana = None
    ApiException = Exception


class AsanaClient:
    """
    Low-level Asana API client.
    
    Wraps the official Asana Python SDK for cleaner integration.
    """
    
    def __init__(
        self,
        access_token: Optional[str] = None,
        workspace_id: Optional[str] = None,
        config: Optional[Config] = None
    ):
        """
        Initialize Asana client.
        
        Args:
            access_token: Asana Personal Access Token or OAuth token
            workspace_id: Default workspace ID
            config: Application configuration
        """
        self.access_token = access_token or os.getenv("ASANA_ACCESS_TOKEN")
        self.workspace_id = workspace_id or os.getenv("ASANA_WORKSPACE_ID")
        self.config = config
        
        self._client = None
        self._tasks_api = None
        self._projects_api = None
        self._sections_api = None
        
        if not HAS_ASANA:
            logger.warning("Asana SDK not installed. Run: pip install asana")
    
    @property
    def is_available(self) -> bool:
        """Check if Asana client is available and configured."""
        return HAS_ASANA and bool(self.access_token)
    
    def _get_client(self):
        """Get or create Asana API client."""
        if not HAS_ASANA:
            raise ImportError("Asana SDK not installed. Run: pip install asana")
        
        if not self.access_token:
            from .exceptions import AsanaAuthenticationException
            raise AsanaAuthenticationException("No Asana access token configured")
        
        if self._client is None:
            configuration = asana.Configuration()
            configuration.access_token = self.access_token
            self._client = asana.ApiClient(configuration)
        
        return self._client
    
    @property
    def tasks_api(self):
        """Get Tasks API instance."""
        if self._tasks_api is None:
            self._tasks_api = asana.TasksApi(self._get_client())
        return self._tasks_api
    
    @property
    def projects_api(self):
        """Get Projects API instance."""
        if self._projects_api is None:
            self._projects_api = asana.ProjectsApi(self._get_client())
        return self._projects_api
    
    @property
    def sections_api(self):
        """Get Sections API instance."""
        if self._sections_api is None:
            self._sections_api = asana.SectionsApi(self._get_client())
        return self._sections_api
    
    # Task Operations
    
    def create_task(
        self,
        name: str,
        project_id: Optional[str] = None,
        assignee: Optional[str] = None,
        due_on: Optional[str] = None,
        notes: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a new task in Asana.
        
        Args:
            name: Task name/title
            project_id: Project to add task to
            assignee: Assignee GID or 'me'
            due_on: Due date (YYYY-MM-DD format)
            notes: Task description/notes
            **kwargs: Additional task properties
            
        Returns:
            Created task data
        """
        body = {"data": {"name": name}}
        
        if project_id:
            body["data"]["projects"] = [project_id]
        elif self.workspace_id:
            body["data"]["workspace"] = self.workspace_id
            
        if assignee:
            body["data"]["assignee"] = assignee
        if due_on:
            body["data"]["due_on"] = due_on
        if notes:
            body["data"]["notes"] = notes
            
        # Add any additional properties
        body["data"].update(kwargs)
        
        try:
            result = self.tasks_api.create_task(body, opt_fields=["gid", "name", "completed", "due_on", "notes"])
            return result.to_dict().get("data", {})
        except ApiException as e:
            logger.error(f"Failed to create Asana task: {e}")
            raise
    
    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get a task by ID."""
        try:
            result = self.tasks_api.get_task(
                task_id,
                opt_fields=["gid", "name", "completed", "due_on", "notes", "assignee", "projects"]
            )
            return result.to_dict().get("data", {})
        except ApiException as e:
            if e.status == 404:
                from .exceptions import AsanaTaskNotFoundException
                raise AsanaTaskNotFoundException(task_id)
            raise
    
    def update_task(self, task_id: str, **updates) -> Dict[str, Any]:
        """Update a task."""
        body = {"data": updates}
        try:
            result = self.tasks_api.update_task(body, task_id)
            return result.to_dict().get("data", {})
        except ApiException as e:
            logger.error(f"Failed to update Asana task: {e}")
            raise
    
    def complete_task(self, task_id: str) -> Dict[str, Any]:
        """Mark a task as completed."""
        return self.update_task(task_id, completed=True)
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        try:
            self.tasks_api.delete_task(task_id)
            return True
        except ApiException as e:
            logger.error(f"Failed to delete Asana task: {e}")
            raise
    
    def list_tasks(
        self,
        project_id: Optional[str] = None,
        assignee: Optional[str] = None,
        completed: Optional[bool] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List tasks with filters.
        
        Args:
            project_id: Filter by project
            assignee: Filter by assignee
            completed: Filter by completion status
            limit: Maximum tasks to return
            
        Returns:
            List of tasks
        """
        opts = {
            "limit": min(limit, 100),
            "opt_fields": ["gid", "name", "completed", "due_on", "notes", "assignee"]
        }
        
        if completed is not None:
            opts["completed_since"] = "now" if not completed else None
        
        try:
            if project_id:
                result = self.tasks_api.get_tasks_for_project(project_id, opts)
            elif assignee and self.workspace_id:
                result = self.tasks_api.get_tasks(
                    assignee=assignee,
                    workspace=self.workspace_id,
                    **opts
                )
            elif self.workspace_id:
                # Get all tasks for workspace requires a project or assignee
                result = self.tasks_api.get_tasks(
                    assignee="me",
                    workspace=self.workspace_id,
                    **opts
                )
            else:
                return []
            
            return [item.to_dict() for item in result]
        except ApiException as e:
            logger.error(f"Failed to list Asana tasks: {e}")
            raise
    
    def search_tasks(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search tasks by text query."""
        if not self.workspace_id:
            logger.warning("Workspace ID required for search")
            return []
        
        try:
            # Use typeahead search for text matching
            result = self.tasks_api.search_tasks_for_workspace(
                self.workspace_id,
                text=query,
                opt_fields=["gid", "name", "completed", "due_on"],
                limit=limit
            )
            return [item.to_dict() for item in result]
        except ApiException as e:
            logger.error(f"Failed to search Asana tasks: {e}")
            return []
    
    # Project Operations
    
    def list_projects(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all projects in workspace."""
        if not self.workspace_id:
            return []
        
        try:
            result = self.projects_api.get_projects(
                workspace=self.workspace_id,
                limit=limit,
                opt_fields=["gid", "name", "archived"]
            )
            return [item.to_dict() for item in result]
        except ApiException as e:
            logger.error(f"Failed to list Asana projects: {e}")
            raise
