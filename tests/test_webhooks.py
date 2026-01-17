"""
Tests for Webhook Functionality

Tests for webhook subscriptions, deliveries, and signature verification.
"""
import pytest
import json
import hmac
import hashlib
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.orm import Session

from src.database.webhook_models import (
    WebhookSubscription,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEventType
)
from src.features.webhook_service import WebhookService
from src.database.models import User


@pytest.fixture
def db_session():
    """Mock database session"""
    session = Mock(spec=Session)
    session.query = Mock()
    session.add = Mock()
    session.commit = Mock()
    session.refresh = Mock()
    session.delete = Mock()
    return session


@pytest.fixture
def test_user():
    """Create a test user"""
    user = User(
        id=1,
        email="test@example.com",
        username="testuser"
    )
    return user


@pytest.fixture
def webhook_service(db_session):
    """Create webhook service instance"""
    return WebhookService(db_session)


@pytest.fixture
def test_subscription():
    """Create a test webhook subscription"""
    return WebhookSubscription(
        id=1,
        user_id=1,
        url="https://example.com/webhook",
        event_types=["email.received", "task.completed"],
        secret="test_secret_123",
        description="Test webhook",
        is_active=True,
        retry_count=3,
        timeout_seconds=10,
        total_deliveries=0,
        successful_deliveries=0,
        failed_deliveries=0
    )


@pytest.fixture
def test_delivery(test_subscription):
    """Create a test webhook delivery"""
    return WebhookDelivery(
        id=1,
        subscription_id=test_subscription.id,
        subscription=test_subscription,
        event_type="email.received",
        event_id="msg-123",
        payload={"subject": "Test Email"},
        status=WebhookDeliveryStatus.PENDING,
        attempt_count=0,
        max_attempts=3
    )


class TestWebhookSubscriptionCRUD:
    """Test webhook subscription CRUD operations"""
    
    def test_create_subscription(self, webhook_service, db_session):
        """Test creating a webhook subscription"""
        subscription = webhook_service.create_subscription(
            user_id=1,
            url="https://example.com/webhook",
            event_types=["email.received"],
            secret="secret123",
            description="Test webhook",
            retry_count=3,
            timeout_seconds=10
        )
        
        # Verify subscription was added to database
        db_session.add.assert_called_once()
        db_session.commit.assert_called_once()
        db_session.refresh.assert_called_once()
    
    def test_get_subscription(self, webhook_service, db_session, test_subscription):
        """Test getting a webhook subscription by ID"""
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = test_subscription
        db_session.query.return_value = mock_query
        
        subscription = webhook_service.get_subscription(1)
        
        assert subscription == test_subscription
        db_session.query.assert_called_once_with(WebhookSubscription)
    
    def test_get_user_subscriptions(self, webhook_service, db_session, test_subscription):
        """Test getting all subscriptions for a user"""
        mock_query = Mock()
        mock_query.filter.return_value.filter.return_value.order_by.return_value.all.return_value = [test_subscription]
        db_session.query.return_value = mock_query
        
        subscriptions = webhook_service.get_user_subscriptions(user_id=1, active_only=True)
        
        assert len(subscriptions) == 1
        assert subscriptions[0] == test_subscription
    
    def test_update_subscription(self, webhook_service, db_session, test_subscription):
        """Test updating a webhook subscription"""
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = test_subscription
        db_session.query.return_value = mock_query
        
        updated = webhook_service.update_subscription(
            subscription_id=1,
            description="Updated description",
            is_active=False
        )
        
        assert updated.description == "Updated description"
        assert updated.is_active == False
        db_session.commit.assert_called_once()
    
    def test_delete_subscription(self, webhook_service, db_session, test_subscription):
        """Test deleting a webhook subscription"""
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = test_subscription
        db_session.query.return_value = mock_query
        
        result = webhook_service.delete_subscription(1)
        
        assert result == True
        db_session.delete.assert_called_once_with(test_subscription)
        db_session.commit.assert_called_once()
    
    def test_delete_nonexistent_subscription(self, webhook_service, db_session):
        """Test deleting a non-existent subscription"""
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        db_session.query.return_value = mock_query
        
        result = webhook_service.delete_subscription(999)
        
        assert result == False
        db_session.delete.assert_not_called()


