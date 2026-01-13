"""
Workflow Event System for Agent Step-by-Step Streaming

This module provides structured events for streaming agent reasoning and actions
to the frontend in real-time, creating an engaging user experience.

Events include:
- Reasoning steps (analyzing query, selecting tools)
- Tool execution (calling calendar, checking conflicts)
- Results and actions (scheduling meeting, creating task)
"""
from enum import Enum
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime
from dataclasses import dataclass, field, asdict
from collections import deque
import inspect
import json

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_EVENT_HISTORY = 1000  # Prevent unbounded memory growth
ERROR_TYPE_MAPPING = {
    'tool': 'TOOL_CALL_ERROR',
    'action': 'ACTION_ERROR',
    'workflow': 'WORKFLOW_ERROR',
}


class WorkflowEventType(Enum):
    """Types of workflow events that can be emitted"""
    
    # Reasoning events
    REASONING_START = "reasoning_start"
    REASONING_STEP = "reasoning_step"
    REASONING_COMPLETE = "reasoning_complete"
    
    # Tool selection events
    TOOL_SELECTION = "tool_selection"
    TOOL_SELECTED = "tool_selected"
    
    # Tool execution events
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_PROGRESS = "tool_call_progress"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    TOOL_CALL_ERROR = "tool_call_error"
    
    # Action events
    ACTION_PLANNED = "action_planned"
    ACTION_EXECUTING = "action_executing"
    ACTION_COMPLETE = "action_complete"
    ACTION_ERROR = "action_error"
    
    # Validation events
    VALIDATION_START = "validation_start"
    VALIDATION_CHECK = "validation_check"
    VALIDATION_COMPLETE = "validation_complete"
    
    # Domain selection events (NEW)
    DOMAIN_SELECTED = "domain_selected"
    
    # Cache events (NEW)
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    
    # Memory events (NEW)
    MEMORY_QUERY = "memory_query"
    MEMORY_RESULT = "memory_result"
    
    # Parallel execution events (NEW)
    PARALLEL_START = "parallel_start"
    PARALLEL_COMPLETE = "parallel_complete"
    
    # Final result
    CONTENT_CHUNK = "content_chunk"
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_ERROR = "workflow_error"

    # Multi-Agent Supervisor events (NEW)
    SUPERVISOR_PLANNING_START = "supervisor_planning_start"
    SUPERVISOR_PLAN_CREATED = "supervisor_plan_created"
    SUPERVISOR_ROUTING = "supervisor_routing"
    SUPERVISOR_ROUTING_COMPLETE = "supervisor_routing_complete"


