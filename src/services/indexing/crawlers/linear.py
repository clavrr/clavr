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
    
    def __init__(self, config: Config, graph_manager=None, vector_store=None):
        super().__init__(config, graph_manager, vector_store)
        self.linear_service: Optional[LinearService] = None
    
    @property
    def source_name(self) -> str:
        return "linear"
    
    async def _initialize_service(self, user_id: int):
        """Initialize Linear service for user."""
        # In a real implementation, we'd get the user's Linear API key
        # from their stored credentials
        if self.linear_service is None:
            self.linear_service = LinearService(self.config)
    
    async def index(
        self,
        user_id: int,
        options: Optional[Dict[str, Any]] = None
    ) -> IndexingResult:
        """
        Index Linear data for a user.
        
        Args:
            user_id: User to index for
            options: Indexing options
            
        Returns:
            IndexingResult with stats
        """
        options = options or {}
        stats = IndexingStats()
        errors = []
        
        try:
            await self._initialize_service(user_id)
            
            if not self.linear_service or not self.linear_service.is_available:
                return IndexingResult(
                    success=False,
                    stats=stats,
                    errors=["Linear not configured for user"]
                )
            
            # 1. Index Teams
            teams = await self.linear_service.get_teams()
            logger.info(f"[LinearIndexer] Found {len(teams)} teams")
            
            for team in teams:
                try:
                    await self._index_team(team, user_id)
                    stats.created += 1
                except Exception as e:
                    errors.append(f"Team {team.get('name')}: {e}")
                    stats.errors += 1
            
            # 2. Index Issues
            issues = await self.linear_service.client.get_issues(limit=500)
            logger.info(f"[LinearIndexer] Found {len(issues)} issues")
            
            for issue in issues:
                try:
                    await self._index_issue(issue, user_id)
                    stats.created += 1
                except Exception as e:
                    errors.append(f"Issue {issue.get('identifier')}: {e}")
                    stats.errors += 1
            
            # 3. Index Active Cycles
            for team in teams:
                try:
                    cycles = await self.linear_service.client.get_cycles(
                        team_id=team.get("id"),
                        is_active=True
                    )
                    for cycle in cycles:
                        await self._index_cycle(cycle, user_id)
                        stats.created += 1
                except Exception as e:
                    errors.append(f"Cycles for {team.get('name')}: {e}")
                    stats.errors += 1
            
            logger.info(f"[LinearIndexer] Indexed {stats.created} items for user {user_id}")
            
            return IndexingResult(
                success=True,
                stats=stats,
                errors=errors if errors else None
            )
            
        except Exception as e:
            logger.error(f"[LinearIndexer] Indexing failed: {e}")
            return IndexingResult(
                success=False,
                stats=stats,
                errors=[str(e)]
            )
        finally:
            if self.linear_service:
                await self.linear_service.close()
    
    async def _index_team(self, team: Dict[str, Any], user_id: int):
        """Index a Linear team."""
        if not self.graph_manager:
            return
        
        # AQL UPSERT for team
        query = """
        UPSERT { _key: @id }
        INSERT {
            _key: @id,
            id: @id,
            name: @name,
            key: @key,
            user_id: @user_id,
            synced_at: DATE_ISO8601(DATE_NOW())
        }
        UPDATE {
            name: @name,
            key: @key,
            user_id: @user_id,
            synced_at: DATE_ISO8601(DATE_NOW())
        }
        IN LinearTeam
        RETURN NEW
        """
        
        await self.graph_manager.execute_query(query, {
            "id": team.get("id"),
            "name": team.get("name"),
            "key": team.get("key"),
            "user_id": user_id
        })
    
    async def _index_issue(self, issue: Dict[str, Any], user_id: int):
        """Index a Linear issue."""
        if not self.graph_manager:
            return
        
        assignee = issue.get("assignee", {}) or {}
        team = issue.get("team", {}) or {}
        state = issue.get("state", {}) or {}
        
        # AQL UPSERT for issue
        query = """
        UPSERT { _key: @id }
        INSERT {
            _key: @id,
            id: @id,
            identifier: @identifier,
            title: @title,
            description: @description,
            priority: @priority,
            state: @state,
            stateType: @state_type,
            dueDate: @due_date,
            url: @url,
            user_id: @user_id,
            team_id: @team_id,
            assignee_email: @assignee_email,
            assignee_name: @assignee_name,
            synced_at: DATE_ISO8601(DATE_NOW())
        }
        UPDATE {
            identifier: @identifier,
            title: @title,
            description: @description,
            priority: @priority,
            state: @state,
            stateType: @state_type,
            dueDate: @due_date,
            url: @url,
            user_id: @user_id,
            team_id: @team_id,
            assignee_email: @assignee_email,
            assignee_name: @assignee_name,
            synced_at: DATE_ISO8601(DATE_NOW())
        }
        IN LinearIssue
        RETURN NEW
        """
        
        await self.graph_manager.execute_query(query, {
            "id": issue.get("id"),
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "description": (issue.get("description") or "")[:500],
            "priority": issue.get("priority"),
            "state": state.get("name"),
            "state_type": state.get("type"),
            "due_date": issue.get("dueDate"),
            "url": issue.get("url"),
            "user_id": user_id,
            "team_id": team.get("id"),
            "assignee_email": assignee.get("email"),
            "assignee_name": assignee.get("name")
        })
        
        # Link to team via edge (if team exists)
        if team.get("id"):
            edge_query = """
            LET issue_id = CONCAT("LinearIssue/", @issue_id)
            LET team_id = CONCAT("LinearTeam/", @team_id)
            UPSERT { _from: issue_id, _to: team_id }
            INSERT { _from: issue_id, _to: team_id, created_at: DATE_ISO8601(DATE_NOW()) }
            UPDATE { updated_at: DATE_ISO8601(DATE_NOW()) }
            IN BELONGS_TO_TEAM
            """
            try:
                await self.graph_manager.execute_query(edge_query, {
                    "issue_id": issue.get("id"),
                    "team_id": team.get("id")
                })
            except Exception as e:
                logger.debug(f"[LinearIndexer] Could not create team edge: {e}")
        
        # Create assignee relationship if exists
        if assignee.get("email"):
            # First upsert the Person node
            person_query = """
            UPSERT { email: @email }
            INSERT { email: @email, name: @name, synced_at: DATE_ISO8601(DATE_NOW()) }
            UPDATE { name: @name, synced_at: DATE_ISO8601(DATE_NOW()) }
            IN Person
            RETURN NEW
            """
            try:
                await self.graph_manager.execute_query(person_query, {
                    "email": assignee.get("email"),
                    "name": assignee.get("name")
                })
                
                # Then create edge
                assign_edge = """
                LET person = FIRST(FOR p IN Person FILTER p.email == @email RETURN p)
                LET issue = DOCUMENT("LinearIssue", @issue_id)
                FILTER person != null AND issue != null
                UPSERT { _from: person._id, _to: issue._id }
                INSERT { _from: person._id, _to: issue._id, rel_type: "ASSIGNED_TO", created_at: DATE_ISO8601(DATE_NOW()) }
                UPDATE { updated_at: DATE_ISO8601(DATE_NOW()) }
                IN ASSIGNED_TO
                """
                await self.graph_manager.execute_query(assign_edge, {
                    "email": assignee.get("email"),
                    "issue_id": issue.get("id")
                })
            except Exception as e:
                logger.debug(f"[LinearIndexer] Could not create assignee edge: {e}")
        
        # Also index to vector store for semantic search
        if self.vector_store and issue.get("title"):
            text = f"{issue.get('identifier')}: {issue.get('title')}"
            if issue.get("description"):
                text += f"\n{issue.get('description')[:300]}"
            
            await self.vector_store.add_documents(
                documents=[text],
                metadatas=[{
                    "source": "linear",
                    "type": "issue",
                    "id": issue.get("id"),
                    "identifier": issue.get("identifier"),
                    "url": issue.get("url"),
                    "user_id": str(user_id)
                }],
                ids=[f"linear-{issue.get('id')}"]
            )
    
    async def _index_cycle(self, cycle: Dict[str, Any], user_id: int):
        """Index a Linear cycle."""
        if not self.graph_manager:
            return
        
        team = cycle.get("team", {}) or {}
        
        # AQL UPSERT for cycle
        query = """
        UPSERT { _key: @id }
        INSERT {
            _key: @id,
            id: @id,
            number: @number,
            name: @name,
            startsAt: @starts_at,
            endsAt: @ends_at,
            team_id: @team_id,
            user_id: @user_id,
            synced_at: DATE_ISO8601(DATE_NOW())
        }
        UPDATE {
            number: @number,
            name: @name,
            startsAt: @starts_at,
            endsAt: @ends_at,
            team_id: @team_id,
            synced_at: DATE_ISO8601(DATE_NOW())
        }
        IN LinearCycle
        RETURN NEW
        """
        
        await self.graph_manager.execute_query(query, {
            "id": cycle.get("id"),
            "number": cycle.get("number"),
            "name": cycle.get("name"),
            "starts_at": cycle.get("startsAt"),
            "ends_at": cycle.get("endsAt"),
            "team_id": team.get("id"),
            "user_id": user_id
        })
        
        # Link cycle to team if exists
        if team.get("id"):
            edge_query = """
            LET cycle_id = CONCAT("LinearCycle/", @cycle_id)
            LET team_id = CONCAT("LinearTeam/", @team_id)
            UPSERT { _from: cycle_id, _to: team_id }
            INSERT { _from: cycle_id, _to: team_id, created_at: DATE_ISO8601(DATE_NOW()) }
            UPDATE { updated_at: DATE_ISO8601(DATE_NOW()) }
            IN CYCLE_OF_TEAM
            """
            try:
                await self.graph_manager.execute_query(edge_query, {
                    "cycle_id": cycle.get("id"),
                    "team_id": team.get("id")
                })
            except Exception as e:
                logger.debug(f"[LinearIndexer] Could not create cycle-team edge: {e}")
        
        # Link issues to cycle
        issues = cycle.get("issues", {}).get("nodes", [])
        for issue in issues:
            link_query = """
            LET issue_id = CONCAT("LinearIssue/", @issue_id)
            LET cycle_id = CONCAT("LinearCycle/", @cycle_id)
            UPSERT { _from: issue_id, _to: cycle_id }
            INSERT { _from: issue_id, _to: cycle_id, created_at: DATE_ISO8601(DATE_NOW()) }
            UPDATE { updated_at: DATE_ISO8601(DATE_NOW()) }
            IN IN_CYCLE
            """
            try:
                await self.graph_manager.execute_query(link_query, {
                    "issue_id": issue.get("id"),
                    "cycle_id": cycle.get("id")
                })
            except Exception as e:
                logger.debug(f"[LinearIndexer] Could not create issue-cycle edge: {e}")
