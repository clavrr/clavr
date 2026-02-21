"""
Linear Indexer (Crawler)

Indexes Linear issues into the Knowledge Graph for semantic search
and cross-stack intelligence.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.base_indexer import BaseIndexer, IndexingResult, IndexingStats
from src.services.indexing.parsers.base import ParsedNode, Relationship
from src.integrations.linear.service import LinearService

logger = setup_logger(__name__)


class LinearIndexer(BaseIndexer):
    """
    Indexes Linear issues and cycles into the Knowledge Graph.
    
    Creates nodes:
    - LinearIssue: Individual issues with metadata
    - LinearCycle: Sprints/cycles
    - LinearTeam: Teams
    
    Creates relationships:
    - (User)-[:ASSIGNED_TO]->(LinearIssue)
    - (LinearIssue)-[:IN_CYCLE]->(LinearCycle)
    - (LinearIssue)-[:BELONGS_TO_TEAM]->(LinearTeam)
    """
    
    def __init__(
        self, 
        config: Config, 
        user_id: int, 
        rag_engine=None, 
        graph_manager=None, 
        topic_extractor=None,
        **kwargs
    ):
        super().__init__(
            config=config, 
            user_id=user_id, 
            rag_engine=rag_engine, 
            graph_manager=graph_manager, 
            topic_extractor=topic_extractor,
            **kwargs
        )
        self.linear_service: Optional[LinearService] = None
    
    @property
    def source_name(self) -> str:
        return "linear"
    
    @property
    def name(self) -> str:
        return "linear"
        
    # Implement abstract methods from BaseIndexer
    async def fetch_delta(self) -> List[Any]:
        """Fetch Linear issues and cycles that need indexing."""
        try:
            await self._initialize_service(self.user_id)
            
            if not self.linear_service or not self.linear_service.is_available:
                logger.warning("[LinearIndexer] Linear not configured or available")
                return []
            
            items = []
            
            # 1. Fetch Teams
            teams = await self.linear_service.get_teams()
            for team in teams:
                items.append({"type": "team", "data": team})
            
            # 2. Fetch Issues
            issues = await self.linear_service.client.get_issues(limit=100)
            for issue in issues:
                items.append({"type": "issue", "data": issue})
            
            # 3. Fetch Active Cycles
            for team in teams:
                try:
                    cycles = await self.linear_service.client.get_cycles(
                        team_id=team.get("id"),
                        is_active=True
                    )
                    for cycle in cycles:
                        items.append({"type": "cycle", "data": cycle})
                except Exception as e:
                    logger.debug(f"[LinearIndexer] Could not fetch cycles for team {team.get('id')}: {e}")
            
            return items
            
        except Exception as e:
            logger.error(f"[LinearIndexer] Fetch delta failed: {e}")
            return []
        
    async def transform_item(self, item_wrapper: Any) -> Optional[List[ParsedNode]]:
        """Transform a Linear item into ParsedNode(s)."""
        item_type = item_wrapper.get("type")
        item = item_wrapper.get("data")
        
        if item_type == "team":
            return [self._transform_team(item)]
        elif item_type == "issue":
            return self._transform_issue(item)
        elif item_type == "cycle":
            return [self._transform_cycle(item)]
        
        return None

    def _transform_team(self, team: Dict[str, Any]) -> ParsedNode:
        return ParsedNode(
            node_id=f"linear_team_{team.get('id')}",
            node_type="LinearTeam",
            properties={
                "id": team.get("id"),
                "name": team.get("name"),
                "key": team.get("key"),
                "user_id": self.user_id,
                "source": "linear"
            }
        )

    def _transform_issue(self, issue: Dict[str, Any]) -> List[ParsedNode]:
        assignee = issue.get("assignee", {}) or {}
        team = issue.get("team", {}) or {}
        state = issue.get("state", {}) or {}
        
        issue_id = f"LinearIssue/{issue.get('id')}"
        
        relationships = []
        
        # Link to team
        if team.get("id"):
            relationships.append(Relationship(
                from_node=issue_id,
                to_node=f"linear_team_{team.get('id')}",
                rel_type="BELONGS_TO_TEAM"
            ))
            
        # Link to person (assignee)
        if assignee.get("email"):
            from src.utils.email_utils import get_person_id_from_email
            person_id = get_person_id_from_email(assignee.get("email"))
            relationships.append(Relationship(
                from_node=person_id,
                to_node=issue_id,
                rel_type="ASSIGNED_TO"
            ))
            
            # COMMUNICATES_WITH — Linear issue assignment = work collaboration signal
            relationships.append(Relationship(
                from_node=f"User/{self.user_id}",
                to_node=person_id,
                rel_type="COMMUNICATES_WITH",
                properties={
                    'source': 'linear',
                    'last_interaction': datetime.utcnow().isoformat(),
                    'strength': 0.2,  # Issue assignment = moderate signal
                }
            ))
            
            # KNOWS — ensure User knows this Linear contact
            assignee_name = assignee.get("name", "")
            aliases = []
            if assignee_name and assignee_name.strip():
                aliases.append(assignee_name)
                first_name = assignee_name.split()[0] if assignee_name.split() else None
                if first_name and first_name != assignee_name:
                    aliases.append(first_name)
            
            relationships.append(Relationship(
                from_node=f"User/{self.user_id}",
                to_node=person_id,
                rel_type="KNOWS",
                properties={
                    'aliases': aliases,
                    'frequency': 1,
                    'source': 'linear',
                }
            ))
            
        issue_node = ParsedNode(
            node_id=issue_id,
            node_type="LinearIssue",
            properties={
                "id": issue.get("id"),
                "identifier": issue.get("identifier"),
                "title": issue.get("title"),
                "description": (issue.get("description") or "")[:500],
                "priority": issue.get("priority"),
                "state": state.get("name"),
                "stateType": state.get("type"),
                "dueDate": issue.get("dueDate"),
                "url": issue.get("url"),
                "user_id": self.user_id,
                "source": "linear"
            },
            searchable_text=f"{issue.get('identifier')}: {issue.get('title')}\n{issue.get('description') or ''}",
            relationships=relationships
        )
        
        return [issue_node]

    def _transform_cycle(self, cycle: Dict[str, Any]) -> ParsedNode:
        team = cycle.get("team", {}) or {}
        cycle_id = f"linear_cycle_{cycle.get('id')}"
        
        relationships = []
        if team.get("id"):
            relationships.append(Relationship(
                from_node=cycle_id,
                to_node=f"linear_team_{team.get('id')}",
                rel_type="CYCLE_OF_TEAM"
            ))
            
        return ParsedNode(
            node_id=cycle_id,
            node_type="LinearCycle",
            properties={
                "id": cycle.get("id"),
                "number": cycle.get("number"),
                "name": cycle.get("name"),
                "startsAt": cycle.get("startsAt"),
                "endsAt": cycle.get("endsAt"),
                "user_id": self.user_id,
                "source": "linear"
            },
            relationships=relationships
        )

    async def _initialize_service(self, user_id: int):
        """Initialize Linear service for user."""
        if not self.linear_service:
            from src.integrations.linear.service import LinearService
            self.linear_service = LinearService(self.config, user_id)
            await self.linear_service.initialize()