class TestWebhookDelivery:
    """Test webhook delivery functionality"""
    
    @pytest.mark.asyncio
    async def test_successful_delivery(self, webhook_service, db_session, test_delivery):
        """Test successful webhook delivery"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            success = await webhook_service._deliver_webhook(test_delivery)
        
        assert success == True
        assert test_delivery.status == WebhookDeliveryStatus.SUCCESS
        assert test_delivery.response_status_code == 200
        assert test_delivery.attempt_count == 1
        db_session.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_failed_delivery_with_retry(self, webhook_service, db_session, test_delivery):
        """Test failed delivery with retry scheduled"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            success = await webhook_service._deliver_webhook(test_delivery)
        
        assert success == False
        assert test_delivery.status == WebhookDeliveryStatus.RETRYING
        assert test_delivery.attempt_count == 1
        assert test_delivery.next_retry_at is not None
    
    @pytest.mark.asyncio
    async def test_failed_delivery_max_retries(self, webhook_service, db_session, test_delivery):
        """Test failed delivery after max retries"""
        test_delivery.attempt_count = 2  # Already tried twice
        
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            success = await webhook_service._deliver_webhook(test_delivery)
        
        assert success == False
        assert test_delivery.status == WebhookDeliveryStatus.FAILED
        assert test_delivery.attempt_count == 3
        assert test_delivery.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_delivery_timeout(self, webhook_service, db_session, test_delivery):
        """Test webhook delivery timeout"""
        import asyncio
        
        async def mock_timeout(*args, **kwargs):
            raise asyncio.TimeoutError("Request timeout")
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=mock_timeout)
            
            success = await webhook_service._deliver_webhook(test_delivery)
        
        assert success == False
        assert test_delivery.status == WebhookDeliveryStatus.RETRYING
        assert "Request timeout" in test_delivery.error_message
    
    @pytest.mark.asyncio
    async def test_delivery_signature_generation(self, webhook_service, test_delivery):
        """Test HMAC signature generation"""
        payload = json.dumps({"test": "data"})
        secret = "test_secret"
        
        signature = webhook_service._generate_signature(payload, secret)
        
        assert signature.startswith("sha256=")
        
        # Verify signature is correct
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        assert signature == f"sha256={expected_signature}"


class TestWebhookSignatureVerification:
    """Test webhook signature verification"""
    
    def test_verify_valid_signature(self):
        """Test verifying a valid signature"""
        payload = json.dumps({"test": "data"})
        secret = "test_secret"
        
        # Generate signature
        signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Verify signature
        is_valid = WebhookService.verify_signature(payload, secret, f"sha256={signature}")
        
        assert is_valid == True
    
    def test_verify_invalid_signature(self):
        """Test verifying an invalid signature"""
        payload = json.dumps({"test": "data"})
        secret = "test_secret"
        wrong_signature = "sha256=invalid_signature_123"
        
        is_valid = WebhookService.verify_signature(payload, secret, wrong_signature)
        
        assert is_valid == False
    
    def test_verify_signature_without_prefix(self):
        """Test verifying signature without sha256= prefix"""
        payload = json.dumps({"test": "data"})
        secret = "test_secret"
        
        signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Verify without prefix
        is_valid = WebhookService.verify_signature(payload, secret, signature)
        
        assert is_valid == True
    
    def test_verify_signature_wrong_secret(self):
        """Test verifying signature with wrong secret"""
        payload = json.dumps({"test": "data"})
        secret = "test_secret"
        wrong_secret = "wrong_secret"
        
        signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        is_valid = WebhookService.verify_signature(payload, wrong_secret, signature)
        
        assert is_valid == False


class TestWebhookRetryLogic:
    """Test webhook retry logic"""
    
    def test_calculate_retry_delay(self, webhook_service):
        """Test exponential backoff calculation"""
        # Attempt 1: 2^1 = 2 seconds
        assert webhook_service._calculate_retry_delay(1) == 2
        
        # Attempt 2: 2^2 = 4 seconds
        assert webhook_service._calculate_retry_delay(2) == 4
        
        # Attempt 3: 2^3 = 8 seconds
        assert webhook_service._calculate_retry_delay(3) == 8
        
        # Large attempt: capped at 3600 seconds (1 hour)
        assert webhook_service._calculate_retry_delay(20) == 3600
    
    @pytest.mark.asyncio
    async def test_retry_pending_webhooks(self, webhook_service, db_session, test_delivery):
        """Test retrying pending webhooks"""
        test_delivery.status = WebhookDeliveryStatus.RETRYING
        test_delivery.next_retry_at = datetime.utcnow() - timedelta(minutes=1)  # Due for retry
        
        mock_query = Mock()
        mock_query.filter.return_value.all.return_value = [test_delivery]
        db_session.query.return_value = mock_query
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            retry_count = await webhook_service.retry_pending_webhooks()
        
        assert retry_count == 1