@dataclass
class WorkflowEvent:
    """
    Structured event representing a single step in the agent's workflow
    
    Attributes:
        type: Type of event (reasoning, tool_call, action, etc.)
        message: Human-readable description of what's happening
        data: Optional structured data (tool name, parameters, results, etc.)
        timestamp: When the event occurred
        metadata: Additional context (confidence, duration, etc.)
    """
    type: WorkflowEventType
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization"""
        return {
            'type': self.type.value,
            'message': self.message,
            'data': self.data,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'metadata': self.metadata
        }
    
    def to_json(self) -> str:
        """Convert event to JSON string"""
        return json.dumps(self.to_dict())


@dataclass
class EmitterStats:
    """Statistics for event emission tracking"""
    total_emitted: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    listener_errors: int = 0
    avg_emit_time_ms: float = 0.0
    _total_emit_time_ms: float = 0.0  # Internal tracking


class WorkflowEventEmitter:
    """
    Event emitter for streaming agent workflow steps
    
    This class allows the agent and orchestrator to emit events at each step,
    which can be captured and streamed to the frontend in real-time.
    
    Example:
        emitter = WorkflowEventEmitter()
        
        # Subscribe to events
        async def handle_event(event: WorkflowEvent):
            await send_to_frontend(event.to_json())
        
        emitter.on_event(handle_event)
        
        # Emit events during workflow
        await emitter.emit_reasoning("Analyzing query to determine which tool to use...")
        await emitter.emit_tool_selected("calendar_tool", {"reason": "User wants to schedule meeting"})
        await emitter.emit_tool_progress("Checking for conflicts...")
    """
    
    def __init__(self, max_history: int = MAX_EVENT_HISTORY):
        """
        Initialize workflow event emitter
        
        Args:
            max_history: Maximum number of events to keep in history (prevents memory leak)
        """
        self.listeners: List[Callable] = []
        self.event_history: deque = deque(maxlen=max_history)
        self.enabled: bool = True
        self._stats = EmitterStats()
    
    def on_event(self, callback: Callable):
        """
        Subscribe to workflow events
        
        Args:
            callback: Async function that receives WorkflowEvent objects
        """
        self.listeners.append(callback)
    
    def remove_listener(self, callback: Callable):
        """Remove a previously added event listener"""
        if callback in self.listeners:
            self.listeners.remove(callback)
    
    def clear_listeners(self):
        """Remove all event listeners"""
        self.listeners.clear()
    
    def enable(self):
        """Enable event emission"""
        self.enabled = True
    
    def disable(self):
        """Disable event emission (for non-streaming queries)"""
        self.enabled = False
    
    async def emit(self, event: WorkflowEvent):
        """
        Emit a workflow event to all subscribers
        
        Args:
            event: WorkflowEvent to emit
        """
        if not self.enabled:
            return
        
        start_time = datetime.now()
        
        # Store in history (deque handles max size automatically)
        self.event_history.append(event)
        
        # Update stats
        self._stats.total_emitted += 1
        event_type = event.type.value
        self._stats.by_type[event_type] = self._stats.by_type.get(event_type, 0) + 1
        
        # Notify all listeners
        for listener in self.listeners:
            try:
                if callable(listener):
                    # Support both sync and async listeners
                    if inspect.iscoroutinefunction(listener):
                        # Async listener - await it
                        await listener(event)
                    else:
                        # Sync listener - call it directly
                        result = listener(event)
                        # If it returns a coroutine, await it
                        if hasattr(result, '__await__'):
                            await result
            except Exception as e:
                # Don't let listener errors break the workflow
                self._stats.listener_errors += 1
                logger.warning(f"Workflow event listener error: {e}")
        
        # Update timing stats
        emit_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        self._stats._total_emit_time_ms += emit_time_ms
        self._stats.avg_emit_time_ms = (
            self._stats._total_emit_time_ms / self._stats.total_emitted
        )
    
    # =========================================================================
    # Convenience methods for emitting specific event types
    # =========================================================================
    
    async def emit_reasoning_start(self, message: str, **kwargs):
        """Emit reasoning start event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.REASONING_START,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_reasoning_step(self, message: str, **kwargs):
        """Emit reasoning step event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.REASONING_STEP,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_tool_selection(self, message: str, **kwargs):
        """Emit tool selection analysis event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.TOOL_SELECTION,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_tool_selected(self, tool_name: str, reason: str = "", **kwargs):
        """Emit tool selected event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.TOOL_SELECTED,
            message=f"Selected {tool_name}" + (f": {reason}" if reason else ""),
            data={'tool': tool_name, 'reason': reason, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_tool_call_start(self, tool_name: str, action: str = "", **kwargs):
        """Emit tool call start event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.TOOL_CALL_START,
            message=f"Calling {tool_name}" + (f" ({action})" if action else ""),
            data={'tool': tool_name, 'action': action, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_tool_progress(self, message: str, **kwargs):
        """Emit tool execution progress event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.TOOL_CALL_PROGRESS,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_tool_complete(self, tool_name: str, result_summary: str = "", **kwargs):
        """Emit tool call complete event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.TOOL_CALL_COMPLETE,
            message=f"Completed {tool_name}" + (f": {result_summary}" if result_summary else ""),
            data={'tool': tool_name, 'result_summary': result_summary, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_validation_start(self, message: str, **kwargs):
        """Emit validation start event (e.g., checking conflicts)"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.VALIDATION_START,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_validation_check(self, check_type: str, result: str, **kwargs):
        """Emit validation check event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.VALIDATION_CHECK,
            message=f"{check_type}: {result}",
            data={'check_type': check_type, 'result': result, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_action_planned(self, action: str, **kwargs):
        """Emit action planned event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.ACTION_PLANNED,
            message=f"Planning to {action}",
            data={'action': action, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_action_executing(self, action: str, **kwargs):
        """Emit action executing event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.ACTION_EXECUTING,
            message=f"Executing: {action}",
            data={'action': action, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_action_complete(self, action: str, result: str = "", **kwargs):
        """Emit action complete event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.ACTION_COMPLETE,
            message=f"Completed: {action}" + (f" - {result}" if result else ""),
            data={'action': action, 'result': result, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_domain_selected(self, domain: str, reason: str = "", **kwargs):
        """Emit domain selected event (email, calendar, tasks)"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.DOMAIN_SELECTED,
            message=f"Selected domain: {domain}" + (f" ({reason})" if reason else ""),
            data={'domain': domain, 'reason': reason, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_cache_hit(self, cache_type: str, key: str = "", **kwargs):
        """Emit cache hit event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.CACHE_HIT,
            message=f"Cache hit: {cache_type}",
            data={'cache_type': cache_type, 'key': key, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_parallel_start(self, task_count: int, **kwargs):
        """Emit parallel execution start event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.PARALLEL_START,
            message=f"Starting {task_count} parallel tasks",
            data={'task_count': task_count, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_parallel_complete(self, completed: int, total: int, **kwargs):
        """Emit parallel execution complete event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.PARALLEL_COMPLETE,
            message=f"Completed {completed}/{total} parallel tasks",
            data={'completed': completed, 'total': total, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_workflow_complete(self, message: str, **kwargs):
        """Emit workflow complete event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.WORKFLOW_COMPLETE,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_content_chunk(self, chunk: str, **kwargs):
        """Emit a chunk of content (for text streaming)"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.CONTENT_CHUNK,
            message=chunk,
            data={'chunk': chunk, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_error(self, error_type: str, message: str, **kwargs):
        """Emit error event"""
        # Use constant mapping instead of inline dict
        event_type_name = ERROR_TYPE_MAPPING.get(error_type, 'WORKFLOW_ERROR')
        event_type = WorkflowEventType[event_type_name]
        
        await self.emit(WorkflowEvent(
            type=event_type,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    # =========================================================================
    # Supervisor convenience methods
    # =========================================================================

    async def emit_supervisor_planning_start(self, message: str, **kwargs):
        """Emit supervisor planning start event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.SUPERVISOR_PLANNING_START,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))

    async def emit_supervisor_plan_created(self, plan_steps: list, **kwargs):
        """Emit supervisor plan created event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.SUPERVISOR_PLAN_CREATED,
            message="Created execution plan",
            data={'plan': plan_steps, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))

    async def emit_supervisor_routing(self, message: str, **kwargs):
        """Emit supervisor routing decision event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.SUPERVISOR_ROUTING,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))

    async def emit_supervisor_routing_complete(self, agent_name: str, reason: str = "", **kwargs):
        """Emit supervisor routing complete event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.SUPERVISOR_ROUTING_COMPLETE,
            message=f"Routing to {agent_name.upper()}" + (f": {reason}" if reason else ""),
            data={'agent': agent_name, 'reason': reason, **(kwargs.get('data') or {})},
            metadata=kwargs.get('metadata')
        ))
    
    # =========================================================================
    # History and stats methods
    # =========================================================================
    
    def get_event_history(self) -> List[Dict[str, Any]]:
        """Get all emitted events as dictionaries"""
        return [event.to_dict() for event in self.event_history]
    
    def clear_history(self):
        """Clear event history"""
        self.event_history.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get emitter statistics"""
        return {
            'total_emitted': self._stats.total_emitted,
            'by_type': dict(self._stats.by_type),
            'listener_errors': self._stats.listener_errors,
            'avg_emit_time_ms': round(self._stats.avg_emit_time_ms, 2),
            'listeners_count': len(self.listeners),
            'history_size': len(self.event_history),
            'max_history': self.event_history.maxlen,
        }
    
    def reset_stats(self):
        """Reset emitter statistics"""
        self._stats = EmitterStats()


def create_workflow_emitter(max_history: int = MAX_EVENT_HISTORY) -> WorkflowEventEmitter:
    """
    Create a new workflow event emitter instance
    
    Args:
        max_history: Maximum events to keep in history
        
    Returns:
        WorkflowEventEmitter instance
    """
    return WorkflowEventEmitter(max_history=max_history)
