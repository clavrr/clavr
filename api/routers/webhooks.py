"""
Webhook API Router

API endpoints for managing webhook subscriptions and viewing delivery history.
"""
import secrets
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, HttpUrl, Field

from src.database import get_async_db
from src.database.webhook_models import WebhookEventType, WebhookDeliveryStatus
from src.features.webhook_service import WebhookService
from src.database.models import User
from api.auth import get_current_user_required as get_current_user

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# Pydantic Schemas

class WebhookSubscriptionCreate(BaseModel):
    """Schema for creating a webhook subscription"""
    url: HttpUrl = Field(..., description="Webhook endpoint URL")
    event_types: List[str] = Field(..., description="List of event types to subscribe to")
    description: Optional[str] = Field(None, max_length=500, description="Optional description")
    retry_count: int = Field(3, ge=0, le=10, description="Maximum retry attempts")
    timeout_seconds: int = Field(10, ge=1, le=60, description="Request timeout in seconds")
    
    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com/webhook",
                "event_types": ["email.received", "task.completed"],
                "description": "Production webhook for email and task events",
                "retry_count": 3,
                "timeout_seconds": 10
            }
        }


class WebhookSubscriptionUpdate(BaseModel):
    """Schema for updating a webhook subscription"""
    url: Optional[HttpUrl] = None
    event_types: Optional[List[str]] = None
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None
    retry_count: Optional[int] = Field(None, ge=0, le=10)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=60)


class WebhookSubscriptionResponse(BaseModel):
    """Schema for webhook subscription response"""
    id: int
    user_id: int
    url: str
    event_types: List[str]
    description: Optional[str]
    is_active: bool
    retry_count: int
    timeout_seconds: int
    created_at: str
    updated_at: Optional[str]
    total_deliveries: int
    successful_deliveries: int
    failed_deliveries: int
    last_delivery_at: Optional[str]
    last_success_at: Optional[str]
    last_failure_at: Optional[str]
    
    class Config:
        from_attributes = True


class WebhookDeliveryResponse(BaseModel):
    """Schema for webhook delivery response"""
    id: int
    subscription_id: int
    event_type: str
    event_id: str
    status: str
    attempt_count: int
    max_attempts: int
    response_status_code: Optional[int]
    error_message: Optional[str]
    created_at: str
    first_attempted_at: Optional[str]
    last_attempted_at: Optional[str]
    completed_at: Optional[str]
    next_retry_at: Optional[str]
    
    class Config:
        from_attributes = True


class WebhookTestResponse(BaseModel):
    """Schema for webhook test response"""
    success: bool
    message: str
    status_code: Optional[int] = None
    response_body: Optional[str] = None


class EventTypeInfo(BaseModel):
    """Schema for event type information"""
    value: str
    description: str


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/event-types", response_model=List[EventTypeInfo])
async def list_event_types():
    """
    Get list of all available webhook event types
    
    Returns a list of all event types that can be subscribed to.
    """
    event_types = [
        {"value": "email.received", "description": "Email received and indexed"},
        {"value": "email.sent", "description": "Email sent successfully"},
        {"value": "email.indexed", "description": "Email indexed in vector database"},
        {"value": "calendar.event.created", "description": "Calendar event created"},
        {"value": "calendar.event.updated", "description": "Calendar event updated"},
        {"value": "calendar.event.deleted", "description": "Calendar event deleted"},
        {"value": "task.created", "description": "Task created"},
        {"value": "task.updated", "description": "Task updated"},
        {"value": "task.completed", "description": "Task marked as completed"},
        {"value": "task.deleted", "description": "Task deleted"},
        {"value": "indexing.started", "description": "Indexing process started"},
        {"value": "indexing.completed", "description": "Indexing process completed"},
        {"value": "indexing.failed", "description": "Indexing process failed"},
        {"value": "user.created", "description": "User account created"},
        {"value": "user.settings.updated", "description": "User settings updated"},
        {"value": "export.completed", "description": "Data export completed"},
        {"value": "sync.completed", "description": "Sync process completed"},
    ]
    return event_types


