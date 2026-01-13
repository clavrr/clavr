"""
Tool Base Mixin - Shared functionality for LangChain tools

Provides common patterns like workflow event emission that can be
mixed into any BaseTool subclass.
"""
import asyncio
from typing import Optional, Any

from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class WorkflowEventMixin:
    """
    Mixin providing workflow event emission for tools.
    
    This enables tools to emit events for real-time UI updates
    during action execution.
    
    Usage:
        class MyTool(WorkflowEventMixin, BaseTool):
            def _run(self, action: str, **kwargs):
                workflow_emitter = kwargs.get('workflow_emitter')
                
                self.emit_action_event(workflow_emitter, 'executing', 'Processing...', action=action)
                # ... do work ...
                self.emit_action_event(workflow_emitter, 'complete', 'Done!', action=action)
    """
    
    def emit_action_event(
        self, 
        workflow_emitter: Optional[Any], 
        event_type: str, 
        message: str, 
        **kwargs
    ) -> None:
        """
        Emit a workflow action event (handles async safely from sync context).
        
        Args:
            workflow_emitter: The workflow emitter instance (may be None)
            event_type: Type of event ('executing', 'complete', 'error')
            message: Human-readable message
            **kwargs: Additional event data (action, result, error, etc.)
        """
        if not workflow_emitter:
            return
            
        try:
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(
                    self._emit_workflow_event_async(workflow_emitter, event_type, message, **kwargs)
                )
            except RuntimeError:
                # No running event loop - skip emission
                pass
        except Exception as e:
            logger.debug(f"Failed to emit workflow event: {e}")
    
    async def _emit_workflow_event_async(
        self, 
        workflow_emitter: Any, 
        event_type: str, 
        message: str, 
        **kwargs
    ) -> None:
        """Async helper to emit workflow events."""
        try:
            action = kwargs.get('action', 'tool_operation')
            
            if event_type == 'executing':
                await workflow_emitter.emit_action_executing(action, data=kwargs)
            elif event_type == 'complete':
                await workflow_emitter.emit_action_complete(
                    action,
                    result=kwargs.get('result', ''),
                    data=kwargs
                )
            elif event_type == 'error':
                await workflow_emitter.emit_error('action', message, data=kwargs)
        except Exception as e:
            logger.debug(f"Workflow event emission failed: {e}")
