"""
Asana Ingestor

Synchronizes Asana Tasks and Projects into the Knowledge Graph.
"""
from datetime import datetime
from typing import Any, List, Optional
import asyncio
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
            person_id = None
            
            # Validate: Must have at least a valid email or name
            if not person_email and not person_name:
                logger.warning(f"[AsanaIngestor] Skipping assignee with no email or name for task {task_id}")
            else:
                # Step 1: Try to find existing Person by email (primary lookup)
                if person_email:
                    person_node = await self.graph.find_node_by_property(NodeType.PERSON, "email", person_email)
                    if person_node:
                        person_id = person_node.get('_id') or person_node.get('id')
                        logger.debug(f"[AsanaIngestor] Found existing person by email: {person_email}")
                
                # Step 2: Fallback - Try to find by name if no email match
                if not person_id and person_name:
                    person_node = await self.graph.find_node_by_property(NodeType.PERSON, "name", person_name)
                    if person_node:
                        person_id = person_node.get('_id') or person_node.get('id')
                        logger.debug(f"[AsanaIngestor] Found existing person by name: {person_name}")
                
                # Step 3: Create new Person node if not found
                if not person_id:
                    # Validate email format before creating
                    import re
                    email_valid = person_email and re.match(r'^[^@]+@[^@]+\.[^@]+$', person_email)
                    
                    # Avoid creating nodes for system/bot accounts
                    system_patterns = ['noreply', 'no-reply', 'notifications', 'system', 'bot@', 'automated']
                    is_system_account = person_email and any(p in person_email.lower() for p in system_patterns)
                    
                    if is_system_account:
                        logger.debug(f"[AsanaIngestor] Skipping system account: {person_email}")
                    elif email_valid or person_name:
                        # Generate a stable ID based on email (preferred) or name
                        if email_valid:
                            person_id = f"person:{person_email.lower()}"
                        else:
                            # Use sanitized name as ID fallback
                            safe_name = re.sub(r'[^a-zA-Z0-9]', '_', person_name.lower())
                            person_id = f"person:asana:{safe_name}"
                        
                        await self.graph.add_node(
                            node_id=person_id,
                            node_type=NodeType.PERSON,
                            properties={
                                "name": person_name or person_email.split('@')[0].title(),
                                "email": person_email if email_valid else None,
                                "source": "asana",
                                "created_by_integration": True
                            }
                        )
                        logger.info(f"[AsanaIngestor] Created Person node: {person_name or person_email}")
                    else:
                        logger.warning(f"[AsanaIngestor] Invalid assignee data, skipping: {assignee}")
                
                # Create relationship if we have a valid person
                if person_id:
                    await self.graph.add_relationship(
                        source_id=task_id,
                        target_id=person_id,
                        rel_type=RelationType.ASSIGNED_TO,
                        properties={"source": "asana"}
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
