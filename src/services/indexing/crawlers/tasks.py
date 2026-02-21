"""
Google Tasks Crawler

Background indexer that crawls Google Tasks for the knowledge graph.
Creates ActionItem nodes and links them to TimeBlocks for temporal queries.

Features:
- Indexes Google Tasks as ActionItem nodes
- Links to TimeBlocks based on due dates
- Extracts topics from task titles and notes
- Tracks overdue tasks for insight generation
"""
from typing import List, Any, Optional, Dict
from datetime import datetime, timedelta
import asyncio

from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.parsers.base import ParsedNode
from src.services.indexing.graph.schema import NodeType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class TasksCrawler(BaseIndexer):
    """
    Crawler that periodically indexes Google Tasks.
    
    Processes:
    - Tasks from all task lists
    - Pending and recently completed tasks
    """
    
    def __init__(
        self,
        config,
        user_id: int,
        task_service=None,
        **kwargs
    ):
        """
        Initialize Tasks crawler.
        
        Args:
            config: Application configuration
            user_id: User ID to index for
            task_service: TaskService instance
        """
        from src.services.service_constants import ServiceConstants
        super().__init__(config, user_id, **kwargs)
        self.task_service = task_service
        self.last_sync_time = datetime.now() - timedelta(days=ServiceConstants.INITIAL_LOOKBACK_DAYS)
        # NOTE: In-memory _task_cache replaced by self._persisted_cache (from BaseIndexer)
        # Durable sync state is loaded automatically in run_sync_cycle
        
        # Tasks-specific settings from ServiceConstants
        self.sync_interval = ServiceConstants.TASK_SYNC_INTERVAL
    
    @property
    def name(self) -> str:
        return "google_tasks"
    
    async def fetch_delta(self) -> List[Any]:
        """
        Fetch Google Tasks that need indexing.
        """
        if not self.task_service:
            logger.warning("[TasksCrawler] No Task service available, skipping sync")
            return []
        
        new_items = []
        
        try:
            # 1. Fetch pending tasks
            pending_tasks = await asyncio.to_thread(
                self.task_service.list_tasks,
                status='pending',
                limit=200,
                show_completed=False
            )
            
            for task in pending_tasks:
                task_id = task.get('id')
                updated = task.get('updated')
                
                if task_id not in self._persisted_cache or self._persisted_cache[task_id] != updated:
                    task['_status'] = 'pending'
                    new_items.append(task)
                    self._persisted_cache[task_id] = updated
            
            # 2. Fetch recently completed tasks (for tracking completion)
            completed_tasks = await asyncio.to_thread(
                self.task_service.list_tasks,
                status='completed',
                limit=50,
                show_completed=True
            )
            
            for task in completed_tasks:
                task_id = task.get('id')
                updated = task.get('updated')
                
                if task_id not in self._persisted_cache or self._persisted_cache[task_id] != updated:
                    task['_status'] = 'completed'
                    new_items.append(task)
                    self._persisted_cache[task_id] = updated
            
            logger.info(f"[TasksCrawler] Found {len(new_items)} tasks to index")
            return new_items
            
        except Exception as e:
            logger.error(f"[TasksCrawler] Fetch delta failed: {e}")
            return []
    
    async def transform_item(self, item: Any) -> Optional[List[ParsedNode]]:
        """
        Transform a Google Task into a graph node.
        """
        try:
            task_id = item.get('id')
            if not task_id:
                return None
            
            # Extract task properties
            title = item.get('title', 'Untitled Task')
            notes = item.get('notes', '')
            due_date = item.get('due')
            status = item.get('_status', 'pending')
            position = item.get('position')
            parent = item.get('parent')
            
            # Handle Google Tasks date format
            if due_date:
                # Google Tasks returns date in RFC 3339 format
                try:
                    due_date = due_date.split('T')[0]  # Extract just the date part
                except Exception as e:
                    logger.debug(f"[TasksCrawler] Failed to parse due_date '{due_date}': {e}")
            
            # Build searchable text
            searchable_parts = [title]
            if notes:
                searchable_parts.append(notes)
            
            searchable_text = ' '.join(searchable_parts)
            
            # Create ActionItem node
            node_id = f"gtask_{task_id.replace('-', '_')}"
            
            properties = {
                'id': task_id, # REQUIRED by schema
                'title': title, # GoogleTask uses title
                'description': notes[:2000] if notes else '', # Map notes to description
                'status': status,
                'notes': notes[:2000] if notes else '',
                'google_task_id': task_id,
                'source': 'google_tasks',
                'user_id': self.user_id,
                'timestamp': item.get('updated'),
                'position': position,
                'parent_id': parent,
                'tasklist_id': item.get('tasklist_id', '@default'),
            }
            
            # Add optional fields only if they exist (to avoid NoneType validation errors)
            if due_date:
                properties['due'] = due_date # Schema expects 'due' or 'due_date'? Schema says 'due' in OPTIONAL for GOOGLE_TASK
                properties['due_date'] = due_date # Keep generic too?
            
            created = item.get('created')
            if created:
                properties['created_at'] = created
                
            completed = item.get('completed')
            if completed:
                properties['completed'] = completed
                properties['completed_at'] = completed # Map to standard
            
            task_node = ParsedNode(
                node_id=node_id,
                node_type=NodeType.GOOGLE_TASK,
                properties=properties,
                searchable_text=searchable_text[:5000],
                relationships=[]
            )
            
            # FIXED: Link to User for graph connectivity
            # ActionItem BELONGS_TO User - ensures tasks appear in visualization
            from src.services.indexing.graph.schema import RelationType
            task_node.relationships.append({
                'from_node': node_id,
                'to_node': f"User/{self.user_id}",
                'rel_type': RelationType.BELONGS_TO.value,
                'properties': {'source': 'google_tasks'}
            })
            
            return [task_node]
            
        except Exception as e:
            logger.warning(f"[TasksCrawler] Transform failed for task: {e}")
            return None
    
    async def get_overdue_tasks(self) -> List[Dict[str, Any]]:
        """Get overdue tasks for insight generation."""
        if not self.task_service:
            return []
        
        try:
            overdue = await asyncio.to_thread(
                self.task_service.get_overdue_tasks,
                limit=50
            )
            return overdue
        except Exception as e:
            logger.error(f"[TasksCrawler] Failed to fetch overdue tasks: {e}")
            return []
