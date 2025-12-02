"""
Celery Worker Manager
Ensures Celery workers are running before queuing tasks
"""
import subprocess
import time
from typing import Optional
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


def is_celery_worker_running() -> bool:
    """
    Check if Celery worker is running
    
    Returns:
        True if worker is running, False otherwise
    """
    try:
        from celery import Celery
        from ..celery_app import celery_app
        
        # Try to ping the worker with a short timeout
        result = celery_app.control.inspect(timeout=1.0).active()
        
        if result is None or len(result) == 0:
            return False
            
        return True
        
    except Exception as e:
        logger.warning(f"Failed to check Celery worker status: {e}")
        return False


def start_celery_worker() -> bool:
    """
    Attempt to start the Celery worker if it's not running
    
    Returns:
        True if worker was started successfully, False otherwise
    """
    try:
        import os
        
        # Get the project root directory
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        start_script = os.path.join(project_root, "scripts", "start_celery.sh")
        
        if not os.path.exists(start_script):
            logger.error(f"Start script not found: {start_script}")
            return False
        
        logger.info("Attempting to start Celery worker...")
        
        # Run the start script
        result = subprocess.run(
            [start_script],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # Wait a moment for worker to start
            time.sleep(2)
            
            # Verify it's running
            if is_celery_worker_running():
                logger.info("Celery worker started successfully")
                return True
            else:
                logger.error("Celery worker script executed but worker is not responding")
                return False
        else:
            logger.error(f"Failed to start Celery worker: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Timeout while starting Celery worker")
        return False
    except Exception as e:
        logger.error(f"Error starting Celery worker: {e}")
        return False


def ensure_celery_worker_running(auto_start: bool = True) -> bool:
    """
    Ensure Celery worker is running, optionally starting it if not
    
    Args:
        auto_start: If True, attempt to start worker if it's not running
        
    Returns:
        True if worker is running (or was started), False otherwise
    """
    if is_celery_worker_running():
        return True
    
    logger.warning("Celery worker is not running")
    
    if auto_start:
        logger.info("Attempting to auto-start Celery worker...")
        return start_celery_worker()
    
    return False


def get_worker_status() -> dict:
    """
    Get detailed status of Celery workers
    
    Returns:
        Dictionary with worker status information
    """
    try:
        from ..celery_app import celery_app
        
        # Get active tasks
        active = celery_app.control.inspect(timeout=1.0).active()
        
        # Get registered tasks
        registered = celery_app.control.inspect(timeout=1.0).registered()
        
        # Get stats
        stats = celery_app.control.inspect(timeout=1.0).stats()
        
        return {
            'running': active is not None and len(active) > 0,
            'worker_count': len(active) if active else 0,
            'active_tasks': sum(len(tasks) for tasks in active.values()) if active else 0,
            'registered_tasks': list(registered.values())[0] if registered else [],
            'workers': list(active.keys()) if active else [],
            'stats': stats
        }
        
    except Exception as e:
        logger.error(f"Failed to get worker status: {e}")
        return {
            'running': False,
            'error': str(e)
        }