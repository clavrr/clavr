"""
Cycle Planner Agent

Ghost Agent that analyzes Linear sprints and suggests issue deferrals.

Uses:
- Linear API for current cycle issues
- GitHub API for PR status
- Slack sentiment (from ThreadAnalyzer) for issue health
- Knowledge Graph for linked data

Runs weekly to prepare sprint recommendations.
"""
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


@dataclass
class IssueRecommendation:
    """Recommendation for a sprint issue."""
    issue_id: str
    issue_title: str
    priority: int
    recommendation: str  # 'keep', 'defer', 'promote'
    reason: str
    confidence: float
    pr_status: Optional[str] = None
    sentiment_signal: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass  
class CyclePlanResult:
    """Result of cycle planning analysis."""
    cycle_id: str
    cycle_name: str
    total_issues: int
    defer_suggestions: List[IssueRecommendation]
    keep_suggestions: List[IssueRecommendation]
    promote_suggestions: List[IssueRecommendation]
    summary: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'cycle_id': self.cycle_id,
            'cycle_name': self.cycle_name,
            'total_issues': self.total_issues,
            'defer_suggestions': [r.to_dict() for r in self.defer_suggestions],
            'keep_suggestions': [r.to_dict() for r in self.keep_suggestions],
            'promote_suggestions': [r.to_dict() for r in self.promote_suggestions],
            'summary': self.summary,
        }


