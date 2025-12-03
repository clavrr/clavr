"""
Notification-related Celery Tasks
Background tasks for sending notifications
"""
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..celery_app import celery_app
from ..base_task import BaseTask, PriorityTask
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


@celery_app.task(base=PriorityTask, bind=True)
def send_email_notification(
    self,
    user_email: str,
    subject: str,
    message: str,
    template: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send an email notification to a user
    
    Args:
        user_email: Recipient email address
        subject: Email subject
        message: Email message
        template: Optional email template name
        
    Returns:
        Notification result
    """
    logger.info(f"Sending email notification to {user_email}")
    
    try:
        from ...utils.config import load_config
        
        config = load_config()
        
        # Check if we have SMTP configuration
        if hasattr(config.email, 'smtp') and config.email.smtp:
            # Use SMTP for notifications (system emails)
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = config.email.address
            msg['To'] = user_email
            
            # Add body (support both plain text and HTML if template provided)
            if template:
                # For templates, we could render HTML here
                html_body = f"""
                <html>
                    <body>
                        <h2>{subject}</h2>
                        <p>{message}</p>
                        <hr>
                        <p><small>Sent by {config.agent.name}</small></p>
                    </body>
                </html>
                """
                msg.attach(MIMEText(message, 'plain'))
                msg.attach(MIMEText(html_body, 'html'))
            else:
                msg.attach(MIMEText(message, 'plain'))
            
            # Send via SMTP
            try:
                with smtplib.SMTP(config.email.smtp.server, config.email.smtp.port) as server:
                    if config.email.smtp.use_tls:
                        server.starttls()
                    # Authenticate if password is provided
                    if config.email.password:
                        server.login(config.email.address, config.email.password)
                    server.send_message(msg)
                    
                logger.info(f"Email notification sent to {user_email} via SMTP")
                
            except Exception as smtp_error:
                logger.warning(f"SMTP send failed: {smtp_error}, falling back to log-only mode")
                # Fallback: just log the notification
                logger.info(f"[NOTIFICATION] To: {user_email} | Subject: {subject} | Message: {message}")
        else:
            # No SMTP configured - log the notification
            logger.info(f"[NOTIFICATION] To: {user_email} | Subject: {subject} | Message: {message}")
            logger.warning("SMTP not configured - notification logged only")
        
        return {
            'recipient': user_email,
            'subject': subject,
            'status': 'sent',
            'template': template,
            'sent_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Failed to send email notification to {user_email}: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def send_calendar_invitation(
    self,
    event_id: str,
    attendees: List[str],
    event_summary: str
) -> Dict[str, Any]:
    """
    Send calendar invitations to attendees
    
    Args:
        event_id: Calendar event ID
        attendees: List of attendee email addresses
        event_summary: Event summary/title
        
    Returns:
        Invitation results
    """
    logger.info(f"Sending calendar invitations for event {event_id}")
    
    successful = 0
    failed = 0
    
    for attendee in attendees:
        try:
            send_email_notification.delay(
                user_email=attendee,
                subject=f"Calendar Invitation: {event_summary}",
                message=f"You have been invited to: {event_summary}",
                template='calendar_invitation'
            )
            successful += 1
            
        except Exception as exc:
            logger.error(f"Failed to send invitation to {attendee}: {exc}")
            failed += 1
    
    logger.info(
        f"Calendar invitations sent: {successful} successful, {failed} failed"
    )
    
    return {
        'event_id': event_id,
        'total': len(attendees),
        'successful': successful,
        'failed': failed,
        'status': 'completed'
    }


@celery_app.task(base=BaseTask, bind=True)
def send_task_reminder(
    self,
    user_id: str,
    task_id: str,
    task_title: str,
    due_date: str
) -> Dict[str, Any]:
    """
    Send a task reminder notification
    
    Args:
        user_id: User ID
        task_id: Task ID
        task_title: Task title
        due_date: Task due date
        
    Returns:
        Reminder result
    """
    logger.info(f"Sending task reminder for task {task_id} to user {user_id}")
    
    try:
        from ...database import get_db_context
        from ...database import User
        
        # Get user email
        with get_db_context() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            user_email = user.email
        
        # Send notification
        send_email_notification.delay(
            user_email=user_email,
            subject=f"Task Reminder: {task_title}",
            message=f"Reminder: {task_title} is due on {due_date}",
            template='task_reminder'
        )
        
        logger.info(f"Task reminder sent for task {task_id}")
        
        return {
            'user_id': user_id,
            'task_id': task_id,
            'status': 'sent'
        }
        
    except Exception as exc:
        logger.error(f"Failed to send task reminder: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def send_digest_email(
    self,
    user_id: str,
    period: str = 'daily'
) -> Dict[str, Any]:
    """
    Send a digest email with summary of activities
    
    Args:
        user_id: User ID
        period: Digest period ('daily', 'weekly', 'monthly')
        
    Returns:
        Digest result
    """
    logger.info(f"Sending {period} digest to user {user_id}")
    
    try:
        from ...database import get_db_context
        from ...database import User
        from ...database.models import Session as DBSession
        from datetime import timedelta
        
        # Get user
        with get_db_context() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Calculate time period for digest
            now = datetime.utcnow()
            if period == 'daily':
                start_time = now - timedelta(days=1)
            elif period == 'weekly':
                start_time = now - timedelta(weeks=1)
            elif period == 'monthly':
                start_time = now - timedelta(days=30)
            else:
                start_time = now - timedelta(days=1)  # Default to daily
            
            # Gather digest data from user's last sync
            digest_data = {
                'new_emails': 0,
                'upcoming_events': 0,
                'pending_tasks': 0,
                'period_start': start_time.isoformat(),
                'period_end': now.isoformat()
            }
            
            # Get email count (if last_email_synced_at is available)
            if user.last_email_synced_at and user.last_email_synced_at >= start_time:
                # Estimate based on sync activity
                digest_data['new_emails'] = 'Recent sync'
                digest_data['has_email_activity'] = True
            else:
                digest_data['has_email_activity'] = False
            
            # Get session activity count
            active_sessions = db.query(DBSession).filter(
                DBSession.user_id == user_id,
                DBSession.created_at >= start_time,
                DBSession.expires_at > now
            ).count()
            
            digest_data['active_sessions'] = active_sessions
            digest_data['user_active'] = active_sessions > 0
        
        # Build digest message
        email_status = digest_data.get('new_emails', 'Unknown')
        if digest_data.get('has_email_activity'):
            email_info = "Email activity detected"
        else:
            email_info = "No recent email activity"
        
        message = f"""
        {period.capitalize()} Digest for {user.email}
        
        Period: {start_time.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%Y-%m-%d %H:%M')}
        
        Activity Summary:
        - {email_info}
        - Active sessions: {digest_data['active_sessions']}
        - Account status: {'Active' if digest_data['user_active'] else 'Inactive'}
        
        ---
        Generated by {period} digest system
        """
        
        send_email_notification.delay(
            user_email=user.email,
            subject=f"Your {period.capitalize()} Digest",
            message=message,
            template=f'{period}_digest'
        )
        
        logger.info(f"{period.capitalize()} digest sent to user {user_id}")
        
        return {
            'user_id': user_id,
            'period': period,
            'data': digest_data,
            'status': 'sent'
        }
        
    except Exception as exc:
        logger.error(f"Failed to send digest to user {user_id}: {exc}")
        raise


@celery_app.task(base=PriorityTask, bind=True)
def send_alert(
    self,
    user_id: str,
    alert_type: str,
    message: str,
    severity: str = 'info'
) -> Dict[str, Any]:
    """
    Send an alert notification to a user
    
    Args:
        user_id: User ID
        alert_type: Type of alert
        message: Alert message
        severity: Alert severity ('info', 'warning', 'error')
        
    Returns:
        Alert result
    """
    logger.info(f"Sending {severity} alert to user {user_id}: {alert_type}")
    
    try:
        from ...database import get_db_context
        from ...database import User
        
        # Get user
        with get_db_context() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")
        
        # Send alert
        send_email_notification.delay(
            user_email=user.email,
            subject=f"Alert: {alert_type}",
            message=message,
            template='alert'
        )
        
        logger.info(f"Alert sent to user {user_id}")
        
        return {
            'user_id': user_id,
            'alert_type': alert_type,
            'severity': severity,
            'status': 'sent'
        }
        
    except Exception as exc:
        logger.error(f"Failed to send alert to user {user_id}: {exc}")
        raise