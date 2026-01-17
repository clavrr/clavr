import os
import asyncio
from typing import Optional, Dict, Any, List

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)

# Try to import the SDK
try:
    from linear_api import LinearClient as LinearSDK
except ImportError:
    logger.error("linear-api SDK not found. Please install it with 'pip install linear-api'")
    LinearSDK = None


class LinearAuthenticationException(Exception):
    """Raised when Linear authentication fails."""
    pass


class LinearAPIException(Exception):
    """Raised when Linear API call fails."""
    def __init__(self, message: str, errors: List[Dict] = None):
        super().__init__(message)
        self.errors = errors or []


class LinearClient:
    """
    Linear API client wrapper using the linear-api SDK.
    Uses asyncio.to_thread to wrap synchronous SDK calls.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[Config] = None
    ):
        """
        Initialize Linear client.
        
        Args:
            api_key: Linear API Key (Personal or OAuth)
            config: Application configuration
        """
        self.api_key = api_key or (config.linear_api_key if config else None) or os.getenv("LINEAR_API_KEY")
        self.config = config
        self._sdk: Optional[LinearSDK] = None
        
    @property
    def sdk(self) -> LinearSDK:
        """Lazy initialization of the SDK."""
        if self._sdk is None:
            if LinearSDK is None:
                raise ImportError("linear-api SDK is required but not installed.")
            if not self.api_key:
                raise LinearAuthenticationException("No Linear API key configured")
            self._sdk = LinearSDK(api_key=self.api_key)
        return self._sdk
    
    @property
    def is_available(self) -> bool:
        """Check if Linear client is available and configured."""
        return bool(self.api_key)
    
    async def get_issues(
        self,
        team_id: Optional[str] = None,
        state: Optional[str] = None,
        assignee_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get issues using the SDK."""
        try:
            def _get():
                issues = self.sdk.issues.list(limit=limit)
                
                filtered = []
                for issue in issues:
                    if team_id and issue.team.id != team_id:
                        continue
                    if state and issue.state.name != state:
                        continue
                    if assignee_id and (not issue.assignee or issue.assignee.id != assignee_id):
                        continue
                    
                    if hasattr(issue, 'model_dump'):
                        filtered.append(issue.model_dump())
                    elif hasattr(issue, 'to_dict'):
                        filtered.append(issue.to_dict())
                    else:
                        filtered.append(issue.__dict__)
                return filtered
                
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.error(f"Error fetching issues via SDK: {e}")
            raise LinearAPIException(str(e))

    async def get_issue(self, issue_id: str) -> Optional[Dict[str, Any]]:
        """Get a single issue by ID using the SDK."""
        try:
            def _get():
                issue = self.sdk.issues.get(issue_id)
                if not issue:
                    return None
                if hasattr(issue, 'model_dump'):
                    return issue.model_dump()
                return issue.__dict__
            
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.error(f"Error fetching issue {issue_id}: {e}")
            return None

    async def create_issue(
        self,
        title: str,
        team_id: str,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        assignee_id: Optional[str] = None,
        state_id: Optional[str] = None,
        due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new issue using the SDK."""
        try:
            def _create():
                kwargs = {
                    "title": title,
                    "team_id": team_id,
                    "description": description,
                    "priority": priority,
                    "assignee_id": assignee_id,
                    "state_id": state_id,
                    "due_date": due_date
                }
                kwargs = {k: v for k, v in kwargs.items() if v is not None}
                
                # The SDK expects teamName in some places, but we have team_id.
                # Let's check how create works in the SDK.
                # Looking at IssueManager.create, it takes LinearIssueInput.
                from linear_api.domain.issue_models import LinearIssueInput
                
                team = self.sdk.teams.get(team_id)
                issue_input = LinearIssueInput(
                    title=title,
                    teamName=team.name,
                    description=description,
                    priority=priority if priority is not None else 3,
                    assigneeId=assignee_id,
                    dueDate=due_date
                )
                if state_id:
                    # Resolve state name for the input if needed, or if it takes stateId
                    # The model has stateName
                    states = self.sdk.teams.get_states(team_id)
                    state = next((s for s in states if s.id == state_id), None)
                    if state:
                        issue_input.stateName = state.name
                
                issue = self.sdk.issues.create(issue_input)
                return issue.model_dump() if hasattr(issue, 'model_dump') else issue.__dict__
                
            return await asyncio.to_thread(_create)
        except Exception as e:
            logger.error(f"Error creating issue: {e}")
            raise LinearAPIException(str(e))

    async def update_issue(
        self,
        issue_id: str,
        **updates
    ) -> Dict[str, Any]:
        """Update an issue using the SDK."""
        try:
            def _update():
                from linear_api.domain.issue_models import LinearIssueUpdateInput
                update_input = LinearIssueUpdateInput(**updates)
                issue = self.sdk.issues.update(issue_id, update_input)
                return issue.model_dump() if hasattr(issue, 'model_dump') else issue.__dict__
                
            return await asyncio.to_thread(_update)
        except Exception as e:
            logger.error(f"Error updating issue {issue_id}: {e}")
            raise LinearAPIException(str(e))

    async def get_teams(self) -> List[Dict[str, Any]]:
        """Get all teams using the SDK."""
        try:
            def _get():
                teams_dict = self.sdk.teams.get_all()
                return [t.model_dump() if hasattr(t, 'model_dump') else t.__dict__ for t in teams_dict.values()]
                
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.error(f"Error fetching teams: {e}")
            return []

    async def get_viewer(self) -> Dict[str, Any]:
        """Get the authenticated user using the SDK."""
        try:
            def _get():
                # UserManager.get_viewer doesn't exist? In client.py it was self.users.get_viewer()
                # But in UserManager it's get_me()?
                # Let's check UserManager
                if hasattr(self.sdk.users, 'get_viewer'):
                    viewer = self.sdk.users.get_viewer()
                else:
                    viewer = self.sdk.users.get_me()
                return viewer.model_dump() if hasattr(viewer, 'model_dump') else viewer.__dict__
                
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.error(f"Error fetching viewer: {e}")
            return {}

    async def search_issues(self, query_text: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search issues using the SDK."""
        try:
            def _search():
                issues = self.sdk.issues.search(query_text, limit=limit)
                return [i.model_dump() if hasattr(i, 'model_dump') else i.__dict__ for i in issues]
                
            return await asyncio.to_thread(_search)
        except Exception as e:
            logger.error(f"Error searching issues: {e}")
            return []

    async def get_projects(self, team_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get projects using the SDK."""
        try:
            def _get():
                projects_dict = self.sdk.projects.get_all(team_id=team_id)
                return [p.model_dump() if hasattr(p, 'model_dump') else p.__dict__ for p in projects_dict.values()]
                
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.error(f"Error fetching projects: {e}")
            return []

    async def get_states(self, team_id: str) -> List[Dict[str, Any]]:
        """Get workflow states for a team using the SDK."""
        try:
            def _get():
                states = self.sdk.teams.get_states(team_id)
                return [s.model_dump() if hasattr(s, 'model_dump') else s.__dict__ for s in states]
                
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.error(f"Error fetching states for team {team_id}: {e}")
            return []

    async def get_issue_comments(self, issue_id: str) -> List[Dict[str, Any]]:
        """Get comments for an issue using the SDK."""
        try:
            def _get():
                comments = self.sdk.issues.get_comments(issue_id)
                return [c.model_dump() if hasattr(c, 'model_dump') else c.__dict__ for c in comments]
                
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.error(f"Error fetching comments for issue {issue_id}: {e}")
            return []

    async def add_comment(self, issue_id: str, body: str) -> Dict[str, Any]:
        """Add a comment to an issue using the SDK."""
        try:
            def _create():
                # SDK might have a direct issues.create_comment or we use self.sdk.execute_graphql
                # Looking at IssueManager (not implemented in the file I saw, but let's check)
                # Actually, many SDKs put it in CommentManager or under issues.
                # Let's try raw GraphQL if unsure, or check if CommentManager exists.
                query = """
                mutation CommentCreate($input: CommentCreateInput!) {
                    commentCreate(input: $input) {
                        success
                        comment {
                            id
                            body
                            createdAt
                        }
                    }
                }
                """
                variables = {"input": {"issueId": issue_id, "body": body}}
                result = self.sdk.execute_graphql(query, variables)
                return result.get("commentCreate", {}).get("comment", {})
                
            return await asyncio.to_thread(_create)
        except Exception as e:
            logger.error(f"Error adding comment to issue {issue_id}: {e}")
            raise LinearAPIException(str(e))

    async def get_cycles(
        self,
        team_id: Optional[str] = None,
        is_active: bool = True
    ) -> List[Dict[str, Any]]:
        """Get cycles using raw GraphQL via the SDK client."""
        try:
            query = """
            query GetCycles($filter: CycleFilter) {
                cycles(filter: $filter) {
                    nodes {
                        id
                        number
                        name
                        startsAt
                        endsAt
                        team {
                            id
                            name
                        }
                    }
                }
            }
            """
            filters = {}
            if is_active:
                filters["isActive"] = {"eq": True}
            if team_id:
                filters["team"] = {"id": {"eq": team_id}}
                
            variables = {"filter": filters} if filters else {}
            
            def _get():
                result = self.sdk.execute_graphql(query, variables)
                return result.get("cycles", {}).get("nodes", [])
                
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.error(f"Error fetching cycles: {e}")
            return []

    async def close(self):
        """No-op for the SDK client."""
        pass
