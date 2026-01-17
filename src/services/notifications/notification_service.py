"""
Notification Service

Handles sending notifications across all channels:
- Email
- In-app notifications (stored in database)
- Push notifications (via web push or mobile)
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_

from src.database.models import InAppNotification, User, UserSettings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class NotificationType(str, Enum):
    """Types of notifications."""
    ACTION_EXECUTED = "action_executed"
    APPROVAL_NEEDED = "approval_needed"
    ACTION_UNDONE = "action_undone"
    ACTION_REJECTED = "action_rejected"
    ACTION_FAILED = "action_failed"
    SYSTEM = "system"
    REMINDER = "reminder"


class NotificationPriority(str, Enum):
    """Priority levels for notifications."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# Icon mapping for action types
ACTION_TYPE_ICONS = {
    "calendar_block": "calendar",
    "calendar_event": "calendar",
    "email_send": "mail",
    "email_draft": "mail",
    "task_create": "check-square",
    "linear_issue": "git-pull-request",
    "slack_message": "message-circle",
}


@dataclass
class NotificationRequest:
    """Request to send a notification."""
    user_id: int
    title: str
    message: str
    notification_type: NotificationType
    priority: NotificationPriority = NotificationPriority.NORMAL
    icon: Optional[str] = None
    action_url: Optional[str] = None
    action_label: Optional[str] = None
    related_action_id: Optional[int] = None
    expires_in_hours: Optional[int] = 24  # Auto-expire after 24 hours by default


