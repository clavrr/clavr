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
from dataclasses import dataclass, asdict
import json


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
    
    # Final result
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_ERROR = "workflow_error"


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
    
    def __init__(self):
        self.listeners: List[Callable] = []
        self.event_history: List[WorkflowEvent] = []
        self.enabled: bool = True
    
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
        
        # Store in history
        self.event_history.append(event)
        
        # Notify all listeners
        for listener in self.listeners:
            try:
                if callable(listener):
                    # Support both sync and async listeners
                    import inspect
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
                import logging
                logging.warning(f"[ERROR] Workflow event listener error: {e}")
    
    # Convenience methods for emitting specific event types
    
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
    
    async def emit_workflow_complete(self, message: str, **kwargs):
        """Emit workflow complete event"""
        await self.emit(WorkflowEvent(
            type=WorkflowEventType.WORKFLOW_COMPLETE,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    async def emit_error(self, error_type: str, message: str, **kwargs):
        """Emit error event"""
        event_type = {
            'tool': WorkflowEventType.TOOL_CALL_ERROR,
            'action': WorkflowEventType.ACTION_ERROR,
            'workflow': WorkflowEventType.WORKFLOW_ERROR
        }.get(error_type, WorkflowEventType.WORKFLOW_ERROR)
        
        await self.emit(WorkflowEvent(
            type=event_type,
            message=message,
            data=kwargs.get('data'),
            metadata=kwargs.get('metadata')
        ))
    
    def get_event_history(self) -> List[Dict[str, Any]]:
        """Get all emitted events as dictionaries"""
        return [event.to_dict() for event in self.event_history]
    
    def clear_history(self):
        """Clear event history"""
        self.event_history.clear()


# Global emitter instance (can be injected into agent/orchestrator)
_global_emitter: Optional[WorkflowEventEmitter] = None


def get_workflow_emitter() -> WorkflowEventEmitter:
    """Get or create the global workflow event emitter"""
    global _global_emitter
    if _global_emitter is None:
        _global_emitter = WorkflowEventEmitter()
    return _global_emitter


def create_workflow_emitter() -> WorkflowEventEmitter:
    """Create a new workflow event emitter instance"""
    return WorkflowEventEmitter()

