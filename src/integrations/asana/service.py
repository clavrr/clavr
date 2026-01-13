"""
Asana Service - Business logic layer for Asana task operations

Provides a clean interface for Asana operations, following the pattern
established by TaskService for Google Tasks.

Features:
- Task CRUD operations
- Project listing
- Search capabilities
- Compatible interface with TaskService for easy switching
"""
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, date

from src.utils.logger import setup_logger
from src.utils.config import Config, load_config

from .client import AsanaClient
from .exceptions import (
    AsanaServiceException,
    AsanaTaskNotFoundException,
    AsanaAuthenticationException,
    AsanaValidationException,
)

logger = setup_logger(__name__)


class AsanaService:
    """
    Asana service providing business logic for task operations.
    
    Features:
    - Create, read, update, delete tasks
    - List and search tasks
    - Project management
    - Compatible API with TaskService for backend switching
    
    Usage:
        from src.integrations.asana import AsanaService
        
        service = AsanaService(config)
        task = service.create_task(title="My task", due_date="2024-12-15")
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        access_token: Optional[str] = None,
        workspace_id: Optional[str] = None
    ):
        """
        Initialize Asana service.
        
        Args:
            config: Application configuration
            access_token: Asana access token (defaults to ASANA_ACCESS_TOKEN env)
            workspace_id: Default workspace ID (defaults to ASANA_WORKSPACE_ID env)
        """
        self.config = config or load_config()
        self._client = AsanaClient(
            access_token=access_token,
            workspace_id=workspace_id,
            config=self.config
        )
        
        logger.info("AsanaService initialized")
    
    @property
    def is_available(self) -> bool:
        """Check if Asana service is available."""
        return self._client.is_available
    
    def _ensure_available(self):
        """Ensure service is available."""
        if not self.is_available:
            raise AsanaServiceException(
                "Asana is not available. Check ASANA_ACCESS_TOKEN environment variable."
            )
    
    def _normalize_due_date(self, due_date: Optional[str]) -> Optional[str]:
        """Convert due date to YYYY-MM-DD format."""
        if not due_date:
            return None
        
        # Handle relative dates
        due_lower = due_date.lower()
        today = date.today()
        
        if due_lower == "today":
            return today.isoformat()
        elif due_lower == "tomorrow":
            from datetime import timedelta
            return (today + timedelta(days=1)).isoformat()
        elif due_lower == "next week":
            from datetime import timedelta
            return (today + timedelta(days=7)).isoformat()
        
        # Try to parse ISO format
        try:
            # Handle ISO datetime
            if "T" in due_date:
                dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                return dt.date().isoformat()
            # Already in date format
            return due_date[:10]  # Take YYYY-MM-DD portion
        except (ValueError, AttributeError):
            logger.warning(f"Could not parse due date: {due_date}")
            return None
    
    # ========================================================================
    # Task Operations (Compatible with TaskService API)
    # ========================================================================
    
    def create_task(
        self,
        title: str,
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        priority: Optional[str] = None,
        project_id: Optional[str] = None,
        assignee: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a new task.
        
        Args:
            title: Task title/description
            due_date: Due date (ISO format or relative like 'tomorrow')
            notes: Task notes/description
            priority: Priority level (mapped to custom field if available)
            project_id: Project to add task to
            assignee: Assignee (use 'me' for current user)
            
        Returns:
            Created task with id, title, status, etc.
        """
        self._ensure_available()
        
        if not title:
            raise AsanaValidationException("title", "Task title is required")
        
        # Normalize due date
        due_on = self._normalize_due_date(due_date)
        
        try:
            result = self._client.create_task(
                name=title,
                due_on=due_on,
                notes=notes,
                project_id=project_id,
                assignee=assignee
            )
            
            # Normalize response to match TaskService format
            return self._normalize_task(result)
            
        except Exception as e:
            logger.error(f"Failed to create Asana task: {e}")
            raise AsanaServiceException(f"Failed to create task: {e}")
    
    def get_task(self, task_id: str) -> Dict[str, Any]:
        """
        Get a single task by ID.
        
        Args:
            task_id: Asana task GID
            
        Returns:
            Task details
        """
        self._ensure_available()
        
        try:
            result = self._client.get_task(task_id)
            return self._normalize_task(result)
        except AsanaTaskNotFoundException:
            raise
        except Exception as e:
            logger.error(f"Failed to get Asana task: {e}")
            raise AsanaServiceException(f"Failed to get task: {e}")
    
    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Update an existing task.
        
        Args:
            task_id: Task ID
            title: New title (optional)
            due_date: New due date (optional)
            notes: New notes (optional)
            priority: New priority (optional)
            status: New status - 'completed' marks as done
            
        Returns:
            Updated task details
        """
        self._ensure_available()
        
        updates = {}
        
        if title:
            updates["name"] = title
        if due_date:
            updates["due_on"] = self._normalize_due_date(due_date)
        if notes:
            updates["notes"] = notes
        if status == "completed":
            updates["completed"] = True
        elif status == "pending":
            updates["completed"] = False
        
        if not updates:
            return self.get_task(task_id)
        
        try:
            result = self._client.update_task(task_id, **updates)
            return self._normalize_task(result)
        except Exception as e:
            logger.error(f"Failed to update Asana task: {e}")
            raise AsanaServiceException(f"Failed to update task: {e}")
    
    def complete_task(self, task_id: str) -> Dict[str, Any]:
        """
        Mark a task as complete.
        
        Args:
            task_id: Task ID
            
        Returns:
            Updated task details
        """
        self._ensure_available()
        
        try:
            result = self._client.complete_task(task_id)
            return self._normalize_task(result)
        except Exception as e:
            logger.error(f"Failed to complete Asana task: {e}")
            raise AsanaServiceException(f"Failed to complete task: {e}")
    
    def delete_task(self, task_id: str) -> Dict[str, Any]:
        """
        Delete a task.
        
        Args:
            task_id: Task ID
            
        Returns:
            Success confirmation
        """
        self._ensure_available()
        
        try:
            self._client.delete_task(task_id)
            return {"success": True, "message": f"Task {task_id} deleted"}
        except Exception as e:
            logger.error(f"Failed to delete Asana task: {e}")
            raise AsanaServiceException(f"Failed to delete task: {e}")
    
    def list_tasks(
        self,
        status: str = "pending",
        project_id: Optional[str] = None,
        limit: int = 100,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        List tasks with filters.
        
        Args:
            status: Task status ('pending', 'completed', 'all')
            project_id: Filter by project
            limit: Maximum tasks to return
            
        Returns:
            List of tasks
        """
        self._ensure_available()
        
        completed = None
        if status == "pending":
            completed = False
        elif status == "completed":
            completed = True
        # status == "all" leaves completed as None
        
        try:
            results = self._client.list_tasks(
                project_id=project_id,
                completed=completed,
                limit=limit
            )
            return [self._normalize_task(t) for t in results]
        except Exception as e:
            logger.error(f"Failed to list Asana tasks: {e}")
            raise AsanaServiceException(f"Failed to list tasks: {e}")
    
    def search_tasks(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Search tasks by query text.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching tasks
        """
        self._ensure_available()
        
        try:
            results = self._client.search_tasks(query, limit=limit)
            return [self._normalize_task(t) for t in results]
        except Exception as e:
            logger.error(f"Failed to search Asana tasks: {e}")
            return []  # Search failures return empty, don't raise
    
    def get_overdue_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get overdue tasks.
        
        Returns:
            List of overdue tasks
        """
        tasks = self.list_tasks(status="pending", limit=limit)
        today = date.today().isoformat()
        
        return [
            t for t in tasks
            if t.get("due_date") and t["due_date"] < today
        ]
    
    # ========================================================================
    # Project Operations
    # ========================================================================
    
    def list_projects(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List all projects.
        
        Returns:
            List of projects
        """
        self._ensure_available()
        
        try:
            results = self._client.list_projects(limit=limit)
            return [
                {
                    "id": p.get("gid"),
                    "name": p.get("name"),
                    "archived": p.get("archived", False)
                }
                for p in results
            ]
        except Exception as e:
            logger.error(f"Failed to list Asana projects: {e}")
            raise AsanaServiceException(f"Failed to list projects: {e}")
    
    # ========================================================================
    # Helpers
    # ========================================================================
    
    def _normalize_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Asana task to standard format.
        
        Maps Asana fields to the format used by TaskService.
        """
        return {
            "id": task.get("gid"),
            "title": task.get("name"),
            "status": "completed" if task.get("completed") else "pending",
            "due_date": task.get("due_on"),
            "notes": task.get("notes"),
            "assignee": task.get("assignee", {}).get("name") if task.get("assignee") else None,
            "source": "asana"
        }
