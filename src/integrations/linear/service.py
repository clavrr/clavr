"""
Linear Service

High-level service for Linear operations.
Provides business logic layer above the raw API client.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config
from .client import LinearClient, LinearAPIException

logger = setup_logger(__name__)


class LinearService:
    """
    High-level Linear service.
    
    Provides:
    - Issue management (create, update, list)
    - Cycle (sprint) tracking
    - Team and state management
    - Sync with Knowledge Graph
    """
    
    def __init__(self, config: Config, api_key: Optional[str] = None):
        """
        Initialize Linear service.
        
        Args:
            config: Application configuration
            api_key: Linear API key (optional, can use env var)
        """
        self.config = config
        self.client = LinearClient(api_key=api_key, config=config)
        self._teams_cache: Optional[List[Dict]] = None
        self._viewer_cache: Optional[Dict] = None
    
    @property
    def is_available(self) -> bool:
        """Check if Linear is configured."""
        return self.client.is_available
    
    async def get_my_issues(
        self,
        state: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get issues assigned to me.
        
        Args:
            state: Filter by state (e.g., "In Progress")
            limit: Maximum issues
            
        Returns:
            List of my issues
        """
        viewer = await self.get_viewer()
        if not viewer:
            return []
        
        return await self.client.get_issues(
            assignee_id=viewer.get("id"),
            state=state,
            limit=limit
        )
    
    async def get_team_issues(
        self,
        team_name: str,
        state: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get issues for a team by name."""
        teams = await self.get_teams()
        team = next((t for t in teams if t["name"].lower() == team_name.lower()), None)
        
        if not team:
            logger.warning(f"Team not found: {team_name}")
            return []
        
        return await self.client.get_issues(
            team_id=team["id"],
            state=state,
            limit=limit
        )
    
    async def create_issue(
        self,
        title: str,
        team_name: Optional[str] = None,
        description: Optional[str] = None,
        priority: str = "medium",
        due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create an issue with friendly parameters.
        
        Args:
            title: Issue title
            team_name: Team name (uses first team if not specified)
            description: Issue description
            priority: Priority string (urgent, high, medium, low)
            due_date: Due date (YYYY-MM-DD)
            
        Returns:
            Created issue
        """
        # Map priority string to number
        priority_map = {
            "urgent": 1,
            "high": 2,
            "medium": 3,
            "low": 4,
            "none": 0
        }
        priority_num = priority_map.get(priority.lower(), 3)
        
        # Get team ID
        teams = await self.get_teams()
        if not teams:
            raise LinearAPIException("No teams available")
        
        if team_name:
            team = next((t for t in teams if t["name"].lower() == team_name.lower()), None)
            if not team:
                raise LinearAPIException(f"Team not found: {team_name}")
        else:
            team = teams[0]
        
        return await self.client.create_issue(
            title=title,
            team_id=team["id"],
            description=description,
            priority=priority_num,
            due_date=due_date
        )
    
    async def get_active_cycle(self, team_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get the active cycle (sprint) for a team.
        
        Args:
            team_name: Team name (uses first team if not specified)
            
        Returns:
            Active cycle or None
        """
        teams = await self.get_teams()
        
        if team_name:
            team = next((t for t in teams if t["name"].lower() == team_name.lower()), None)
            team_id = team["id"] if team else None
        else:
            team_id = teams[0]["id"] if teams else None
        
        cycles = await self.client.get_cycles(team_id=team_id, is_active=True)
        return cycles[0] if cycles else None
    
    async def get_high_priority_deadlines(self, days_ahead: int = 7) -> List[Dict[str, Any]]:
        """
        Get high priority issues with upcoming deadlines.
        
        Used by conflict detector to check calendar vs Linear deadlines.
        
        Args:
            days_ahead: Look ahead window in days
            
        Returns:
            List of high priority issues with due dates
        """
        all_issues = await self.client.get_issues(limit=100)
        
        now = datetime.utcnow()
        deadline_issues = []
        
        for issue in all_issues:
            due_date_str = issue.get("dueDate")
            priority = issue.get("priority", 4)
            state_type = issue.get("state", {}).get("type", "")
            
            # Skip completed issues
            if state_type in ["completed", "canceled"]:
                continue
            
            # Check if high priority (1=urgent, 2=high)
            if priority not in [1, 2]:
                continue
            
            # Check due date
            if due_date_str:
                try:
                    due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
                    days_until = (due_date.replace(tzinfo=None) - now).days
                    
                    if 0 <= days_until <= days_ahead:
                        issue["days_until_due"] = days_until
                        deadline_issues.append(issue)
                except (ValueError, TypeError):
                    pass
        
        # Sort by days until due
        deadline_issues.sort(key=lambda x: x.get("days_until_due", 999))
        
        return deadline_issues
    
    async def get_teams(self) -> List[Dict[str, Any]]:
        """Get teams (cached)."""
        if self._teams_cache is None:
            self._teams_cache = await self.client.get_teams()
        return self._teams_cache
    
    async def get_viewer(self) -> Dict[str, Any]:
        """Get current user (cached)."""
        if self._viewer_cache is None:
            self._viewer_cache = await self.client.get_viewer()
        return self._viewer_cache
    
    async def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search issues."""
        return await self.client.search_issues(query, limit)
    
    async def get_projects(self, team_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get projects, optionally filtered by team name."""
        team_id = None
        if team_name:
            teams = await self.get_teams()
            team = next((t for t in teams if t["name"].lower() == team_name.lower()), None)
            if team:
                team_id = team["id"]
        
        return await self.client.get_projects(team_id=team_id)

    async def add_comment(self, issue_id: str, body: str) -> Dict[str, Any]:
        """Add a comment to an issue."""
        return await self.client.add_comment(issue_id, body)

    async def get_issue_comments(self, issue_id: str) -> List[Dict[str, Any]]:
        """Get comments for an issue."""
        return await self.client.get_issue_comments(issue_id)
    
    async def sync_issues_to_graph(self, graph_manager, user_id: int) -> int:
        """
        Sync Linear issues to Knowledge Graph.
        
        Args:
            graph_manager: KnowledgeGraphManager instance
            user_id: User ID for graph nodes
            
        Returns:
            Number of issues synced
        """
        issues = await self.client.get_issues(limit=200)
        synced = 0
        
        for issue in issues:
            try:
                # Create or update LinearIssue node
                query = """
                MERGE (i:LinearIssue {id: $id})
                SET i.identifier = $identifier,
                    i.title = $title,
                    i.priority = $priority,
                    i.state = $state,
                    i.dueDate = $dueDate,
                    i.url = $url,
                    i.user_id = $user_id,
                    i.synced_at = datetime()
                RETURN i
                """
                
                await graph_manager.execute_query(query, {
                    "id": issue.get("id"),
                    "identifier": issue.get("identifier"),
                    "title": issue.get("title"),
                    "priority": issue.get("priority"),
                    "state": issue.get("state", {}).get("name"),
                    "dueDate": issue.get("dueDate"),
                    "url": issue.get("url"),
                    "user_id": user_id
                })
                
                synced += 1
                
            except Exception as e:
                logger.error(f"Failed to sync issue {issue.get('identifier')}: {e}")
        
        logger.info(f"[Linear] Synced {synced} issues to graph for user {user_id}")
        return synced
    
    async def close(self):
        """Close the client."""
        await self.client.close()
