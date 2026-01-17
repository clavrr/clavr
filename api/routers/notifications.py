"""
Notifications API Router

Endpoints for managing in-app notifications.
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_async_db as get_db
from src.database.models import User, InAppNotification
from src.services.notifications import NotificationService
from src.utils.logger import setup_logger
from api.dependencies import get_current_user_required

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ==================== Response Models ====================

class NotificationResponse(BaseModel):
    """Response model for a notification."""
    id: int
    title: str
    message: str
    notification_type: str
    priority: str
    icon: Optional[str]
    action_url: Optional[str]
    action_label: Optional[str]
    is_read: bool
    created_at: datetime
    expires_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class NotificationCountResponse(BaseModel):
    """Response for notification count."""
    unread: int
    total: int


# ==================== Endpoints ====================

@router.get("", response_model=List[NotificationResponse])
async def get_notifications(
    unread_only: bool = Query(False, description="Only return unread notifications"),
    include_dismissed: bool = Query(False, description="Include dismissed notifications"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Get notifications for the current user."""
    service = NotificationService(db)
    
    if unread_only:
        notifications = await service.get_unread_notifications(user.id, limit=limit)
    else:
        notifications = await service.get_all_notifications(
            user.id, 
            include_dismissed=include_dismissed,
            limit=limit
        )
    
    return [
        NotificationResponse(
            id=n.id,
            title=n.title,
            message=n.message,
            notification_type=n.notification_type,
            priority=n.priority,
            icon=n.icon,
            action_url=n.action_url,
            action_label=n.action_label,
            is_read=n.is_read,
            created_at=n.created_at,
            expires_at=n.expires_at,
        ) for n in notifications
    ]


@router.get("/count", response_model=NotificationCountResponse)
async def get_notification_count(
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Get notification counts for the current user."""
    service = NotificationService(db)
    
    unread = await service.get_unread_count(user.id)
    all_notifications = await service.get_all_notifications(user.id, limit=1000)
    
    return NotificationCountResponse(
        unread=unread,
        total=len(all_notifications)
    )


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Mark a notification as read."""
    service = NotificationService(db)
    success = await service.mark_as_read(notification_id, user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"message": "Notification marked as read", "id": notification_id}


@router.post("/read-all")
async def mark_all_notifications_read(
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Mark all notifications as read."""
    service = NotificationService(db)
    count = await service.mark_all_as_read(user.id)
    
    return {"message": f"Marked {count} notifications as read", "count": count}


@router.post("/{notification_id}/dismiss")
async def dismiss_notification(
    notification_id: int,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Dismiss a notification."""
    service = NotificationService(db)
    success = await service.dismiss_notification(notification_id, user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"message": "Notification dismissed", "id": notification_id}


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: int,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific notification."""
    from sqlalchemy import select, and_
    
    stmt = select(InAppNotification).where(
        and_(
            InAppNotification.id == notification_id,
            InAppNotification.user_id == user.id
        )
    )
    
    result = await db.execute(stmt)
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return NotificationResponse(
        id=notification.id,
        title=notification.title,
        message=notification.message,
        notification_type=notification.notification_type,
        priority=notification.priority,
        icon=notification.icon,
        action_url=notification.action_url,
        action_label=notification.action_label,
        is_read=notification.is_read,
        created_at=notification.created_at,
        expires_at=notification.expires_at,
    )