class TestWebhookEventTriggers:
    """Test webhook event triggering"""
    
    @pytest.mark.asyncio
    async def test_trigger_webhook_event(self, webhook_service, db_session, test_subscription):
        """Test triggering a webhook event"""
        # Mock get_active_subscriptions_for_event
        mock_query = Mock()
        mock_query.filter.return_value.all.return_value = [test_subscription]
        db_session.query.return_value = mock_query
        
        with patch.object(webhook_service, '_deliver_webhook', new=AsyncMock()) as mock_deliver:
            deliveries = await webhook_service.trigger_webhook_event(
                event_type=WebhookEventType.EMAIL_RECEIVED,
                event_id="msg-123",
                payload={"subject": "Test Email"},
                user_id=1
            )
        
        db_session.add.assert_called()
        db_session.commit.assert_called()
        mock_deliver.assert_called()
    
    def test_get_active_subscriptions_for_event(self, webhook_service, db_session, test_subscription):
        """Test getting subscriptions for specific event type"""
        mock_query = Mock()
        mock_query.filter.return_value.all.return_value = [test_subscription]
        db_session.query.return_value = mock_query
        
        subscriptions = webhook_service.get_active_subscriptions_for_event(
            WebhookEventType.EMAIL_RECEIVED
        )
        
        assert len(subscriptions) == 1
        assert subscriptions[0] == test_subscription


class TestWebhookDeliveryHistory:
    """Test webhook delivery history"""
    
    def test_get_delivery_history(self, webhook_service, db_session, test_delivery):
        """Test getting delivery history for a subscription"""
        mock_query = Mock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [test_delivery]
        db_session.query.return_value = mock_query
        
        deliveries = webhook_service.get_delivery_history(
            subscription_id=1,
            limit=100
        )
        
        assert len(deliveries) == 1
        assert deliveries[0] == test_delivery
    
    def test_cleanup_old_deliveries(self, webhook_service, db_session):
        """Test cleaning up old webhook deliveries"""
        mock_query = Mock()
        mock_query.filter.return_value.delete.return_value = 50
        db_session.query.return_value = mock_query
        
        deleted_count = webhook_service.cleanup_old_deliveries(days=30)
        
        assert deleted_count == 50
        db_session.commit.assert_called_once()


class TestWebhookEventTypes:
    """Test webhook event types"""
    
    def test_all_event_types_defined(self):
        """Test that all event types are properly defined"""
        event_types = [e.value for e in WebhookEventType]
        
        # Email events
        assert "email.received" in event_types
        assert "email.sent" in event_types
        assert "email.indexed" in event_types
        
        # Calendar events
        assert "calendar.event.created" in event_types
        assert "calendar.event.updated" in event_types
        assert "calendar.event.deleted" in event_types
        
        # Task events
        assert "task.created" in event_types
        assert "task.updated" in event_types
        assert "task.completed" in event_types
        assert "task.deleted" in event_types
        
        # Indexing events
        assert "indexing.started" in event_types
        assert "indexing.completed" in event_types
        assert "indexing.failed" in event_types
        
        # User events
        assert "user.created" in event_types
        assert "user.settings.updated" in event_types
        
        # System events
        assert "export.completed" in event_types
        assert "sync.completed" in event_types
    
    def test_event_type_values(self):
        """Test event type values follow naming convention"""
        for event_type in WebhookEventType:
            # Should be lowercase with dots
            assert event_type.value.islower()
            assert '.' in event_type.value
            
            # Should follow category.action pattern
            parts = event_type.value.split('.')
            assert len(parts) >= 2


class TestWebhookStatistics:
    """Test webhook statistics tracking"""
    
    @pytest.mark.asyncio
    async def test_statistics_on_success(self, webhook_service, db_session, test_delivery):
        """Test that statistics are updated on successful delivery"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            await webhook_service._deliver_webhook(test_delivery)
        
        # Check subscription statistics
        subscription = test_delivery.subscription
        assert subscription.successful_deliveries == 1
        assert subscription.total_deliveries == 1
        assert subscription.last_success_at is not None
    
    @pytest.mark.asyncio
    async def test_statistics_on_failure(self, webhook_service, db_session, test_delivery):
        """Test that statistics are updated on failed delivery"""
        test_delivery.attempt_count = 2  # Already tried twice
        
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Error"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            await webhook_service._deliver_webhook(test_delivery)
        
        # Check subscription statistics
        subscription = test_delivery.subscription
        assert subscription.failed_deliveries == 1
        assert subscription.total_deliveries == 1
        assert subscription.last_failure_at is not None


# Integration test with mock HTTP server
class TestWebhookIntegration:
    """Integration tests for webhook functionality"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_webhook_flow(self, webhook_service, db_session):
        """Test complete webhook flow from creation to delivery"""
        # This would require a real database and HTTP server
        # Skipping for now, but can be implemented with pytest-httpserver
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
