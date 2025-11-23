"""
Calendar-related Celery Tasks
Background tasks for calendar operations

CalendarService and standardized error handling.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from ..celery_app import celery_app
from ..base_task import BaseTask, IdempotentTask
from ...utils.logger import setup_logger
from ...integrations.google_calendar.service import CalendarService
from ...integrations.google_calendar.exceptions import (
    CalendarServiceException,
    EventNotFoundException,
    AuthenticationException,
    ServiceUnavailableException,
    wrap_external_exception
)
from ...utils.config import load_config
from ...core.credential_provider import CredentialFactory

logger = setup_logger(__name__)


@celery_app.task(base=IdempotentTask, bind=True)
def sync_user_calendar(self, user_id: str) -> Dict[str, Any]:
    """
    Sync calendar events for a single user using CalendarService
    
    Args:
        user_id: User ID
        
    Returns:
        Sync results with statistics
    """
    logger.info(f"Starting calendar sync for user {user_id}")
    
    try:
        from ...database import get_db_context
        from ...database.models import User
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise AuthenticationException(
                    message=f"User {user_id} not found",
                    service_name="calendar"
                )
            
            # Create service using CredentialFactory (handles all credential logic)
            config = load_config()
            factory = CredentialFactory(config)
            calendar_service = factory.create_service('calendar', user_id=user_id, db_session=db)
        
        # Sync events from last 30 days to next 90 days via service layer
        today = datetime.now().date()
        start_date = (today - timedelta(days=30)).isoformat()
        end_date = (today + timedelta(days=90)).isoformat()
        
        events = calendar_service.list_events(
            start_date=start_date,
            end_date=end_date
        )
        
        logger.info(f"Synced {len(events)} calendar events for user {user_id}")
        
        return {
            'user_id': user_id,
            'events_synced': len(events),
            'sync_time': datetime.utcnow().isoformat(),
            'status': 'success'
        }
    
    except CalendarServiceException as exc:
        logger.error(f"Calendar sync failed for user {user_id}: {exc}")
        raise
    except Exception as exc:
        logger.error(f"Calendar sync failed for user {user_id}: {exc}")
        wrapped_exc = wrap_external_exception(exc, "calendar", "sync_user_calendar")
        raise wrapped_exc


@celery_app.task(base=BaseTask, bind=True)
def create_event_with_notification(
    self,
    user_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    send_notifications: bool = True
) -> Dict[str, Any]:
    """
    Create a calendar event and optionally send notifications using CalendarService
    
    Args:
        user_id: User ID
        summary: Event summary/title
        start_time: Event start time (ISO format)
        end_time: Event end time (ISO format)
        description: Event description
        location: Event location
        attendees: List of attendee email addresses
        send_notifications: Whether to send notifications
        
    Returns:
        Created event details
    """
    logger.info(f"Creating calendar event '{summary}' for user {user_id}")
    
    try:
        from ...database import get_db_context
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            calendar_service = factory.create_service('calendar', user_id=user_id, db_session=db)
        
        # Create event via service layer
        event = calendar_service.create_event(
            title=summary,
            start_time=start_time,
            end_time=end_time,
            description=description or "",
            location=location or "",
            attendees=attendees
        )
        
        if not event:
            raise CalendarServiceException(
                message="Failed to create calendar event - no event returned",
                service_name="calendar"
            )
        
        # Send notifications if requested
        if send_notifications and attendees:
            from .notification_tasks import send_calendar_invitation
            send_calendar_invitation.delay(
                event_id=event['id'],
                attendees=attendees,
                event_summary=summary
            )
        
        logger.info(f"Created calendar event {event['id']} for user {user_id}")
        
        return {
            'user_id': user_id,
            'event_id': event['id'],
            'summary': summary,
            'status': 'created',
            'created_time': datetime.utcnow().isoformat()
        }
    
    except CalendarServiceException as exc:
        logger.error(f"Failed to create calendar event for user {user_id}: {exc}")
        raise
    except Exception as exc:
        logger.error(f"Failed to create calendar event for user {user_id}: {exc}")
        wrapped_exc = wrap_external_exception(exc, "calendar", "create_event_with_notification")
        raise wrapped_exc


@celery_app.task(base=BaseTask, bind=True)
def update_recurring_events(
    self,
    user_id: str,
    event_id: str,
    updates: Dict[str, Any],
    update_all: bool = False
) -> Dict[str, Any]:
    """
    Update a recurring event or all instances
    
    Args:
        user_id: User ID
        event_id: Event ID
        updates: Event updates to apply
        update_all: If True, update all instances; else just this one
        
    Returns:
        Update results
    """
    logger.info(f"Updating recurring event {event_id} for user {user_id}")
    
    try:
        from ...database import get_db_context
        from datetime import datetime as dt
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            calendar_service = factory.create_service('calendar', user_id=user_id, db_session=db)
        
        if update_all:
            # Update the recurring event pattern
            calendar_service.update_event(event_id=event_id, **updates)
            updated_count = 1
        else:
            # Update only this instance
            calendar_service.update_event(event_id=event_id, **updates)
            updated_count = 1
        
        logger.info(f"Updated {updated_count} event instance(s)")
        
        return {
            'user_id': user_id,
            'event_id': event_id,
            'updated_count': updated_count,
            'status': 'updated'
        }
        
    except Exception as exc:
        logger.error(f"Failed to update recurring event {event_id}: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def cleanup_old_calendar_events(
    self,
    user_id: str,
    days_old: int = 365
) -> Dict[str, Any]:
    """
    Delete calendar events older than specified days
    
    Args:
        user_id: User ID
        days_old: Delete events older than this many days
        
    Returns:
        Cleanup results
    """
    logger.info(f"Cleaning up events older than {days_old} days for user {user_id}")
    
    try:
        from ...database import get_db_context
        from datetime import datetime as dt
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            calendar_service = factory.create_service('calendar', user_id=user_id, db_session=db)
        
        # Get old events (events ending before days_old ago)
        end_date = datetime.utcnow() - timedelta(days=days_old)
        old_events = calendar_service.list_events(
            start_date=(datetime.utcnow() - timedelta(days=days_old + 365)).isoformat(),
            end_date=end_date.isoformat()
        )
        
        deleted_count = 0
        
        for event in old_events:
            try:
                calendar_service.delete_event(event_id=event['id'])
                deleted_count += 1
            except Exception as exc:
                logger.warning(f"Failed to delete event {event['id']}: {exc}")
        
        logger.info(f"Deleted {deleted_count} old events for user {user_id}")
        
        return {
            'user_id': user_id,
            'deleted_count': deleted_count,
            'status': 'completed'
        }
        
    except Exception as exc:
        logger.error(f"Calendar cleanup failed for user {user_id}: {exc}")
        raise
