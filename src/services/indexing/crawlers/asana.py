"""
Asana Crawler

Background indexer that crawls Asana tasks and projects for the knowledge graph.
Creates ActionItem and Project nodes, links to assignees, and creates temporal relationships.

Features:
- Indexes Asana tasks as ActionItem nodes
- Indexes Asana projects as Project nodes
- Creates Person nodes for assignees
- Links to TimeBlocks for temporal queries
- Extracts topics from task descriptions
"""
from typing import List, Any, Optional, Dict
from datetime import datetime, timedelta
import asyncio

from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.parsers.base import ParsedNode, Relationship
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.service_constants import ServiceConstants
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class AsanaCrawler(BaseIndexer):
    """
    Crawler that periodically indexes Asana tasks and projects.
    
    Processes:
    - Tasks → ActionItem nodes
    - Projects → Project nodes
    - Assignees → Person nodes
    - Task dependencies → PRECEDED/FOLLOWS relationships
    """
    
    def __init__(
        self,
        config,
        user_id: int,
        asana_service=None,
        **kwargs
    ):
        """
        Initialize Asana crawler.
        
        Args:
            config: Application configuration
            user_id: User ID to index for
            asana_service: AsanaService instance
        """
        super().__init__(config, user_id, **kwargs)
        self.asana_service = asana_service
        self.last_sync_time = datetime.now() - timedelta(days=ServiceConstants.INITIAL_LOOKBACK_DAYS)
        self._task_cache = {}
        self._project_cache = {}
        
        # Asana-specific settings from ServiceConstants
        self.sync_interval = ServiceConstants.ASANA_SYNC_INTERVAL
    
    @property
    def name(self) -> str:
        return "asana"
    
    async def fetch_delta(self) -> List[Any]:
        """
        Fetch Asana tasks and projects.
        """
        if not self.asana_service:
            logger.warning("[AsanaCrawler] No Asana service available, skipping sync")
            return []
        
        new_items = []
        
        try:
            # 1. Fetch projects first
            projects = await asyncio.to_thread(
                self.asana_service.list_projects,
                limit=100
            )
            
            for project in projects:
                project_id = project.get('gid')
                if project_id not in self._project_cache:
                    project['_item_type'] = 'project'
                    new_items.append(project)
                    self._project_cache[project_id] = True
            
            # 2. Fetch pending tasks (most important)
            pending_tasks = await asyncio.to_thread(
                self.asana_service.list_tasks,
                status='pending',
                limit=200
            )
            
            for task in pending_tasks:
                task_id = task.get('gid') or task.get('id')
                modified = task.get('modified_at')
                
                # Check if task is new or modified
                if task_id not in self._task_cache or self._task_cache[task_id] != modified:
                    task['_item_type'] = 'task'
                    new_items.append(task)
                    self._task_cache[task_id] = modified
            
            # 3. Fetch recently completed tasks
            completed_tasks = await asyncio.to_thread(
                self.asana_service.list_tasks,
                status='completed',
                limit=50
            )
            
            for task in completed_tasks:
                task_id = task.get('gid') or task.get('id')
                modified = task.get('modified_at')
                
                if task_id not in self._task_cache or self._task_cache[task_id] != modified:
                    task['_item_type'] = 'task'
                    new_items.append(task)
                    self._task_cache[task_id] = modified
            
            logger.info(f"[AsanaCrawler] Found {len(new_items)} items to index")
            return new_items
            
        except Exception as e:
            logger.error(f"[AsanaCrawler] Fetch delta failed: {e}")
            return []
    
    async def transform_item(self, item: Any) -> Optional[List[ParsedNode]]:
        """
        Transform Asana item (task or project) into graph nodes.
        """
        item_type = item.get('_item_type', 'task')
        
        if item_type == 'project':
            return await self._transform_project(item)
        else:
            return await self._transform_task(item)
    
    async def _transform_task(self, item: Dict[str, Any]) -> Optional[List[ParsedNode]]:
        """Transform an Asana task into graph nodes."""
        try:
            nodes = []
            
            task_id = item.get('gid') or item.get('id')
            if not task_id:
                return None
            
            # Extract task properties
            title = item.get('name') or item.get('title', 'Untitled Task')
            notes = item.get('notes', '')
            status = 'completed' if item.get('completed') else 'pending'
            due_date = item.get('due_on') or item.get('due_date')
            created_at = item.get('created_at')
            assignee = item.get('assignee')
            projects = item.get('projects', [])
            
            # Build searchable text
            searchable_parts = [title]
            if notes:
                searchable_parts.append(notes)
            
            searchable_text = ' '.join(searchable_parts)
            
            # Extract custom fields for schema mapping
            schema_props = self._extract_custom_fields(item.get('custom_fields', []))
            
            # Create ActionItem node
            node_id = f"asana_task_{task_id}"
            
            task_node = ParsedNode(
                node_id=node_id,
                node_type=NodeType.ACTION_ITEM,
                properties={
                    'description': title,
                    'status': status,
                    'notes': notes[:2000] if notes else '',
                    'due_date': due_date,
                    'asana_task_id': task_id,
                    'source': 'asana',
                    'user_id': self.user_id,
                    'timestamp': created_at,
                    'created_at': created_at,
                    'completed': item.get('completed', False),
                    'priority': self._extract_priority(item),
                    'schema_properties': schema_props,
                },
                searchable_text=searchable_text[:10000],
                relationships=[]
            )
            
            nodes.append(task_node)
            
            # Create Person node for assignee
            if assignee and isinstance(assignee, dict):
                assignee_node, assignee_rel = self._create_person_from_asana(
                    asana_user=assignee,
                    task_node_id=node_id,
                    rel_type=RelationType.ASSIGNED_TO
                )
                if assignee_node:
                    nodes.append(assignee_node)
                    task_node.relationships.append(assignee_rel)
            
            # Link to projects
            for project in projects:
                project_id = project.get('gid')
                if project_id:
                    project_node_id = f"asana_project_{project_id}"
                    task_node.relationships.append(Relationship(
                        from_node=node_id,
                        to_node=project_node_id,
                        rel_type=RelationType.PART_OF
                    ))
            
            return nodes
            
        except Exception as e:
            logger.warning(f"[AsanaCrawler] Task transform failed: {e}")
            return None

    def _extract_custom_fields(self, custom_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract Asana custom fields into a flat schema dictionary.
        """
        schema_props = {}
        
        for field in custom_fields:
            try:
                name = field.get('name')
                if not name:
                    continue
                    
                field_type = field.get('type')
                value = None
                
                if field_type == 'text':
                    value = field.get('text_value')
                elif field_type == 'number':
                    value = field.get('number_value')
                elif field_type == 'enum':
                    enum_value = field.get('enum_value')
                    if enum_value:
                        value = enum_value.get('name')
                elif field_type == 'multi_enum':
                    multi_enum_values = field.get('multi_enum_values', [])
                    value = [v.get('name') for v in multi_enum_values]
                elif field_type == 'date':
                    date_value = field.get('date_value')
                    if date_value:
                        value = date_value.get('date') or date_value.get('date_time')
                elif field_type == 'people':
                    people_value = field.get('people_value', [])
                    value = [p.get('name') for p in people_value]
                else:
                    # Fallback to display value
                    value = field.get('display_value')

                if value is not None and value != "" and value != []:
                    schema_props[name] = value
                    
            except Exception as e:
                logger.debug(f"Failed to extract custom field {field.get('name')}: {e}")
                continue
                
        return schema_props
    
    async def _transform_project(self, item: Dict[str, Any]) -> Optional[List[ParsedNode]]:
        """Transform an Asana project into a graph node."""
        try:
            project_id = item.get('gid')
            if not project_id:
                return None
            
            name = item.get('name', 'Untitled Project')
            notes = item.get('notes', '')
            
            node_id = f"asana_project_{project_id}"
            
            project_node = ParsedNode(
                node_id=node_id,
                node_type=NodeType.PROJECT,
                properties={
                    'name': name,
                    'description': notes[:2000] if notes else '',
                    'asana_project_id': project_id,
                    'source': 'asana',
                    'user_id': self.user_id,
                    'created_at': item.get('created_at'),
                },
                searchable_text=f"{name} {notes}"[:5000]
            )
            
            return [project_node]
            
        except Exception as e:
            logger.warning(f"[AsanaCrawler] Project transform failed: {e}")
            return None
    
    def _create_person_from_asana(
        self,
        asana_user: Dict[str, Any],
        task_node_id: str,
        rel_type: RelationType
    ) -> tuple:
        """Create a Person node from Asana user data."""
        user_id = asana_user.get('gid')
        name = asana_user.get('name', 'Unknown')
        email = asana_user.get('email')
        
        if not user_id:
            return None, None
        
        # Use email-based ID if available for cross-source merging
        from src.services.indexing.node_id_utils import generate_person_id
        if email:
            person_node_id = generate_person_id(email=email)
        else:
            person_node_id = generate_person_id(source='asana', source_id=user_id)
        
        person_node = ParsedNode(
            node_id=person_node_id,
            node_type=NodeType.PERSON,
            properties={
                'name': name,
                'email': email,
                'asana_user_id': user_id,
                'source': 'asana',
            },
            searchable_text=f"{name} {email or ''}"
        )
        
        relationship = Relationship(
            from_node=task_node_id,
            to_node=person_node_id,
            rel_type=rel_type
        )
        
        return person_node, relationship
    
    def _extract_priority(self, task: Dict[str, Any]) -> Optional[int]:
        """
        Extract priority from Asana task.
        
        Asana uses custom fields for priority, so this may need customization.
        """
        # Check for custom priority field
        custom_fields = task.get('custom_fields', [])
        for field in custom_fields:
            if 'priority' in field.get('name', '').lower():
                # Map to numeric priority
                value = field.get('display_value', '').lower()
                if 'high' in value or 'urgent' in value:
                    return 1
                elif 'medium' in value:
                    return 2
                elif 'low' in value:
                    return 3
        
        return None
    
    async def fetch_overdue_tasks(self) -> List[Dict[str, Any]]:
        """Fetch overdue tasks for potential insight generation."""
        if not self.asana_service:
            return []
        
        try:
            overdue = await asyncio.to_thread(
                self.asana_service.get_overdue_tasks,
                limit=50
            )
            return overdue
        except Exception as e:
            logger.error(f"[AsanaCrawler] Failed to fetch overdue tasks: {e}")
            return []
