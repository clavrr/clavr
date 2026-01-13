"""
Events Module - Workflow event system for streaming

Provides:
- WorkflowEventEmitter: Emits structured events for streaming agent reasoning
- WorkflowEventType: Enum of event types
- WorkflowEvent: Structured event dataclass
- EmitterStats: Statistics for event emission tracking
- create_workflow_emitter: Factory function for creating emitters
"""

from .workflow_events import (
    WorkflowEventEmitter,
    WorkflowEventType,
    WorkflowEvent,
    EmitterStats,
    create_workflow_emitter,
    MAX_EVENT_HISTORY,
)

__all__ = [
    'WorkflowEventEmitter',
    'WorkflowEventType',
    'WorkflowEvent',
    'EmitterStats',
    'create_workflow_emitter',
    'MAX_EVENT_HISTORY',
]
