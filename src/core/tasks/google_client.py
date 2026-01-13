"""
Google Tasks Client
Integrates with Google Tasks API to manage tasks
"""
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ...utils.logger import setup_logger
from ...utils.config import Config
from ...utils.api import get_api_url_with_fallback
from ..base import BaseGoogleAPIClient
from .utils import format_task_from_google

logger = setup_logger(__name__)


class GoogleTasksClient(BaseGoogleAPIClient):
    """
    Google Tasks API client
    
    Provides methods to interact with Google Tasks:
    - List tasks
    - Create tasks
    - Update tasks
    - Complete tasks
    - Delete tasks
    """
    
    def __init__(self, config: Config, credentials: Optional[Credentials] = None):
        """
        Initialize Google Tasks client
        
        Args:
            config: Configuration object
            credentials: OAuth2 credentials (if None, will try to load from token.json)
        """
        self._account_restricted = False  # Track if Account Restricted error occurred
        super().__init__(config, credentials)
    
    def _build_service(self) -> Any:
        """Build Google Tasks API service"""
        return build('tasks', 'v1', credentials=self.credentials, cache_discovery=False)
    
    def _get_required_scopes(self) -> List[str]:
        """Get required Google Tasks scopes"""
        # Accept either full access or readonly access
        return [
            'https://www.googleapis.com/auth/tasks',
            'https://www.googleapis.com/auth/tasks.readonly'
        ]
    
    def _get_service_name(self) -> str:
        """Get service name"""
        return "Google Tasks"
    
    def list_tasks(self, tasklist_id: str = "@default", show_completed: bool = False) -> List[Dict[str, Any]]:
        """
        List tasks from Google Tasks
        
        Args:
            tasklist_id: ID of the task list (default: @default for primary list)
            show_completed: Whether to include completed tasks
            
        Returns:
            List of task dictionaries
        """
        if not self.is_available():
            logger.warning("Google Tasks service not available")
            return []
        
        try:
            # CRITICAL: Try BOTH showCompleted=True and showCompleted=False to catch all tasks
            # Google Tasks API can have sync issues where tasks appear pending in UI but completed in API
            # or vice versa. Fetching both ensures we get everything.
            all_tasks_dict = {}  # Use dict with task ID as key to deduplicate
            
            # First, fetch with showCompleted=False (pending tasks)
            tasks_pending: List[Dict[str, Any]] = []
            page_token: Optional[str] = None
            page_count = 0
            while True:
                page_count += 1
                request = self.service.tasks().list(
                    tasklist=tasklist_id,
                    showCompleted=False,  # Get pending tasks
                    showHidden=True,  # CRITICAL: Include hidden tasks
                    maxResults=100,
                    pageToken=page_token
                )
                results = request.execute()
                page_items = results.get('items', [])
                for task in page_items:
                    task_id = task.get('id')
                    if task_id:
                        all_tasks_dict[task_id] = task
                tasks_pending.extend(page_items)
                logger.debug(f"[GOOGLE_TASKS] Page {page_count} (showCompleted=False): Retrieved {len(page_items)} tasks (total so far: {len(tasks_pending)})")
                page_token = results.get('nextPageToken')
                if not page_token:
                    break
            
            # Then, fetch with showCompleted=True (all tasks) if requested
            if show_completed:
                page_token = None
                page_count = 0
                while True:
                    page_count += 1
                    request = self.service.tasks().list(
                        tasklist=tasklist_id,
                        showCompleted=True,  # Get all tasks including completed
                        showHidden=True,  # CRITICAL: Include hidden tasks
                        maxResults=100,
                        pageToken=page_token
                    )
                    results = request.execute()
                    page_items = results.get('items', [])
                    for task in page_items:
                        task_id = task.get('id')
                        if task_id:
                            all_tasks_dict[task_id] = task  # Will overwrite if duplicate, keeping latest
                    logger.debug(f"[GOOGLE_TASKS] Page {page_count} (showCompleted=True): Retrieved {len(page_items)} tasks")
                    page_token = results.get('nextPageToken')
                    if not page_token:
                        break
            
            # Convert dict back to list
            tasks = list(all_tasks_dict.values())
            logger.info(f"[GOOGLE_TASKS] Combined results: {len(tasks_pending)} pending-only + {len(all_tasks_dict)} total unique = {len(tasks)} tasks")
            
            # Debug: Log raw task details summary
            if tasks:
                logger.info(f"[GOOGLE_TASKS] Retrieved {len(tasks)} total unique tasks from tasklist={tasklist_id}")
                
                raw_statuses = [task.get('status', 'MISSING') for task in tasks[:10]]
                raw_titles = [task.get('title', 'NO TITLE')[:30] for task in tasks[:10]]
                logger.debug(f"[GOOGLE_TASKS] Raw task statuses (first 10): {raw_statuses}")
                logger.debug(f"[GOOGLE_TASKS] Raw task titles (first 10): {raw_titles}")
            else:
                logger.warning(f"[GOOGLE_TASKS] No tasks retrieved from Google Tasks API (show_completed={show_completed}, tasklist={tasklist_id})")
            
            # Convert to our format using utility function
            # Filter out deleted tasks
            formatted_tasks = []
            for task in tasks:
                formatted = format_task_from_google(task)
                # Skip deleted tasks
                if formatted.get('status') != 'deleted':
                    formatted_tasks.append(formatted)
                else:
                    logger.debug(f"[GOOGLE_TASKS] Skipping deleted task: {task.get('title', 'NO TITLE')[:50]}")
            
            # Log formatted tasks to see the mapping
            if formatted_tasks:
                logger.info(f"[GOOGLE_TASKS] Formatted {len(formatted_tasks)} tasks:")
                for i, task in enumerate(formatted_tasks, 1):
                    formatted_status = task.get('status', 'MISSING')
                    formatted_title = task.get('title', 'NO TITLE')[:50]
                    logger.info(f"[GOOGLE_TASKS]   Formatted task {i}: status='{formatted_status}', title='{formatted_title}'")
            
            # Debug: Log formatted task statuses and titles
            if formatted_tasks:
                formatted_statuses = [t.get('status', 'MISSING') for t in formatted_tasks[:10]]
                formatted_titles = [t.get('title', 'NO TITLE')[:30] for t in formatted_tasks[:10]]
                logger.debug(f"[GOOGLE_TASKS] Formatted task statuses (first 10): {formatted_statuses}")
                logger.debug(f"[GOOGLE_TASKS] Formatted task titles (first 10): {formatted_titles}")
            
            logger.info(f"Retrieved {len(formatted_tasks)} tasks from Google Tasks (show_completed={show_completed}, pages={page_count})")
            return formatted_tasks
            
        except HttpError as e:
            if e.resp.status == 403:
                logger.error(f"Google Tasks API error: {e}")
                logger.error("This usually means the OAuth credentials don't have the required scopes.")
                logger.error("Please re-authenticate with the Google Tasks scope: https://www.googleapis.com/auth/tasks")
            else:
                logger.error(f"Google Tasks API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to list Google Tasks: {e}")
            return []
    
    def create_task(self, title: str, notes: str = "", due: str = None, tasklist_id: str = "@default") -> Optional[Dict[str, Any]]:
        """
        Create a new task in Google Tasks
        
        Args:
            title: Task title
            notes: Task notes/description
            due: Due date (YYYY-MM-DD format or RFC 3339 format)
            tasklist_id: ID of the task list
            
        Returns:
            Created task dictionary or None if failed
        """
        if not self.is_available():
            logger.warning("Google Tasks service not available")
            return None
        
        try:
            task_body = {
                'title': title,
                'notes': notes
            }
            
            if due:
                # Google Tasks API requires RFC 3339 format (YYYY-MM-DDTHH:MM:SS.000Z)
                # Convert from YYYY-MM-DD if needed
                if 'T' not in due:
                    # Simple date format like "2025-12-05" - convert to RFC 3339
                    # Use midnight UTC as the default time (standard convention for all-day due dates)
                    try:
                        due_datetime = datetime.strptime(due, "%Y-%m-%d")
                        due = due_datetime.replace(hour=0, minute=0, second=0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                        logger.debug(f"[GOOGLE_TASKS] Converted due date to RFC 3339: {due}")
                    except ValueError:
                        logger.warning(f"[GOOGLE_TASKS] Could not parse due date: {due}")
                        # Don't set due date if we can't parse it
                        due = None
                
                if due:
                    task_body['due'] = due
            
            result = self.service.tasks().insert(
                tasklist=tasklist_id,
                body=task_body
            ).execute()
            
            logger.info(f"Created Google Task: {title}")
            return result
            
        except HttpError as e:
            error_str = str(e)
            error_details = getattr(e, 'error_details', None)
            
            # Check for Account Restricted error
            if 'Account Restricted' in error_str or (error_details and any('Account Restricted' in str(d) for d in error_details)):
                self._account_restricted = True
                logger.warning("[WARNING] Google Tasks API: Account Restricted")
                logger.warning("This usually means your Google account needs admin approval or the app needs to be published.")
                logger.warning("To fix this:")
                logger.warning("1. Ensure you're added as a test user in Google Cloud Console (OAuth consent screen)")
                logger.warning("2. Or publish your app in Google Cloud Console")
                api_url = get_api_url_with_fallback(self)
                logger.warning(f"3. Then re-authenticate at: {api_url}/auth/google/login")
            elif e.resp.status == 403:
                logger.error(f"Google Tasks API error (403): {e}")
                logger.error("This usually means the OAuth credentials don't have the required scopes.")
                logger.error("Please re-authenticate with the Google Tasks scope: https://www.googleapis.com/auth/tasks")
            else:
                logger.error(f"Google Tasks API error creating task: {e}")
            return None
        except Exception as e:
            error_str = str(e)
            # Check for Account Restricted in generic exceptions (might come from OAuth flow)
            if 'Account Restricted' in error_str or ('access_denied' in error_str and 'Account Restricted' in error_str):
                self._account_restricted = True
                logger.warning("[WARNING] Google Tasks API: Account Restricted")
                logger.warning("This usually means your Google account needs admin approval or the app needs to be published.")
                logger.warning("To fix this:")
                logger.warning("1. Ensure you're added as a test user in Google Cloud Console (OAuth consent screen)")
                logger.warning("2. Or publish your app in Google Cloud Console")
                api_url = get_api_url_with_fallback(self)
                logger.warning(f"3. Then re-authenticate at: {api_url}/auth/google/login")
            else:
                logger.error(f"Failed to create Google Task: {e}")
            return None
    
    def update_task(self, task_id: str, tasklist_id: str = "@default", **kwargs) -> Optional[Dict[str, Any]]:
        """
        Update an existing task
        
        Args:
            task_id: ID of the task to update
            tasklist_id: ID of the task list
            **kwargs: Task fields to update (title, due, notes, status)
            
        Returns:
            Updated task dictionary or None if failed
        """
        if not self.is_available():
            logger.warning("Google Tasks service not available")
            return None
        
        try:
            # First get the task to preserve its data
            task = self.service.tasks().get(
                tasklist=tasklist_id,
                task=task_id
            ).execute()
            
            # Update fields from kwargs
            if 'title' in kwargs:
                task['title'] = kwargs['title']
            if 'due' in kwargs:
                task['due'] = kwargs['due']
            elif 'due_date' in kwargs:
                task['due'] = kwargs['due_date']
            if 'notes' in kwargs:
                task['notes'] = kwargs['notes']
            if 'status' in kwargs:
                task['status'] = kwargs['status']
            
            # Update the task
            updated_task = self.service.tasks().update(
                tasklist=tasklist_id,
                task=task_id,
                body=task
            ).execute()
            
            logger.info(f"Updated Google Task: {updated_task.get('title', task_id)}")
            return format_task_from_google(updated_task)
            
        except HttpError as e:
            logger.error(f"Google Tasks API error updating task: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to update Google Task: {e}")
            return None
    
    def complete_task(self, task_id: str, tasklist_id: str = "@default") -> bool:
        """
        Mark a task as completed
        
        Args:
            task_id: ID of the task to complete
            tasklist_id: ID of the task list
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.warning("Google Tasks service not available")
            return False
        
        try:
            # First get the task to preserve its data
            task = self.service.tasks().get(
                tasklist=tasklist_id,
                task=task_id
            ).execute()
            
            # Update the task to mark it as completed
            task['status'] = 'completed'
            
            self.service.tasks().update(
                tasklist=tasklist_id,
                task=task_id,
                body=task
            ).execute()
            
            logger.info(f"Completed Google Task: {task.get('title', task_id)}")
            return True
            
        except HttpError as e:
            logger.error(f"Google Tasks API error completing task: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to complete Google Task: {e}")
            return False
    
    def delete_task(self, task_id: str, tasklist_id: str = "@default") -> bool:
        """
        Delete a task
        
        Args:
            task_id: ID of the task to delete
            tasklist_id: ID of the task list
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.warning("Google Tasks service not available")
            return False
        
        try:
            self.service.tasks().delete(
                tasklist=tasklist_id,
                task=task_id
            ).execute()
            
            logger.info(f"Deleted Google Task: {task_id}")
            return True
            
        except HttpError as e:
            logger.error(f"Google Tasks API error deleting task: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete Google Task: {e}")
            return False
    
    def get_task_lists(self) -> List[Dict[str, Any]]:
        """
        Get all task lists
        
        Returns:
            List of task list dictionaries
        """
        if not self.is_available():
            logger.warning("Google Tasks service not available")
            return []
        
        try:
            results = self.service.tasklists().list().execute()
            tasklists = results.get('items', [])
            
            logger.info(f"Retrieved {len(tasklists)} task lists from Google Tasks")
            return tasklists
            
        except HttpError as e:
            logger.error(f"Google Tasks API error getting task lists: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to get Google task lists: {e}")
            return []
