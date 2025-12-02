"""
Base classes, enums, and dataclasses for orchestration

This module contains the foundational types used across all orchestration components:
- ExecutionStatus: Enum for tracking execution state throughout the pipeline
- ToolDependency: Enum for defining relationships between execution steps
- ExecutionStep: Represents a single step in multi-step orchestration (supports EMAIL, TASK, CALENDAR, NOTION domains)
- OrchestrationResult: Final result of orchestrated execution
- ContextEnrichment: Cross-domain context enrichment metadata

Integration Points:
- Used by: Orchestrator, ExecutionPlanner, DomainValidator, RoutingAnalytics, OrchestratorRole
- Provides: Type-safe data structures for all orchestration operations
- Enables: Consistent state tracking and error handling across components
- Supports: Domain-aware execution with Notion integration
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class ExecutionStatus(Enum):
    """Execution status for tracking step completion"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    BLOCKED = "blocked"
    
    @property
    def is_terminal(self) -> bool:
        """Check if status is terminal (execution has ended)"""
        return self in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.BLOCKED)
    
    @property
    def is_active(self) -> bool:
        """Check if status indicates active execution"""
        return self in (ExecutionStatus.IN_PROGRESS, ExecutionStatus.RETRYING)
    
    @property
    def is_error(self) -> bool:
        """Check if status indicates an error state"""
        return self in (ExecutionStatus.FAILED, ExecutionStatus.BLOCKED)
    
    def __str__(self) -> str:
        """String representation"""
        return self.value


class ToolDependency(Enum):
    """Tool dependency types for execution planning"""
    REQUIRES_DATA = "requires_data"
    PROVIDES_CONTEXT = "provides_context"
    ENRICHES_RESULTS = "enriches_results"
    INDEPENDENT = "independent"
    
    @property
    def is_dependent(self) -> bool:
        """Check if this dependency type requires previous steps"""
        return self != ToolDependency.INDEPENDENT
    
    @property
    def is_sequential(self) -> bool:
        """Check if this dependency type enforces strict ordering"""
        return self == ToolDependency.REQUIRES_DATA
    
    def __str__(self) -> str:
        """String representation"""
        return self.value


