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
            # For prototype, we'll check a default user_id=1 or configured user.
            user_id = 1 # Keep user_id here as it's used by both perception and evaluation
            
            # Load Graph Manager (Phase 7: Living Memory)
            from ...services.indexing.graph import KnowledgeGraphManager
            # Initialize with default config/ArangoDB credentials.
            # Ideally we check config.indexing.enable_graph or similar
            graph_manager = None
            try:
                graph_manager = KnowledgeGraphManager(config=config)
                # Quick check if backend is available (will log warning if not)
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
            except Exception:
                pass 
                
            # Phase 5: Perception Agent (Signal Filtering)
            from ...agents.perception.agent import PerceptionAgent, PerceptionEvent, SignalType
            perception_agent = PerceptionAgent()
            
            email_service = None
            try:
                email_service = factory.create_service('email', user_id=user_id, db_session=db)
            except Exception:
                pass # Email might not be active
                
            # Simulate Event Stream (e.g. check last 15 mins of email)
            detected_triggers = []
            if email_service:
                # Fetch recent unread
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
            planner = ProactivePlanner(db)
            
            # Pass initialized calendar_service
            plans = asyncio.run(planner.check_goals_against_state(user_id, calendar_service))
            
            for plan in plans:
                logger.info(f"[Planning] 🧠 Plan Generated: {plan['type']} - {plan['description']}")
                
                # Execute Plan: Block Time
                if plan['type'] == 'block_time' and calendar_service:
                    try:
                        # Assuming create_event signature: summary, start, end
                        # Need to parse start string to datetime
                        start_time = datetime.fromisoformat(plan['params']['start'])
                        end_time = start_time + timedelta(minutes=plan['params']['duration_minutes'])
                        
                        # Execute Calendar Block
                        # calendar_service.create_event(summary=..., start=..., end=...)
                        # Mocking execution for safety unless user approved 'Auto-Exec'.
                        # For now, we LOG the action.
                        logger.info(f"[Planning] 🚀 EXECUTION: Blocking Calendar for '{plan['params']['summary']}'")
                        # calendar_service.create_event(...) 
                    except Exception as e:
                        logger.error(f"[Planning] Execution failed: {e}")
            
            # Continue with Standard Periodic Evaluation (Phase 1-2 logic)
            # 1. Initialize Credentials & Calendar Service
            calendar_service = None
            try:
                # Use factory to create service with credentials automatically
                calendar_service = factory.create_service(
                    'calendar', 
                    user_id=user_id, 
                    db_session=db
                )
            except Exception as e:
                logger.warning(f"[Thinking] Failed to init CalendarService: {e}")
                
            # 2. Initialize Semantic Memory (already done above, but keeping for clarity if needed elsewhere)
            # semantic_memory = SemanticMemory(db) 
            
            # 3. Initialize Evaluator with services
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
                
                # Execute Action
                if proposed == "generate_morning_briefing":
                    logger.info(f"[Thinking] Triggering morning briefing for user {user_id}")
                    # In a real app, we might check if one was already sent today to avoid duplicates.
                    # For now, we trust the evaluator's logic (time window).
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
                
            return result
        
    except Exception as e:
        logger.error(f"[Thinking] Error in think loop: {e}", exc_info=True)
        raise e

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
            except Exception:
                 pass # Optional context
                 
            # Task Service
            task_service = None
            try:
                 task_service = factory.create_service('task', user_id=user_id, db_session=db)
            except Exception:
                 pass # Optional context
                 
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
    """
    logger.info("[Ingestion] Starting Asana crawl...")
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
        
        # Run Sync
        # In real world, we'd persist 'last_sync_time' in DB or Redis
        # For prototype, we sync 'recent' delta every time.
        async def run_sync():
            return await ingestor.run_sync()
            
        stats = asyncio.run(run_sync())
        
        logger.info(f"[Ingestion] Asana Sync Complete. Stats: {stats}")
        return {"status": "success", "stats": stats}
        
    except Exception as e:
        logger.error(f"[Ingestion] Asana crawl failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}

