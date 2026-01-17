"""
Webhook Celery Tasks

Background tasks for webhook delivery and maintenance.
"""
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from ..celery_app import celery_app
from ..base_task import BaseTask, IdempotentTask
from src.database import get_db_context
from src.database.webhook_models import WebhookEventType
from src.features.webhook_service import WebhookService

logger = logging.getLogger(__name__)


@celery_app.task(base=BaseTask, bind=True)
def deliver_webhook_task(
    self,
    event_type: str,
    event_id: str,
    payload: Dict[str, Any],
    user_id: Optional[int] = None
):
    """
    Celery task to deliver webhooks asynchronously
    """
    with get_db_context() as db:
        try:
            webhook_service = WebhookService(db)
            
            # Validate event type
            try:
                event_type_enum = WebhookEventType(event_type)
            except ValueError:
                logger.error(f"Invalid event type: {event_type}")
                return {'status': 'error', 'error': f'Invalid event type: {event_type}'}
            
            # Unified Async Execution Block
            async def process_webhook():
                # 1. Primary Delivery
                await webhook_service.trigger_webhook_event(
                    event_type=event_type_enum,
                    event_id=event_id,
                    payload=payload,
                    user_id=user_id
                )
                
                # 2. Ghost Internal Dispatch (Isolated)
                try:
                    await self._dispatch_to_ghost_agents(db, payload, event_type, event_id, user_id)
                except Exception as ex:
                    logger.error(f"[Ghost] Dispatch failed for {event_type}: {ex}")

            # Run everything in a single loop
            asyncio.run(process_webhook())
            
            return {
                'status': 'success',
                'event_type': event_type,
                'event_id': event_id
            }
            
        except Exception as e:
            logger.error(f"Webhook delivery failed: {e}")
            return {'status': 'error', 'error': str(e)}

    async def _dispatch_to_ghost_agents(self, db, payload, event_type, event_id, user_id):
        """Helper to manage Ghost dispatch flow."""
        from src.agents.perception.agent import PerceptionAgent
        from src.agents.perception.types import PerceptionEvent
        from src.features.ghost.meeting_prepper import MeetingPrepper
        from src.features.ghost.relationship_gardener import RelationshipGardener
        from src.features.ghost.document_tracker import DocumentTrackerAgent
        from src.features.ghost.thread_analyzer import ThreadAnalyzerAgent
        from api.dependencies import AppState
        
        config = AppState.get_config()
        graph_manager = AppState.get_knowledge_graph_manager()
        
        # Initialize Agents
        perception = PerceptionAgent(config)
        prepper = MeetingPrepper(db, config)
        gardener = RelationshipGardener(db, config)
        doc_tracker = DocumentTrackerAgent(db, config)
        thread_analyzer = ThreadAnalyzerAgent(db, config, graph_manager)
        
        # Convert webhook payload to PerceptionEvent
        perception_event = None
        if event_type.startswith("email."):
            perception_event = PerceptionEvent(
                type="email",
                source_id=payload.get("id", event_id),
                content={
                    "id": payload.get("id"),
                    "from": payload.get("from") or payload.get("sender"),
                    "subject": payload.get("subject", ""),
                },
                timestamp=datetime.utcnow().isoformat()
            )
        elif event_type.startswith("calendar."):
            perception_event = PerceptionEvent(
                type="calendar",
                source_id=payload.get("id", event_id),
                content={
                    "id": payload.get("id"),
                    "summary": payload.get("summary", ""),
                },
                timestamp=datetime.utcnow().isoformat()
            )
        
        # Perception filtering
        trigger = None
        if perception_event:
            trigger = await perception.perceive_event(perception_event, user_id)
        
        # Dispatch logic
        if event_type in ["calendar.event.created", "calendar.event.updated"]:
            if trigger or perception_event is None:
                await prepper.handle_event(event_type, payload, user_id)
        elif event_type == "email.sent":
            await gardener.handle_event(event_type, payload, user_id)
        elif event_type == "document.indexed":
            await doc_tracker.handle_event(event_type, payload, user_id)
        elif event_type in ["slack.thread.updated", "slack.message.created"]:
            await thread_analyzer.handle_event(event_type, payload, user_id)


