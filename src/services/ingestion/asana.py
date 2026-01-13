"""
Asana Ingestor

Synchronizes Asana Tasks and Projects into the Knowledge Graph.
"""
from datetime import datetime
from typing import Any, List, Optional
import logging

from .base import BaseIngestor
from ...indexing.graph import NodeType, RelationType

logger = logging.getLogger(__name__)

class AsanaIngestor(BaseIngestor):
    
    async def fetch_delta(self, last_sync_time: Optional[datetime]) -> List[Any]:
        """
        Fetch changed tasks from Asana API.
        
        NOTE: In this MVP, we will mock the API call or use the existing 
        AsanaService if available. For safety, we'll return a mocked list 
        demonstrating the data structure.
        """
        # In real impl: application_service.get_tasks_modified_since(last_sync_time)
        
        # Mock Data Structure
        mock_tasks = [
            {
                "gid": "1200", 
                "name": "Finalize Q4 Strategy", 
                "assignee": {"gid": "user_1", "email": "me@company.com", "name": "Me"},
                "projects": [{"gid": "proj_1", "name": "Strategy 2025"}],
                "completed": False,
                "due_on": "2025-12-20"
            },
            {
                "gid": "1205", 
                "name": "Design New Homepage", 
                "assignee": {"gid": "user_2", "email": "designer@company.com", "name": "Alice Design"},
                "projects": [{"gid": "proj_2", "name": "Website Redesign"}],
                "completed": True,
                "due_on": "2025-12-15"
            }
        ]
        return mock_tasks

    async def ingest_item(self, item: Any) -> None:
        """
        Maps an Asana Task to Graph Nodes:
        Task -> (:ActionItem)
        Assignee -> (:Person)
        Project -> (:Project)
        """
        task_id = f"asana:{item['gid']}"
        task_name = item['name']
        is_completed = item['completed']
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
            proj_id = f"asana_proj:{proj['gid']}"
            proj_name = proj['name']
            
            # Create Project Node (Idempotent)
            await self.graph.add_node(
                node_id=proj_id,
                node_type=NodeType.PROJECT,
                properties={
                    "name": proj_name,
                    "status": "active" # Assume active if task is attached
                }
            )
            
            # Link: ActionItem -[PART_OF]-> Project
            # Schema checking: Task PART_OF Project
            await self.graph.add_relationship(
                source_id=task_id,
                target_id=proj_id,
                rel_type=RelationType.PART_OF, # Assuming PART_OF exists in schema for Task->Project
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
