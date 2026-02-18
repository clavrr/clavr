"""
Autonomy Tasks

Background tasks for the Agent's "Think Loop".
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from ..celery_app import celery_app
from ..base_task import BaseTask
from ...utils.logger import setup_logger
from ...ai.autonomy.evaluator import ContextEvaluator
from ...ai.memory.semantic_memory import SemanticMemory
from ...utils.config import load_config
from ...database import get_db_context, User
from ...core.credential_provider import CredentialFactory

logger = setup_logger(__name__)

@celery_app.task(base=BaseTask, bind=True, name='src.workers.tasks.autonomy_tasks.proactive_think')
def proactive_think(self) -> Dict[str, Any]:
    """
    The Proactive "Think" Loop.
    
    Runs periodically to evaluate user context and propose actions.
    Values returned are logged by Celery.
    """
    logger.info("[Thinking] Starting proactive context evaluation...")
    
    try:
        # Load config
        config = load_config()
        
        with get_db_context() as db:
            # Get all active users to process (not just hardcoded user_id=1)
            # Use sync query since we're in a sync Celery task
            from src.database.models import User
            
            active_users = db.query(User.id).filter(User.is_active == True).all()
            active_user_ids = [row[0] for row in active_users]
            
            if not active_user_ids:
                logger.info("[AutonomyTask] No active users found, skipping")
                return {"status": "skipped", "reason": "no_active_users"}
            
            logger.info(f"[AutonomyTask] Processing {len(active_user_ids)} active users")
            
            all_results = []
            for user_id in active_user_ids:
                try:
                    result = _process_user_autonomy(db, config, user_id)
                    all_results.append({"user_id": user_id, "result": result})
                except Exception as e:
                    logger.error(f"[AutonomyTask] Failed for user {user_id}: {e}")
                    all_results.append({"user_id": user_id, "error": str(e)})
            
            return {"status": "completed", "results": all_results}
                    
    except Exception as e:
        logger.error(f"[Thinking] Error in think loop: {e}", exc_info=True)
        raise e


def _process_user_autonomy(db, config, user_id: int) -> Dict[str, Any]:
    """Process autonomy logic for a single user."""
    logger.info(f"[Thinking] Processing user {user_id}...")
    
    # Load Graph Manager (Phase 7: Living Memory)
    from ...services.indexing.graph import KnowledgeGraphManager
    graph_manager = None
    try:
        graph_manager = KnowledgeGraphManager(config=config)
    except Exception as e:
        logger.warning(f"[Thinking] Graph Manager init failed: {e}")

    # Services (Perception Needs Semantic Memory + Graph)
    semantic_memory = SemanticMemory(db)
    
    # Factory for gathering raw streams
    factory = CredentialFactory(config)
    
    # Initialize Calendar Service EARLY (needed for Planning)
    calendar_service = None
    try:
        calendar_service = factory.create_service('calendar', user_id=user_id, db_session=db)
    except Exception as e:
        logger.debug(f"[Thinking] Calendar service not available: {e}")
        
    # Phase 5: Perception Agent (Signal Filtering)
    from ...agents.perception.agent import PerceptionAgent, PerceptionEvent, SignalType
    perception_agent = PerceptionAgent(config)
    
    email_service = None
    try:
        email_service = factory.create_service('email', user_id=user_id, db_session=db)
    except Exception as e:
        logger.debug(f"[Thinking] Email service not available: {e}")
        
    # Simulate Event Stream (e.g. check last 15 mins of email)
    detected_triggers = []
    if email_service:
        recent_emails = email_service.search_emails(query="is:unread newer_than:15m", limit=5) or []
        for email in recent_emails:
            event = PerceptionEvent(
                type="email", 
                source_id=email.get('id'), 
                content=email, 
                timestamp=datetime.now().isoformat()
            )
            trigger = asyncio.run(perception_agent.perceive_event(event, user_id))
            if trigger:
                detected_triggers.append(trigger)
                
    # Log Triggers
    for t in detected_triggers:
        logger.info(f"[Thinking] ⚡️ Perception Trigger: {t.category.upper()} - {t.reason}")
         
    # Phase 6: Proactive Planning (Goal-Driven Reasoning)
    from ...ai.autonomy.planner import ProactivePlanner
    planner = ProactivePlanner(db, config)
    
    plans = asyncio.run(planner.check_goals_against_state(user_id, calendar_service))
    
    # Phase 6.5: Execute Plans via ActionExecutor
    for plan in plans:
        logger.info(f"[Planning] 🧠 Plan Generated: {plan['type']} - {plan['description']}")
        
        # Execute via ActionExecutor (respects user autonomy settings)
        try:
            from ...ai.autonomy.action_executor import ActionExecutor
            from ...database.async_database import async_session_factory
            
            async def execute_plan_async():
                async with async_session_factory() as async_db:
                    executor = ActionExecutor(async_db, config, factory)
                    return await executor.execute_plan(dict(plan), user_id)
            
            result = asyncio.run(execute_plan_async())
            
            if result.success:
                if result.status == 'executed':
                    logger.info(f"[Planning] ✅ EXECUTED: {plan['type']} (action_id={result.action_id})")
                elif result.status == 'pending_approval':
                    logger.info(f"[Planning] ⏳ PENDING APPROVAL: {plan['type']} (action_id={result.action_id})")
            else:
                logger.error(f"[Planning] ❌ FAILED: {plan['type']} - {result.error}")
                
        except Exception as e:
            logger.error(f"[Planning] Execution error: {e}", exc_info=True)
    

    # Context Evaluation (Phase 1-2 logic)
    evaluator = ContextEvaluator(
        config=config,
        calendar_service=calendar_service,
        semantic_memory=semantic_memory
    )
    
    async def run_evaluation():
        return await evaluator.evaluate_context(user_id)
        
    result = asyncio.run(run_evaluation())
    
    action_needed = result.get('action_needed')
    proposed = result.get('proposed_action')
    reason = result.get('reason')
    
    if action_needed:
        logger.info(f"[Thinking] 💡 Action Proposed: {proposed.upper()} (Reason: {reason})")
        
        if proposed == "generate_morning_briefing":
            logger.info(f"[Thinking] Triggering morning briefing for user {user_id}")
            generate_morning_briefing.delay(user_id)
            
        elif proposed == "prepare_meeting_brief":
            event_id = result.get('context_data', {}).get('event_id')
            if event_id:
                logger.info(f"[Thinking] Triggering meeting brief for {event_id}")
                generate_meeting_brief.delay(user_id, event_id)
            else:
                logger.warning("[Thinking] Proposed meeting brief but no event_id found.")
    else:
        logger.info(f"[Thinking] 💤 No action needed. (Reason: {reason})")
        
    # Phase 7: Proactive Insight Generation
    from ...services.proactive.context_service import ProactiveContextService
    context_service = ProactiveContextService(config, db_session=db, graph_manager=graph_manager)
    
    insight_result = asyncio.run(context_service.generate_proactive_insight(user_id))
    if insight_result and insight_result.get('insight'):
        logger.info(f"[Thinking] 🌟 Proactive Insight: {insight_result['insight']}")
    
    return result


@celery_app.task(base=BaseTask, bind=True, name='src.workers.tasks.autonomy_tasks.generate_morning_briefing')
def generate_morning_briefing(self, user_id: int) -> Dict[str, Any]:
    """
    Generates and delivers a morning briefing (daily summary).
    Typically triggered by proactive_think.
    """
    logger.info(f"[Briefing] Generating morning briefing for user {user_id}...")
    
    try:
        config = load_config()
        
        with get_db_context() as db:
            # 1. Initialize all services
            factory = CredentialFactory(config)
            
            # Email Service (Required for delivery)
            # We assume user has email credentials if they are using this.
            email_service = None
            try:
                email_service = factory.create_service('email', user_id=user_id, db_session=db)
            except Exception as e:
                logger.error(f"[Briefing] Cannot init EmailService: {e}")
                return {"status": "failed", "reason": "No email service"}
                
            # Calendar Service
            calendar_service = None
            try:
                 calendar_service = factory.create_service('calendar', user_id=user_id, db_session=db)
            except Exception as e:
                 logger.debug(f"[Briefing] Calendar service not available: {e}")
                 
            # Task Service
            task_service = None
            try:
                 task_service = factory.create_service('task', user_id=user_id, db_session=db)
            except Exception as e:
                 logger.debug(f"[Briefing] Task service not available: {e}")
                 
            # 2. Generate Briefing
            from ...ai.autonomy.briefing import BriefingGenerator
            generator = BriefingGenerator(config)
            
            async def run_gen():
                return await generator.generate_briefing(
                    user_id=user_id,
                    calendar_service=calendar_service,
                    email_service=email_service,
                    task_service=task_service
                )
            
            briefing_text = asyncio.run(run_gen())
            
            # 3. Deliver (Send Email)
            # Verify user email address
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.email:
                logger.error(f"[Briefing] User {user_id} has no email address.")
                return {"status": "failed", "reason": "No user email"}
                
            email_service.send_email(
                to=user.email,
                subject=f"Daily Briefing: {datetime.now().strftime('%A, %b %d')}",
                body=briefing_text,
                html=False # Briefing is markdown, maybe convert to HTML later. Text is fine for now.
            )
            
            logger.info(f"[Briefing] Sent to {user.email}")
            return {
                "status": "sent",
                "recipient": user.email,
                "length": len(briefing_text)
            }
            
    except Exception as e:
        logger.error(f"[Briefing] Morning briefing failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@celery_app.task(base=BaseTask, bind=True, name='src.workers.tasks.autonomy_tasks.generate_meeting_brief')
def generate_meeting_brief(self, user_id: int, event_id: str) -> Dict[str, Any]:
    """
    Generates and delivers a meeting dossier.
    """
    logger.info(f"[Briefing] Generating meeting brief for user {user_id}, event {event_id}...")
    
    try:
        config = load_config()
        
        with get_db_context() as db:
            factory = CredentialFactory(config)
            
            # Services
            email_service = None
            calendar_service = None
            semantic_memory = None
            
            try:
                email_service = factory.create_service('email', user_id=user_id, db_session=db)
                calendar_service = factory.create_service('calendar', user_id=user_id, db_session=db)
                semantic_memory = SemanticMemory(db)
            except Exception as e:
                logger.error(f"[Briefing] Service init failed: {e}")
                return {"status": "failed", "reason": "Service init failed"}
                
            # Generate Brief
            from ...ai.autonomy.briefing import MeetingBriefGenerator
            generator = MeetingBriefGenerator(config)
            
            async def run_gen():
                return await generator.generate_brief(
                    user_id=user_id,
                    event_id=event_id,
                    calendar_service=calendar_service,
                    email_service=email_service,
                    semantic_memory=semantic_memory
                )
            
            brief_text = asyncio.run(run_gen())
            
            # Deliver
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.email:
                 return {"status": "failed", "reason": "No user email"}
                 
            email_service.send_email(
                to=user.email,
                subject=f"Meeting Brief: Prepared for Upcoming Meeting",
                body=brief_text,
                html=False
            )
            
            logger.info(f"[Briefing] Meeting brief sent to {user.email}")
            return {"status": "sent"}
            
    except Exception as e:
        logger.error(f"[Briefing] Meeting brief failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}

@celery_app.task(base=BaseTask, bind=True, name='src.workers.tasks.autonomy_tasks.ingest_asana_delta')
def ingest_asana_delta(self) -> Dict[str, Any]:
    """
    Background crawler for Asana.
    Fetches tasks and updates the Knowledge Graph.
    
    Uses Redis to persist sync state for efficient delta syncs.
    """
    logger.info("[Ingestion] Starting Asana crawl...")
    
    # Redis key for sync state
    SYNC_STATE_KEY = "asana:last_sync_time"
    
    try:
        config = load_config()
        
        # Initialize Graph Manager
        from ...services.indexing.graph import KnowledgeGraphManager
        graph_manager = None
        try:
            graph_manager = KnowledgeGraphManager(config=config)
        except Exception as e:
            logger.error(f"[Ingestion] Graph init failed: {e}")
            return {"status": "failed", "reason": "Graph init failed"}

        # Initialize Ingestor
        from ...services.ingestion.asana import AsanaIngestor
        ingestor = AsanaIngestor(graph_manager, config)
        
        # Get last sync time from Redis
        last_sync_time = None
        redis_client = None
        
        try:
            import redis
            import os
            
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis.from_url(redis_url, decode_responses=True)
            
            stored_time = redis_client.get(SYNC_STATE_KEY)
            if stored_time:
                last_sync_time = datetime.fromisoformat(stored_time)
                logger.info(f"[Ingestion] Resuming from last sync: {last_sync_time}")
            else:
                # First sync - start from 7 days ago to get recent history
                last_sync_time = datetime.utcnow() - timedelta(days=7)
                logger.info(f"[Ingestion] First sync, fetching from: {last_sync_time}")
                
        except ImportError:
            logger.warning("[Ingestion] Redis not available, syncing last 24 hours")
            last_sync_time = datetime.utcnow() - timedelta(hours=24)
        except Exception as e:
            logger.warning(f"[Ingestion] Redis error: {e}, syncing last 24 hours")
            last_sync_time = datetime.utcnow() - timedelta(hours=24)
        
        # Record sync start time (to save after successful sync)
        sync_start_time = datetime.utcnow()
        
        # Run Sync with last_sync_time
        async def run_sync():
            return await ingestor.run_sync(last_sync_time=last_sync_time)
            
        stats = asyncio.run(run_sync())
        
        # Update last sync time in Redis on success
        if redis_client and stats.get('processed', 0) >= 0:
            try:
                redis_client.set(SYNC_STATE_KEY, sync_start_time.isoformat())
                # Set TTL of 30 days (in case sync stops running, we don't want stale data)
                redis_client.expire(SYNC_STATE_KEY, 60 * 60 * 24 * 30)
                logger.info(f"[Ingestion] Updated last_sync_time to {sync_start_time}")
            except Exception as e:
                logger.warning(f"[Ingestion] Failed to update sync time in Redis: {e}")
        
        logger.info(f"[Ingestion] Asana Sync Complete. Stats: {stats}")
        return {
            "status": "success", 
            "stats": stats,
            "last_sync_time": last_sync_time.isoformat() if last_sync_time else None,
            "sync_completed_at": sync_start_time.isoformat()
        }
        
    except Exception as e:
        logger.error(f"[Ingestion] Asana crawl failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}

