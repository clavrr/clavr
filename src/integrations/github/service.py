"""
GitHub Service

High-level service for GitHub operations.
Provides business logic for cycle planning integration.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from src.utils.logger import setup_logger
from src.utils.config import Config
from .client import GitHubClient

logger = setup_logger(__name__)


@dataclass
class PRStatus:
    """Status of a PR linked to a Linear issue."""
    issue_id: str
    pr_number: int
    pr_title: str
    pr_url: str
    is_ready: bool
    review_status: str  # 'approved', 'changes_requested', 'pending'
    ci_status: str  # 'success', 'failure', 'pending'
    author: str


class GitHubService:
    """
    High-level GitHub service for Cycle Planner integration.
    
    Provides:
    - PR status tracking for Linear issues
    - Sprint readiness analysis
    - Issue-PR linking
    """
    
    def __init__(self, config: Config, token: Optional[str] = None):
        """
        Initialize GitHub service.
        
        Args:
            config: Application config
            token: GitHub PAT (optional, uses GITHUB_TOKEN env var)
        """
        self.config = config
        self.client = GitHubClient(token)
        self._default_repo: Optional[tuple] = None
    
    @property
    def is_available(self) -> bool:
        """Check if GitHub is configured."""
        return self.client.is_configured
    
    def set_default_repo(self, owner: str, repo: str):
        """Set default repository for operations."""
        self._default_repo = (owner, repo)
    
    async def get_pr_status_for_issue(
        self, 
        issue_id: str,
        owner: Optional[str] = None,
        repo: Optional[str] = None
    ) -> Optional[PRStatus]:
        """
        Get PR status for a Linear issue.
        
        Searches for PRs mentioning the issue ID in title/body.
        
        Args:
            issue_id: Linear issue identifier (e.g., "ENG-123")
            owner: GitHub repo owner (uses default if not specified)
            repo: GitHub repo name (uses default if not specified)
            
        Returns:
            PRStatus if found, None otherwise
        """
        if not self.is_available:
            logger.warning("[GitHub] Not configured, skipping PR status check")
            return None
        
        # Use default repo if not specified
        if not owner or not repo:
            if self._default_repo:
                owner, repo = self._default_repo
            else:
                logger.warning("[GitHub] No repository specified")
                return None
        
        try:
            # Search for PRs mentioning this issue
            prs = await self.client.search_prs_mentioning_issue(owner, repo, issue_id)
            
            if not prs:
                return None
            
            # Get the first (most recent) matching PR
            pr = prs[0]
            pr_number = pr.get('number')
            
            # Get detailed status
            status = await self.client.get_pr_status(owner, repo, pr_number)
            
            return PRStatus(
                issue_id=issue_id,
                pr_number=pr_number,
                pr_title=status.get('title', ''),
                pr_url=status.get('url', ''),
                is_ready=status.get('is_ready', False),
                review_status=status.get('review_status', 'pending'),
                ci_status=status.get('ci_status', 'pending'),
                author=status.get('author', ''),
            )
            
        except Exception as e:
            logger.error(f"[GitHub] Error getting PR status for {issue_id}: {e}")
            return None
    
    async def get_sprint_pr_summary(
        self,
        issue_ids: List[str],
        owner: Optional[str] = None,
        repo: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get PR summary for a list of sprint issues.
        
        Returns:
            Dict with summary stats and per-issue status
        """
        statuses = []
        ready_count = 0
        blocked_count = 0
        no_pr_count = 0
        
        for issue_id in issue_ids:
            status = await self.get_pr_status_for_issue(issue_id, owner, repo)
            
            if status:
                statuses.append(status)
                if status.is_ready:
                    ready_count += 1
                elif status.review_status == 'changes_requested' or status.ci_status == 'failure':
                    blocked_count += 1
            else:
                no_pr_count += 1
        
        return {
            'total_issues': len(issue_ids),
            'with_prs': len(statuses),
            'ready_to_merge': ready_count,
            'blocked': blocked_count,
            'no_pr': no_pr_count,
            'statuses': statuses,
        }
    
    async def analyze_issue_for_deferral(
        self, 
        issue_id: str,
        owner: Optional[str] = None,
        repo: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze if an issue should be deferred to next sprint.
        
        Considers:
        - PR status (blocked PRs suggest deferral)
        - Review status (changes requested = likely delay)
        - CI status (failing CI = needs work)
        
        Returns:
            Dict with recommendation and reasoning
        """
        status = await self.get_pr_status_for_issue(issue_id, owner, repo)
        
        if not status:
            return {
                'issue_id': issue_id,
                'recommendation': 'unknown',
                'reason': 'No linked PR found',
                'confidence': 0.3,
            }
        
        # Analyze based on status
        if status.is_ready:
            return {
                'issue_id': issue_id,
                'recommendation': 'keep',
                'reason': f'PR #{status.pr_number} is ready to merge',
                'confidence': 0.9,
                'pr_url': status.pr_url,
            }
        
        if status.ci_status == 'failure':
            return {
                'issue_id': issue_id,
                'recommendation': 'defer',
                'reason': f'PR #{status.pr_number} has failing CI',
                'confidence': 0.7,
                'pr_url': status.pr_url,
            }
        
        if status.review_status == 'changes_requested':
            return {
                'issue_id': issue_id,
                'recommendation': 'defer',
                'reason': f'PR #{status.pr_number} needs changes',
                'confidence': 0.8,
                'pr_url': status.pr_url,
            }
        
        # Pending review - could go either way
        return {
            'issue_id': issue_id,
            'recommendation': 'keep',
            'reason': f'PR #{status.pr_number} awaiting review',
            'confidence': 0.5,
            'pr_url': status.pr_url,
        }
    
    async def close(self):
        """Close the client."""
        await self.client.close()
