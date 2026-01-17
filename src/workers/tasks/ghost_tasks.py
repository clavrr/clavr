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
                            title=f"📊 Sprint Analysis: {result.cycle_name}",
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

