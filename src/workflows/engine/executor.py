"""
Workflow Executor

Runs workflows with:
- State management
- Event emission
- Error handling
- Logging
"""
import asyncio
from typing import Dict, Any, Type, Optional, List
from datetime import datetime

from ..base.workflow import Workflow, WorkflowContext, WorkflowStatus
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class WorkflowExecutor:
    """
    Executes workflow instances with full lifecycle management.
    
    Features:
    - Async execution with timeout support
    - State persistence via StateManager
    - Event emission for monitoring
    - Comprehensive logging
    """
    
    def __init__(
        self,
        state_manager: Optional['StateManager'] = None,
        event_emitter: Optional['EventEmitter'] = None,
        default_timeout: int = 300  # 5 minutes
    ):
        """
        Initialize the workflow executor.
        
        Args:
            state_manager: Optional state persistence manager
            event_emitter: Optional event emitter for workflow events
            default_timeout: Default execution timeout in seconds
        """
        self._workflows: Dict[str, Type[Workflow]] = {}
        self._workflow_factories: Dict[str, callable] = {}
        self.state_manager = state_manager
        self.event_emitter = event_emitter
        self.default_timeout = default_timeout
        
        logger.info("[WORKFLOWS] WorkflowExecutor initialized")
    
    def register(
        self,
        workflow_class: Type[Workflow],
        factory: Optional[callable] = None
    ):
        """
        Register a workflow definition.
        
        Args:
            workflow_class: Workflow class to register
            factory: Optional factory function to create instances
                     Factory receives (user_id, **kwargs) and returns Workflow
        """
        name = workflow_class.name
        self._workflows[name] = workflow_class
        
        if factory:
            self._workflow_factories[name] = factory
        
        logger.info(f"[WORKFLOWS] Registered workflow: {name}")
    
    def get_registered_workflows(self) -> List[Dict[str, str]]:
        """Get list of registered workflow definitions"""
        return [
            {
                "name": cls.name,
                "description": cls.description,
                "version": getattr(cls, 'version', '1.0.0')
            }
            for cls in self._workflows.values()
        ]
    
    async def run(
        self,
        workflow_name: str,
        user_id: int,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        **factory_kwargs
    ) -> Dict[str, Any]:
        """
        Execute a workflow by name.
        
        Args:
            workflow_name: Name of registered workflow
            user_id: User ID for the workflow
            params: Workflow parameters
            timeout: Execution timeout in seconds
            **factory_kwargs: Additional kwargs for workflow factory
            
        Returns:
            Workflow result dictionary
            
        Raises:
            ValueError: If workflow not registered
            TimeoutError: If execution exceeds timeout
            Exception: Workflow execution errors
        """
        # Get workflow class
        workflow_class = self._workflows.get(workflow_name)
        if not workflow_class:
            raise ValueError(f"Unknown workflow: {workflow_name}")
        
        # Create workflow instance
        if workflow_name in self._workflow_factories:
            workflow = self._workflow_factories[workflow_name](
                user_id=user_id,
                **factory_kwargs
            )
        else:
            workflow = workflow_class()
        
        # Validate parameters
        required_params = workflow.get_required_params()
        params = params or {}
        
        for param in required_params:
            if param not in params:
                raise ValueError(f"Missing required parameter: {param}")
        
        if not workflow.validate_params(params):
            raise ValueError("Invalid workflow parameters")
        
        # Create context
        context = WorkflowContext.create(
            workflow_name=workflow_name,
            user_id=user_id,
            params=params
        )
        
        # Persist initial state
        if self.state_manager:
            await self.state_manager.save(context)
        
        # Emit start event
        await self._emit_event(
            f"workflow.{workflow_name}.started",
            {
                "workflow_id": context.workflow_id,
                "user_id": user_id,
                "params": params
            }
        )
        
        logger.info(
            f"[WORKFLOWS] Starting {workflow_name} "
            f"(id={context.workflow_id}, user={user_id})"
        )
        
        try:
            # Start workflow
            context.start()
            await workflow.on_start(context)
            
            # Execute with timeout
            timeout = timeout or self.default_timeout
            result = await asyncio.wait_for(
                workflow.execute(context),
                timeout=timeout
            )
            
            # Complete workflow
            context.complete(result)
            await workflow.on_complete(context, result)
            
            # Persist final state
            if self.state_manager:
                await self.state_manager.save(context)
            
            # Emit completion event
            await self._emit_event(
                f"workflow.{workflow_name}.completed",
                {
                    "workflow_id": context.workflow_id,
                    "user_id": user_id,
                    "duration_seconds": (
                        context.completed_at - context.started_at
                    ).total_seconds() if context.completed_at and context.started_at else 0,
                    "result_keys": list(result.keys()) if result else []
                }
            )
            
            logger.info(
                f"[WORKFLOWS] Completed {workflow_name} "
                f"(id={context.workflow_id})"
            )
            
            return {
                "workflow_id": context.workflow_id,
                "status": context.status.value,
                "result": result,
                "duration_seconds": (
                    context.completed_at - context.started_at
                ).total_seconds() if context.completed_at and context.started_at else 0
            }
            
        except asyncio.TimeoutError:
            context.fail(f"Workflow timed out after {timeout} seconds")
            await workflow.on_error(context, TimeoutError())
            
            if self.state_manager:
                await self.state_manager.save(context)
            
            await self._emit_event(
                f"workflow.{workflow_name}.timeout",
                {"workflow_id": context.workflow_id}
            )
            
            logger.error(
                f"[WORKFLOWS] Timeout in {workflow_name} "
                f"(id={context.workflow_id})"
            )
            raise
            
        except Exception as e:
            context.fail(str(e))
            await workflow.on_error(context, e)
            
            if self.state_manager:
                await self.state_manager.save(context)
            
            await self._emit_event(
                f"workflow.{workflow_name}.failed",
                {
                    "workflow_id": context.workflow_id,
                    "error": str(e),
                    "error_step": context.error_step
                }
            )
            
            logger.error(
                f"[WORKFLOWS] Failed {workflow_name} "
                f"(id={context.workflow_id}): {e}"
            )
            raise
    
    async def cancel(self, workflow_id: str, reason: str = "User cancelled"):
        """
        Cancel a running workflow.
        
        Args:
            workflow_id: ID of workflow to cancel
            reason: Cancellation reason
        """
        if self.state_manager:
            context = await self.state_manager.get(workflow_id)
            if context and context.status == WorkflowStatus.RUNNING:
                context.status = WorkflowStatus.CANCELLED
                context.error = reason
                context.completed_at = datetime.utcnow()
                await self.state_manager.save(context)
                
                await self._emit_event(
                    f"workflow.{context.workflow_name}.cancelled",
                    {"workflow_id": workflow_id, "reason": reason}
                )
                
                logger.info(f"[WORKFLOWS] Cancelled {workflow_id}: {reason}")
    
    async def get_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        Get workflow execution status.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            Status dictionary or None if not found
        """
        if self.state_manager:
            context = await self.state_manager.get(workflow_id)
            if context:
                return context.to_dict()
        return None
    
    async def _emit_event(self, event_type: str, data: Dict[str, Any]):
        """Emit a workflow event"""
        if self.event_emitter:
            await self.event_emitter.emit(event_type, data)
        
        # Always log events
        logger.debug(f"[WORKFLOWS] Event: {event_type} - {data}")


class EventEmitter:
    """
    Simple event emitter for workflow events.
    
    Events can be consumed by:
    - Logging systems
    - Monitoring/alerting
    - Webhooks
    - Real-time notifications
    """
    
    def __init__(self):
        self._handlers: Dict[str, List[callable]] = {}
    
    def on(self, event_type: str, handler: callable):
        """Subscribe to an event type"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    async def emit(self, event_type: str, data: Dict[str, Any]):
        """Emit an event"""
        # Call exact match handlers
        for handler in self._handlers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                else:
                    handler(event_type, data)
            except Exception as e:
                logger.error(f"[WORKFLOWS] Event handler error: {e}")
        
        # Call wildcard handlers
        for pattern, handlers in self._handlers.items():
            if pattern.endswith('*') and event_type.startswith(pattern[:-1]):
                for handler in handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event_type, data)
                        else:
                            handler(event_type, data)
                    except Exception as e:
                        logger.error(f"[WORKFLOWS] Event handler error: {e}")


