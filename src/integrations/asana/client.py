"""
Asana API Client

Low-level wrapper for Asana Python SDK.
Handles authentication and API calls.
"""
import os
from typing import Optional, Dict, Any, List
import requests

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

    @property
    def unavailable_reason(self) -> Optional[str]:
        """Return reason code when client is unavailable."""
        if not HAS_ASANA:
            return "sdk_missing"
        if not self.access_token:
            return "token_missing"
        return None
    
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

    def _list_workspace_ids(self) -> List[str]:
        """Fetch workspace IDs available to the current token."""
        if not self.access_token:
            return []

        try:
            resp = requests.get(
                "https://app.asana.com/api/1.0/workspaces",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=10,
            )
            if resp.status_code >= 400:
                logger.warning(f"Failed to list Asana workspaces (status={resp.status_code})")
                return []
            items = resp.json().get("data", [])
            return [w.get("gid") for w in items if w.get("gid")]
        except Exception as e:
            logger.warning(f"Failed to list Asana workspaces: {e}")
            return []

    def _resolve_workspace_id(self) -> Optional[str]:
        """Resolve and cache workspace id for OAuth users when not explicitly configured."""
        if self.workspace_id:
            return self.workspace_id

        workspace_ids = self._list_workspace_ids()
        if workspace_ids:
            self.workspace_id = workspace_ids[0]
            logger.info(f"[AsanaClient] Resolved workspace id for OAuth user: {self.workspace_id}")

        return self.workspace_id
    
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

    @staticmethod
    def _coerce_item_dict(value: Any) -> Dict[str, Any]:
        """Normalize SDK item responses across Asana client versions."""
        if value is None:
            return {}

        if isinstance(value, dict):
            nested = value.get("data")
            return nested if isinstance(nested, dict) else value

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            payload = to_dict()
            if isinstance(payload, dict):
                nested = payload.get("data")
                return nested if isinstance(nested, dict) else payload

        logger.debug(f"Unexpected Asana SDK item type: {type(value)}")
        return {}

    @classmethod
    def _coerce_collection(cls, value: Any) -> List[Dict[str, Any]]:
        """Normalize SDK collection responses across Asana client versions."""
        if value is None:
            return []

        if isinstance(value, dict):
            nested = value.get("data")
            if isinstance(nested, list):
                return [item for item in (cls._coerce_item_dict(raw) for raw in nested) if item]
            item = cls._coerce_item_dict(value)
            return [item] if item else []

        try:
            iterator = iter(value)
        except TypeError:
            item = cls._coerce_item_dict(value)
            return [item] if item else []

        items: List[Dict[str, Any]] = []
        for raw in iterator:
            item = cls._coerce_item_dict(raw)
            if item:
                items.append(item)
        return items
    
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
        workspace_id = self._resolve_workspace_id()
        body = {"data": {"name": name}}
        
        if project_id:
            body["data"]["projects"] = [project_id]
        elif workspace_id:
            body["data"]["workspace"] = workspace_id
        else:
            raise ValueError("No Asana workspace available for task creation")
            
        if assignee:
            body["data"]["assignee"] = assignee
        if due_on:
            body["data"]["due_on"] = due_on
        if notes:
            body["data"]["notes"] = notes
            
        # Add any additional properties
        body["data"].update(kwargs)
        
        try:
            opts = {"opt_fields": "gid,name,completed,due_on,notes"}
            result = self.tasks_api.create_task(body, opts)
            return self._coerce_item_dict(result)
        except ApiException as e:
            logger.error(f"Failed to create Asana task: {e}")
            raise
    
    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get a task by ID."""
        try:
            opts = {"opt_fields": "gid,name,completed,due_on,notes,assignee,projects"}
            result = self.tasks_api.get_task(task_id, opts)
            return self._coerce_item_dict(result)
        except ApiException as e:
            if e.status == 404:
                from .exceptions import AsanaTaskNotFoundException
                raise AsanaTaskNotFoundException(task_id)
            raise
    
    def update_task(self, task_id: str, **updates) -> Dict[str, Any]:
        """Update a task."""
        body = {"data": updates}
        try:
            result = self.tasks_api.update_task(body, task_id, {})
            return self._coerce_item_dict(result)
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
            "opt_fields": "gid,name,completed,due_on,notes,assignee"
        }
        workspace_id = self._resolve_workspace_id()
        
        if completed is False:
            opts["completed_since"] = "now"
        
        try:
            if project_id:
                result = self.tasks_api.get_tasks_for_project(project_id, opts)
            elif assignee and workspace_id:
                scoped_opts = {**opts, "assignee": assignee, "workspace": workspace_id}
                result = self.tasks_api.get_tasks(scoped_opts)
            elif workspace_id:
                # Get all tasks for workspace requires a project or assignee
                scoped_opts = {**opts, "assignee": "me", "workspace": workspace_id}
                result = self.tasks_api.get_tasks(scoped_opts)
            else:
                raise ValueError("No Asana workspace available for listing tasks")

            return self._coerce_collection(result)
        except ApiException as e:
            logger.error(f"Failed to list Asana tasks: {e}")
            raise
    
    def search_tasks(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search tasks by text query."""
        workspace_id = self._resolve_workspace_id()
        if not workspace_id:
            logger.warning("Workspace ID required for search")
            return []
        
        try:
            # Use typeahead search for text matching
            opts = {
                "text": query,
                "opt_fields": "gid,name,completed,due_on",
                "limit": limit,
            }
            result = self.tasks_api.search_tasks_for_workspace(workspace_id, opts)
            return self._coerce_collection(result)
        except ApiException as e:
            logger.error(f"Failed to search Asana tasks: {e}")
            return []
    
    # Project Operations

    def create_project(self, name: str, notes: Optional[str] = None) -> Dict[str, Any]:
        """Create an Asana project in the resolved workspace."""
        workspace_id = self._resolve_workspace_id()
        if not workspace_id:
            raise ValueError("No Asana workspace available for project creation")

        payload = {
            "data": {
                "name": name,
                "workspace": workspace_id,
            }
        }
        if notes:
            payload["data"]["notes"] = notes

        resp = requests.post(
            "https://app.asana.com/api/1.0/projects",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json=payload,
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.error(f"Failed to create Asana project (status={resp.status_code}): {resp.text[:200]}")
            raise ValueError(f"Asana API error ({resp.status_code}) creating project")

        return resp.json().get("data", {})
    
    def list_projects(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all projects in workspace."""
        workspace_id = self._resolve_workspace_id()
        
        safe_limit = max(1, min(int(limit or 100), 100))
        workspace_candidates: List[Optional[str]] = []
        if workspace_id:
            workspace_candidates.append(workspace_id)
        for wid in self._list_workspace_ids():
            if wid not in workspace_candidates:
                workspace_candidates.append(wid)
        if not workspace_candidates:
            workspace_candidates.append(None)

        had_success = False
        last_status: Optional[int] = None
        last_error: Optional[str] = None

        for wid in workspace_candidates:
            params = {
                "limit": safe_limit,
                "opt_fields": "gid,name,archived,workspace",
            }
            if wid:
                params["workspace"] = wid

            resp = requests.get(
                "https://app.asana.com/api/1.0/projects",
                headers={"Authorization": f"Bearer {self.access_token}"},
                params=params,
                timeout=15,
            )
            if resp.status_code >= 400:
                last_status = resp.status_code
                last_error = resp.text[:200]
                logger.warning(
                    f"Failed to list Asana projects for workspace {wid or 'unscoped'} "
                    f"(status={resp.status_code}): {resp.text[:120]}"
                )
                continue

            had_success = True
            data = resp.json().get("data", [])
            if data:
                if wid:
                    self.workspace_id = wid
                else:
                    resolved = data[0].get("workspace", {}).get("gid") if isinstance(data[0], dict) else None
                    if resolved:
                        self.workspace_id = resolved
                return data

        if had_success:
            return []

        logger.error(
            f"Failed to list Asana projects across workspaces "
            f"(last_status={last_status}, last_error={last_error})"
        )
        raise ValueError(f"Asana API error ({last_status}) listing projects")