@celery_app.task(base=IdempotentTask, bind=True)
def retry_failed_webhooks_task(self) -> Dict[str, Any]:
    """
    Celery task to retry failed webhook deliveries
    
    This task should be run periodically (e.g., every 5 minutes) to process
    the retry queue.
    
    Returns:
        Retry results with count of processed webhooks
    """
    with get_db_context() as db:
        try:
            webhook_service = WebhookService(db)
            
            # Retry pending webhooks (async)
            retry_count = asyncio.run(webhook_service.retry_pending_webhooks())
            
            logger.info(f"Processed {retry_count} webhook retries")
            
            return {
                'status': 'success',
                'retry_count': retry_count,
                'processed_at': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error retrying webhooks: {e}")
            raise


@celery_app.task(base=IdempotentTask, bind=True)
def cleanup_old_deliveries_task(self, days: int = 30) -> Dict[str, Any]:
    """
    Celery task to clean up old webhook delivery records
    
    Args:
        days: Delete deliveries older than this many days (default: 30)
    
    Returns:
        Cleanup results with count of deleted deliveries
        
    This task should be run periodically (e.g., daily) to prevent the
    webhook_deliveries table from growing indefinitely.
    """
    with get_db_context() as db:
        try:
            webhook_service = WebhookService(db)
            deleted_count = webhook_service.cleanup_old_deliveries(days=days)
            
            logger.info(f"Cleaned up {deleted_count} old webhook deliveries (older than {days} days)")
            
            return {
                'status': 'success',
                'deleted_count': deleted_count,
                'days_old': days,
                'cleaned_at': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up webhook deliveries: {e}")
            raise


# Helper Functions for Integration

def trigger_email_received_webhook(email_id: str, email_data: Dict[str, Any], user_id: int):
    """
    Helper to trigger EMAIL_RECEIVED webhook
    
    Args:
        email_id: Email message ID
        email_data: Email data (subject, from, to, body preview, etc.)
        user_id: User ID
        
    Returns:
        Celery task result
    """
    return deliver_webhook_task.delay(
        event_type=WebhookEventType.EMAIL_RECEIVED.value,
        event_id=email_id,
        payload=email_data,
        user_id=user_id
    )


def trigger_calendar_event_created_webhook(event_id: str, event_data: Dict[str, Any], user_id: int):
    """
    Helper to trigger CALENDAR_EVENT_CREATED webhook
    
    Args:
        event_id: Calendar event ID
        event_data: Event data (title, start, end, location, etc.)
        user_id: User ID
        
    Returns:
        Celery task result
    """
    # Standard webhook delivery
    result = deliver_webhook_task.delay(
        event_type=WebhookEventType.CALENDAR_EVENT_CREATED.value,
        event_id=event_id,
        payload=event_data,
        user_id=user_id
    )
    
    # Also check for conflicts with Linear deadlines
    check_calendar_conflicts.delay(
        event_data=event_data,
        user_id=user_id
    )
    
    return result


@celery_app.task(base=BaseTask, bind=True, name='src.workers.tasks.webhook_tasks.check_calendar_conflicts')
def check_calendar_conflicts(self, event_data: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """
    Check if a calendar event conflicts with Linear high-priority deadlines.
    
    Triggered when a new calendar event is created.
    Part of Killer Feature #2: Conflict Resolution.
    """
    logger.info(f"[ConflictCheck] Checking conflicts for user {user_id}")
    
    try:
        from src.features.detection.conflict_detector import check_calendar_event_for_conflicts
        from src.utils.config import load_config
        
        config = load_config()
        
        with get_db_context() as db:
            result = asyncio.run(
                check_calendar_event_for_conflicts(event_data, user_id, config, db)
            )
        
        if result.get('status') == 'notified':
            logger.info(f"[ConflictCheck] Found {result.get('conflicts', 0)} conflict(s) for user {user_id}")
        
        return result
        
    except Exception as e:
        logger.error(f"[ConflictCheck] Error: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def trigger_task_completed_webhook(task_id: str, task_data: Dict[str, Any], user_id: int):
    """
    Helper to trigger TASK_COMPLETED webhook
    
    Args:
        task_id: Task ID
        task_data: Task data (title, description, due date, etc.)
        user_id: User ID
        
    Returns:
        Celery task result
    """
    return deliver_webhook_task.delay(
        event_type=WebhookEventType.TASK_COMPLETED.value,
        event_id=task_id,
        payload=task_data,
        user_id=user_id
    )


def trigger_indexing_completed_webhook(job_id: str, indexing_data: Dict[str, Any], user_id: int):
    """
    Helper to trigger INDEXING_COMPLETED webhook
    
    Args:
        job_id: Indexing job ID
        indexing_data: Indexing results (count, duration, errors, etc.)
        user_id: User ID
        
    Returns:
        Celery task result
    """
    return deliver_webhook_task.delay(
        event_type=WebhookEventType.INDEXING_COMPLETED.value,
        event_id=job_id,
        payload=indexing_data,
        user_id=user_id
    )


def trigger_export_completed_webhook(export_id: str, export_data: Dict[str, Any], user_id: int):
    """
    Helper to trigger EXPORT_COMPLETED webhook
    
    Args:
        export_id: Export job ID
        export_data: Export details (format, file path, size, etc.)
        user_id: User ID
        
    Returns:
        Celery task result
    """
    return deliver_webhook_task.delay(
        event_type=WebhookEventType.EXPORT_COMPLETED.value,
        event_id=export_id,
        payload=export_data,
        user_id=user_id
    )