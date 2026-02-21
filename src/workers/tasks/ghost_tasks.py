"""
Ghost Tasks

Celery tasks for the Ghost Service (Deep Work Shield).
"""
from typing import Dict, Any
from datetime import datetime

from ..celery_app import celery_app
from ..base_task import IdempotentTask
from src.utils.logger import setup_logger
from src.database import get_db_context
from src.database.models import User
from src.services.ghost.service import GhostService
from src.utils.config import load_config

logger = setup_logger(__name__)

@celery_app.task(base=IdempotentTask, bind=True)
def run_ghost_checks(self) -> Dict[str, Any]:
    """
    Periodic task to run Ghost Checks for all users.
    """
    logger.info("Starting global Ghost Check cycle")
    
    results = {
        "processed": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        config = load_config()
        
        with get_db_context() as db:
            users = db.query(User).all()
            ghost_service = GhostService(db, config)
            
            for user in users:
                try:
                    # We run this synchronously inside the task for now since GhostService methods are async
                    # But Celery tasks are sync unless we use async_to_sync or run loop.
                    # GhostService uses 'async def'. We need to run it.
                    import asyncio
                    
                    # Create a new loop for this sync blocking task
                    # Or better, us asyncio.run
                    asyncio.run(ghost_service.run_ghost_check(user.id))
                    results["processed"] += 1
                except Exception as e:
                    logger.error(f"Ghost check failed for user {user.id}: {e}")
                    results["errors"] += 1
            
        return results
        
    except Exception as e:
        logger.error(f"Global ghost check failed: {e}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def send_daily_email_digest(self) -> Dict[str, Any]:
    """
    Daily task to send email digests to all users.
    """
    logger.info("Starting daily email digest cycle")
    
    results = {
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        config = load_config()
        
        with get_db_context() as db:
            users = db.query(User).all()
            
            from src.features.ghost.email_digest import EmailDigestAgent
            
            for user in users:
                try:
                    digest_agent = EmailDigestAgent(db, config)
                    import asyncio
                    asyncio.run(digest_agent.send_digest(user.id))
                    results["sent"] += 1
                except Exception as e:
                    logger.error(f"Email digest failed for user {user.id}: {e}")
                    results["errors"] += 1
        
        logger.info(f"Digest cycle complete: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Global email digest failed: {e}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def send_reconnect_suggestions(self) -> Dict[str, Any]:
    """
    Weekly task to send relationship reconnect suggestions.
    """
    logger.info("Starting weekly reconnect suggestions cycle")
    
    results = {
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        config = load_config()
        
        with get_db_context() as db:
            users = db.query(User).all()
            
            from src.features.ghost.relationship_gardener import RelationshipGardener
            
            for user in users:
                try:
                    gardener = RelationshipGardener(db, config)
                    import asyncio
                    asyncio.run(gardener.send_reconnect_suggestions(user.id))
                    results["sent"] += 1
                except Exception as e:
                    logger.error(f"Reconnect suggestions failed for user {user.id}: {e}")
                    results["errors"] += 1
        
        logger.info(f"Reconnect cycle complete: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Global reconnect suggestions failed: {e}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def check_deep_work_shield(self) -> Dict[str, Any]:
    """
    Periodic task (every 30 min) to check if Deep Work Shield should activate.
    
    For each user:
    - Checks open Linear ticket count
    - Checks calendar availability
    - If conditions met, activates shield (calendar block + Slack status)
    """
    logger.info("Starting Deep Work Shield check cycle")
    
    results = {
        "processed": 0,
        "activated": 0,
        "skipped": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        config = load_config()
        
        with get_db_context() as db:
            users = db.query(User).all()
            
            from src.features.protection.deep_work_shield import DeepWorkShieldAgent
            from src.core.credential_provider import CredentialFactory
            
            factory = CredentialFactory(config)
            
            for user in users:
                try:
                    import asyncio
                    
                    agent = DeepWorkShieldAgent(config, factory)
                    result = asyncio.run(agent.check_and_activate(user.id, db))
                    
                    results["processed"] += 1
                    if result.get("status") == "activated":
                        results["activated"] += 1
                        logger.info(f"[DeepWorkShield] Activated for user {user.id}")
                    else:
                        results["skipped"] += 1
                        
                except Exception as e:
                    logger.error(f"Deep Work Shield check failed for user {user.id}: {e}")
                    results["errors"] += 1
        
        logger.info(f"Deep Work Shield cycle complete: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Global Deep Work Shield check failed: {e}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def run_cycle_planning(self) -> Dict[str, Any]:
    """
    Weekly task to analyze Linear sprints and suggest issue deferrals.
    
    Killer Feature #3: Cycle Planner
    
    For each user:
    - Gets active Linear cycle/sprint
    - Checks GitHub PR status for each issue
    - Analyzes Slack sentiment
    - Suggests which issues to defer/promote
    - Sends report via notification
    """
    logger.info("Starting weekly Cycle Planning analysis")
    
    results = {
        "processed": 0,
        "reports_sent": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        config = load_config()
        
        with get_db_context() as db:
            users = db.query(User).all()
            
            from src.features.ghost.cycle_planner import CyclePlannerAgent
            from src.integrations.linear.service import LinearService
            from src.integrations.github import GitHubService
            from src.services.notifications import (
                NotificationService, 
                NotificationRequest,
                NotificationType,
                NotificationPriority,
            )
            
            for user in users:
                try:
                    import asyncio
                    
                    # Initialize services
                    linear = LinearService(config)
                    github = GitHubService(config)
                    
                    agent = CyclePlannerAgent(config, linear, github)
                    
                    # Run analysis
                    result = asyncio.run(agent.analyze_current_cycle(user.id))
                    
                    if result and (result.defer_suggestions or result.promote_suggestions):
                        # Build notification message
                        message = _build_cycle_report(result)
                        
                        # Send notification
                        notification_service = NotificationService(db)
                        request = NotificationRequest(
                            user_id=user.id,
                            title=f"Sprint Analysis: {result.cycle_name}",
                            message=message,
                            notification_type=NotificationType.SYSTEM,
                            priority=NotificationPriority.NORMAL,
                            icon="bar-chart",
                            expires_in_hours=168,  # 1 week
                        )
                        
                        asyncio.run(notification_service.send_notification(request))
                        results["reports_sent"] += 1
                    
                    results["processed"] += 1
                    
                except Exception as e:
                    logger.error(f"Cycle planning failed for user {user.id}: {e}")
                    results["errors"] += 1
        
        logger.info(f"Cycle Planning complete: {results}")
        return results
        
    except Exception as e:
        logger.error(f"Global Cycle Planning failed: {e}")
        raise


def _build_cycle_report(result) -> str:
    """Build human-readable cycle planning report."""
    lines = [result.summary, ""]
    
    if result.defer_suggestions:
        lines.append("**Suggested to Defer:**")
        for r in result.defer_suggestions[:5]:
            lines.append(f"• {r.issue_id}: {r.reason}")
        lines.append("")
    
    if result.promote_suggestions:
        lines.append("**Ready to Complete:**")
        for r in result.promote_suggestions[:5]:
            lines.append(f"• {r.issue_id}: {r.reason}")
    
    return "\n".join(lines)


# Module-level instance cache for ghost tasks (Celery workers are
# process-scoped, so this avoids per-task Redis reconnection overhead).
_ghost_cache: Dict[str, Any] = {}


@celery_app.task(base=IdempotentTask, bind=True)
def sweep_follow_ups(self) -> Dict[str, Any]:
    """
    Periodic task to advance overdue follow-ups through the escalation chain.

    Calls FollowUpTracker.run_sweep() for each user, which handles:
    - State advancement (FLAGGED → REMINDED_ONCE → REMINDED_TWICE → ESCALATED)
    - Auto-drafting context-aware follow-up replies via EmailAutoResponder
    - Slack DM escalation for overdue threads
    - Revenue-signal-proportional timing (high-value deals escalate faster)
    """
    logger.info("Starting Follow-Up sweep cycle")

    results = {
        "processed": 0,
        "advanced": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        config = load_config()
        from src.services.follow_up_tracker import FollowUpTracker

        cache_key = f"tracker_{id(config)}"
        if cache_key not in _ghost_cache:
            _ghost_cache[cache_key] = FollowUpTracker(config)
        tracker = _ghost_cache[cache_key]

        with get_db_context() as db:
            users = db.query(User).all()

            for user in users:
                try:
                    import asyncio
                    summary = asyncio.run(tracker.run_sweep(user.id))
                    results["advanced"] += summary.get("threads_advanced", 0)
                    results["processed"] += 1
                except Exception as e:
                    logger.error(f"Follow-up sweep failed for user {user.id}: {e}")
                    results["errors"] += 1

        logger.info(f"Follow-Up sweep complete: {results}")
        return results

    except Exception as e:
        logger.error(f"Global follow-up sweep failed: {e}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def run_meeting_closer(self) -> Dict[str, Any]:
    """
    Periodic task to process recently-ended meetings.

    Looks at calendar events that ended in the last 30 minutes,
    runs MeetingCloser.handle_event for each applicable event.
    """
    logger.info("Starting Meeting Closer cycle")

    results = {
        "processed": 0,
        "action_items_created": 0,
        "skipped": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        config = load_config()
        from src.features.ghost.meeting_closer import MeetingCloser
        from src.core.credential_provider import CredentialFactory
        from src.integrations.google_calendar.service import CalendarService
        import asyncio

        factory = CredentialFactory(config)

        with get_db_context() as db:
            users = db.query(User).all()

            for user in users:
                try:
                    creds = factory.get_credentials(user.id, provider="google_calendar")
                    if not creds:
                        results["skipped"] += 1
                        continue

                    cal_svc = CalendarService(config, credentials=creds)

                    # Get events that ended in the last 35 minutes
                    from datetime import timedelta
                    now = datetime.utcnow()
                    window_start = now - timedelta(minutes=35)

                    events = cal_svc.list_events(
                        start_date=window_start.isoformat() + "Z",
                        end_date=now.isoformat() + "Z",
                        max_results=10,
                    )

                    if not events:
                        results["skipped"] += 1
                        continue

                    closer = MeetingCloser(db, config)

                    for event in events:
                        try:
                            result = asyncio.run(
                                closer.handle_event("calendar.event.ended", event, user.id)
                            )
                            if result and result.get("action_items"):
                                results["action_items_created"] += len(result["action_items"])
                            results["processed"] += 1
                        except Exception as e:
                            logger.warning(f"Meeting closer failed for event: {e}")
                            results["errors"] += 1

                except Exception as e:
                    logger.error(f"Meeting closer failed for user {user.id}: {e}")
                    results["errors"] += 1

        logger.info(f"Meeting Closer cycle complete: {results}")
        return results

    except Exception as e:
        logger.error(f"Global Meeting Closer failed: {e}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def check_pr_bottlenecks(self) -> Dict[str, Any]:
    """
    Periodic task to detect PR review bottlenecks.

    For each user with GitHub configured, scans open PRs
    and sends a notification if bottlenecks are found.
    """
    logger.info("Starting PR Bottleneck check cycle")

    results = {
        "processed": 0,
        "bottlenecks_found": 0,
        "notifications_sent": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        config = load_config()
        from src.features.ghost.pr_bottleneck_detector import PRBottleneckDetector
        from src.integrations.github import GitHubService
        from src.services.notifications import (
            NotificationService,
            NotificationRequest,
            NotificationType,
            NotificationPriority,
        )
        import asyncio
        import os

        # Skip if no GitHub token configured
        if not os.getenv("GITHUB_TOKEN"):
            logger.info("[PRBottleneck] No GITHUB_TOKEN set, skipping")
            return results

        with get_db_context() as db:
            users = db.query(User).all()

            for user in users:
                try:
                    github = GitHubService(config)
                    if not github.is_available:
                        continue

                    detector = PRBottleneckDetector(config, github)

                    # Use default repo from env or user config
                    owner = os.getenv("GITHUB_OWNER", "")
                    repo = os.getenv("GITHUB_REPO", "")
                    if not owner or not repo:
                        continue

                    report = asyncio.run(
                        detector.detect_bottlenecks(user.id, owner, repo)
                    )
                    results["processed"] += 1
                    results["bottlenecks_found"] += len(report.bottlenecks)

                    message = detector.format_notification(report)
                    if message:
                        notification_service = NotificationService(db)
                        request = NotificationRequest(
                            user_id=user.id,
                            title="PR Bottleneck Alert",
                            message=message,
                            notification_type=NotificationType.SYSTEM,
                            priority=NotificationPriority.NORMAL,
                            icon="git-pull-request",
                            expires_in_hours=24,
                        )
                        asyncio.run(notification_service.send_notification(request))
                        results["notifications_sent"] += 1

                    asyncio.run(github.close())

                except Exception as e:
                    logger.error(f"PR bottleneck check failed for user {user.id}: {e}")
                    results["errors"] += 1

        logger.info(f"PR Bottleneck check complete: {results}")
        return results

    except Exception as e:
        logger.error(f"Global PR Bottleneck check failed: {e}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def run_sprint_retro(self) -> Dict[str, Any]:
    """
    Weekly task to generate sprint retrospective summaries.

    Runs Friday afternoon after the Cycle Planner.
    Uses Linear cycle data, GitHub PR stats, and velocity trends.
    """
    logger.info("Starting Sprint Retro generation")

    results = {
        "processed": 0,
        "retros_sent": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        config = load_config()
        from src.features.ghost.sprint_retro_summarizer import SprintRetroSummarizer
        from src.integrations.linear.service import LinearService
        from src.integrations.github import GitHubService
        from src.services.sprint_velocity import SprintVelocityService
        from src.services.notifications import (
            NotificationService,
            NotificationRequest,
            NotificationType,
            NotificationPriority,
        )
        import asyncio

        with get_db_context() as db:
            users = db.query(User).all()

            for user in users:
                try:
                    linear = LinearService(config, user_id=user.id)
                    github = GitHubService(config)
                    velocity = SprintVelocityService(config)

                    summarizer = SprintRetroSummarizer(
                        config, linear, github, velocity,
                    )

                    report = asyncio.run(
                        summarizer.generate_retro(user.id)
                    )

                    if report:
                        message = summarizer.format_notification(report)
                        notification_service = NotificationService(db)
                        request = NotificationRequest(
                            user_id=user.id,
                            title=f"Sprint Retro: {report.cycle_name}",
                            message=message,
                            notification_type=NotificationType.SYSTEM,
                            priority=NotificationPriority.NORMAL,
                            icon="bar-chart-2",
                            expires_in_hours=168,  # 1 week
                        )
                        asyncio.run(notification_service.send_notification(request))
                        results["retros_sent"] += 1

                    results["processed"] += 1

                    asyncio.run(linear.close())
                    asyncio.run(github.close())

                except Exception as e:
                    logger.error(f"Sprint retro failed for user {user.id}: {e}")
                    results["errors"] += 1

        logger.info(f"Sprint Retro generation complete: {results}")
        return results

    except Exception as e:
        logger.error(f"Global Sprint Retro generation failed: {e}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def send_morning_digest(self) -> Dict[str, Any]:
    """
    Daily task to send a comprehensive morning digest.

    Aggregates calendar, follow-ups, PR bottlenecks, customer health,
    sprint velocity, and urgent insights into a single notification.
    """
    logger.info("Starting Morning Digest cycle")

    results = {
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        config = load_config()
        from src.features.ghost.morning_digest import MorningDigestAgent
        from src.services.notifications import (
            NotificationService,
            NotificationRequest,
            NotificationType,
            NotificationPriority,
        )
        import asyncio

        with get_db_context() as db:
            users = db.query(User).all()

            for user in users:
                try:
                    agent = MorningDigestAgent(config)
                    digest = asyncio.run(agent.send_digest(user.id, db))

                    if digest.has_content:
                        message = agent.format_notification(digest)
                        notification_service = NotificationService(db)
                        request = NotificationRequest(
                            user_id=user.id,
                            title="Morning Digest",
                            message=message,
                            notification_type=NotificationType.SYSTEM,
                            priority=NotificationPriority.NORMAL,
                            icon="sunrise",
                            expires_in_hours=16,  # expires by end of day
                        )
                        asyncio.run(notification_service.send_notification(request))
                        results["sent"] += 1
                    else:
                        results["skipped"] += 1

                except Exception as e:
                    logger.error(f"Morning digest failed for user {user.id}: {e}")
                    results["errors"] += 1

        logger.info(f"Morning Digest cycle complete: {results}")
        return results

    except Exception as e:
        logger.error(f"Global Morning Digest failed: {e}")
        raise
