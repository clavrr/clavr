from typing import Dict, Any, Optional, Type
from src.utils.logger import setup_logger
from src.workflows.definitions import (
    MorningBriefingWorkflow,
    EmailToActionWorkflow,
    WeeklyPlanningWorkflow,
    EndOfDayReviewWorkflow,
    BatchEmailProcessorWorkflow
)
# Import tools/services interfaces if needed for type hinting, 
# but we receive them as objects

logger = setup_logger(__name__)

class WorkflowFactory:
    """
    Factory for instantiating workflows with their required dependencies.
    """
    
    @staticmethod
    def create_workflow(
        workflow_name: str,
        email_tool: Any,
        calendar_tool: Any,
        task_tool: Any,
        params: Dict[str, Any]
    ):
        """
        Create and configure a workflow instance.
        """
        try:
            if workflow_name == "morning_briefing":
                return MorningBriefingWorkflow(
                    calendar_service=calendar_tool.calendar_service,
                    task_service=task_tool.task_service,
                    email_service=email_tool.email_service
                )
                
            elif workflow_name == "email_to_action":
                ai_analyzer = getattr(email_tool, 'email_ai_analyzer', None)
                return EmailToActionWorkflow(
                    email_service=email_tool.email_service,
                    calendar_service=calendar_tool.calendar_service,
                    task_service=task_tool.task_service,
                    email_ai_analyzer=ai_analyzer
                )
                
            elif workflow_name == "batch_email_processor":
                ai_analyzer = getattr(email_tool, 'email_ai_analyzer', None)
                return BatchEmailProcessorWorkflow(
                    email_service=email_tool.email_service,
                    calendar_service=calendar_tool.calendar_service,
                    task_service=task_tool.task_service,
                    email_ai_analyzer=ai_analyzer
                )
                
            elif workflow_name == "weekly_planning":
                return WeeklyPlanningWorkflow(
                    calendar_service=calendar_tool.calendar_service,
                    task_service=task_tool.task_service
                )
                
            elif workflow_name == "end_of_day_review":
                email_service = None
                if params.get("include_email_stats", True):
                    email_service = email_tool.email_service
                
                return EndOfDayReviewWorkflow(
                    calendar_service=calendar_tool.calendar_service,
                    task_service=task_tool.task_service,
                    email_service=email_service
                )
            
            else:
                logger.error(f"Unknown workflow type: {workflow_name}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to instantiate workflow {workflow_name}: {e}")
            raise
