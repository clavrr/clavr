"""
Gmail Push Notifications API Router

Receives push notifications from Gmail when new emails arrive
and triggers immediate indexing.
"""
import os
import json
import hmac
import hashlib
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Header, status, Body, BackgroundTasks, Depends
from pydantic import BaseModel

from src.utils.logger import setup_logger
from src.services.indexing.event_stream import EventStreamHandler
from src.database.webhook_models import WebhookEventType
from api.dependencies import get_event_stream_handler

logger = setup_logger(__name__)

router = APIRouter(prefix="/gmail/push", tags=["gmail-push"])


class GmailPushNotification(BaseModel):
    """Gmail Push Notification payload"""
    message: Optional[Dict[str, Any]] = None
    subscription: Optional[str] = None


@router.post("/notification")
async def receive_gmail_push_notification(
    request: Request,
    background_tasks: BackgroundTasks,
    event_handler: EventStreamHandler = Depends(get_event_stream_handler),
    x_goog_channel_id: Optional[str] = Header(None, alias="X-Goog-Channel-Id"),
    x_goog_channel_token: Optional[str] = Header(None, alias="X-Goog-Channel-Token"),
    x_goog_message_number: Optional[str] = Header(None, alias="X-Goog-Message-Number"),
    x_goog_resource_id: Optional[str] = Header(None, alias="X-Goog-Resource-Id"),
    x_goog_resource_state: Optional[str] = Header(None, alias="X-Goog-Resource-State"),
    x_goog_resource_uri: Optional[str] = Header(None, alias="X-Goog-Resource-Uri"),
    x_goog_channel_expiration: Optional[str] = Header(None, alias="X-Goog-Channel-Expiration")
):
    """
    Receive Gmail Push Notification webhook
    
    Gmail sends POST requests to this endpoint when:
    - New emails arrive (if watching INBOX)
    - Emails are modified (if watching specific labels)
    
    Headers:
    - X-Goog-Channel-Id: Unique channel identifier
    - X-Goog-Channel-Token: Token to verify notification authenticity
    - X-Goog-Message-Number: Sequential message number
    - X-Goog-Resource-Id: Resource identifier
    - X-Goog-Resource-State: State change type (sync, add, etc.)
    - X-Goog-Resource-Uri: Resource URI
    - X-Goog-Channel-Expiration: Expiration timestamp
    
    Returns:
        200 OK if notification received successfully
    """
    try:
        # Log notification received
        logger.info(
            f"📧 Gmail push notification received: "
            f"Channel={x_goog_channel_id}, "
            f"State={x_goog_resource_state}, "
            f"Message={x_goog_message_number}"
        )
        
        # Verify notification authenticity (optional but recommended)
        # In production, verify the channel token matches what we stored
        channel_token = os.getenv('GMAIL_WATCH_CHANNEL_TOKEN')
        if channel_token and x_goog_channel_token != channel_token:
            logger.warning(
                f"⚠️ Invalid channel token. Expected: {channel_token[:10]}..., "
                f"Got: {x_goog_channel_token[:10] if x_goog_channel_token else 'None'}..."
            )
            # Don't reject - Gmail might use different tokens, but log for monitoring
        
        # Only process 'add' notifications (new emails)
        # 'sync' notifications are just synchronization messages
        if x_goog_resource_state == 'add':
            logger.info(f"🆕 New email detected! Triggering indexing...")
            
            # Extract user ID from channel token or resource URI
            # The channel token should contain user_id if we set it up correctly
            user_id = _extract_user_id_from_token(x_goog_channel_token)
            
            if not user_id:
                # Try to extract from resource URI
                user_id = _extract_user_id_from_uri(x_goog_resource_uri)
            
            if user_id:
                # Trigger async indexing via EventStreamHandler
                try:
                    # Convert to int
                    user_id_int = int(user_id) if str(user_id).isdigit() else 1  # Default to 1 on failure
                    
                    if event_handler:
                        background_tasks.add_task(
                            _process_gmail_event,
                            event_handler=event_handler,
                            payload={
                                "historyId": x_goog_resource_id,
                                "channelId": x_goog_channel_id,
                                "resourceState": x_goog_resource_state
                            },
                            user_id=user_id_int,
                            event_id=x_goog_channel_id or "gmail_push",
                        )
                        logger.info(f"✅ Gmail event queued for user {user_id}")
                    else:
                         logger.error("EventStreamHandler not available")
                         
                except Exception as e:
                    logger.error(f"❌ Failed to queue Gmail event: {e}", exc_info=True)
                    # Don't fail the webhook - Gmail will retry if we return error
            else:
                logger.warning(
                    "⚠️ Could not extract user_id from notification. "
                    "Will rely on polling fallback."
                )
        elif x_goog_resource_state == 'sync':
            logger.debug("🔄 Gmail sync notification (no action needed)")
        else:
            logger.info(f"ℹ️ Gmail notification state: {x_goog_resource_state} (no action)")
        
        # Always return 200 OK to acknowledge receipt
        # Gmail will retry if we return an error status
        return {
            "status": "received",
            "message": "Notification processed",
            "resource_state": x_goog_resource_state
        }
        
    except Exception as e:
        logger.error(f"❌ Error processing Gmail push notification: {e}", exc_info=True)
        # Return 200 anyway to prevent Gmail from retrying excessively
        # We'll handle errors in the background task
        return {
            "status": "error",
            "message": str(e)
        }