class StateManager:
    """
    In-memory state manager for workflow contexts.
    
    For production, replace with database-backed implementation.
    """
    
    def __init__(self):
        self._states: Dict[str, WorkflowContext] = {}
    
    async def save(self, context: WorkflowContext):
        """Save workflow context"""
        self._states[context.workflow_id] = context
    
    async def get(self, workflow_id: str) -> Optional[WorkflowContext]:
        """Get workflow context by ID"""
        return self._states.get(workflow_id)
    
    async def delete(self, workflow_id: str):
        """Delete workflow context"""
        if workflow_id in self._states:
            del self._states[workflow_id]
    
    async def get_by_user(
        self,
        user_id: int,
        status: Optional[WorkflowStatus] = None,
        limit: int = 20
    ) -> List[WorkflowContext]:
        """Get workflow contexts for a user"""
        results = [
            ctx for ctx in self._states.values()
            if ctx.user_id == user_id
        ]
        
        if status:
            results = [ctx for ctx in results if ctx.status == status]
        
        # Sort by started_at descending
        results.sort(
            key=lambda x: x.started_at or datetime.min,
            reverse=True
        )
        
        return results[:limit]
    
    async def cleanup_old(self, max_age_hours: int = 24):
        """Remove old completed/failed workflows"""
        cutoff = datetime.utcnow()
        to_delete = []
        
        for workflow_id, context in self._states.items():
            if context.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                if context.completed_at:
                    age_hours = (cutoff - context.completed_at).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        to_delete.append(workflow_id)
        
        for workflow_id in to_delete:
            del self._states[workflow_id]
        
        logger.info(f"[WORKFLOWS] Cleaned up {len(to_delete)} old workflows")