@dataclass
class ExecutionStep:
    """
    Represents a single execution step in the reasoning chain
    
    Supports domains: EMAIL, TASK, CALENDAR, NOTION, GENERAL
    
    Attributes:
        id: Unique identifier for the step
        tool_name: Name of the tool to execute (e.g., 'email', 'calendar', 'notion')
        action: Action to perform (e.g., 'search', 'create', 'update')
        query: Natural language query for this step
        intent: Intent classification (e.g., 'email', 'task', 'calendar', 'notion')
        domain: Optional domain classification (e.g., 'email', 'task', 'calendar', 'notion')
                If not provided, inferred from tool_name
        dependencies: List of step IDs this step depends on
        dependency_type: Type of dependency relationship
        context_requirements: Additional context needed for execution
        status: Current execution status
        result: Execution result (if completed)
        error: Error message (if failed)
        retry_count: Number of retry attempts
        execution_time: Time taken to execute (in seconds)
        created_at: Timestamp when step was created
    """
    id: str
    tool_name: str
    action: str
    query: str
    intent: str
    domain: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    dependency_type: ToolDependency = ToolDependency.INDEPENDENT
    context_requirements: Dict[str, Any] = field(default_factory=dict)
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    execution_time: Optional[float] = None
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Validate and initialize step"""
        if self.created_at is None:
            self.created_at = datetime.now()
        
        # Validate required fields
        if not self.id or not self.tool_name or not self.query:
            raise ValueError("ExecutionStep requires id, tool_name, and query")
        
        # Auto-set domain from tool_name if not provided
        if self.domain is None:
            self.domain = self._infer_domain_from_tool_name()
        
        # Auto-set dependency type based on dependencies
        if not self.dependency_type or self.dependency_type == ToolDependency.INDEPENDENT:
            if self.dependencies:
                self.dependency_type = ToolDependency.REQUIRES_DATA
    
    def _infer_domain_from_tool_name(self) -> str:
        """Infer domain from tool_name"""
        tool_lower = self.tool_name.lower()
        
        # Map tool names to domains
        if 'email' in tool_lower:
            return 'email'
        elif 'task' in tool_lower or 'todo' in tool_lower:
            return 'task'
        elif 'calendar' in tool_lower or 'event' in tool_lower or 'meeting' in tool_lower:
            return 'calendar'
        elif 'notion' in tool_lower:
            return 'notion'
        else:
            return 'general'
    
    def is_ready_to_execute(self) -> bool:
        """Check if step is ready to execute"""
        return self.status == ExecutionStatus.PENDING
    
    def is_waiting_for_dependencies(self) -> bool:
        """Check if step is blocked waiting for dependencies"""
        return self.status == ExecutionStatus.BLOCKED and self.dependencies
    
    def mark_in_progress(self) -> None:
        """Mark step as in progress"""
        self.status = ExecutionStatus.IN_PROGRESS
    
    def mark_completed(self, result: str, execution_time: float) -> None:
        """Mark step as completed with result"""
        self.status = ExecutionStatus.COMPLETED
        self.result = result
        self.execution_time = execution_time
    
    def mark_failed(self, error: str) -> None:
        """Mark step as failed with error message"""
        self.status = ExecutionStatus.FAILED
        self.error = error
    
    def mark_blocked(self, reason: str) -> None:
        """Mark step as blocked"""
        self.status = ExecutionStatus.BLOCKED
        self.error = reason
    
    def can_retry(self, max_retries: int = 3) -> bool:
        """Check if step can be retried"""
        return self.retry_count < max_retries and self.status == ExecutionStatus.FAILED
    
    def increment_retry(self) -> None:
        """Increment retry count and reset status"""
        self.retry_count += 1
        if self.retry_count > 0:
            self.status = ExecutionStatus.RETRYING
        self.error = None
        self.result = None
    
    def get_domain(self) -> str:
        """Get the domain for this step (inferred or explicit)"""
        return self.domain or self._infer_domain_from_tool_name()
    
    def is_domain(self, domain: str) -> bool:
        """Check if this step belongs to a specific domain"""
        return self.get_domain().lower() == domain.lower()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary for serialization"""
        return {
            'id': self.id,
            'tool_name': self.tool_name,
            'action': self.action,
            'query': self.query,
            'intent': self.intent,
            'domain': self.get_domain(),
            'dependencies': self.dependencies,
            'dependency_type': self.dependency_type.value,
            'status': self.status.value,
            'result': self.result,
            'error': self.error,
            'retry_count': self.retry_count,
            'execution_time': self.execution_time,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExecutionStep':
        """Create ExecutionStep from dictionary"""
        data = data.copy()
        
        # Convert string enums to enums
        if 'dependency_type' in data and isinstance(data['dependency_type'], str):
            data['dependency_type'] = ToolDependency(data['dependency_type'])
        
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = ExecutionStatus(data['status'])
        
        # Convert ISO format datetime back to datetime
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        
        return cls(**data)
    
    def __repr__(self) -> str:
        """String representation for debugging"""
        domain_str = f", domain={self.get_domain()}" if self.domain else ""
        return (
            f"ExecutionStep(id={self.id}, tool={self.tool_name}{domain_str}, "
            f"status={self.status.value}, retries={self.retry_count})"
        )


@dataclass
class OrchestrationResult:
    """Result of orchestrated multi-step execution"""
    success: bool
    final_result: str
    steps_executed: int
    total_steps: int
    execution_time: float
    errors: List[str] = field(default_factory=list)
    context_used: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def has_errors(self) -> bool:
        """Check if result contains errors"""
        return len(self.errors) > 0
    
    @property
    def completion_rate(self) -> float:
        """Get completion rate as percentage"""
        if self.total_steps == 0:
            return 0.0
        return (self.steps_executed / self.total_steps) * 100.0
    
    @property
    def is_partial_success(self) -> bool:
        """Check if execution partially succeeded"""
        return self.success and self.steps_executed < self.total_steps
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization"""
        return {
            'success': self.success,
            'final_result': self.final_result,
            'steps_executed': self.steps_executed,
            'total_steps': self.total_steps,
            'execution_time': self.execution_time,
            'completion_rate': self.completion_rate,
            'errors': self.errors,
            'has_errors': self.has_errors,
            'context_used': self.context_used
        }
    
    def __str__(self) -> str:
        """String representation for logging"""
        status = "✓ Success" if self.success else "✗ Failed"
        return (
            f"{status} | Steps: {self.steps_executed}/{self.total_steps} | "
            f"Time: {self.execution_time:.2f}s | Errors: {len(self.errors)}"
        )


@dataclass
class ContextEnrichment:
    """
    Context enrichment between domains
    
    Supports cross-domain context sharing between EMAIL, TASK, CALENDAR, NOTION domains.
    Used for enriching execution context when steps span multiple domains.
    
    Example:
        Email → Notion: Create Notion page from email content
        Calendar → Task: Create task from calendar event
        Task → Email: Send email about task completion
    """
    source_domain: str
    target_domain: str
    enrichment_type: str
    enriched_context: Dict[str, Any]
    confidence: float
    
    def is_high_confidence(self, threshold: float = 0.75) -> bool:
        """Check if enrichment confidence exceeds threshold"""
        return self.confidence >= threshold
    
    def supports_domain(self, domain: str) -> bool:
        """Check if enrichment supports a specific domain"""
        return domain.lower() in [self.source_domain.lower(), self.target_domain.lower()]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'source_domain': self.source_domain,
            'target_domain': self.target_domain,
            'enrichment_type': self.enrichment_type,
            'enriched_context': self.enriched_context,
            'confidence': self.confidence
        }
    
    def __repr__(self) -> str:
        """String representation"""
        return (
            f"ContextEnrichment({self.source_domain}→{self.target_domain}, "
            f"type={self.enrichment_type}, confidence={self.confidence:.2f})"
        )


# ===== UTILITY FUNCTIONS =====

def get_execution_status(value: str) -> ExecutionStatus:
    """
    Get ExecutionStatus from string value with fallback.
    
    Args:
        value: Status value string
        
    Returns:
        ExecutionStatus enum or PENDING if invalid
    """
    try:
        return ExecutionStatus(value)
    except ValueError:
        return ExecutionStatus.PENDING


def get_tool_dependency(value: str) -> ToolDependency:
    """
    Get ToolDependency from string value with fallback.
    
    Args:
        value: Dependency value string
        
    Returns:
        ToolDependency enum or INDEPENDENT if invalid
    """
    try:
        return ToolDependency(value)
    except ValueError:
        return ToolDependency.INDEPENDENT


def create_execution_step(
    tool_name: str,
    query: str,
    intent: str,
    action: str = "search",
    step_id: Optional[str] = None,
    dependencies: Optional[List[str]] = None,
    domain: Optional[str] = None
) -> ExecutionStep:
    """
    Factory function to create ExecutionStep with sensible defaults.
    
    Args:
        tool_name: Name of the tool to execute (e.g., 'email', 'calendar', 'notion')
        query: Query string for the tool
        intent: Intent classification (email, task, calendar, notion, general)
        action: Action type (default: "search")
        step_id: Optional custom step ID (auto-generated if None)
        dependencies: Optional list of dependency step IDs
        domain: Optional domain classification (auto-inferred from tool_name if None)
        
    Returns:
        ExecutionStep with initialized fields
        
    Example:
        >>> step = create_execution_step('email', 'find unread messages', 'email')
        >>> step.id
        'email_...'
        >>> step.get_domain()
        'email'
        
        >>> step = create_execution_step('notion', 'create a page', 'notion', action='create_page')
        >>> step.get_domain()
        'notion'
    """
    import uuid
    
    if step_id is None:
        step_id = f"{tool_name}_{uuid.uuid4().hex[:8]}"
    
    if dependencies is None:
        dependencies = []
    
    return ExecutionStep(
        id=step_id,
        tool_name=tool_name.lower(),
        action=action.lower(),
        query=query,
        intent=intent.lower(),
        domain=domain.lower() if domain else None,
        dependencies=dependencies,
        dependency_type=ToolDependency.REQUIRES_DATA if dependencies else ToolDependency.INDEPENDENT
    )


def create_orchestration_result(
    success: bool,
    final_result: str,
    steps_executed: int = 0,
    total_steps: int = 0,
    execution_time: float = 0.0,
    errors: Optional[List[str]] = None
) -> OrchestrationResult:
    """
    Factory function to create OrchestrationResult with sensible defaults.
    
    Args:
        success: Whether orchestration succeeded
        final_result: Final result string
        steps_executed: Number of steps that executed
        total_steps: Total number of steps planned
        execution_time: Total execution time in seconds
        errors: Optional list of error messages
        
    Returns:
        OrchestrationResult with initialized fields
        
    Example:
        >>> result = create_orchestration_result(
        ...     success=True,
        ...     final_result="Tasks retrieved successfully",
        ...     steps_executed=1,
        ...     total_steps=1,
        ...     execution_time=0.5
        ... )
    """
    if errors is None:
        errors = []
    
    return OrchestrationResult(
        success=success,
        final_result=final_result,
        steps_executed=steps_executed,
        total_steps=total_steps,
        execution_time=execution_time,
        errors=errors
    )
