"""
Workflows API Router

Provides REST API endpoints for executing and managing workflows.
"""
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from src.workflows.engine import WorkflowExecutor, StateManager, EventEmitter
from src.workflows.definitions import (
    MorningBriefingWorkflow,
    EmailToActionWorkflow,
    WeeklyPlanningWorkflow,
    EndOfDayReviewWorkflow,
    BatchEmailProcessorWorkflow
)
from src.database.models import User
from api.dependencies import AppState
from api.middleware import require_session
from src.utils.logger import setup_logger
from src.workers.tasks import run_workflow

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Global workflow executor instance
_executor: Optional[WorkflowExecutor] = None
_state_manager: Optional[StateManager] = None
_event_emitter: Optional[EventEmitter] = None


def get_executor() -> WorkflowExecutor:
    """Get or create the workflow executor"""
    global _executor, _state_manager, _event_emitter
    
    if _executor is None:
        _state_manager = StateManager()
        _event_emitter = EventEmitter()
        _executor = WorkflowExecutor(
            state_manager=_state_manager,
            event_emitter=_event_emitter
        )
        
        # Register workflow classes (factories are registered per-endpoint)
        logger.info("[WORKFLOWS API] Executor initialized")
    
    return _executor


# ============================================
# Request/Response Models
# ============================================

class MorningBriefingParams(BaseModel):
    max_emails: int = Field(default=10, ge=1, le=50)
    max_tasks: int = Field(default=10, ge=1, le=50)
    include_recommendations: bool = True


class EmailToActionParams(BaseModel):
    email_id: str
    auto_create_tasks: bool = True
    auto_create_events: bool = True
    auto_archive: bool = False


class WeeklyPlanningParams(BaseModel):
    include_last_week: bool = True
    week_offset: int = Field(default=0, ge=0, le=4)


class BatchEmailParams(BaseModel):
    email_ids: Optional[list[str]] = None
    query: str = "is:unread"
    max_emails: int = Field(default=10, ge=1, le=50)
    auto_create_tasks: bool = True
    auto_create_events: bool = True


class WorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


# ============================================
# Endpoints
# ============================================

@router.get("/")
async def list_workflows():
    """List available workflows"""
    return {
        "workflows": [
            {
                "name": "morning_briefing",
                "description": "Generate morning briefing with schedule, tasks, and emails",
                "endpoint": "/api/workflows/morning-briefing"
            },
            {
                "name": "email_to_action",
                "description": "Process email and create tasks/events",
                "endpoint": "/api/workflows/email-to-action"
            },
            {
                "name": "weekly_planning",
                "description": "Weekly planning overview with recommendations",
                "endpoint": "/api/workflows/weekly-planning"
            },
            {
                "name": "end_of_day_review",
                "description": "End of day summary with productivity insights",
                "endpoint": "/api/workflows/end-of-day"
            },
            {
                "name": "batch_email_processor",
                "description": "Process multiple emails in batch",
                "endpoint": "/api/workflows/batch-emails"
            }
        ]
    }


@router.get("/morning-briefing")
async def morning_briefing(
    params: MorningBriefingParams = Depends(),
    user: User = Depends(require_session)
):
    """
    Generate morning briefing in the background.
    """
    try:
        # Queue the workflow task
        task = run_workflow.delay(
            user_id=user.id,
            workflow_name="morning_briefing",
            params=params.model_dump()
        )
        
        return {
            "workflow_id": task.id,
            "status": "queued",
            "message": "Morning briefing generation started in background",
            "check_status_url": f"/api/workflows/status/{task.id}"
        }
        
    except Exception as e:
        logger.error(f"Failed to queue morning briefing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-to-action")
async def email_to_action(
    params: EmailToActionParams,
    user: User = Depends(require_session)
):
    """
    Process an email and convert to actions in the background.
    """
    try:
        task = run_workflow.delay(
            user_id=user.id,
            workflow_name="email_to_action",
            params=params.model_dump()
        )
        
        return {
            "workflow_id": task.id,
            "status": "queued",
            "message": "Email processing started in background",
            "check_status_url": f"/api/workflows/status/{task.id}"
        }
        
    except Exception as e:
        logger.error(f"Failed to queue email-to-action: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weekly-planning")
async def weekly_planning(
    params: WeeklyPlanningParams = Depends(),
    user: User = Depends(require_session)
):
    """
    Generate weekly planning survey in the background.
    """
    try:
        task = run_workflow.delay(
            user_id=user.id,
            workflow_name="weekly_planning",
            params=params.model_dump()
        )
        
        return {
            "workflow_id": task.id,
            "status": "queued",
            "message": "Weekly planning started in background",
            "check_status_url": f"/api/workflows/status/{task.id}"
        }
        
    except Exception as e:
        logger.error(f"Failed to queue weekly-planning: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/end-of-day")
async def end_of_day_review(
    include_email_stats: bool = Query(default=True),
    user: User = Depends(require_session)
):
    """
    Generate end-of-day review in the background.
    """
    try:
        task = run_workflow.delay(
            user_id=user.id,
            workflow_name="end_of_day_review",
            params={"include_email_stats": include_email_stats}
        )
        
        return {
            "workflow_id": task.id,
            "status": "queued",
            "message": "End-of-day review started in background",
            "check_status_url": f"/api/workflows/status/{task.id}"
        }
        
    except Exception as e:
        logger.error(f"Failed to queue end-of-day: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-emails")
async def batch_process_emails(
    params: BatchEmailParams,
    user: User = Depends(require_session)
):
    """
    Process multiple emails in batch in the background.
    """
    try:
        task = run_workflow.delay(
            user_id=user.id,
            workflow_name="batch_email_processor",
            params=params.model_dump()
        )
        
        return {
            "workflow_id": task.id,
            "status": "queued",
            "message": "Batch email processing started in background",
            "check_status_url": f"/api/workflows/status/{task.id}"
        }
        
    except Exception as e:
        logger.error(f"Failed to queue batch-emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{workflow_id}")
async def get_workflow_status(
    workflow_id: str,
    user: User = Depends(require_session)
):
    """Get the status of a workflow execution"""
    executor = get_executor()
    status = await executor.get_status(workflow_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # Verify user owns this workflow
    if status.get('user_id') != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return status


@router.get("/history")
async def get_workflow_history(
    workflow_name: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_session)
):
    """Get workflow execution history for the current user"""
    global _state_manager
    
    if _state_manager is None:
        get_executor()  # Initialize
    
    history = await _state_manager.get_by_user(
        user_id=user.id,
        limit=limit
    )
    
    if workflow_name:
        history = [h for h in history if h.workflow_name == workflow_name]
    
    return {
        "count": len(history),
        "workflows": [h.to_dict() for h in history]
    }
