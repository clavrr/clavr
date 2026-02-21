"""
Slack Events Router

Handles incoming Slack events via HTTP (Events API).
Supports url_verification, event_callback for messages, reactions, and channels.
Routes events through EventStreamHandler for indexing and triggers outbound webhooks.
"""
from typing import Dict, Any, Optional
import hmac
import hashlib
import time
import json
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends, status
from pydantic import BaseModel

from src.utils.logger import setup_logger
from src.services.indexing.event_stream import EventStreamHandler, EventType
from src.services.user_mapping import UserMappingService
from src.database.webhook_models import WebhookEventType
from api.dependencies import get_event_stream_handler, get_config

logger = setup_logger(__name__)

router = APIRouter(tags=["Slack Events"])


class SlackEvent(BaseModel):
    token: Optional[str] = None
    challenge: Optional[str] = None
    type: str
    event_id: Optional[str] = None
    event_time: Optional[int] = None
    event: Optional[Dict[str, Any]] = None
    team_id: Optional[str] = None
    api_app_id: Optional[str] = None


# Map Slack inner event types → (EventStreamHandler type, WebhookEventType)
SLACK_EVENT_ROUTING: Dict[str, Dict[str, Any]] = {
    "app_mention": {
        "stream_type": EventType.SLACK_MESSAGE,
        "webhook_type": WebhookEventType.SLACK_MESSAGE_RECEIVED,
    },
    "message": {
        "stream_type": EventType.SLACK_MESSAGE,
        "webhook_type": WebhookEventType.SLACK_MESSAGE_RECEIVED,
    },
    "reaction_added": {
        "stream_type": EventType.SLACK_REACTION,
        "webhook_type": WebhookEventType.SLACK_REACTION_ADDED,
    },
    "channel_created": {
        "stream_type": None,  # No indexing needed
        "webhook_type": WebhookEventType.SLACK_CHANNEL_CREATED,
    },
    "member_joined_channel": {
        "stream_type": None,  # No indexing needed
        "webhook_type": None,  # Informational only
    },
}


async def verify_slack_signature(request: Request, config=Depends(get_config)):
    """
    Verify that the request came from Slack.
    Reference: https://api.slack.com/authentication/verifying-requests-from-slack
    """
    # Skip verification for local dev/testing if configured
    if config.is_development and not config.slack.signing_secret:
        logger.warning("Skipping Slack signature verification in dev mode")
        return

    signing_secret = config.slack.signing_secret
    if not signing_secret:
        logger.warning("Slack signing secret not configured")
        return

    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    signature = request.headers.get("X-Slack-Signature")

    if not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Missing Slack signature headers")

    # Check for replay attacks (ignore requests older than 5 minutes)
    if abs(time.time() - int(timestamp)) > 60 * 5:
        raise HTTPException(status_code=400, detail="Request timestamp out of range")

    # Read body
    body = await request.body()
    body_decoded = body.decode("utf-8")

    sig_basestring = f"v0:{timestamp}:{body_decoded}"

    my_signature = "v0=" + hmac.new(
        key=signing_secret.encode("utf-8"),
        msg=sig_basestring.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(my_signature, signature):
        logger.warning(
            f"Slack signature verification failed. Expected: {my_signature}, Got: {signature}"
        )
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


async def _process_slack_event(
    payload: Dict[str, Any],
    event_handler: Optional[EventStreamHandler],
    user_id: int,
):
    """
    Background processing for a Slack event:
    1. Route through EventStreamHandler for indexing.
    2. Trigger outbound webhooks via Celery.
    """
    event_data = payload.get("event", {})
    inner_type = event_data.get("type", "")
    event_id = payload.get("event_id", "")

    routing = SLACK_EVENT_ROUTING.get(inner_type, {})

    # --- 1. Real-time indexing ---
    stream_type = routing.get("stream_type")
    if stream_type and event_handler:
        try:
            await event_handler.handle_event(
                event_type=stream_type,
                payload=payload,
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f"[SlackEvents] EventStreamHandler error for {inner_type}: {e}")

    # --- 2. Outbound webhook delivery ---
    webhook_type: Optional[WebhookEventType] = routing.get("webhook_type")
    if webhook_type:
        try:
            from src.workers.tasks.webhook_tasks import deliver_webhook_task

            deliver_webhook_task.delay(
                event_type=webhook_type.value,
                event_id=event_id,
                payload=payload,
                user_id=user_id,
            )
            logger.info(
                f"[SlackEvents] Queued webhook {webhook_type.value} for event {event_id}"
            )
        except Exception as e:
            logger.error(f"[SlackEvents] Failed to queue webhook for {inner_type}: {e}")

    # --- 3. Autonomous Bridge dispatch ---
    if inner_type in ("reaction_added", "app_mention"):
        try:
            from src.services.autonomous_bridge import AutonomousBridgeService

            await AutonomousBridgeService.try_handle(
                event_type=inner_type,
                payload=payload,
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f"[SlackEvents] Bridge dispatch error for {inner_type}: {e}")


@router.post("/slack/events", status_code=status.HTTP_200_OK)
async def handle_slack_event(
    request: Request,
    background_tasks: BackgroundTasks,
    event_handler: EventStreamHandler = Depends(get_event_stream_handler),
):
    """
    Handle incoming Slack events.
    Supporting:
    - url_verification (Challenge)
    - event_callback (Messages, Reactions, Channels)
    """
    # 1. Verify Signature
    try:
        config = get_config()
        await verify_slack_signature(request, config)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating Slack request: {e}")
        raise HTTPException(status_code=400, detail="Error validating request")

    # 2. Parse Body
    try:
        body_bytes = await request.body()
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = payload.get("type")

    # 3. Handle URL Verification Challenge
    if event_type == "url_verification":
        logger.info("Received Slack url_verification challenge")
        return {"challenge": payload.get("challenge")}

    # 4. Handle Event Callback
    if event_type == "event_callback":
        event_data = payload.get("event", {})
        inner_type = event_data.get("type", "")
        event_id = payload.get("event_id")

        # --- Resolve Slack user → Clavr user ---
        slack_user_id = event_data.get("user")  # present on most event types
        user_id = _resolve_user_id(slack_user_id)

        logger.info(
            f"Processing Slack event {event_id} ({inner_type}) for user_id={user_id}"
        )

        # Ignore bot's own messages to prevent loops
        if event_data.get("bot_id") or event_data.get("subtype") == "bot_message":
            logger.debug(f"Ignoring bot message in event {event_id}")
            return {"status": "ok"}

        # Process in background (Slack requires response < 3s)
        background_tasks.add_task(
            _process_slack_event,
            payload=payload,
            event_handler=event_handler,
            user_id=user_id,
        )

        return {"status": "ok"}

    # 5. Handle other types (rate_limited, etc.)
    logger.info(f"Received unhandled Slack event type: {event_type}")
    return {"status": "ignored"}


def _resolve_user_id(slack_user_id: Optional[str]) -> int:
    """
    Resolve a Slack user ID to a Clavr user ID.

    Uses UserMappingService with DB session. Falls back to DEFAULT_USER_ID
    if resolution is not possible (no DB, no match, etc.).
    """
    from src.services.user_mapping import DEFAULT_USER_ID

    if not slack_user_id:
        return DEFAULT_USER_ID

    try:
        from src.database import get_db_context

        with get_db_context() as db:
            mapping_service = UserMappingService(db)
            return mapping_service.resolve_or_default(slack_user_id=slack_user_id)
    except Exception as e:
        logger.warning(
            f"[SlackEvents] User resolution failed for {slack_user_id}, using default: {e}"
        )
        return DEFAULT_USER_ID