@router.post("", response_model=WebhookSubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook_subscription(
    subscription_data: WebhookSubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Create a new webhook subscription
    
    Creates a webhook subscription for the current user. A unique secret will be
    automatically generated for HMAC signature verification.
    
    **Request Body:**
    - url: Webhook endpoint URL (must be HTTPS in production)
    - event_types: List of event types to subscribe to
    - description: Optional description for the webhook
    - retry_count: Maximum number of retry attempts (default: 3)
    - timeout_seconds: Request timeout in seconds (default: 10)
    
    **Response:**
    Returns the created webhook subscription with a generated secret.
    """
    webhook_service = WebhookService(db)
    
    # Validate event types
    valid_event_types = {e.value for e in WebhookEventType}
    for event_type in subscription_data.event_types:
        if event_type not in valid_event_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid event type: {event_type}"
            )
    
    # Generate secure secret
    secret = secrets.token_urlsafe(32)
    
    # Create subscription
    subscription = webhook_service.create_subscription(
        user_id=current_user.id,
        url=str(subscription_data.url),
        event_types=subscription_data.event_types,
        secret=secret,
        description=subscription_data.description,
        retry_count=subscription_data.retry_count,
        timeout_seconds=subscription_data.timeout_seconds
    )
    
    # Include secret in response (only shown once during creation)
    response = WebhookSubscriptionResponse.from_orm(subscription)
    response_dict = response.dict()
    response_dict['secret'] = secret  # Include secret in creation response
    
    return response_dict


@router.get("", response_model=List[WebhookSubscriptionResponse])
async def list_webhook_subscriptions(
    active_only: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get all webhook subscriptions for the current user
    
    **Query Parameters:**
    - active_only: If true, only return active subscriptions (default: true)
    
    **Response:**
    Returns a list of webhook subscriptions (without secrets).
    """
    webhook_service = WebhookService(db)
    subscriptions = webhook_service.get_user_subscriptions(
        user_id=current_user.id,
        active_only=active_only
    )
    
    return [WebhookSubscriptionResponse.from_orm(sub) for sub in subscriptions]


@router.get("/{subscription_id}", response_model=WebhookSubscriptionResponse)
async def get_webhook_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a specific webhook subscription by ID
    
    **Path Parameters:**
    - subscription_id: ID of the webhook subscription
    
    **Response:**
    Returns the webhook subscription details (without secret).
    """
    webhook_service = WebhookService(db)
    subscription = webhook_service.get_subscription(subscription_id)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook subscription not found"
        )
    
    # Verify ownership
    if subscription.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this webhook subscription"
        )
    
    return WebhookSubscriptionResponse.from_orm(subscription)


@router.patch("/{subscription_id}", response_model=WebhookSubscriptionResponse)
async def update_webhook_subscription(
    subscription_id: int,
    update_data: WebhookSubscriptionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Update a webhook subscription
    
    **Path Parameters:**
    - subscription_id: ID of the webhook subscription
    
    **Request Body:**
    All fields are optional. Only provided fields will be updated.
    - url: New webhook endpoint URL
    - event_types: New list of event types
    - description: New description
    - is_active: Enable/disable the webhook
    - retry_count: New retry count
    - timeout_seconds: New timeout
    
    **Response:**
    Returns the updated webhook subscription.
    """
    webhook_service = WebhookService(db)
    subscription = webhook_service.get_subscription(subscription_id)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook subscription not found"
        )
    
    # Verify ownership
    if subscription.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this webhook subscription"
        )
    
    # Validate event types if provided
    if update_data.event_types:
        valid_event_types = {e.value for e in WebhookEventType}
        for event_type in update_data.event_types:
            if event_type not in valid_event_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid event type: {event_type}"
                )
    
    # Prepare update data
    updates = update_data.dict(exclude_unset=True)
    if 'url' in updates:
        updates['url'] = str(updates['url'])
    
    # Update subscription
    updated_subscription = webhook_service.update_subscription(
        subscription_id=subscription_id,
        **updates
    )
    
    return WebhookSubscriptionResponse.from_orm(updated_subscription)


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Delete a webhook subscription
    
    **Path Parameters:**
    - subscription_id: ID of the webhook subscription
    
    **Response:**
    Returns 204 No Content on success.
    """
    webhook_service = WebhookService(db)
    subscription = webhook_service.get_subscription(subscription_id)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook subscription not found"
        )
    
    # Verify ownership
    if subscription.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this webhook subscription"
        )
    
    # Delete subscription
    webhook_service.delete_subscription(subscription_id)
    
    return None


@router.post("/{subscription_id}/test", response_model=WebhookTestResponse)
async def test_webhook_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Test a webhook subscription by sending a test event
    
    **Path Parameters:**
    - subscription_id: ID of the webhook subscription
    
    **Response:**
    Returns the result of the test delivery.
    """
    webhook_service = WebhookService(db)
    subscription = webhook_service.get_subscription(subscription_id)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook subscription not found"
        )
    
    # Verify ownership
    if subscription.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to test this webhook subscription"
        )
    
    # Send test webhook
    test_payload = {
        "test": True,
        "message": "This is a test webhook from Clavr Agent",
        "subscription_id": subscription_id,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    deliveries = await webhook_service.trigger_webhook_event(
        event_type=WebhookEventType.USER_SETTINGS_UPDATED,  # Use a neutral event type
        event_id=f"test-{subscription_id}-{int(datetime.utcnow().timestamp())}",
        payload=test_payload,
        user_id=current_user.id
    )
    
    if deliveries:
        delivery = deliveries[0]
        return WebhookTestResponse(
            success=delivery.status == WebhookDeliveryStatus.SUCCESS,
            message="Test webhook sent successfully" if delivery.status == WebhookDeliveryStatus.SUCCESS else "Test webhook failed",
            status_code=delivery.response_status_code,
            response_body=delivery.response_body[:500] if delivery.response_body else None
        )
    else:
        return WebhookTestResponse(
            success=False,
            message="No webhook was triggered (subscription may not match event type)"
        )


@router.get("/{subscription_id}/deliveries", response_model=List[WebhookDeliveryResponse])
async def get_webhook_deliveries(
    subscription_id: int,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get delivery history for a webhook subscription
    
    **Path Parameters:**
    - subscription_id: ID of the webhook subscription
    
    **Query Parameters:**
    - limit: Maximum number of deliveries to return (default: 100, max: 1000)
    
    **Response:**
    Returns a list of webhook deliveries with their status and response details.
    """
    webhook_service = WebhookService(db)
    subscription = webhook_service.get_subscription(subscription_id)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook subscription not found"
        )
    
    # Verify ownership
    if subscription.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access deliveries for this webhook subscription"
        )
    
    # Limit to max 1000
    limit = min(limit, 1000)
    
    deliveries = webhook_service.get_delivery_history(
        subscription_id=subscription_id,
        limit=limit
    )
    
    return [WebhookDeliveryResponse.from_orm(delivery) for delivery in deliveries]
