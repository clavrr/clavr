"""
Google Tasks-related Celery Tasks
Background tasks for Google Tasks operations

Refactored to use TaskService instead of direct client access.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from ..celery_app import celery_app
from ..base_task import BaseTask, IdempotentTask
from ...utils.logger import setup_logger
from ...integrations.google_tasks.service import TaskService
from ...utils.config import load_config
from ...core.credential_provider import CredentialFactory

logger = setup_logger(__name__)


@celery_app.task(base=IdempotentTask, bind=True)
def sync_user_tasks(self, user_id: str, tasklist_id: str = "@default") -> Dict[str, Any]:
    """
    Sync Google Tasks for a single user using TaskService
    
    Args:
        user_id: User ID
        tasklist_id: Task list ID (default: @default for primary list)
        
    Returns:
        Sync results with statistics
    """
    logger.info(f"Starting Google Tasks sync for user {user_id}")
    
    try:
        from ...database import get_db_context
        from ...database.models import User
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Create service using CredentialFactory
            config = load_config()
            factory = CredentialFactory(config)
            task_service = factory.create_service('task', user_id=user_id, db_session=db)
        
        # Sync tasks (including completed tasks) via service layer
        tasks = task_service.list_tasks(
            status='all',  # Get both active and completed
            limit=1000
        )
        
        logger.info(f"Synced {len(tasks)} Google Tasks for user {user_id}")
        
        return {
            'user_id': user_id,
            'tasklist_id': tasklist_id,
            'tasks_synced': len(tasks),
            'sync_time': datetime.utcnow().isoformat(),
            'status': 'success'
        }
        
    except Exception as exc:
        logger.error(f"Google Tasks sync failed for user {user_id}: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def create_task_with_notification(
    self,
    user_id: str,
    title: str,
    notes: Optional[str] = None,
    due: Optional[str] = None,
    tasklist_id: str = "@default",
    send_notification: bool = True
) -> Dict[str, Any]:
    """
    Create a Google Task and optionally send notification using TaskService
    
    Args:
        user_id: User ID
        title: Task title
        notes: Task notes/description
        due: Due date (ISO format)
        tasklist_id: Task list ID (default: @default)
        send_notification: Whether to send notification
        
    Returns:
        Created task details
    """
    logger.info(f"Creating Google Task '{title}' for user {user_id}")
    
    try:
        from ...database import get_db_context
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            task_service = factory.create_service('task', user_id=user_id, db_session=db)
        
        # Create task via service layer
        task = task_service.create_task(
            title=title,
            notes=notes or "",
            due_date=due,
            category='work',
            priority='medium'
        )
        
        if not task:
            raise Exception("Failed to create Google Task - no task returned")
        
        # Send notification if requested
        if send_notification:
            from .notification_tasks import send_task_reminder
            send_task_reminder.delay(
                task_id=task['id'],
                task_title=title,
                user_id=user_id
            )
        
        logger.info(f"Created Google Task {task['id']} for user {user_id}")
        
        return {
            'user_id': user_id,
            'task_id': task['id'],
            'title': title,
            'tasklist_id': tasklist_id,
            'status': 'created',
            'created_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Failed to create Google Task for user {user_id}: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def complete_task(
    self,
    user_id: str,
    task_id: str,
    tasklist_id: str = "@default"
) -> Dict[str, Any]:
    """
    Mark a Google Task as complete
    
    Args:
        user_id: User ID
        task_id: Task ID
        tasklist_id: Task list ID (default: @default)
        
    Returns:
        Completion result
    """
    logger.info(f"Completing Google Task {task_id} for user {user_id}")
    
    try:
        from ...database import get_db_context
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            task_service = factory.create_service('task', user_id=user_id, db_session=db)
        
        # Complete the task
        success = task_service.complete_task(task_id=task_id, tasklist_id=tasklist_id)
        
        if not success:
            raise Exception("Failed to complete Google Task")
        
        logger.info(f"Completed Google Task {task_id} for user {user_id}")
        
        # Trigger webhook if task is completed
        from .webhook_tasks import trigger_task_completed_webhook
        trigger_task_completed_webhook(
            task_id=task_id,
            task_data={'task_id': task_id, 'tasklist_id': tasklist_id, 'completed_at': datetime.utcnow().isoformat()},
            user_id=user_id
        )
        
        return {
            'user_id': user_id,
            'task_id': task_id,
            'tasklist_id': tasklist_id,
            'status': 'completed',
            'completed_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Failed to complete Google Task {task_id}: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def delete_task(
    self,
    user_id: str,
    task_id: str,
    tasklist_id: str = "@default"
) -> Dict[str, Any]:
    """
    Delete a Google Task
    
    Args:
        user_id: User ID
        task_id: Task ID
        tasklist_id: Task list ID (default: @default)
        
    Returns:
        Deletion result
    """
    logger.info(f"Deleting Google Task {task_id} for user {user_id}")
    
    try:
        from ...database import get_db_context
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            task_service = factory.create_service('task', user_id=user_id, db_session=db)
        
        # Delete the task
        success = task_service.delete_task(task_id=task_id, tasklist_id=tasklist_id)
        
        if not success:
            raise Exception("Failed to delete Google Task")
        
        logger.info(f"Deleted Google Task {task_id} for user {user_id}")
        
        return {
            'user_id': user_id,
            'task_id': task_id,
            'tasklist_id': tasklist_id,
            'status': 'deleted',
            'deleted_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Failed to delete Google Task {task_id}: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def cleanup_completed_tasks(
    self,
    user_id: str,
    days_old: int = 30,
    tasklist_id: str = "@default"
) -> Dict[str, Any]:
    """
    Delete completed Google Tasks older than specified days
    
    Args:
        user_id: User ID
        days_old: Delete completed tasks older than this many days
        tasklist_id: Task list ID (default: @default)
        
    Returns:
        Cleanup results
    """
    logger.info(f"Cleaning up completed tasks older than {days_old} days for user {user_id}")
    
    try:
        from ...database import get_db_context
        from datetime import datetime as dt
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            task_service = factory.create_service('task', user_id=user_id, db_session=db)
        
        # Get all tasks including completed
        all_tasks = task_service.list_tasks(tasklist_id=tasklist_id, show_completed=True)
        
        # Calculate cutoff date
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        deleted_count = 0
        
        # Filter and delete old completed tasks
        for task in all_tasks:
            # Check if task is completed and has a completed date
            if task.get('status') == 'completed' and task.get('completed'):
                try:
                    # Parse completed date (RFC 3339 format)
                    completed_date_str = task['completed']
                    # Remove 'Z' and parse
                    completed_date = datetime.fromisoformat(completed_date_str.replace('Z', '+00:00'))
                    
                    # Check if older than cutoff
                    if completed_date < cutoff_date.replace(tzinfo=completed_date.tzinfo):
                        task_service.delete_task(task_id=task['id'], tasklist_id=tasklist_id)
                        deleted_count += 1
                        
                except Exception as exc:
                    logger.warning(f"Failed to delete task {task['id']}: {exc}")
        
        logger.info(f"Deleted {deleted_count} old completed tasks for user {user_id}")
        
        return {
            'user_id': user_id,
            'tasklist_id': tasklist_id,
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat(),
            'status': 'completed'
        }
        
    except Exception as exc:
        logger.error(f"Tasks cleanup failed for user {user_id}: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def sync_all_task_lists(
    self,
    user_id: str
) -> Dict[str, Any]:
    """
    Sync all task lists for a user
    
    Args:
        user_id: User ID
        
    Returns:
        Sync results with statistics
    """
    logger.info(f"Syncing all task lists for user {user_id}")
    
    try:
        from ...database import get_db_context
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            task_service = factory.create_service('task', user_id=user_id, db_session=db)
        
        # Get all task lists via service
        task_lists = task_service.get_task_lists()
        
        total_tasks = 0
        synced_lists = []
        
        # Sync tasks from each list
        for task_list in task_lists:
            list_id = task_list['id']
            list_title = task_list.get('title', 'Untitled')
            
            tasks = task_service.list_tasks(tasklist_id=list_id, show_completed=True)
            total_tasks += len(tasks)
            
            synced_lists.append({
                'list_id': list_id,
                'list_title': list_title,
                'task_count': len(tasks)
            })
        
        logger.info(f"Synced {len(task_lists)} task lists with {total_tasks} total tasks for user {user_id}")
        
        return {
            'user_id': user_id,
            'task_lists_synced': len(task_lists),
            'total_tasks_synced': total_tasks,
            'task_lists': synced_lists,
            'sync_time': datetime.utcnow().isoformat(),
            'status': 'success'
        }
        
    except Exception as exc:
        logger.error(f"All task lists sync failed for user {user_id}: {exc}")
        raise