"""
Weekly Reasoning Digest Ghost Agent

Generates a weekly summary of all reasoning agent activity — surfacing
the most impactful patterns, decisions, and insights discovered by
Clavr's autonomous ghost agents over the past 7 days.

Designed to run every Monday at 7:00 AM UTC via Celery beat.

Sections:
  • Relationship changes (RelationshipGardener)
  • Commitment tracking (MeetingCloser → FollowUpTracker)
  • Customer health trends (CustomerHealthService)
  • Thread insights (ThreadAnalyzer)
  • PR bottleneck patterns (PRBottleneckDetector)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


# ──────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────

@dataclass
class ReasoningInsight:
    """A single insight surfaced by a reasoning agent."""
    agent: str
    summary: str
    detail: str = ""
    impact: str = "info"  # info, warning, critical
    count: int = 1
    timestamp: float = field(default_factory=time.time)


@dataclass
class WeeklyDigest:
    """Full weekly reasoning report for a user."""
    user_id: int = 0
    period_start: str = ""
    period_end: str = ""
    insights: List[ReasoningInsight] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    @property
    def has_content(self) -> bool:
        return len(self.insights) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "period": {
                "start": self.period_start,
                "end": self.period_end,
            },
            "insights": [
                {
                    "agent": i.agent,
                    "summary": i.summary,
                    "detail": i.detail,
                    "impact": i.impact,
                    "count": i.count,
                }
                for i in self.insights
            ],
            "stats": self.stats,
            "generated_at": self.generated_at,
        }


# ──────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────

class WeeklyReasoningDigestAgent:
    """
    Ghost Agent that generates weekly reasoning reports.

    Aggregates activity from all ghost agents to provide a high-level
    view of what Clavr discovered and acted on during the past week.
    """

    def __init__(self, config: Config):
        self.config = config

    async def generate_digest(
        self, user_id: int, db_session: Any = None
    ) -> WeeklyDigest:
        """
        Build a weekly reasoning digest for *user_id*.

        Each section collector fails independently — the digest
        includes whatever data is available.
        """
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        digest = WeeklyDigest(
            user_id=user_id,
            period_start=week_ago.isoformat(),
            period_end=now.isoformat(),
        )

        # Collect insights from all reasoning agents concurrently
        results = await asyncio.gather(
            self._relationship_insights(user_id, week_ago),
            self._commitment_insights(user_id, week_ago),
            self._health_trend_insights(user_id),
            self._thread_insights(user_id, week_ago, db_session),
            self._pr_pattern_insights(user_id),
            return_exceptions=True,
        )

        total_events = 0
        for result in results:
            if isinstance(result, list):
                digest.insights.extend(result)
                total_events += len(result)
            elif isinstance(result, Exception):
                logger.debug(
                    f"[WeeklyDigest] Section collection error: {result}"
                )

        # Sort by impact level (critical → warning → info)
        impact_order = {"critical": 0, "warning": 1, "info": 2}
        digest.insights.sort(
            key=lambda i: impact_order.get(i.impact, 3)
        )

        # Compute summary stats
        digest.stats = {
            "total_insights": len(digest.insights),
            "critical_count": sum(
                1 for i in digest.insights if i.impact == "critical"
            ),
            "warning_count": sum(
                1 for i in digest.insights if i.impact == "warning"
            ),
            "agents_reporting": len({
                i.agent for i in digest.insights
            }),
        }

        logger.info(
            f"[WeeklyDigest] Generated for user {user_id}: "
            f"{len(digest.insights)} insights "
            f"({digest.stats['critical_count']} critical, "
            f"{digest.stats['warning_count']} warnings)"
        )

        return digest

    # ── Section Collectors ─────────────────────

    async def _relationship_insights(
        self, user_id: int, since: datetime
    ) -> List[ReasoningInsight]:
        """Summarize relationship changes over the past week."""
        insights = []
        try:
            from src.services.indexing.graph.manager import (
                KnowledgeGraphManager,
            )

            graph = KnowledgeGraphManager(self.config)

            # Find relationships that weakened significantly
            query = """
            FOR edge IN COMMUNICATES_WITH
                FILTER edge._from == CONCAT("User/", @user_id)
                FILTER edge.strength < 0.3
                FILTER edge.interaction_count > 2
                LET person = DOCUMENT(edge._to)
                SORT edge.strength ASC
                LIMIT 5
                RETURN {
                    name: person.name,
                    email: person.email,
                    strength: edge.strength,
                    last_interaction: edge.last_interaction,
                    interaction_count: edge.interaction_count
                }
            """

            fading = await graph.execute_query(
                query, {"user_id": str(user_id)}
            )

            if fading:
                insights.append(ReasoningInsight(
                    agent="RelationshipGardener",
                    summary=f"{len(fading)} relationships fading",
                    detail=", ".join(
                        r.get("name", r.get("email", "?"))
                        for r in fading[:3]
                    ),
                    impact="warning" if len(fading) > 2 else "info",
                    count=len(fading),
                ))

            # Find strongest new relationships
            strong_query = """
            FOR edge IN COMMUNICATES_WITH
                FILTER edge._from == CONCAT("User/", @user_id)
                FILTER edge.strength > 0.7
                FILTER edge.interaction_count > 3
                LET person = DOCUMENT(edge._to)
                SORT edge.strength DESC
                LIMIT 3
                RETURN {
                    name: person.name,
                    strength: edge.strength,
                    meeting_count: edge.meeting_count,
                    email_count: edge.email_count,
                    slack_count: edge.slack_count
                }
            """

            strong = await graph.execute_query(
                strong_query, {"user_id": str(user_id)}
            )

            if strong:
                insights.append(ReasoningInsight(
                    agent="RelationshipGardener",
                    summary=f"{len(strong)} strong relationships maintained",
                    detail=", ".join(
                        r.get("name", "?") for r in strong
                    ),
                    impact="info",
                    count=len(strong),
                ))

        except Exception as e:
            logger.debug(f"[WeeklyDigest] Relationship insights failed: {e}")

        return insights

    async def _commitment_insights(
        self, user_id: int, since: datetime
    ) -> List[ReasoningInsight]:
        """Summarize commitment tracking over the past week."""
        insights = []
        try:
            from src.services.follow_up_tracker import FollowUpTracker

            tracker = FollowUpTracker(self.config)
            overdue = tracker.get_overdue(user_id)

            # Filter to meeting commitments
            meeting_overdue = [
                t for t in (overdue or [])
                if getattr(t, "signal_type", "") == "MEETING_COMMITMENT"
            ]

            if meeting_overdue:
                insights.append(ReasoningInsight(
                    agent="MeetingCloser",
                    summary=f"{len(meeting_overdue)} meeting commitments overdue",
                    detail="; ".join(
                        getattr(t, "subject", "?")[:40]
                        for t in meeting_overdue[:3]
                    ),
                    impact="critical" if len(meeting_overdue) > 3 else "warning",
                    count=len(meeting_overdue),
                ))

            # General overdue follow-ups
            other_overdue = [
                t for t in (overdue or [])
                if getattr(t, "signal_type", "") != "MEETING_COMMITMENT"
            ]
            if other_overdue:
                insights.append(ReasoningInsight(
                    agent="FollowUpTracker",
                    summary=f"{len(other_overdue)} email follow-ups overdue",
                    impact="warning" if len(other_overdue) > 5 else "info",
                    count=len(other_overdue),
                ))

        except Exception as e:
            logger.debug(f"[WeeklyDigest] Commitment insights failed: {e}")

        return insights

    async def _health_trend_insights(
        self, user_id: int
    ) -> List[ReasoningInsight]:
        """Summarize customer health trajectory changes."""
        insights = []
        try:
            from src.services.customer_health import (
                CustomerHealthService, HealthTrend,
            )

            health = CustomerHealthService(self.config)
            at_risk = await health.get_at_risk_accounts(user_id)

            if at_risk:
                declining = [
                    a for a in at_risk
                    if a.trend == HealthTrend.DECLINING
                ]
                if declining:
                    insights.append(ReasoningInsight(
                        agent="CustomerHealth",
                        summary=f"{len(declining)} accounts declining in health",
                        detail=", ".join(
                            a.account for a in declining[:3]
                        ),
                        impact="critical",
                        count=len(declining),
                    ))

                stable_risk = [
                    a for a in at_risk
                    if a.trend == HealthTrend.STABLE
                ]
                if stable_risk:
                    insights.append(ReasoningInsight(
                        agent="CustomerHealth",
                        summary=f"{len(stable_risk)} at-risk accounts (stable but low)",
                        impact="warning",
                        count=len(stable_risk),
                    ))

        except Exception as e:
            logger.debug(f"[WeeklyDigest] Health insights failed: {e}")

        return insights

    async def _thread_insights(
        self, user_id: int, since: datetime, db_session: Any = None
    ) -> List[ReasoningInsight]:
        """Summarize decisions and issues detected from threads."""
        insights = []

        if not db_session:
            return insights

        try:
            from sqlalchemy import select
            from src.database.models import GhostDraft

            # Count ghost drafts created this week
            stmt = (
                select(GhostDraft)
                .where(GhostDraft.user_id == user_id)
                .where(GhostDraft.created_at >= since)
            )
            result = await db_session.execute(stmt)
            drafts = result.scalars().all()

            if drafts:
                approved = [d for d in drafts if d.status == "approved"]
                pending = [d for d in drafts if d.status == "draft"]

                insights.append(ReasoningInsight(
                    agent="ThreadAnalyzer",
                    summary=(
                        f"{len(drafts)} thread issues detected "
                        f"({len(approved)} approved, {len(pending)} pending)"
                    ),
                    impact="info",
                    count=len(drafts),
                ))

        except Exception as e:
            logger.debug(f"[WeeklyDigest] Thread insights failed: {e}")

        return insights

    async def _pr_pattern_insights(
        self, user_id: int
    ) -> List[ReasoningInsight]:
        """Summarize recurring PR bottleneck patterns."""
        insights = []
        try:
            import os
            from src.features.ghost.pr_bottleneck_detector import (
                PRBottleneckDetector,
            )
            from src.integrations.github import GitHubService

            owner = os.getenv("GITHUB_OWNER", "")
            repo = os.getenv("GITHUB_REPO", "")
            if not (owner and repo):
                return insights

            github = GitHubService(self.config)
            if not github.is_available:
                return insights

            detector = PRBottleneckDetector(self.config, github)
            report = await detector.detect_bottlenecks(user_id, owner, repo)

            if report.bottlenecks:
                critical = [
                    b for b in report.bottlenecks if b.severity == "critical"
                ]
                insights.append(ReasoningInsight(
                    agent="PRBottleneckDetector",
                    summary=(
                        f"{len(report.bottlenecks)} PR bottlenecks "
                        f"({len(critical)} critical)"
                    ),
                    impact="warning" if critical else "info",
                    count=len(report.bottlenecks),
                ))

            await github.close()

        except Exception as e:
            logger.debug(f"[WeeklyDigest] PR insights failed: {e}")

        return insights

    # ── Formatting ────────────────────────────

    def format_notification(self, digest: WeeklyDigest) -> str:
        """Format the weekly digest as a readable notification message."""
        lines = [
            "**Weekly Reasoning Report**",
            f"*{digest.period_start[:10]} → {digest.period_end[:10]}*",
            "",
        ]

        if not digest.has_content:
            lines.append(
                "Quiet week -- no notable patterns detected. "
                "All systems running smoothly."
            )
            return "\n".join(lines)

        # Stats summary
        stats = digest.stats
        lines.append(
            f"**{stats.get('total_insights', 0)} insights** from "
            f"**{stats.get('agents_reporting', 0)} agents**"
        )

        if stats.get("critical_count"):
            lines.append(
                f"  [CRITICAL] {stats['critical_count']} critical items need attention"
            )
        if stats.get("warning_count"):
            lines.append(
                f"  [WARNING] {stats['warning_count']} warnings to review"
            )
        lines.append("")

        # Group by impact
        impact_icons = {
            "critical": "[CRITICAL]",
            "warning": "[WARNING]",
            "info": "[OK]",
        }

        for insight in digest.insights:
            icon = impact_icons.get(insight.impact, "[INFO]")
            agent_short = insight.agent.replace("Agent", "").strip()
            lines.append(
                f"{icon} **{agent_short}**: {insight.summary}"
            )
            if insight.detail:
                lines.append(f"   {insight.detail}")

        lines.append("")
        lines.append(
            "*— Generated by Clavr's autonomous reasoning agents*"
        )

        return "\n".join(lines)
