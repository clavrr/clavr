"""
Reactive Graph Service

This service acts as the central nervous system of the "Living" graph.
It subscribes to indexing events (Node Created, Relation Created) and dispatches
micro-reasoning tasks to specialized agents.

Triggers:
- Meeting Created -> Trigger Preparation Agent
- Email Created -> Trigger Entity Linker / Topic Extractor
- Task Created -> Trigger Gap Analysis
"""
import asyncio
from typing import Dict, Any, List, Callable, Awaitable
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

class GraphEventType(str, Enum):
    NODE_CREATED = "NODE_CREATED"
    NODE_UPDATED = "NODE_UPDATED"
    RELATION_CREATED = "RELATION_CREATED"

@dataclass
class GraphEvent:
    type: GraphEventType
    node_type: NodeType
    node_id: str
    properties: Dict[str, Any]
    user_id: int
    timestamp: datetime = datetime.utcnow()

class ReactiveGraphService:
    """
    Manages event subscriptions and dispatches reasoning tasks.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self._handlers: Dict[GraphEventType, List[Callable[[GraphEvent], Awaitable[None]]]] = {
            GraphEventType.NODE_CREATED: [],
            GraphEventType.NODE_UPDATED: [],
            GraphEventType.RELATION_CREATED: []
        }
        self.queue = asyncio.Queue()
        self.is_running = False
        self._worker_task = None
        
    async def start(self):
        """Start the event processing worker."""
        if self.is_running:
            return
        
        self.is_running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("[ReactiveGraphService] Started event loop")
        
    async def stop(self):
        """Stop the service."""
        self.is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("[ReactiveGraphService] Stopped")
        
    async def emit(self, event: GraphEvent):
        """Emit an event to the bus."""
        if not self.is_running:
            logger.warning("[ReactiveGraphService] Event emitted but service not running")
            return
        await self.queue.put(event)
        
    def resolve_handlers(self, event: GraphEvent) -> List[Callable]:
        """Get all handlers for this event."""
        return self._handlers.get(event.type, [])
        
    def subscribe(self, event_type: GraphEventType, handler: Callable[[GraphEvent], Awaitable[None]]):
        """Subscribe to an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        
    async def _process_queue(self):
        """Background worker to process events."""
        while self.is_running:
            try:
                event = await self.queue.get()
                handlers = self.resolve_handlers(event)
                
                # Execute handlers concurrently
                if handlers:
                    await asyncio.gather(
                        *[self._safe_execute(h, event) for h in handlers],
                        return_exceptions=True
                    )
                    
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ReactiveGraphService] queue error: {e}")
                
    async def _safe_execute(self, handler, event):
        """Execute a handler safely."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"[ReactiveGraphService] Handler failed {handler}: {e}")

# Global instance
_reactive_service = None

def get_reactive_service():
    return _reactive_service

def init_reactive_service(config):
    global _reactive_service
    _reactive_service = ReactiveGraphService(config)
    return _reactive_service