class NotificationService:
    """
    Service for sending notifications to users.
    
    Supports multiple channels:
    - In-app (stored in database, displayed in app UI)
    - Email (via send_email task)
    - Push (future: via Firebase/APNs)
    """
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    async def send_notification(
        self,
        request: NotificationRequest,
        channels: Optional[List[str]] = None
    ) -> Dict[str, bool]:
        """
        Send notification to user across specified channels.
        
        Args:
            request: NotificationRequest with notification details
            channels: List of channels to send to. If None, uses user preferences.
                     Options: ['in_app', 'email', 'push']
        
        Returns:
            Dict with channel -> success status
        """
        results = {}
        
        # Get user preferences if channels not specified
        if channels is None:
            channels = await self._get_user_notification_channels(request.user_id)
        
        # Always send in-app notification (unless explicitly excluded)
        if 'in_app' in channels:
            results['in_app'] = await self._send_in_app(request)
        
        # Send email if enabled
        if 'email' in channels:
            results['email'] = await self._send_email(request)
        
        # Send push if enabled
        if 'push' in channels:
            results['push'] = await self._send_push(request)
        
        return results
    
    async def _get_user_notification_channels(self, user_id: int) -> List[str]:
        """Get user's preferred notification channels from settings."""
        channels = ['in_app']  # Always include in-app
        
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == user_id)
            result = await self.db.execute(stmt)
            settings = result.scalar_one_or_none()
            
            if settings:
                if settings.email_notifications:
                    channels.append('email')
                if settings.push_notifications:
                    channels.append('push')
            else:
                # Default to email if no settings
                channels.append('email')
                
        except Exception as e:
            logger.warning(f"[Notifications] Failed to get user settings: {e}")
            channels.append('email')  # Default fallback
        
        return channels
    
    async def _send_in_app(self, request: NotificationRequest) -> bool:
        """Store notification in database for in-app display."""
        try:
            expires_at = None
            if request.expires_in_hours:
                expires_at = datetime.utcnow() + timedelta(hours=request.expires_in_hours)
            
            notification = InAppNotification(
                user_id=request.user_id,
                title=request.title,
                message=request.message,
                notification_type=request.notification_type.value,
                priority=request.priority.value,
                icon=request.icon or ACTION_TYPE_ICONS.get('system', 'bell'),
                action_url=request.action_url,
                action_label=request.action_label,
                related_action_id=request.related_action_id,
                expires_at=expires_at,
            )
            
            self.db.add(notification)
            await self.db.commit()
            
            logger.info(f"[Notifications] In-app notification created for user {request.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"[Notifications] Failed to create in-app notification: {e}")
            return False
    
    async def _send_email(self, request: NotificationRequest) -> bool:
        """Send email notification."""
        try:
            # Get user email
            stmt = select(User.email).where(User.id == request.user_id)
            result = await self.db.execute(stmt)
            email = result.scalar_one_or_none()
            
            if not email:
                logger.warning(f"[Notifications] No email for user {request.user_id}")
                return False
            
            # Use Celery task for async email sending
            from src.workers.tasks.email_tasks import send_email
            
            # Build HTML email body
            html_body = self._build_email_html(request)
            
            send_email.delay(
                to=email,
                subject=request.title,
                body=html_body,
                user_id=str(request.user_id),
                html=True,
            )
            
            logger.info(f"[Notifications] Email queued for {email}")
            return True
            
        except Exception as e:
            logger.error(f"[Notifications] Failed to send email: {e}")
            return False
    
    async def _send_push(self, request: NotificationRequest) -> bool:
        """Send push notification (placeholder for future implementation)."""
        # TODO: Implement push notifications via Firebase/APNs
        # For now, log and return True to indicate it was "sent"
        logger.info(f"[Notifications] Push notification queued for user {request.user_id}: {request.title}")
        
        # In production, this would:
        # 1. Look up user's push tokens from database
        # 2. Send via Firebase Cloud Messaging (FCM) for web/Android
        # 3. Send via APNs for iOS
        # 4. Handle failures and token cleanup
        
        return True
    
    def _build_email_html(self, request: NotificationRequest) -> str:
        """Build HTML email body for notification."""
        priority_colors = {
            'low': '#6b7280',
            'normal': '#3b82f6',
            'high': '#f59e0b',
            'urgent': '#ef4444',
        }
        
        color = priority_colors.get(request.priority.value, '#3b82f6')
        
        action_button = ""
        if request.action_url and request.action_label:
            action_button = f'''
            <p style="margin: 20px 0;">
                <a href="{request.action_url}" 
                   style="background: {color}; color: white; padding: 12px 24px; 
                          border-radius: 8px; text-decoration: none; font-weight: 500;">
                    {request.action_label}
                </a>
            </p>
            '''
        
        return f'''
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                    color: #1f2937; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="border-left: 4px solid {color}; padding-left: 16px;">
                <h2 style="color: {color}; margin: 0 0 12px 0; font-size: 20px;">
                    {request.title}
                </h2>
                <p style="margin: 0; line-height: 1.6; color: #4b5563;">
                    {request.message}
                </p>
            </div>
            {action_button}
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
            <p style="font-size: 12px; color: #9ca3af;">
                This is an automated notification from Clavr.
            </p>
        </div>
        '''
    
    # ==================== Query Methods ====================
    
    async def get_unread_notifications(
        self, 
        user_id: int, 
        limit: int = 50
    ) -> List[InAppNotification]:
        """Get unread notifications for a user."""
        stmt = select(InAppNotification).where(
            and_(
                InAppNotification.user_id == user_id,
                InAppNotification.is_read == False,
                InAppNotification.is_dismissed == False
            )
        ).order_by(InAppNotification.created_at.desc()).limit(limit)
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_all_notifications(
        self, 
        user_id: int, 
        include_dismissed: bool = False,
        limit: int = 100
    ) -> List[InAppNotification]:
        """Get all notifications for a user."""
        conditions = [InAppNotification.user_id == user_id]
        
        if not include_dismissed:
            conditions.append(InAppNotification.is_dismissed == False)
        
        stmt = select(InAppNotification).where(
            and_(*conditions)
        ).order_by(InAppNotification.created_at.desc()).limit(limit)
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_unread_count(self, user_id: int) -> int:
        """Get count of unread notifications."""
        from sqlalchemy import func
        
        stmt = select(func.count(InAppNotification.id)).where(
            and_(
                InAppNotification.user_id == user_id,
                InAppNotification.is_read == False,
                InAppNotification.is_dismissed == False
            )
        )
        
        result = await self.db.execute(stmt)
        return result.scalar() or 0
    
    async def mark_as_read(self, notification_id: int, user_id: int) -> bool:
        """Mark a notification as read."""
        stmt = update(InAppNotification).where(
            and_(
                InAppNotification.id == notification_id,
                InAppNotification.user_id == user_id
            )
        ).values(is_read=True, read_at=datetime.utcnow())
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0
    
    async def mark_all_as_read(self, user_id: int) -> int:
        """Mark all notifications as read for a user."""
        stmt = update(InAppNotification).where(
            and_(
                InAppNotification.user_id == user_id,
                InAppNotification.is_read == False
            )
        ).values(is_read=True, read_at=datetime.utcnow())
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount
    
    async def dismiss_notification(self, notification_id: int, user_id: int) -> bool:
        """Dismiss a notification."""
        stmt = update(InAppNotification).where(
            and_(
                InAppNotification.id == notification_id,
                InAppNotification.user_id == user_id
            )
        ).values(is_dismissed=True, dismissed_at=datetime.utcnow())
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0
    
    async def cleanup_expired(self) -> int:
        """Delete expired notifications."""
        from sqlalchemy import delete
        
        stmt = delete(InAppNotification).where(
            and_(
                InAppNotification.expires_at.isnot(None),
                InAppNotification.expires_at < datetime.utcnow()
            )
        )
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount
