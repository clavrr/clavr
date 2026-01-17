"""
GitHub API Client

Lightweight client for GitHub REST API.
Used for fetching PR status and linking to Linear issues.
"""
import os
from typing import Dict, Any, List, Optional
import httpx

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# GitHub API base URL
GITHUB_API_URL = "https://api.github.com"


class GitHubClient:
    """
    GitHub REST API client.
    
    Uses a Personal Access Token (PAT) for authentication.
    Supports fetching PRs, checking status, and linking to Linear issues.
    """
    
    def __init__(self, token: Optional[str] = None):
        """
        Initialize GitHub client.
        
        Args:
            token: GitHub Personal Access Token. Defaults to GITHUB_TOKEN env var.
        """
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"
        
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    def is_configured(self) -> bool:
        """Check if GitHub is configured with a token."""
        return bool(self.token)
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=GITHUB_API_URL,
                headers=self.headers,
                timeout=30.0
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def get_user(self) -> Dict[str, Any]:
        """Get authenticated user info."""
        client = await self._get_client()
        response = await client.get("/user")
        response.raise_for_status()
        return response.json()
    
    async def get_user_repos(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Get repositories for authenticated user."""
        client = await self._get_client()
        response = await client.get(
            "/user/repos",
            params={"per_page": limit, "sort": "updated"}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_repo_prs(
        self, 
        owner: str, 
        repo: str,
        state: str = "open",
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get pull requests for a repository.
        
        Args:
            owner: Repository owner (user or org)
            repo: Repository name
            state: PR state ('open', 'closed', 'all')
            limit: Maximum PRs to return
        """
        client = await self._get_client()
        response = await client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": limit}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_pr(self, owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
        """Get a specific pull request."""
        client = await self._get_client()
        response = await client.get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
        response.raise_for_status()
        return response.json()
    
    async def get_pr_reviews(
        self, 
        owner: str, 
        repo: str, 
        pr_number: int
    ) -> List[Dict[str, Any]]:
        """Get reviews for a pull request."""
        client = await self._get_client()
        response = await client.get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        )
        response.raise_for_status()
        return response.json()
    
    async def get_pr_status(
        self, 
        owner: str, 
        repo: str, 
        pr_number: int
    ) -> Dict[str, Any]:
        """
        Get combined status for a PR (CI checks, reviews, etc.).
        
        Returns:
            Dict with:
            - mergeable: bool
            - review_status: 'approved', 'changes_requested', 'pending'
            - ci_status: 'success', 'failure', 'pending'
            - is_ready: bool (ready to merge)
        """
        pr = await self.get_pr(owner, repo, pr_number)
        reviews = await self.get_pr_reviews(owner, repo, pr_number)
        
        # Analyze review status
        review_states = [r.get('state', '').upper() for r in reviews]
        if 'APPROVED' in review_states and 'CHANGES_REQUESTED' not in review_states:
            review_status = 'approved'
        elif 'CHANGES_REQUESTED' in review_states:
            review_status = 'changes_requested'
        else:
            review_status = 'pending'
        
        # Check mergeable status (includes CI)
        mergeable = pr.get('mergeable', False)
        mergeable_state = pr.get('mergeable_state', 'unknown')
        
        ci_status = 'pending'
        if mergeable_state == 'clean':
            ci_status = 'success'
        elif mergeable_state in ['blocked', 'dirty']:
            ci_status = 'failure'
        
        return {
            'pr_number': pr_number,
            'title': pr.get('title', ''),
            'state': pr.get('state', ''),
            'mergeable': mergeable,
            'review_status': review_status,
            'ci_status': ci_status,
            'is_ready': mergeable and review_status == 'approved' and ci_status == 'success',
            'url': pr.get('html_url', ''),
            'author': pr.get('user', {}).get('login', ''),
        }
    
    async def search_prs_mentioning_issue(
        self, 
        owner: str, 
        repo: str, 
        issue_id: str
    ) -> List[Dict[str, Any]]:
        """
        Search for PRs that mention a Linear issue ID.
        
        Searches PR titles and bodies for the issue identifier (e.g., "ENG-123").
        """
        client = await self._get_client()
        
        # Search query: PRs in repo mentioning the issue ID
        query = f"repo:{owner}/{repo} is:pr {issue_id}"
        
        response = await client.get(
            "/search/issues",
            params={"q": query, "per_page": 10}
        )
        response.raise_for_status()
        
        results = response.json()
        return results.get('items', [])
