"""
Celery Health Check Endpoint
Verifies that Celery worker is running and responsive
"""
from fastapi import APIRouter, HTTPException
from celery.result import AsyncResult
from typing import Dict, Any
import logging

from src.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/celery")
async def check_celery_health() -> Dict[str, Any]:
    """
    Check if Celery worker is running and responsive
    
    Returns:
        Status of Celery worker with details
        
    Raises:
        HTTPException: If Celery worker is not responding
    """
    try:
        # Get worker stats (this will timeout if no workers are running)
        inspect = celery_app.control.inspect(timeout=2.0)
        
        # Check active workers
        stats = inspect.stats()
        active_tasks = inspect.active()
        registered_tasks = inspect.registered()
        
        if not stats:
            logger.error("❌ No Celery workers found!")
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "unhealthy",
                    "error": "No Celery workers are running",
                    "fix": "Run: ./scripts/start_celery.sh"
                }
            )
        
        # Count workers
        worker_count = len(stats.keys())
        
        # Get task counts
        total_active_tasks = sum(len(tasks) for tasks in (active_tasks.values() if active_tasks else []))
        
        return {
            "status": "healthy",
            "workers": worker_count,
            "active_tasks": total_active_tasks,
            "worker_details": {
                worker_name: {
                    "active_tasks": len(active_tasks.get(worker_name, [])) if active_tasks else 0,
                    "registered_tasks": len(registered_tasks.get(worker_name, [])) if registered_tasks else 0,
                }
                for worker_name in stats.keys()
            },
            "message": f"✅ {worker_count} Celery worker(s) running"
        }
        
    except Exception as e:
        logger.error(f"❌ Celery health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "error": str(e),
                "fix": "Celery worker may not be running. Run: ./scripts/start_celery.sh"
            }
        )


@router.get("/celery/test-task")
async def test_celery_task() -> Dict[str, Any]:
    """
    Test Celery by queuing a simple task
    
    Returns:
        Task ID and status
    """
    try:
        from src.workers.tasks.maintenance_tasks import health_check_task
        
        # Queue a simple health check task
        task = health_check_task.delay()
        
        return {
            "status": "task_queued",
            "task_id": task.id,
            "message": "Task queued successfully. Worker should process it shortly.",
            "check_status": f"/health/celery/task/{task.id}"
        }
        
    except Exception as e:
        logger.error(f"Failed to queue test task: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": str(e),
                "fix": "Check if Celery worker is running: ./scripts/start_celery.sh"
            }
        )


@router.get("/celery/task/{task_id}")
async def check_task_status(task_id: str) -> Dict[str, Any]:
    """
    Check the status of a specific Celery task
    
    Args:
        task_id: The Celery task ID
        
    Returns:
        Task status and result
    """
    try:
        result = AsyncResult(task_id, app=celery_app)
        
        return {
            "task_id": task_id,
            "status": result.state,
            "ready": result.ready(),
            "successful": result.successful() if result.ready() else None,
            "result": result.result if result.ready() else None,
            "traceback": str(result.traceback) if result.failed() else None
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e)}
        )