class CyclePlannerAgent:
    """
    Ghost Agent for sprint/cycle planning.
    
    Analyzes current cycle issues and suggests:
    - Which issues to defer to next sprint (blocked/behind)
    - Which issues to keep (on track)
    - Which issues to promote (ready to complete)
    
    Uses multiple signals:
    1. GitHub PR status (ready/blocked/pending)
    2. Slack sentiment (positive/negative mentions)
    3. Linear priority and deadline proximity
    """
    
    def __init__(
        self, 
        config: Config,
        linear_service: Any = None,
        github_service: Any = None,
        graph_manager: Any = None
    ):
        self.config = config
        self.linear = linear_service
        self.github = github_service
        self.graph = graph_manager
        
        # Configuration for GitHub repo (can be set per-user)
        self.github_owner: Optional[str] = None
        self.github_repo: Optional[str] = None
    
    def set_github_repo(self, owner: str, repo: str):
        """Set GitHub repository for PR lookups."""
        self.github_owner = owner
        self.github_repo = repo
        if self.github:
            self.github.set_default_repo(owner, repo)
    
    async def analyze_current_cycle(
        self, 
        user_id: int,
        team_name: Optional[str] = None
    ) -> Optional[CyclePlanResult]:
        """
        Analyze the current sprint/cycle and generate recommendations.
        
        Args:
            user_id: User ID for context
            team_name: Linear team name (uses first team if not specified)
            
        Returns:
            CyclePlanResult with recommendations
        """
        try:
            # 1. Initialize services if needed
            if not self.linear:
                from src.integrations.linear.service import LinearService
                self.linear = LinearService(self.config)
            
            if not self.linear.is_available():
                logger.warning("[CyclePlanner] Linear not available")
                return None
            
            # 2. Get active cycle
            cycle = await self.linear.get_active_cycle(team_name)
            if not cycle:
                logger.info("[CyclePlanner] No active cycle found")
                return None
            
            cycle_id = cycle.get('id', '')
            cycle_name = cycle.get('name', 'Current Sprint')
            
            logger.info(f"[CyclePlanner] Analyzing cycle: {cycle_name}")
            
            # 3. Get issues in this cycle
            issues = cycle.get('issues', {}).get('nodes', [])
            if not issues:
                # Fallback: get team issues
                issues = await self.linear.get_team_issues(team_name, limit=50)
            
            if not issues:
                return CyclePlanResult(
                    cycle_id=cycle_id,
                    cycle_name=cycle_name,
                    total_issues=0,
                    defer_suggestions=[],
                    keep_suggestions=[],
                    promote_suggestions=[],
                    summary="No issues in current cycle."
                )
            
            # 4. Analyze each issue
            defer_list = []
            keep_list = []
            promote_list = []
            
            for issue in issues:
                recommendation = await self._analyze_issue(issue, user_id)
                
                if recommendation.recommendation == 'defer':
                    defer_list.append(recommendation)
                elif recommendation.recommendation == 'promote':
                    promote_list.append(recommendation)
                else:
                    keep_list.append(recommendation)
            
            # 5. Build summary
            summary = self._build_summary(
                cycle_name, 
                len(issues), 
                len(defer_list), 
                len(promote_list)
            )
            
            return CyclePlanResult(
                cycle_id=cycle_id,
                cycle_name=cycle_name,
                total_issues=len(issues),
                defer_suggestions=defer_list,
                keep_suggestions=keep_list,
                promote_suggestions=promote_list,
                summary=summary,
            )
            
        except Exception as e:
            logger.error(f"[CyclePlanner] Error analyzing cycle: {e}", exc_info=True)
            return None
    
    async def _analyze_issue(
        self, 
        issue: Dict[str, Any],
        user_id: int
    ) -> IssueRecommendation:
        """Analyze a single issue and generate recommendation."""
        issue_id = issue.get('identifier', issue.get('id', ''))
        issue_title = issue.get('title', '')[:60]
        priority = issue.get('priority', 0)
        state = issue.get('state', {}).get('name', '')
        
        pr_status = None
        github_signal = None
        sentiment_signal = None
        
        # 1. Check GitHub PR status
        if self.github and self.github.is_available:
            try:
                analysis = await self.github.analyze_issue_for_deferral(
                    issue_id, 
                    self.github_owner, 
                    self.github_repo
                )
                pr_status = analysis.get('recommendation')
                github_signal = analysis.get('reason')
            except Exception as e:
                logger.debug(f"[CyclePlanner] GitHub check failed for {issue_id}: {e}")
        
        # 2. Check Slack sentiment (from Knowledge Graph)
        if self.graph:
            try:
                sentiment_signal = await self._get_sentiment_signal(issue_id, user_id)
            except Exception as e:
                logger.debug(f"[CyclePlanner] Sentiment check failed for {issue_id}: {e}")
        
        # 3. Make recommendation based on signals
        recommendation, reason, confidence = self._make_recommendation(
            issue_id=issue_id,
            priority=priority,
            state=state,
            pr_status=pr_status,
            github_signal=github_signal,
            sentiment_signal=sentiment_signal,
        )
        
        return IssueRecommendation(
            issue_id=issue_id,
            issue_title=issue_title,
            priority=priority,
            recommendation=recommendation,
            reason=reason,
            confidence=confidence,
            pr_status=pr_status,
            sentiment_signal=sentiment_signal,
        )
    
    async def _get_sentiment_signal(
        self, 
        issue_id: str, 
        user_id: int
    ) -> Optional[str]:
        """Query Knowledge Graph for Slack sentiment about an issue."""
        if not self.graph:
            return None
        
        try:
            # Search for messages mentioning this issue
            # This would query the graph for Slack messages with this issue ID
            query = f"""
                FOR msg IN slack_messages
                    FILTER msg.user_id == @user_id
                    FILTER CONTAINS(LOWER(msg.text), LOWER(@issue_id))
                    SORT msg.timestamp DESC
                    LIMIT 5
                    RETURN msg
            """
            
            # For now, return None - full implementation would analyze sentiment
            # of retrieved messages
            return None
            
        except Exception as e:
            logger.debug(f"[CyclePlanner] Graph query failed: {e}")
            return None
    
    def _make_recommendation(
        self,
        issue_id: str,
        priority: int,
        state: str,
        pr_status: Optional[str],
        github_signal: Optional[str],
        sentiment_signal: Optional[str],
    ) -> tuple[str, str, float]:
        """
        Make recommendation based on all signals.
        
        Returns:
            (recommendation, reason, confidence)
        """
        # High priority handling
        if priority >= 3:  # Urgent/High
            if pr_status == 'keep' or state == 'In Review':
                return ('promote', f'High priority {issue_id} is on track', 0.8)
            elif pr_status == 'defer':
                return ('defer', f'{issue_id}: {github_signal}', 0.7)
            else:
                return ('keep', f'High priority {issue_id} needs attention', 0.6)
        
        # GitHub-based decisions
        if pr_status == 'defer':
            return ('defer', github_signal or 'PR blocked', 0.75)
        
        if pr_status == 'keep' and github_signal and 'ready' in github_signal.lower():
            return ('promote', github_signal, 0.85)
        
        # Sentiment-based (if negative mentions found)
        if sentiment_signal and 'blocked' in sentiment_signal.lower():
            return ('defer', 'Blocked per Slack discussion', 0.65)
        
        # Default: keep with low confidence
        return ('keep', 'No signals suggest deferral', 0.5)
    
    def _build_summary(
        self, 
        cycle_name: str, 
        total: int, 
        defer_count: int, 
        promote_count: int
    ) -> str:
        """Build human-readable summary."""
        if defer_count == 0 and promote_count == 0:
            return f"{cycle_name}: All {total} issues on track. No changes suggested."
        
        parts = []
        if defer_count > 0:
            parts.append(f"{defer_count} issue(s) to defer")
        if promote_count > 0:
            parts.append(f"{promote_count} issue(s) ready to complete")
        
        return f"{cycle_name}: {', '.join(parts)} out of {total} total."


async def run_cycle_planning(
    user_id: int,
    config: Config,
    team_name: Optional[str] = None,
    github_owner: Optional[str] = None,
    github_repo: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to run cycle planning.
    Called by Celery task.
    """
    from src.integrations.linear.service import LinearService
    from src.integrations.github.service import GitHubService
    
    linear = LinearService(config)
    github = GitHubService(config) if GitHubService else None
    
    agent = CyclePlannerAgent(config, linear, github)
    
    if github_owner and github_repo:
        agent.set_github_repo(github_owner, github_repo)
    
    result = await agent.analyze_current_cycle(user_id, team_name)
    
    if result:
        return result.to_dict()
    return None
