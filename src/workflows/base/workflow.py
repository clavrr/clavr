"""
Base Workflow Module

Provides abstract base classes for workflow definitions:
- WorkflowContext: Execution state and parameters
- WorkflowStep: Individual workflow step
- Workflow: Base class for workflow definitions
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
from enum import Enum
import uuid


class WorkflowStatus(str, Enum):
    """Workflow execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class WorkflowContext:
    """
    Execution context for workflows.
    
    Holds state, parameters, and results throughout workflow execution.
    Can be persisted and resumed.
    """
    workflow_id: str
    workflow_name: str
    user_id: int
    status: WorkflowStatus = WorkflowStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Input parameters
    params: Dict[str, Any] = field(default_factory=dict)
    
    # Execution state (intermediate results)
    state: Dict[str, Any] = field(default_factory=dict)
    
    # Final result
    result: Optional[Dict[str, Any]] = None
    
    # Error information
    error: Optional[str] = None
    error_step: Optional[str] = None
    
    # Step tracking
    current_step: int = 0
    total_steps: int = 0
    step_history: List[Dict[str, Any]] = field(default_factory=list)
    
    @classmethod
    def create(
        cls,
        workflow_name: str,
        user_id: int,
        params: Optional[Dict[str, Any]] = None
    ) -> 'WorkflowContext':
        """Create a new workflow context"""
        return cls(
            workflow_id=str(uuid.uuid4()),
            workflow_name=workflow_name,
            user_id=user_id,
            params=params or {}
        )
    
    def start(self):
        """Mark workflow as started"""
        self.status = WorkflowStatus.RUNNING
        self.started_at = datetime.utcnow()
    
    def complete(self, result: Dict[str, Any]):
        """Mark workflow as completed"""
        self.status = WorkflowStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.result = result
    
    def fail(self, error: str, step: Optional[str] = None):
        """Mark workflow as failed"""
        self.status = WorkflowStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.error = error
        self.error_step = step
    
    def record_step(self, step_name: str, result: Any, duration_ms: int):
        """Record a completed step"""
        self.step_history.append({
            "step": step_name,
            "result_summary": str(result)[:200] if result else None,
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat()
        })
        self.current_step += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "user_id": self.user_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "params": self.params,
            "state": self.state,
            "result": self.result,
            "error": self.error,
            "error_step": self.error_step,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "step_history": self.step_history
        }


class Workflow(ABC):
    """
    Abstract base class for workflow definitions.
    
    Subclasses implement the execute() method with workflow logic.
    Supports lifecycle hooks for start, complete, and error handling.
    """
    
    # Workflow metadata (override in subclass)
    name: str = "base_workflow"
    description: str = "Base workflow"
    version: str = "1.0.0"
    
    @abstractmethod
    async def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """
        Execute the workflow.
        
        Args:
            context: Workflow execution context
            
        Returns:
            Result dictionary
        """
        pass
    
    async def on_start(self, context: WorkflowContext):
        """
        Called before workflow execution starts.
        Override for initialization logic.
        """
        pass
    
    async def on_complete(self, context: WorkflowContext, result: Dict[str, Any]):
        """
        Called after workflow completes successfully.
        Override for cleanup or notification logic.
        """
        pass
    
    async def on_error(self, context: WorkflowContext, error: Exception):
        """
        Called when workflow fails.
        Override for error handling or recovery logic.
        """
        pass
    
    async def on_cancel(self, context: WorkflowContext):
        """
        Called when workflow is cancelled.
        Override for cleanup logic.
        """
        pass
    
    def validate_params(self, params: Dict[str, Any]) -> bool:
        """
        Validate input parameters.
        Override to add parameter validation.
        
        Returns:
            True if parameters are valid
        """
        return True
    
    def get_required_params(self) -> List[str]:
        """
        Get list of required parameter names.
        Override to specify required parameters.
        """
        return []
    
    def get_param_schema(self) -> Dict[str, Any]:
        """
        Get JSON schema for parameters.
        Override to provide parameter documentation.
        """
        return {}


class WorkflowStep:
    """
    Represents a single step in a workflow.
    
    Used for building step-based workflows with clear progression.
    """
    
    def __init__(
        self,
        name: str,
        func: Callable,
        description: str = "",
        required: bool = True,
        retry_count: int = 0
    ):
        """
        Initialize a workflow step.
        
        Args:
            name: Step identifier
            func: Async function to execute
            description: Human-readable description
            required: If False, errors won't fail the workflow
            retry_count: Number of retries on failure
        """
        self.name = name
        self.func = func
        self.description = description
        self.required = required
        self.retry_count = retry_count
    
    async def execute(self, context: WorkflowContext) -> Any:
        """Execute the step function"""
        return await self.func(context)


class StepBasedWorkflow(Workflow):
    """
    Workflow implementation that executes a sequence of steps.
    
    Provides automatic step tracking and error handling.
    """
    
    def __init__(self):
        self.steps: List[WorkflowStep] = []
    
    def add_step(
        self,
        name: str,
        func: Callable,
        description: str = "",
        required: bool = True
    ):
        """Add a step to the workflow"""
        self.steps.append(WorkflowStep(
            name=name,
            func=func,
            description=description,
            required=required
        ))
    
    async def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute all steps in sequence"""
        context.total_steps = len(self.steps)
        results = {}
        
        for step in self.steps:
            start_time = datetime.utcnow()
            
            try:
                result = await step.execute(context)
                results[step.name] = result
                context.state[step.name] = result
                
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                context.record_step(step.name, result, duration_ms)
                
            except Exception as e:
                if step.required:
                    context.fail(str(e), step.name)
                    raise
                else:
                    # Non-required step failed, continue
                    results[step.name] = {"error": str(e)}
                    context.record_step(step.name, {"error": str(e)}, 0)
        
        return results
