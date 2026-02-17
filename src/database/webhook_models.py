"""
Webhook Models

Database models for webhook subscriptions and delivery tracking.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, Index, Enum
from sqlalchemy.orm import relationship
import enum

from .models import Base


class WebhookEventType(str, enum.Enum):
    """Supported webhook event types"""
    # Email events
    EMAIL_RECEIVED = "email.received"
    EMAIL_SENT = "email.sent"
    EMAIL_INDEXED = "email.indexed"
    
    # Calendar events
    CALENDAR_EVENT_CREATED = "calendar.event.created"
    CALENDAR_EVENT_UPDATED = "calendar.event.updated"
    CALENDAR_EVENT_DELETED = "calendar.event.deleted"
    
    # Task events
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    TASK_DELETED = "task.deleted"
    
    # Indexing events
    INDEXING_STARTED = "indexing.started"
    INDEXING_COMPLETED = "indexing.completed"
    INDEXING_FAILED = "indexing.failed"
    
    # User events
    USER_CREATED = "user.created"
    USER_SETTINGS_UPDATED = "user.settings.updated"
    
    # Slack events
    SLACK_MESSAGE_RECEIVED = "slack.message.received"
    SLACK_REACTION_ADDED = "slack.reaction.added"
    SLACK_CHANNEL_CREATED = "slack.channel.created"
    
    # System events
    EXPORT_COMPLETED = "export.completed"
    SYNC_COMPLETED = "sync.completed"


class WebhookSubscription(Base):
    """
    Webhook subscription model
    
    Stores webhook endpoints that should receive event notifications
    """
    __tablename__ = 'webhook_subscriptions'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Webhook configuration
    url = Column(String(2048), nullable=False)  # Endpoint URL
    event_types = Column(JSON, nullable=False)  # List of WebhookEventType values
    secret = Column(String(255), nullable=False)  # Secret for HMAC signature
    description = Column(String(500))  # Optional description
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Delivery configuration
    retry_count = Column(Integer, default=3, nullable=False)  # Max retry attempts
    timeout_seconds = Column(Integer, default=10, nullable=False)  # Request timeout
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Statistics
    total_deliveries = Column(Integer, default=0, nullable=False)
    successful_deliveries = Column(Integer, default=0, nullable=False)
    failed_deliveries = Column(Integer, default=0, nullable=False)
    last_delivery_at = Column(DateTime)
    last_success_at = Column(DateTime)
    last_failure_at = Column(DateTime)
    
    # Relationships
    user = relationship("User", backref="webhook_subscriptions")
    deliveries = relationship("WebhookDelivery", back_populates="subscription", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_webhook_user_active', 'user_id', 'is_active'),
        Index('idx_webhook_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<WebhookSubscription(id={self.id}, user_id={self.user_id}, url='{self.url}')>"


class WebhookDeliveryStatus(str, enum.Enum):
    """Webhook delivery status"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class WebhookDelivery(Base):
    """
    Webhook delivery tracking
    
    Records each attempt to deliver a webhook event
    """
    __tablename__ = 'webhook_deliveries'
    
    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey('webhook_subscriptions.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Event details
    event_type = Column(String(100), nullable=False, index=True)
    event_id = Column(String(255), nullable=False, index=True)  # Unique event identifier
    payload = Column(JSON, nullable=False)  # Event payload
    
    # Delivery status
    status = Column(
        Enum(WebhookDeliveryStatus, native_enum=False, length=50),
        default=WebhookDeliveryStatus.PENDING,
        nullable=False,
        index=True
    )
    
    # Delivery attempts
    attempt_count = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    
    # Response details
    response_status_code = Column(Integer)
    response_body = Column(Text)
    error_message = Column(Text)
    
    # Timing
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    first_attempted_at = Column(DateTime)
    last_attempted_at = Column(DateTime)
    completed_at = Column(DateTime)
    next_retry_at = Column(DateTime, index=True)  # For retry queue
    
    # Relationships
    subscription = relationship("WebhookSubscription", back_populates="deliveries")
    
    # Indexes
    __table_args__ = (
        Index('idx_webhook_delivery_status_retry', 'status', 'next_retry_at'),
        Index('idx_webhook_delivery_event', 'event_type', 'event_id'),
    )
    
    def __repr__(self):
        return f"<WebhookDelivery(id={self.id}, event_type='{self.event_type}', status='{self.status}')>"
