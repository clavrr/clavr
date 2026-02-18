"""
Proactive Voice Nudge Tasks

Celery beat task that periodically evaluates all connected users
for nudge-worthy events and pushes notifications via WebSocket.
"""
import asyncio
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def evaluate_nudges_task():
    """
    Periodic task: scan connected users for proactive voice nudge triggers.

    Runs every 60 seconds via Celery beat. For each connected user,
    it checks for meeting_imminent, urgent_email, ghost_draft_ready,
    and deadline_approaching triggers.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_evaluate_nudges_async())
        loop.close()
    except Exception as e:
        logger.error(f"[ProactiveNudge] Task error: {e}", exc_info=True)


async def _evaluate_nudges_async():
    """Async implementation of the nudge evaluation."""
    from api.websocket_manager import get_connection_manager
    from src.services.voice_proactivity import VoiceProactivityService
    from src.utils.config import load_config

    config = load_config()
    manager = get_connection_manager()
    svc = VoiceProactivityService(config=config)

    connected_users = manager.get_connected_users()
    if not connected_users:
        return

    logger.info(f"[ProactiveNudge] Evaluating nudges for {len(connected_users)} connected users")

    for user_id in connected_users:
        try:
            nudges = await svc.check_proactive_triggers(user_id)
            for nudge in nudges:
                sent = await manager.send_to_user(user_id, nudge.to_dict())
                if sent > 0:
                    svc.record_nudge_delivered(user_id)
                    logger.info(
                        f"[ProactiveNudge] Delivered {nudge.trigger_type.value} "
                        f"nudge to user {user_id}"
                    )
        except Exception as e:
            logger.debug(f"[ProactiveNudge] Error for user {user_id}: {e}")
