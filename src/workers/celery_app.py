"""
Celery Application Configuration
Provides distributed task queue for async processing

CRITICAL CONFIGURATION NOTES:
------------------------------
1. WORKER POOL MODE:
   - MUST use --pool=solo when starting workers
   - Default 'prefork' pool causes SIGSEGV crashes with Qdrant/OpenAI
   - Solo pool is single-threaded but compatible with threading libraries
   
   CORRECT: celery -A src.workers.celery_app worker --pool=solo
   WRONG:   celery -A src.workers.celery_app worker  (uses prefork by default)

2. AUTOMATIC EMAIL INDEXING:
   - New users get automatic indexing via api/auth_routes.py
   - Celery worker MUST be running for indexing to work
   - Use scripts/start_celery.sh to ensure proper configuration

3. MONITORING:
   - Logs: logs/celery.log
   - PID file: logs/celery.pid
   - Use: tail -f logs/celery.log to monitor
"""
import os
from celery import Celery
from kombu import Queue, Exchange

from ..utils.logger import setup_logger
from ..utils.urls import URLs

logger = setup_logger(__name__)

# Redis configuration - Use centralized URLs
REDIS_URL = URLs.REDIS
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', REDIS_URL)

# Create Celery app
celery_app = Celery(
    'notely_agent',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        'src.workers.tasks.email_tasks',
        'src.workers.tasks.calendar_tasks',
        'src.workers.tasks.indexing_tasks',
        'src.workers.tasks.notification_tasks',
        'src.workers.tasks.notification_tasks',
        'src.workers.tasks.maintenance_tasks',
        'src.workers.tasks.autonomy_tasks',
    ]
)

# Celery configuration
celery_app.conf.update(
    # Task routing
    task_routes={
        'src.workers.tasks.email_tasks.*': {'queue': 'email'},
        'src.workers.tasks.calendar_tasks.*': {'queue': 'calendar'},
        'src.workers.tasks.indexing_tasks.*': {'queue': 'indexing'},
        'src.workers.tasks.notification_tasks.*': {'queue': 'notifications'},
    },
    
    # Task queues
    task_queues=(
        Queue('default', Exchange('default'), routing_key='default'),
        Queue('email', Exchange('email'), routing_key='email'),
        Queue('calendar', Exchange('calendar'), routing_key='calendar'),
        Queue('indexing', Exchange('indexing'), routing_key='indexing'),
        Queue('notifications', Exchange('notifications'), routing_key='notifications'),
        Queue('priority', Exchange('priority'), routing_key='priority'),
    ),
    
    # Task execution settings
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
    
    # Task result settings
    result_expires=3600,  # Results expire after 1 hour
    result_persistent=True,
    
    # Task execution options
    task_acks_late=True,  # Acknowledge tasks after completion
    task_reject_on_worker_lost=True,
    task_track_started=True,
    
    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time per worker
    worker_max_tasks_per_child=1000,  # Restart worker after 1000 tasks
    
    # Retry settings
    task_default_retry_delay=60,  # Retry after 60 seconds
    task_max_retries=3,
    
    # Rate limiting
    task_annotations={
        'src.workers.tasks.email_tasks.sync_emails': {'rate_limit': '10/m'},
        'src.workers.tasks.indexing_tasks.index_emails': {'rate_limit': '5/m'},
        'src.workers.tasks.notification_tasks.send_email_notification': {'rate_limit': '100/m'},
    },
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
    
    # Beat scheduler settings (for periodic tasks)
    # PHASE 3: AUTOMATIC INCREMENTAL EMAIL SYNCING
    beat_schedule={
        # Incremental email indexing (new emails only) - every 30 minutes
        # Uses optimized parallel fetching for fast updates
        'incremental-email-sync-every-30-minutes': {
            'task': 'src.workers.tasks.indexing_tasks.sync_all_users_emails',
            'schedule': 1800.0,  # 30 minutes (optimized for balance between freshness and resource usage)
            'options': {
                'queue': 'indexing',
                'expires': 1500,  # Task expires after 25 minutes
            }
        },
        
        # Email metadata sync (fast, lightweight) - every 5 minutes
        # This syncs email metadata without full indexing
        'sync-email-metadata-every-5-minutes': {
            'task': 'src.workers.tasks.email_tasks.sync_all_users_emails',
            'schedule': 300.0,  # 5 minutes
            'options': {
                'queue': 'email',
                'expires': 240,  # Task expires after 4 minutes
            }
        },
        
        # System maintenance tasks
        'cleanup-expired-sessions-hourly': {
            'task': 'src.workers.tasks.maintenance_tasks.cleanup_expired_sessions',
            'schedule': 3600.0,  # 1 hour
            'options': {'queue': 'default'}
        },
        'update-cache-stats-hourly': {
            'task': 'src.workers.tasks.maintenance_tasks.update_cache_statistics',
            'schedule': 3600.0,  # 1 hour
            'options': {'queue': 'default'}
        },
        
        # Health check task (verify workers are responsive)
        'health-check-every-5-minutes': {
            'task': 'src.workers.tasks.maintenance_tasks.health_check_task',
            'schedule': 300.0,  # 5 minutes
            'options': {'queue': 'default'}
        },
        
        # Autonomy: Proactive Think Loop (Phase 1)
        'proactive-think-every-15-minutes': {
            'task': 'src.workers.tasks.autonomy_tasks.proactive_think',
            'schedule': 900.0,  # 15 minutes
            'options': {'queue': 'default'}
        },
    },
    
    # Beat scheduler configuration
    beat_schedule_filename='logs/celerybeat-schedule',  # Store schedule in logs directory
    beat_max_loop_interval=5,  # Check for new tasks every 5 seconds
)

# Task base class configuration
celery_app.conf.task_base = 'src.workers.base_task:BaseTask'


@celery_app.task(bind=True)
def debug_task(self):
    """Debug task to test Celery setup"""
    logger.info(f'Request: {self.request!r}')
    return f'Task executed successfully on worker {self.request.hostname}'


def get_celery_app() -> Celery:
    """Get the Celery application instance"""
    return celery_app


# Task status helpers
def get_task_status(task_id: str) -> dict:
    """
    Get the status of a task
    
    Args:
        task_id: Task ID
        
    Returns:
        Task status information
    """
    from celery.result import AsyncResult
    
    result = AsyncResult(task_id, app=celery_app)
    
    return {
        'task_id': task_id,
        'state': result.state,
        'status': result.status,
        'result': result.result if result.ready() else None,
        'info': result.info,
        'traceback': result.traceback if result.failed() else None,
    }


def cancel_task(task_id: str, terminate: bool = False) -> bool:
    """
    Cancel a running task
    
    Args:
        task_id: Task ID
        terminate: If True, forcefully terminate the task
        
    Returns:
        True if task was cancelled
    """
    from celery.result import AsyncResult
    
    result = AsyncResult(task_id, app=celery_app)
    
    if terminate:
        celery_app.control.revoke(task_id, terminate=True, signal='SIGKILL')
    else:
        celery_app.control.revoke(task_id)
    
    logger.info(f"Task {task_id} {'terminated' if terminate else 'cancelled'}")
    return True


def purge_queue(queue_name: str) -> int:
    """
    Purge all tasks from a queue
    
    Args:
        queue_name: Name of the queue to purge
        
    Returns:
        Number of tasks purged
    """
    with celery_app.connection_or_acquire() as conn:
        return celery_app.control.purge()


if __name__ == '__main__':
    # Start Celery worker
    celery_app.start()