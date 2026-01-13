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
    user: User = Depends(require_session),
    request = None
):
    """
    Generate morning briefing.
    
    Provides:
    - Today's calendar events
    - Urgent and overdue tasks
    - Important unread emails
    - AI-powered recommendations
    """
    try:
        # Get services for user
        from fastapi import Request
        if request is None:
            from starlette.requests import Request as StarletteRequest
            # Create a minimal request context if needed
            
        email_tool = await AppState.get_email_tool(user.id, request)
        calendar_tool = await AppState.get_calendar_tool(user.id, request)
        task_tool = await AppState.get_task_tool(user.id, request)
        
        # Create workflow instance
        workflow = MorningBriefingWorkflow(
            calendar_service=calendar_tool.calendar_service,
            task_service=task_tool.task_service,
            email_service=email_tool.email_service
        )
        
        # Execute
        from src.workflows.base import WorkflowContext
        context = WorkflowContext.create(
            workflow_name="morning_briefing",
            user_id=user.id,
            params=params.model_dump()
        )
        
        context.start()
        result = await workflow.execute(context)
        context.complete(result)
        
        return WorkflowResponse(
            workflow_id=context.workflow_id,
            status="completed",
            result=result,
            duration_seconds=(
                context.completed_at - context.started_at
            ).total_seconds() if context.completed_at and context.started_at else 0
        )
        
    except Exception as e:
        logger.error(f"Morning briefing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email-to-action")
async def email_to_action(
    params: EmailToActionParams,
    user: User = Depends(require_session),
    request = None
):
    """
    Process an email and convert to actions.
    
    Automatically:
    - Extracts action items → creates tasks
    - Detects meeting requests → creates events
    - Classifies email by urgency/category
    """
    try:
        email_tool = await AppState.get_email_tool(user.id, request)
        calendar_tool = await AppState.get_calendar_tool(user.id, request)
        task_tool = await AppState.get_task_tool(user.id, request)
        
        # Check if AI analyzer is available
        ai_analyzer = getattr(email_tool, 'email_ai_analyzer', None)
        if not ai_analyzer:
            raise HTTPException(
                status_code=400,
                detail="Email AI analyzer not available. This workflow requires AI features."
            )
        
        workflow = EmailToActionWorkflow(
            email_service=email_tool.email_service,
            calendar_service=calendar_tool.calendar_service,
            task_service=task_tool.task_service,
            email_ai_analyzer=ai_analyzer
        )
        
        from src.workflows.base import WorkflowContext
        context = WorkflowContext.create(
            workflow_name="email_to_action",
            user_id=user.id,
            params=params.model_dump()
        )
        
        context.start()
        result = await workflow.execute(context)
        context.complete(result)
        
        return WorkflowResponse(
            workflow_id=context.workflow_id,
            status="completed",
            result=result,
            duration_seconds=(
                context.completed_at - context.started_at
            ).total_seconds() if context.completed_at and context.started_at else 0
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Email to action failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weekly-planning")
async def weekly_planning(
    params: WeeklyPlanningParams = Depends(),
    user: User = Depends(require_session),
    request = None
):
    """
    Generate weekly planning overview.
    
    Provides:
    - This week's calendar with daily breakdown
    - Tasks due this week by priority
    - Last week's productivity stats (optional)
    - Workload distribution analysis
    - AI recommendations
    """
    try:
        calendar_tool = await AppState.get_calendar_tool(user.id, request)
        task_tool = await AppState.get_task_tool(user.id, request)
        
        workflow = WeeklyPlanningWorkflow(
            calendar_service=calendar_tool.calendar_service,
            task_service=task_tool.task_service
        )
        
        from src.workflows.base import WorkflowContext
        context = WorkflowContext.create(
            workflow_name="weekly_planning",
            user_id=user.id,
            params=params.model_dump()
        )
        
        context.start()
        result = await workflow.execute(context)
        context.complete(result)
        
        return WorkflowResponse(
            workflow_id=context.workflow_id,
            status="completed",
            result=result,
            duration_seconds=(
                context.completed_at - context.started_at
            ).total_seconds() if context.completed_at and context.started_at else 0
        )
        
    except Exception as e:
        logger.error(f"Weekly planning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/end-of-day")
async def end_of_day_review(
    include_email_stats: bool = True,
    user: User = Depends(require_session),
    request = None
):
    """
    Generate end-of-day review.
    
    Provides:
    - Today's accomplishments
    - Tasks completed
    - Productivity score
    - Tomorrow's preview
    - Personalized insights
    """
    try:
        calendar_tool = await AppState.get_calendar_tool(user.id, request)
        task_tool = await AppState.get_task_tool(user.id, request)
        email_service = None
        
        if include_email_stats:
            try:
                email_tool = await AppState.get_email_tool(user.id, request)
                email_service = email_tool.email_service
            except:
                pass  # Email stats are optional
        
        workflow = EndOfDayReviewWorkflow(
            calendar_service=calendar_tool.calendar_service,
            task_service=task_tool.task_service,
            email_service=email_service
        )
        
        from src.workflows.base import WorkflowContext
        context = WorkflowContext.create(
            workflow_name="end_of_day_review",
            user_id=user.id,
            params={"include_email_stats": include_email_stats}
        )
        
        context.start()
        result = await workflow.execute(context)
        context.complete(result)
        
        return WorkflowResponse(
            workflow_id=context.workflow_id,
            status="completed",
            result=result,
            duration_seconds=(
                context.completed_at - context.started_at
            ).total_seconds() if context.completed_at and context.started_at else 0
        )
        
    except Exception as e:
        logger.error(f"End of day review failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-emails")
async def batch_process_emails(
    params: BatchEmailParams,
    user: User = Depends(require_session),
    request = None
):
    """
    Process multiple emails in batch.
    
    Can process:
    - Specific email IDs
    - Unread emails (default)
    - Custom Gmail query
    """
    try:
        email_tool = await AppState.get_email_tool(user.id, request)
        calendar_tool = await AppState.get_calendar_tool(user.id, request)
        task_tool = await AppState.get_task_tool(user.id, request)
        
        ai_analyzer = getattr(email_tool, 'email_ai_analyzer', None)
        if not ai_analyzer:
            raise HTTPException(
                status_code=400,
                detail="Email AI analyzer not available"
            )
        
        workflow = BatchEmailProcessorWorkflow(
            email_service=email_tool.email_service,
            calendar_service=calendar_tool.calendar_service,
            task_service=task_tool.task_service,
            email_ai_analyzer=ai_analyzer
        )
        
        from src.workflows.base import WorkflowContext
        context = WorkflowContext.create(
            workflow_name="batch_email_processor",
            user_id=user.id,
            params=params.model_dump()
        )
        
        context.start()
        result = await workflow.execute(context)
        context.complete(result)
        
        return WorkflowResponse(
            workflow_id=context.workflow_id,
            status="completed",
            result=result,
            duration_seconds=(
                context.completed_at - context.started_at
            ).total_seconds() if context.completed_at and context.started_at else 0
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch email processing failed: {e}")
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
