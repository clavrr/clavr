"""
Task Service - Business logic layer for task/to-do operations

Provides a clean interface for task operations using Google Tasks API.

CLOUD-ONLY: This service requires Google OAuth credentials.
Local storage has been removed for simplicity and cloud-native architecture.

This service is used by:
- TaskTool (LangChain tool)
- Task background workers (Celery tasks)
- API endpoints
- Email and Calendar tools (for task creation from emails/events)

Architecture:
    TaskService → GoogleTasksClient (required)
    TaskService → EmailService (for email integration)
    TaskService → CalendarService (for calendar integration)

Breaking Change (v3.0.0):
    - Local storage removed
    - Credentials now required
    - Use CredentialFactory to create TaskService with auto-credential loading
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from src.core.tasks.google_client import GoogleTasksClient
from src.utils.logger import setup_logger
from src.utils.config import Config
from .exceptions import (
    TaskServiceException,
    TaskNotFoundException,
    TaskValidationException,
    TaskIntegrationException,
    ServiceUnavailableException,
    AuthenticationException
)

logger = setup_logger(__name__)


class TaskService:
    """
    Task service providing business logic for task/to-do operations
    
    CLOUD-ONLY: Requires Google Tasks authentication.
    Local storage support has been removed in v3.0.0 for simplicity.
    
    Features:
    - Create, update, delete, complete tasks
    - Search and filter tasks
    - Bulk operations
    - Task analytics and insights
    - Email integration (create tasks from emails)
    - Calendar integration (create tasks from events)
    - Subtask management
    - Recurring tasks
    - Task reminders
    
    Migration from v2.x:
        OLD: TaskService(config)  # credentials optional
        NEW: TaskService(config, credentials)  # credentials required
        
        Use CredentialFactory for automatic credential loading:
            factory = CredentialFactory(config)
            task_service = factory.create_service('task', user_id=user_id, db_session=db)
    """
    
    def __init__(
        self,
        config: Config,
        credentials: Any
    ):
        """
        Initialize task service with Google Tasks
        
        Args:
            config: Application configuration
            credentials: Google OAuth credentials (REQUIRED)
            
        Raises:
            AuthenticationException: If credentials not provided
            ServiceUnavailableException: If Google Tasks API unavailable
            
        Example:
            from src.core.credential_provider import CredentialFactory
            
            factory = CredentialFactory(config)
            task_service = factory.create_service('task', user_id=123, db_session=db)
        """
        if not credentials:
            raise AuthenticationException(
                message="[INTEGRATION_REQUIRED] Tasks permission not granted. Please enable Google integration in Settings.",
                service_name="tasks"
            )
        
        self.config = config
        self.credentials = credentials
        
        # Initialize Google Tasks client (required)
        try:
            self.google_tasks = GoogleTasksClient(config, credentials=credentials)
            
            if not self.google_tasks.is_available():
                raise ServiceUnavailableException(
                    message="[INTEGRATION_REQUIRED] Tasks permission not granted. Please enable Google integration in Settings.",
                    service_name="tasks"
                )
            
            logger.info("[TASK_SERVICE] Google Tasks client initialized successfully")
            
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to initialize Google Tasks: {e}")
            raise ServiceUnavailableException(
                message=f"Failed to initialize Google Tasks: {str(e)}",
                service_name="tasks",
                cause=e
            )
    
    def _get_backend(self):
        """Get Google Tasks backend (only option now)"""
        return self.google_tasks
    
    def _is_google_tasks(self) -> bool:
        """Check if using Google Tasks backend (always True now)"""
        return True
    
    # ===================================================================
    # CORE TASK OPERATIONS
    # ===================================================================
    
    def create_task(
        self,
        title: str,
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        priority: str = "medium",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        project: Optional[str] = None,
        parent_id: Optional[str] = None,
        subtasks: Optional[List[str]] = None,
        recurrence: Optional[str] = None,
        reminder_days: Optional[int] = None,
        estimated_hours: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Create a new task
        
        Args:
            title: Task title/description
            due_date: Due date (ISO format)
            notes: Task notes
            priority: Priority level (low/medium/high/critical)
            category: Task category
            tags: Task tags
            project: Project name
            parent_id: Parent task ID (for subtasks)
            subtasks: List of subtask descriptions
            recurrence: Recurrence pattern
            reminder_days: Days before due date for reminder
            estimated_hours: Estimated hours to complete
            
        Returns:
            Created task details
            
        Raises:
            TaskValidationException: If task data is invalid
            TaskServiceException: If creation fails
        """
        try:
            if not title or not title.strip():
                raise TaskValidationException(
                    "Task title is required",
                    service_name="task"
                )
            
            logger.info(f"[TASK_SERVICE] Creating task: {title}")
            
            if self._is_google_tasks():
                # Google Tasks (limited fields)
                task = self.google_tasks.create_task(
                    title=title,
                    due=due_date,
                    notes=notes or ""
                )
                
                # Check if task creation failed
                if not task:
                    raise TaskServiceException(
                        f"Failed to create task: Google Tasks API returned None",
                        service_name="task",
                        details={'title': title}
                    )
                
                task_id = task.get('id')
                
                # Create subtasks if provided
                if subtasks:
                    for subtask_title in subtasks:
                        subtask = self.google_tasks.create_task(
                            title=subtask_title
                            # Note: Google Tasks API doesn't support parent parameter in create
                            # Would need to use move() or patch() after creation
                        )
                        if not subtask:
                            logger.warning(f"[TASK_SERVICE] Failed to create subtask: {subtask_title}")
            
            logger.info(f"[TASK_SERVICE] Task created: {task_id}")
            return task
            
        except TaskValidationException:
            raise
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to create task: {e}")
            raise TaskServiceException(
                f"Failed to create task: {str(e)}",
                service_name="task",
                details={'title': title}
            )
    
    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update an existing task
        
        Args:
            task_id: Task ID
            title: New title (optional)
            due_date: New due date (optional)
            notes: New notes (optional)
            priority: New priority (optional)
            category: New category (optional)
            tags: New tags (optional)
            status: New status (optional)
            
        Returns:
            Updated task details
            
        Raises:
            TaskNotFoundException: If task not found
        """
        try:
            logger.info(f"[TASK_SERVICE] Updating task: {task_id}")
            
            if self._is_google_tasks():
                update_data = {}
                if title:
                    update_data['title'] = title
                if due_date:
                    update_data['due'] = due_date
                if notes is not None:
                    update_data['notes'] = notes
                if status:
                    update_data['status'] = status
                
                task = self.google_tasks.update_task(task_id, **update_data)
                
                if not task:
                    raise TaskServiceException(
                        f"Failed to update task: Google Tasks API returned None",
                        service_name="task",
                        details={'task_id': task_id}
                    )
            
            logger.info(f"[TASK_SERVICE] Task updated: {task_id}")
            return task
            
        except TaskNotFoundException:
            raise
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to update task: {e}")
            raise TaskServiceException(
                f"Failed to update task: {str(e)}",
                service_name="task",
                details={'task_id': task_id}
            )
    
    def complete_task(self, task_id: str, tasklist_id: str = "@default") -> Dict[str, Any]:
        """
        Mark a task as complete
        
        Args:
            task_id: Task ID
            tasklist_id: Task list ID (default: @default, only for Google Tasks)
            
        Returns:
            Updated task details
        """
        try:
            logger.info(f"[TASK_SERVICE] Completing task: {task_id}")
            
            if self._is_google_tasks():
                success = self.google_tasks.complete_task(task_id, tasklist_id=tasklist_id)
                if not success:
                    raise TaskServiceException(
                        f"Failed to complete task {task_id}",
                        service_name="task",
                        details={'task_id': task_id}
                    )
                # Return success dict - task was already completed by complete_task()
                task = {'id': task_id, 'status': 'completed'}
            
            logger.info(f"[TASK_SERVICE] Task completed: {task_id}")
            return task
            
        except TaskServiceException:
            raise
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to complete task: {e}")
            raise TaskServiceException(
                f"Failed to complete task: {str(e)}",
                service_name="task",
                details={'task_id': task_id}
            )
    
    def delete_task(self, task_id: str, tasklist_id: str = "@default") -> Dict[str, Any]:
        """
        Delete a task
        
        Args:
            task_id: Task ID
            tasklist_id: Task list ID (default: @default, only for Google Tasks)
            
        Returns:
            Success confirmation
        """
        try:
            logger.info(f"[TASK_SERVICE] Deleting task: {task_id}")
            
            if self._is_google_tasks():
                self.google_tasks.delete_task(task_id, tasklist_id=tasklist_id)
            
            logger.info(f"[TASK_SERVICE] Task deleted: {task_id}")
            return {'task_id': task_id, 'status': 'deleted'}
            
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to delete task: {e}")
            raise TaskServiceException(
                f"Failed to delete task: {str(e)}",
                service_name="task",
                details={'task_id': task_id}
            )
    
    def get_task(self, task_id: str, tasklist_id: str = "@default") -> Dict[str, Any]:
        """
        Get a single task by ID
        
        Args:
            task_id: Task ID
            tasklist_id: Task list ID (default: @default, only for Google Tasks)
            
        Returns:
            Task details
            
        Raises:
            TaskNotFoundException: If task not found
        """
        try:
            if self._is_google_tasks():
                # GoogleTasksClient doesn't have get_task method, so fetch from list
                # Get all tasks and find the one with matching ID
                all_tasks = self.google_tasks.list_tasks(tasklist_id=tasklist_id, show_completed=True)
                task = next((t for t in all_tasks if t.get('id') == task_id), None)
            else:
                task = None
            
            if not task:
                raise TaskNotFoundException(
                    f"Task {task_id} not found",
                    service_name="task"
                )
            
            return task
            
        except TaskNotFoundException:
            raise
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to get task: {e}")
            raise TaskServiceException(
                f"Failed to get task: {str(e)}",
                service_name="task",
                details={'task_id': task_id}
            )
    
    # ===================================================================
    # SEARCH AND LISTING
    # ===================================================================
    
    def list_tasks(
        self,
        status: str = "pending",
        priority: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        project: Optional[str] = None,
        limit: int = 100,
        tasklist_id: str = "@default",
        show_completed: bool = False,
        fast_mode: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List tasks with filters
        
        Args:
            status: Task status (pending/completed/all)
            priority: Priority filter
            category: Category filter
            tags: Tags filter
            project: Project filter
            limit: Maximum results
            tasklist_id: Task list ID (default: @default, only for Google Tasks)
            show_completed: Show completed tasks (only for Google Tasks)
            fast_mode: Fast mode for voice (only check @default list)
            
        Returns:
            List of tasks
        """
        try:
            logger.info(f"[TASK_SERVICE] Listing tasks: status={status}, fast_mode={fast_mode}")
            
            if self._is_google_tasks():
                # Google Tasks (limited filtering)
                # CRITICAL FIX: Check ALL task lists, not just @default
                # Users might have tasks in different lists
                if fast_mode:
                    all_task_lists = [{'id': '@default', 'title': 'My Tasks'}]
                    logger.info("[TASK_SERVICE] Fast mode: Using @default list only")
                else:
                    try:
                        all_task_lists = self.google_tasks.get_task_lists()
                        logger.info(f"[TASK_SERVICE] Found {len(all_task_lists)} task lists: {[tl.get('title', tl.get('id', 'Unknown')) for tl in all_task_lists]}")
                    except Exception as e:
                        logger.warning(f"[TASK_SERVICE] Could not get task lists, using @default only: {e}")
                        all_task_lists = [{'id': '@default', 'title': 'My Tasks'}]
                
                # Collect tasks from all task lists
                all_tasks = []
                api_show_completed = show_completed
                for task_list in all_task_lists:
                    list_id = task_list.get('id', '@default')
                    list_title = task_list.get('title', 'Unknown')
                    
                    # CRITICAL: Always fetch all tasks (show_completed=True) to avoid 
                    # Google API sync issues where pending tasks are misclassified.
                    # We will filter for 'needsAction' client-side for better reliability.
                    if status == "pending":
                        api_show_completed = True
                        logger.info(f"[TASK_SERVICE] Fetching all tasks from '{list_title}' ({list_id}) for pending filter")
                    elif status == "completed":
                        api_show_completed = True
                    else:
                        # For "all" status, get everything
                        api_show_completed = show_completed or True
                    
                    list_tasks = self.google_tasks.list_tasks(
                        tasklist_id=list_id,
                        show_completed=api_show_completed
                    )
                    logger.info(f"[TASK_SERVICE] Retrieved {len(list_tasks)} tasks from '{list_title}' ({list_id})")
                    all_tasks.extend(list_tasks)
                
                tasks = all_tasks
                logger.info(f"[TASK_SERVICE] Total tasks from all lists: {len(tasks)}")
                
                logger.info(f"[TASK_SERVICE] Retrieved {len(tasks)} tasks from Google Tasks API (show_completed={api_show_completed}, requested_status={status})")
                
                # Log task summary for debugging
                if tasks:
                    logger.info(f"[TASK_SERVICE] Retrieved {len(tasks)} tasks from Google Tasks API")
                
                # Filter by status client-side to ensure accuracy
                # CRITICAL: Filter by raw Google API status='needsAction' to get truly pending tasks
                original_count = len(tasks)
                if status == "pending":
                    # CRITICAL: Log all raw statuses before filtering to debug
                    all_raw_statuses = [t.get('raw_status', t.get('status', 'MISSING')) for t in tasks]
                    status_counts = {}
                    for s in all_raw_statuses:
                        status_counts[s] = status_counts.get(s, 0) + 1
                    logger.info(f"[TASK_SERVICE] Raw status breakdown before filtering: {status_counts}")
                    
                    # CRITICAL: Filter to tasks with raw_status='needsAction' (truly pending)
                    # ALSO include tasks with status='completed' but updated AFTER completion
                    # This handles Google API sync delays where uncompleted tasks still show status='completed'
                    # but were updated after completion (indicating they were uncompleted)
                    from datetime import datetime
                    import dateutil.parser
                    
                    pending_tasks_filtered = []
                    
                    for t in tasks:
                        if t.get('status') == 'deleted':
                            continue
                        
                        raw_status = t.get('raw_status', t.get('status', ''))
                        
                        # Always include tasks with raw_status='needsAction'
                        if raw_status == 'needsAction':
                            pending_tasks_filtered.append(t)
                        # Also include tasks with status='completed' but updated AFTER completion AND recently (within 7 days)
                        # This indicates they were uncompleted (Google API quirk - status doesn't update immediately)
                        # Only include if updated recently to avoid including old completed tasks
                        elif raw_status == 'completed':
                            completed_timestamp = t.get('completed')
                            updated_timestamp = t.get('updated')
                            
                            if completed_timestamp and updated_timestamp:
                                try:
                                    completed_dt = dateutil.parser.parse(completed_timestamp)
                                    updated_dt = dateutil.parser.parse(updated_timestamp)
                                    now = datetime.utcnow()
                                    if updated_dt.tzinfo:
                                        updated_dt = updated_dt.replace(tzinfo=None)
                                    if now.tzinfo:
                                        now = now.replace(tzinfo=None)
                                    
                                    days_since_update = (now - updated_dt).days
                                    # If updated AFTER completion AND updated within last 7 days, task was likely uncompleted
                                    if updated_dt > completed_dt and days_since_update <= 7:
                                        logger.info(f"[TASK_SERVICE] Including '{t.get('title', 'NO TITLE')[:50]}' as pending (updated {days_since_update}d ago after completion - likely uncompleted)")
                                        pending_tasks_filtered.append(t)
                                except Exception as e:
                                    logger.debug(f"Could not parse timestamps for task {t.get('id')}: {e}")
                            elif not completed_timestamp:
                                # No completed timestamp but status='completed' - check if updated recently
                                if updated_timestamp:
                                    try:
                                        updated_dt = dateutil.parser.parse(updated_timestamp)
                                        now = datetime.utcnow()
                                        if updated_dt.tzinfo:
                                            updated_dt = updated_dt.replace(tzinfo=None)
                                        if now.tzinfo:
                                            now = now.replace(tzinfo=None)
                                        days_since_update = (now - updated_dt).days
                                        # Only include if updated within last 7 days
                                        if days_since_update <= 7:
                                            logger.info(f"[TASK_SERVICE] Including '{t.get('title', 'NO TITLE')[:50]}' as pending (status='completed' but no completed timestamp, updated {days_since_update}d ago - likely uncompleted)")
                                            pending_tasks_filtered.append(t)
                                    except Exception:
                                        pass
                    
                    tasks = pending_tasks_filtered
                    logger.info(f"[TASK_SERVICE] Filtered to {len(tasks)} pending tasks (raw_status='needsAction') from {original_count} total")
                    
                    # Log which tasks are being kept AND which were filtered out
                    if tasks:
                        kept_tasks = [(t.get('id', 'NO_ID')[:10], t.get('title', 'NO TITLE')[:50], t.get('raw_status', t.get('status', 'NO_STATUS'))) for t in tasks]
                        logger.info(f"[TASK_SERVICE] Kept {len(tasks)} pending tasks:")
                        for i, (task_id, title, task_status) in enumerate(kept_tasks, 1):
                            logger.info(f"[TASK_SERVICE]   {i}. [raw_status={task_status}] {title}")
                    
                    # Also log tasks that were filtered out (for debugging) - check raw_status
                    filtered_out = [t for t in all_tasks if t.get('raw_status', t.get('status', '')) != 'needsAction' or t.get('status') == 'deleted']
                    if filtered_out:
                        logger.info(f"[TASK_SERVICE] Filtered out {len(filtered_out)} non-pending tasks:")
                        for i, task in enumerate(filtered_out[:10], 1):  # Log first 10
                            raw_stat = task.get('raw_status', task.get('status', 'NO_STATUS'))
                            logger.info(f"[TASK_SERVICE]   {i}. [raw_status={raw_stat}] {task.get('title', 'NO TITLE')[:50]}")
                elif status == "completed":
                    tasks = [t for t in tasks if t.get('status') == 'completed']
                    logger.info(f"[TASK_SERVICE] Filtered to {len(tasks)} completed tasks (from {original_count} total)")
                # If status == "all", keep all tasks
                
                # Debug: Log first few task statuses and titles
                if tasks:
                    logger.info(f"[TASK_SERVICE] Sample task statuses: {[t.get('status') for t in tasks[:5]]}")
                    logger.info(f"[TASK_SERVICE] Sample task titles: {[t.get('title', 'NO TITLE')[:30] for t in tasks[:5]]}")
                
                tasks = tasks[:limit]  # Limit client-side
            
            logger.info(f"[TASK_SERVICE] Found {len(tasks)} tasks")
            return tasks
            
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to list tasks: {e}")
            raise TaskServiceException(
                f"Failed to list tasks: {str(e)}",
                service_name="task"
            )
    
    def search_tasks(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search tasks by query"""
        try:
            if self._is_google_tasks():
                # Simple title search for Google Tasks
                # Get both pending and completed tasks for search
                all_tasks = self.google_tasks.list_tasks(show_completed=True)
                query_lower = query.lower()
                matching_tasks = [
                    t for t in all_tasks
                    if query_lower in t.get('title', '').lower()
                ]
                logger.info(f"[TASK_SERVICE] Search found {len(matching_tasks)} tasks matching '{query}'")
                return matching_tasks
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Task search failed: {e}")
            raise TaskServiceException(
                f"Task search failed: {str(e)}",
                service_name="task"
            )
    
    def get_overdue_tasks(self, limit: int = 50, fast_mode: bool = False) -> List[Dict[str, Any]]:
        """Get overdue tasks"""
        if self._is_google_tasks():
            # For Google Tasks, filter client-side
            all_tasks = self.list_tasks(show_completed=False, fast_mode=fast_mode)
            now = datetime.now()
            return [
                t for t in all_tasks
                if t.get('due') and datetime.fromisoformat(t['due'].replace('Z', '+00:00')) < now
            ][:limit]
    
    def get_task_lists(self) -> List[Dict[str, Any]]:
        """
        Get all task lists (Google Tasks only)
        
        Returns:
            List of task lists with their metadata
            
        Raises:
            TaskServiceException: If not using Google Tasks or operation fails
        """
        try:
            if not self._is_google_tasks():
                logger.warning("[TASK_SERVICE] get_task_lists only available for Google Tasks")
                return [{'id': '@default', 'title': 'My Tasks'}]
            
            logger.info("[TASK_SERVICE] Getting all task lists")
            task_lists = self.google_tasks.get_task_lists()
            logger.info(f"[TASK_SERVICE] Found {len(task_lists)} task lists")
            return task_lists
            
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to get task lists: {e}")
            raise TaskServiceException(
                f"Failed to get task lists: {str(e)}",
                service_name="task"
            )
    
    # ===================================================================
    # BULK OPERATIONS
    # ===================================================================
    
    def bulk_complete(self, task_ids: List[str]) -> Dict[str, Any]:
        """Complete multiple tasks"""
        try:
            success_count = 0
            failed_count = 0
            
            for task_id in task_ids:
                try:
                    self.complete_task(task_id)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to complete task {task_id}: {e}")
                    failed_count += 1
            
            return {
                'total': len(task_ids),
                'success': success_count,
                'failed': failed_count
            }
        except Exception as e:
            raise TaskServiceException(
                f"Bulk complete failed: {str(e)}",
                service_name="task"
            )
    
    def bulk_delete(self, task_ids: List[str]) -> Dict[str, Any]:
        """Delete multiple tasks"""
        try:
            success_count = 0
            failed_count = 0
            
            for task_id in task_ids:
                try:
                    self.delete_task(task_id)
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete task {task_id}: {e}")
                    failed_count += 1
            
            return {
                'total': len(task_ids),
                'success': success_count,
                'failed': failed_count
            }
        except Exception as e:
            raise TaskServiceException(
                f"Bulk delete failed: {str(e)}",
                service_name="task"
            )
    
    # ===================================================================
    # ANALYTICS
    # ===================================================================
    
    def get_analytics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get task analytics
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Task statistics and insights
        """
        try:
            if self._is_google_tasks():
                # Basic analytics for Google Tasks
                all_tasks = self.google_tasks.list_tasks(show_completed=True)
                completed = [t for t in all_tasks if t.get('status') == 'completed']
                pending = [t for t in all_tasks if t.get('status') != 'completed']
                
                return {
                    'total_tasks': len(all_tasks),
                    'completed': len(completed),
                    'pending': len(pending),
                    'completion_rate': (len(completed) / len(all_tasks) * 100) if all_tasks else 0
                }
                
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to get analytics: {e}")
            raise TaskServiceException(
                f"Failed to get analytics: {str(e)}",
                service_name="task"
            )
    
    # ===================================================================
    # INTEGRATIONS
    # ===================================================================
    
    def create_task_from_email(
        self,
        email_id: str,
        email_subject: str,
        email_body: Optional[str] = None,
        auto_extract: bool = False
    ) -> Dict[str, Any]:
        """
        Create a task from an email
        
        Args:
            email_id: Email ID for linking
            email_subject: Email subject
            email_body: Email body (optional)
            auto_extract: Use AI to extract action items
            
        Returns:
            Created task details
        """
        try:
            logger.info(f"[TASK_SERVICE] Creating task from email: {email_id}")
            
            # Simple implementation: create task with email subject as title
            task = self.create_task(
                title=f"Follow up: {email_subject}",
                notes=f"From email: {email_id}\n\n{email_body or ''}",
                tags=['email'],
                category='email'
            )
            
            logger.info(f"[TASK_SERVICE] Task created from email")
            return task
            
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to create task from email: {e}")
            raise TaskIntegrationException(
                f"Failed to create task from email: {str(e)}",
                service_name="task",
                details={'email_id': email_id}
            )
    
    def create_task_from_event(
        self,
        event_id: str,
        event_title: str,
        event_time: str,
        task_type: str = "preparation"
    ) -> Dict[str, Any]:
        """
        Create a task from a calendar event
        
        Args:
            event_id: Event ID for linking
            event_title: Event title
            event_time: Event time
            task_type: Type of task (preparation/followup)
            
        Returns:
            Created task details
        """
        try:
            logger.info(f"[TASK_SERVICE] Creating {task_type} task for event: {event_id}")
            
            if task_type == "preparation":
                title = f"Prepare for: {event_title}"
                # Set due date 2 hours before event
                try:
                    event_dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                    due_dt = event_dt - timedelta(hours=2)
                    due_date = due_dt.isoformat()
                except:
                    due_date = None
            else:  # followup
                title = f"Follow up: {event_title}"
                # Set due date 1 day after event
                try:
                    event_dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                    due_dt = event_dt + timedelta(days=1)
                    due_date = due_dt.isoformat()
                except:
                    due_date = None
            
            task = self.create_task(
                title=title,
                due_date=due_date,
                notes=f"Related to calendar event: {event_id}",
                tags=['calendar', task_type],
                category='meeting'
            )
            
            logger.info(f"[TASK_SERVICE] Task created from calendar event")
            return task
            
        except Exception as e:
            logger.error(f"[TASK_SERVICE] Failed to create task from event: {e}")
            raise TaskIntegrationException(
                f"Failed to create task from event: {str(e)}",
                service_name="task",
                details={'event_id': event_id}
            )
