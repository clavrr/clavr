"""
Asana Ingestor

Synchronizes Asana Tasks and Projects into the Knowledge Graph.
"""
from datetime import datetime
from typing import Any, List, Optional
import logging

from .base import BaseIngestor
from ...indexing.graph import NodeType, RelationType
from ...integrations.asana.service import AsanaService

logger = logging.getLogger(__name__)

class AsanaIngestor(BaseIngestor):
    
    def __init__(self, graph_manager, config, asana_service: Optional[AsanaService] = None):
        super().__init__(graph_manager, config)
        self.asana_service = asana_service

    async def fetch_delta(self, last_sync_time: Optional[datetime]) -> List[Any]:
        """
        Fetch changed tasks and projects from Asana API.
        """
        if not self.asana_service:
            logger.warning("[AsanaIngestor] AsanaService not provided. Ensure it is initialized with user credentials.")
            return []
            
        try:
            # Fetch recently modified tasks
            tasks = await asyncio.to_thread(
                self.asana_service.list_tasks,
                limit=100
            )
            
            # Enrich tasks with project info
            enriched_items = []
            for task in tasks:
                task['_item_type'] = 'task'
                enriched_items.append(task)
                
            # Fetch projects
            projects = await asyncio.to_thread(
                self.asana_service.list_projects,
                limit=50
            )
            for project in projects:
                project['_item_type'] = 'project'
                enriched_items.append(project)
                
            return enriched_items
        except Exception as e:
            logger.error(f"[AsanaIngestor] Failed to fetch data: {e}")
            return []

    async def ingest_item(self, item: Any) -> None:
        if item.get('_item_type') == 'project':
            await self._ingest_project(item)
            return

        task_id = f"asana:{item.get('gid', item.get('id'))}"
        task_name = item.get('name', item.get('title'))
        is_completed = item.get('status') == 'completed' or item.get('completed', False)
        status = "completed" if is_completed else "active"
        
        # 1. Create ActionItem Node
        await self.graph.add_node(
            node_id=task_id,
            node_type=NodeType.ACTION_ITEM,
            properties={
                "name": task_name,
                "status": status,
                "source": "asana",
                "deadline": item.get('due_on')
            }
        )
        
        # 2. Link Assignee (Person)
        assignee = item.get('assignee')
        if assignee:
            person_email = assignee.get('email')
            person_name = assignee.get('name')
            
            # Try to find existing Person by email
            person_node = await self.graph.find_node_by_property(NodeType.PERSON, "email", person_email)
            
            if not person_node:
                # Create Person Node if not exists
                # In real scenario, we might want to be careful creating people blindly
                # but for an MVP graph, it's safer to have nodes than not.
                person_id = f"person:{person_email}"
                await self.graph.add_node(
                    node_id=person_id,
                    node_type=NodeType.PERSON,
                    properties={
                        "name": person_name,
                        "email": person_email
                    }
                )
            else:
                person_id = person_node['id']
                
            # Add Relationship: ActionItem -[ASSIGNED_TO]-> Person
            # Wait, schema is usually Task -> ASSIGNED_TO -> Person? 
            # Or Person -> ASSIGNED_TO -> Task?
            # Let's check Schema or common sense: "Task is assigned to Person"
            await self.graph.add_relationship(
                source_id=task_id,
                target_id=person_id,
                rel_type=RelationType.ASSIGNED_TO,
                properties={}
            )

        # 3. Link Project
        for proj in item.get('projects', []):
            proj_id = f"asana_proj:{proj.get('gid', proj.get('id'))}"
            proj_name = proj.get('name')
            
            # Create Project Node (Idempotent)
            await self.graph.add_node(
                node_id=proj_id,
                node_type=NodeType.PROJECT,
                properties={
                    "name": proj_name,
                    "status": "active"
                }
            )
            
            # Link: ActionItem -[PART_OF]-> Project
            await self.graph.add_relationship(
                source_id=task_id,
                target_id=proj_id,
                rel_type=RelationType.PART_OF,
                properties={}
            )
            
            # Link: Person -[WORKS_ON]-> Project
            if assignee:
                 await self.graph.add_relationship(
                    source_id=person_id,
                    target_id=proj_id,
                    rel_type=RelationType.WORKS_ON,
                    properties={}
                )

    async def _ingest_project(self, item: Any) -> None:
        """Process Asana Project node."""
        proj_id = f"asana_proj:{item.get('gid', item.get('id'))}"
        await self.graph.add_node(
            node_id=proj_id,
            node_type=NodeType.PROJECT,
            properties={
                "name": item.get('name'),
                "status": "active",
                "source": "asana"
            }
        )