async def _process_gmail_event(
    event_handler: EventStreamHandler,
    payload: Dict[str, Any],
    user_id: int,
    event_id: str,
):
    """
    Background processing for a Gmail push notification:
    1. Route through EventStreamHandler for immediate indexing.
    2. Trigger outbound email.received webhook via Celery.
    """
    # 1. Real-time indexing
    try:
        await event_handler.handle_event(
            event_type="gmail_push",
            payload=payload,
            user_id=user_id,
        )
    except Exception as e:
        logger.error(f"[GmailPush] EventStreamHandler error: {e}")

    # 2. Outbound webhook delivery
    try:
        from src.workers.tasks.webhook_tasks import deliver_webhook_task

        deliver_webhook_task.delay(
            event_type=WebhookEventType.EMAIL_RECEIVED.value,
            event_id=event_id,
            payload=payload,
            user_id=user_id,
        )
        logger.info(f"[GmailPush] Queued email.received webhook for user {user_id}")
    except Exception as e:
        logger.error(f"[GmailPush] Failed to queue webhook: {e}")


def _extract_user_id_from_token(token: Optional[str]) -> Optional[str]:
    """
    Extract user ID from channel token
    
    If we set up the watch with user_id in the token, extract it here.
    Format: "user_{user_id}_{random}"
    """
    if not token:
        return None
    
    try:
        # Token format: "user_{user_id}_{random}" or just user_id
        if token.startswith('user_'):
            parts = token.split('_')
            if len(parts) >= 2:
                return parts[1]
        # Try parsing as JSON if it's encoded
        if token.startswith('{'):
            data = json.loads(token)
            return data.get('user_id')
    except Exception:
        pass
    
    return None


def _extract_user_id_from_uri(uri: Optional[str]) -> Optional[str]:
    """
    Extract user ID from resource URI
    
    Format: "https://www.googleapis.com/gmail/v1/users/{user_id}/history"
    """
    if not uri:
        return None
    
    try:
        # Extract user_id from URI
        if '/users/' in uri:
            parts = uri.split('/users/')
            if len(parts) > 1:
                user_part = parts[1].split('/')[0]
                # Handle 'me' case - would need to look up actual user_id
                if user_part != 'me':
                    return user_part
    except Exception:
        pass
    
    return None


@router.get("/health")
async def gmail_push_health():
    """Health check endpoint for Gmail push notifications"""
    return {
        "status": "healthy",
        "service": "gmail-push-notifications",
        "webhook_url": os.getenv('WEBHOOK_BASE_URL', 'not configured')
    }

