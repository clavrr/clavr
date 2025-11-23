"""
Base Task Class
Provides common functionality for all Celery tasks
"""
from celery import Task
from typing import Any, Optional
import time

from ..utils.logger import setup_logger
from ..utils import PerformanceContext

logger = setup_logger(__name__)


class BaseTask(Task):
    """
    Base task class with common functionality
    
    Features:
    - Automatic retries with exponential backoff
    - Performance tracking
    - Error logging
    - Task lifecycle hooks
    """
    
    # Default retry settings
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True
    
    def __call__(self, *args, **kwargs):
        """Task execution with performance tracking"""
        task_name = self.name.split('.')[-1]
        
        with PerformanceContext(f"celery_task_{task_name}"):
            logger.info(f"Starting task: {self.name} (ID: {self.request.id})")
            start_time = time.time()
            
            try:
                result = super().__call__(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"Completed task: {self.name} in {duration:.2f}s")
                return result
                
            except Exception as exc:
                duration = time.time() - start_time
                logger.error(
                    f"Task failed: {self.name} after {duration:.2f}s - {exc}",
                    exc_info=True
                )
                raise
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is retried"""
        logger.warning(
            f"Retrying task {self.name} (ID: {task_id}) - "
            f"Attempt {self.request.retries + 1}/{self.max_retries} - "
            f"Error: {exc}"
        )
        super().on_retry(exc, task_id, args, kwargs, einfo)
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails"""
        logger.error(
            f"Task failed permanently: {self.name} (ID: {task_id}) - "
            f"Error: {exc}",
            exc_info=True
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)
    
    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds"""
        logger.debug(f"Task succeeded: {self.name} (ID: {task_id})")
        super().on_success(retval, task_id, args, kwargs)
    
    def before_start(self, task_id, args, kwargs):
        """Called before task starts"""
        logger.debug(f"Task starting: {self.name} (ID: {task_id})")
        super().before_start(task_id, args, kwargs)
    
    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        """Called after task returns"""
        logger.debug(f"Task returned: {self.name} (ID: {task_id}) - Status: {status}")
        super().after_return(status, retval, task_id, args, kwargs, einfo)


class PriorityTask(BaseTask):
    """High-priority task that should be executed immediately"""
    queue = 'priority'
    priority = 9


class LongRunningTask(BaseTask):
    """Task that may take a long time to complete"""
    soft_time_limit = 3600  # 1 hour soft limit
    time_limit = 3900  # 65 minutes hard limit
    
    def on_timeout(self, soft, timeout):
        """Called when task times out"""
        logger.error(
            f"Task timeout: {self.name} - "
            f"{'Soft' if soft else 'Hard'} timeout of {timeout}s"
        )


class IdempotentTask(BaseTask):
    """Task that can be safely retried without side effects"""
    acks_late = True
    reject_on_worker_lost = True
