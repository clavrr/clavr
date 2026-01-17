import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime

from ..celery_app import celery_app
from ..base_task import IdempotentTask
from src.utils.logger import setup_logger
from src.utils.config import load_config
from api.dependencies import AppState
from src.workflows.base import WorkflowContext
from src.workflows.definitions import (
    MorningBriefingWorkflow,
    EmailToActionWorkflow,
    WeeklyPlanningWorkflow,
    EndOfDayReviewWorkflow,
    BatchEmailProcessorWorkflow
)

logger = setup_logger(__name__)

WORKFLOW_MAP = {
    "morning_briefing": MorningBriefingWorkflow,
    "email_to_action": EmailToActionWorkflow,
    "weekly_planning": WeeklyPlanningWorkflow,
    "end_of_day_review": EndOfDayReviewWorkflow,
    "batch_email_processor": BatchEmailProcessorWorkflow
}

@celery_app.task(base=IdempotentTask, bind=True, name='src.workers.tasks.workflow_tasks.run_workflow')
def run_workflow(self, user_id: int, workflow_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Background task to execute a workflow.
    """
    logger.info(f"[WORKFLOW] Starting background workflow {workflow_name} for user {user_id}")
    
    async def _execute():
        # 1. Get workflow class
        workflow_cls = WORKFLOW_MAP.get(workflow_name)
        if not workflow_cls:
            return {"status": "failed", "error": f"Unknown workflow: {workflow_name}"}
            
        # 2. Initialize tools/services (without requiring a real Request)
        # These AppState methods handle credential retrieval from DB internally
        email_tool = await AppState.get_email_tool(user_id)
        calendar_tool = await AppState.get_calendar_tool(user_id)
        task_tool = await AppState.get_task_tool(user_id)
        
        # 3. Instantiate specific workflow via Factory
        from src.workflows.factory import WorkflowFactory
        try:
            workflow = WorkflowFactory.create_workflow(
                workflow_name=workflow_name,
                email_tool=email_tool,
                calendar_tool=calendar_tool,
                task_tool=task_tool,
                params=params
            )
            
            if not workflow:
                return {"status": "failed", "error": f"Unknown workflow or initialization failed: {workflow_name}"}
                
        except Exception as e:
            logger.error(f"Workflow {workflow_name} factory creation failed: {e}")
            return {"status": "failed", "error": f"Initialization failed: {str(e)}"}

        # 4. Create Context and Execute
        context = WorkflowContext.create(
            workflow_name=workflow_name,
            user_id=user_id,
            params=params
        )
        
        context.start()
        try:
            result = await workflow.execute(context)
            context.complete(result)
            return {
                "status": "completed",
                "workflow_id": context.workflow_id,
                "result": result,
                "duration": (context.completed_at - context.started_at).total_seconds() if context.completed_at else 0
            }
        except Exception as e:
            logger.error(f"Workflow {workflow_name} execution failed: {e}")
            return {"status": "failed", "error": str(e), "workflow_id": context.workflow_id}

    return asyncio.run(_execute())
