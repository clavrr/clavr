"""
Emailfrom ..celery_app import celery_app
from ..base_task import BaseTask, LongRunningTask, IdempotentTask
from ...utils.logger import setup_logger
from ...database import get_db_context, User
from ...integrations.gmail.service import EmailService
from ...integrations.gmail.exceptions import (
    EmailServiceException,
    EmailNotFoundException,
    EmailSendException,
    AuthenticationException,
    ServiceUnavailableException
)ry Tasks
Background tasks for email operations

Refactored to use EmailService and standardized error handling.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from ..celery_app import celery_app
from ..base_task import BaseTask, LongRunningTask, IdempotentTask
from ...utils.logger import setup_logger
from ...database import get_db_context, User
from ...integrations.gmail.service import EmailService
from ...integrations.gmail.exceptions import (
    EmailServiceException,
    EmailNotFoundException,
    EmailSendException,
    AuthenticationException,
    ServiceUnavailableException,
    wrap_external_exception
)
from ...utils.config import load_config
from ...core.credential_provider import CredentialFactory

logger = setup_logger(__name__)


@celery_app.task(base=IdempotentTask, bind=True)
def sync_user_emails(self, user_id: str, max_results: int = 100) -> Dict[str, Any]:
    """
    Sync emails for a single user using EmailService
    
    Args:
        user_id: User ID
        max_results: Maximum number of emails to sync
        
    Returns:
        Sync results with statistics
    """
    logger.info(f"Starting email sync for user {user_id}")
    
    try:
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise AuthenticationException(
                    message=f"User {user_id} not found",
                    service_name="email"
                )
            
            # Create service using CredentialFactory (handles all credential logic)
            config = load_config()
            factory = CredentialFactory(config)
            email_service = factory.create_service('email', user_id=user_id, db_session=db)
            
            # Sync emails via service layer
            messages = email_service.list_emails(max_results=max_results)
            
            # Update user's last sync time
            user.last_email_synced_at = datetime.utcnow()
            db.commit()
            
            # Trigger webhooks for new emails (Ghost Piping)
            from .webhook_tasks import trigger_email_received_webhook
            
            webhook_count = 0
            for msg in messages:
                # We only trigger if it's a recent message to avoid flooding
                # For now, simplistic approach: trigger for all synced (consumer handles idempotency)
                try:
                    trigger_email_received_webhook.delay(
                        email_id=msg.get('id'),
                        email_data=msg,
                        user_id=int(user_id) if str(user_id).isdigit() else user_id
                    )
                    webhook_count += 1
                except Exception as e:
                    logger.warning(f"Failed to trigger webhook for email {msg.get('id')}: {e}")
            
            logger.info(f"Synced {len(messages)} emails for user {user_id}, triggered {webhook_count} events")
            
            return {
                'user_id': user_id,
                'emails_synced': len(messages),
                'events_triggered': webhook_count,
                'sync_time': datetime.utcnow().isoformat(),
                'status': 'success'
            }
    
    except EmailServiceException as exc:
        logger.error(f"Email sync failed for user {user_id}: {exc}")
        raise
    except Exception as exc:
        logger.error(f"Email sync failed for user {user_id}: {exc}")
        wrapped_exc = wrap_external_exception(exc, "email", "sync_user_emails")
        raise wrapped_exc


@celery_app.task(base=LongRunningTask, bind=True)
def sync_all_users_emails(self) -> Dict[str, Any]:
    """
    Sync emails for all active users
    
    Returns:
        Sync results with statistics
    """
    logger.info("Starting email sync for all users")
    
    try:
        with get_db_context() as db:
            # Get all active users
            users = db.query(User).filter(
                User.indexing_status.in_(['active', 'completed'])
            ).all()
            
            total_users = len(users)
            successful_syncs = 0
            failed_syncs = 0
            
            for user in users:
                try:
                    # Queue individual sync task
                    sync_user_emails.delay(user.id)
                    successful_syncs += 1
                    
                except Exception as exc:
                    logger.error(f"Failed to queue sync for user {user.id}: {exc}")
                    failed_syncs += 1
            
            logger.info(
                f"Queued email sync for {successful_syncs}/{total_users} users "
                f"({failed_syncs} failed)"
            )
            
            return {
                'total_users': total_users,
                'successful': successful_syncs,
                'failed': failed_syncs,
                'sync_time': datetime.utcnow().isoformat(),
                'status': 'completed'
            }
            
    except Exception as exc:
        logger.error(f"Bulk email sync failed: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def send_email(
    self,
    to: str,
    subject: str,
    body: str,
    user_id: str,
    html: bool = False
) -> Dict[str, Any]:
    """
    Send an email via EmailService
    
    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body
        user_id: User ID (email sender)
        html: Whether body is HTML
        
    Returns:
        Send result
    """
    logger.info(f"Sending email to {to} for user {user_id}")
    
    try:
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            # Create service using CredentialFactory (handles all credential logic)
            config = load_config()
            factory = CredentialFactory(config)
            email_service = factory.create_service('email', user_id=user_id, db_session=db)
        
        # Send email via service layer
        result = email_service.send_email(
            to=to,
            subject=subject,
            body=body
        )
        
        logger.info(f"Email sent to {to}")
        
        # Trigger 'email.sent' webhook for Relationship Gardener
        from .webhook_tasks import deliver_webhook_task
        from src.database.webhook_models import WebhookEventType
        
        try:
             deliver_webhook_task.delay(
                event_type=WebhookEventType.EMAIL_SENT.value,
                event_id=result.get('id', 'unknown'),
                payload={
                    'to': to,
                    'subject': subject,
                    'message_id': result.get('id'),
                    'timestamp': datetime.utcnow().isoformat()
                },
                user_id=int(user_id) if str(user_id).isdigit() else user_id
            )
        except Exception as e:
            logger.warning(f"Failed to trigger email.sent webhook: {e}")
        
        return {
            'to': to,
            'subject': subject,
            'message_id': result.get('id'),
            'status': 'sent',
            'sent_time': datetime.utcnow().isoformat()
        }
    
    except EmailServiceException as exc:
        logger.error(f"Failed to send email to {to}: {exc}")
        raise
    except Exception as exc:
        logger.error(f"Failed to send email to {to}: {exc}")
        wrapped_exc = wrap_external_exception(exc, "email", "send_email")
        raise wrapped_exc


@celery_app.task(base=BaseTask, bind=True)
def batch_send_emails(
    self,
    emails: List[Dict[str, str]],
    user_id: str
) -> Dict[str, Any]:
    """
    Send multiple emails in batch
    
    Args:
        emails: List of email dicts with 'to', 'subject', 'body'
        user_id: User ID (email sender)
        
    Returns:
        Batch send results
    """
    logger.info(f"Sending batch of {len(emails)} emails for user {user_id}")
    
    successful = 0
    failed = 0
    results = []
    
    for email_data in emails:
        try:
            result = send_email.delay(
                to=email_data['to'],
                subject=email_data['subject'],
                body=email_data['body'],
                user_id=user_id,
                html=email_data.get('html', False)
            )
            results.append({
                'to': email_data['to'],
                'task_id': result.id,
                'status': 'queued'
            })
            successful += 1
            
        except Exception as exc:
            logger.error(f"Failed to queue email to {email_data['to']}: {exc}")
            results.append({
                'to': email_data['to'],
                'status': 'failed',
                'error': str(exc)
            })
            failed += 1
    
    logger.info(f"Batch send completed: {successful} queued, {failed} failed")
    
    return {
        'total': len(emails),
        'successful': successful,
        'failed': failed,
        'results': results,
        'status': 'completed'
    }


@celery_app.task(base=BaseTask, bind=True)
def archive_old_emails(
    self,
    user_id: str,
    days_old: int = 90
) -> Dict[str, Any]:
    """
    Archive emails older than specified days
    
    Args:
        user_id: User ID
        days_old: Archive emails older than this many days
        
    Returns:
        Archive results
    """
    logger.info(f"Archiving emails older than {days_old} days for user {user_id}")
    
    try:
        from datetime import datetime as dt
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            email_service = factory.create_service('email', user_id=user_id, db_session=db)
        
        # Calculate cutoff date
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Search for old emails
        query = f"before:{cutoff_date.strftime('%Y/%m/%d')}"
        old_messages = email_service.search_emails(query=query)
        
        archived_count = 0
        
        # Archive messages using batch operation
        if old_messages:
            message_ids = [message['id'] for message in old_messages]
            try:
                # Use EmailService's archive_emails method (batch operation)
                result = email_service.archive_emails(message_ids=message_ids)
                archived_count = result.get('success', 0)
                
            except Exception as exc:
                logger.warning(f"Failed to archive messages: {exc}")
                archived_count = 0
        
        logger.info(f"Archived {archived_count} emails for user {user_id}")
        
        return {
            'user_id': user_id,
            'archived_count': archived_count,
            'cutoff_date': cutoff_date.isoformat(),
            'status': 'completed'
        }
        
    except Exception as exc:
        logger.error(f"Email archiving failed for user {user_id}: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def cleanup_spam(
    self,
    user_id: str,
    days_old: int = 30
) -> Dict[str, Any]:
    """
    Delete spam emails older than specified days
    
    Args:
        user_id: User ID
        days_old: Delete spam older than this many days
        
    Returns:
        Cleanup results
    """
    logger.info(f"Cleaning up spam older than {days_old} days for user {user_id}")
    
    try:
        from datetime import datetime as dt
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            config = load_config()
            factory = CredentialFactory(config)
            email_service = factory.create_service('email', user_id=user_id, db_session=db)
        
        # Calculate cutoff date
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Search for old spam
        query = f"in:spam before:{cutoff_date.strftime('%Y/%m/%d')}"
        spam_messages = email_service.search_emails(query=query)
        
        # Delete spam messages using batch operation
        deleted_count = 0
        if spam_messages:
            message_ids = [message['id'] for message in spam_messages]
            try:
                # Use EmailService's delete_emails method (batch operation)
                result = email_service.delete_emails(message_ids=message_ids)
                deleted_count = result.get('success', 0)
                
            except Exception as exc:
                logger.warning(f"Failed to delete spam messages: {exc}")
        
        logger.info(f"Deleted {deleted_count} spam emails for user {user_id}")
        
        return {
            'user_id': user_id,
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat(),
            'status': 'completed'
        }
        
    except Exception as exc:
        logger.error(f"Spam cleanup failed for user {user_id}: {exc}")
        raise