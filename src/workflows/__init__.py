"""
Workflows Package

Automated productivity workflows that combine multiple tools.

Architecture (v2.0):
- base/: Core abstractions (Workflow, WorkflowContext, WorkflowStep)
- engine/: Execution infrastructure (WorkflowExecutor, StateManager, EventEmitter)
- definitions/: Workflow implementations

Example usage:
    from src.workflows.definitions import MorningBriefingWorkflow
    from src.workflows.engine import WorkflowExecutor
    
    # Create workflow
    workflow = MorningBriefingWorkflow(
        calendar_service=calendar,
        task_service=tasks,
        email_service=email
    )
    
    # Execute via executor
    executor = WorkflowExecutor()
    result = await executor.run(
        workflow_name="morning_briefing",
        user_id=user.id,
        params={"max_emails": 10}
    )
"""

# Base classes
from .base import (
    Workflow,
    WorkflowContext,
    WorkflowStatus,
    WorkflowStep,
    StepBasedWorkflow
)

# Engine
from .engine import (
    WorkflowExecutor,
    StateManager,
    EventEmitter
)

# Workflow definitions
from .definitions import (
    MorningBriefingWorkflow,
    EmailToActionWorkflow,
    BatchEmailProcessorWorkflow,
    WeeklyPlanningWorkflow,
    EndOfDayReviewWorkflow
)

__all__ = [
    # Base
    'Workflow',
    'WorkflowContext',
    'WorkflowStatus',
    'WorkflowStep',
    'StepBasedWorkflow',
    # Engine
    'WorkflowExecutor',
    'StateManager',
    'EventEmitter',
    # Definitions
    'MorningBriefingWorkflow',
    'EmailToActionWorkflow',
    'BatchEmailProcessorWorkflow',
    'WeeklyPlanningWorkflow',
    'EndOfDayReviewWorkflow',
]

