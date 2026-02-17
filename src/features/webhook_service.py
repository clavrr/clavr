"""
Webhook Service - Manage and trigger webhooks

Full database-backed implementation for webhook subscriptions,
delivery with HTTP POST, HMAC signatures, retries, and statistics.
"""
import hmac
import hashlib
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src.database.webhook_models import (
    WebhookSubscription,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEventType,
)
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

# Maximum retry delay (1 hour)
MAX_RETRY_DELAY = 3600


class WebhookService:
    """Database-backed service for managing webhook subscriptions and deliveries."""

    def __init__(self, db_session: Optional[Session] = None):
        self.db = db_session

    # ------------------------------------------------------------------
    # Subscription CRUD
    # ------------------------------------------------------------------

    def create_subscription(
        self,
        user_id: int,
        url: str,
        event_types: List[str],
        secret: str,
        description: Optional[str] = None,
        retry_count: int = 3,
        timeout_seconds: int = 10,
    ) -> WebhookSubscription:
        """Create a new webhook subscription."""
        subscription = WebhookSubscription(
            user_id=user_id,
            url=url,
            event_types=event_types,
            secret=secret,
            description=description,
            retry_count=retry_count,
            timeout_seconds=timeout_seconds,
            is_active=True,
            total_deliveries=0,
            successful_deliveries=0,
            failed_deliveries=0,
        )
        self.db.add(subscription)
        self.db.commit()
        self.db.refresh(subscription)
        return subscription

    def get_subscription(self, subscription_id: int) -> Optional[WebhookSubscription]:
        """Get a webhook subscription by ID."""
        return (
            self.db.query(WebhookSubscription)
            .filter(WebhookSubscription.id == subscription_id)
            .first()
        )

    def get_user_subscriptions(
        self,
        user_id: int,
        active_only: bool = True,
    ) -> List[WebhookSubscription]:
        """Get all subscriptions for a user."""
        query = self.db.query(WebhookSubscription).filter(
            WebhookSubscription.user_id == user_id
        )
        if active_only:
            query = query.filter(WebhookSubscription.is_active == True)
        return query.order_by(WebhookSubscription.created_at).all()

    def update_subscription(
        self,
        subscription_id: int,
        **kwargs,
    ) -> Optional[WebhookSubscription]:
        """Update a webhook subscription with arbitrary fields."""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return None
        for key, value in kwargs.items():
            if hasattr(subscription, key):
                setattr(subscription, key, value)
        subscription.updated_at = datetime.utcnow()
        self.db.commit()
        return subscription

    def delete_subscription(self, subscription_id: int) -> bool:
        """Delete a webhook subscription."""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False
        self.db.delete(subscription)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Event triggering
    # ------------------------------------------------------------------

    def get_active_subscriptions_for_event(
        self,
        event_type: WebhookEventType,
    ) -> List[WebhookSubscription]:
        """Return active subscriptions that listen for *event_type*."""
        all_active = (
            self.db.query(WebhookSubscription)
            .filter(WebhookSubscription.is_active == True)
            .all()
        )
        # event_types is a JSON list stored in the column
        return [
            s
            for s in all_active
            if event_type.value in (s.event_types or [])
        ]

    async def trigger_webhook_event(
        self,
        event_type: WebhookEventType,
        event_id: str,
        payload: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> List[WebhookDelivery]:
        """
        Find all active subscriptions matching *event_type* and deliver
        the payload to each one.
        """
        subscriptions = self.get_active_subscriptions_for_event(event_type)
        if user_id is not None:
            subscriptions = [s for s in subscriptions if s.user_id == user_id]

        deliveries: List[WebhookDelivery] = []
        for sub in subscriptions:
            delivery = WebhookDelivery(
                subscription_id=sub.id,
                event_type=event_type.value,
                event_id=event_id,
                payload=payload,
                status=WebhookDeliveryStatus.PENDING,
                attempt_count=0,
                max_attempts=sub.retry_count,
            )
            self.db.add(delivery)
            self.db.commit()

            # Attach the subscription object so _deliver_webhook can access it
            delivery.subscription = sub

            await self._deliver_webhook(delivery)
            deliveries.append(delivery)

        return deliveries

    # ------------------------------------------------------------------
    # HTTP delivery
    # ------------------------------------------------------------------

    async def _deliver_webhook(self, delivery: WebhookDelivery) -> bool:
        """
        Deliver a single webhook via HTTP POST.

        Updates delivery status, subscription statistics, and schedules
        retries on failure.
        """
        import httpx

        subscription = delivery.subscription
        payload_str = json.dumps(delivery.payload)
        signature = self._generate_signature(payload_str, subscription.secret)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Webhook-Event": delivery.event_type,
            "X-Webhook-Delivery-Id": str(delivery.id),
        }

        now = datetime.utcnow()
        delivery.attempt_count += 1
        if delivery.first_attempted_at is None:
            delivery.first_attempted_at = now
        delivery.last_attempted_at = now
        delivery.status = WebhookDeliveryStatus.PROCESSING

        try:
            async with httpx.AsyncClient(timeout=subscription.timeout_seconds) as client:
                response = await client.post(
                    subscription.url,
                    content=payload_str,
                    headers=headers,
                )

            delivery.response_status_code = response.status_code
            delivery.response_body = response.text[:2000] if response.text else None

            if 200 <= response.status_code < 300:
                # Success
                delivery.status = WebhookDeliveryStatus.SUCCESS
                delivery.completed_at = datetime.utcnow()

                subscription.successful_deliveries = (subscription.successful_deliveries or 0) + 1
                subscription.total_deliveries = (subscription.total_deliveries or 0) + 1
                subscription.last_delivery_at = datetime.utcnow()
                subscription.last_success_at = datetime.utcnow()

                self.db.commit()
                return True
            else:
                # Non-2xx response — schedule retry or fail
                return self._handle_delivery_failure(
                    delivery, subscription, f"HTTP {response.status_code}"
                )

        except Exception as e:
            delivery.error_message = str(e)
            return self._handle_delivery_failure(delivery, subscription, str(e))

    def _handle_delivery_failure(
        self,
        delivery: WebhookDelivery,
        subscription: WebhookSubscription,
        reason: str,
    ) -> bool:
        """Mark delivery as retrying or permanently failed."""
        if delivery.attempt_count < delivery.max_attempts:
            delay = self._calculate_retry_delay(delivery.attempt_count)
            delivery.status = WebhookDeliveryStatus.RETRYING
            delivery.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
            delivery.error_message = reason
        else:
            delivery.status = WebhookDeliveryStatus.FAILED
            delivery.completed_at = datetime.utcnow()
            delivery.error_message = reason

            subscription.failed_deliveries = (subscription.failed_deliveries or 0) + 1
            subscription.total_deliveries = (subscription.total_deliveries or 0) + 1
            subscription.last_delivery_at = datetime.utcnow()
            subscription.last_failure_at = datetime.utcnow()

        self.db.commit()
        return False

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    async def retry_pending_webhooks(self) -> int:
        """Retry all deliveries that are due for retry."""
        due = (
            self.db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.status == WebhookDeliveryStatus.RETRYING,
                WebhookDelivery.next_retry_at <= datetime.utcnow(),
            )
            .all()
        )

        count = 0
        for delivery in due:
            await self._deliver_webhook(delivery)
            count += 1
        return count

    @staticmethod
    def _calculate_retry_delay(attempt: int) -> int:
        """Exponential backoff: 2^attempt seconds, capped at MAX_RETRY_DELAY."""
        return min(2 ** attempt, MAX_RETRY_DELAY)

    # ------------------------------------------------------------------
    # Signature helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_signature(payload: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for a payload."""
        sig = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={sig}"

    @staticmethod
    def verify_signature(payload: str, secret: str, signature: str) -> bool:
        """Verify an inbound webhook signature."""
        if signature.startswith("sha256="):
            signature = signature[7:]

        expected = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # History & cleanup
    # ------------------------------------------------------------------

    def get_delivery_history(
        self,
        subscription_id: int,
        limit: int = 100,
    ) -> List[WebhookDelivery]:
        """Get delivery history for a subscription."""
        return (
            self.db.query(WebhookDelivery)
            .filter(WebhookDelivery.subscription_id == subscription_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
            .all()
        )

    def cleanup_old_deliveries(self, days: int = 30) -> int:
        """Delete deliveries older than *days*."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = (
            self.db.query(WebhookDelivery)
            .filter(WebhookDelivery.created_at < cutoff)
            .delete()
        )
        self.db.commit()
        return deleted
