"""
Voice Proactivity Router

API endpoints for:
  - Wake-word audio verification
  - Nudge preference management
  - Proactive voice nudge WebSocket
"""
import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_async_db
from src.database.models import User
from src.utils.logger import setup_logger
from api.auth import get_current_user_required
from api.dependencies import get_config

logger = setup_logger(__name__)
router = APIRouter(prefix="/voice", tags=["voice-proactivity"])

# Wake-Word Verification

@router.post("/wake")
async def verify_wake_word(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user_required),
):
    """
    Receive a wake-word audio snippet and verify server-side.

    Expects raw PCM S16LE mono audio at 16kHz.

    Returns:
        JSON with verified status, confidence, and detected phrase.
    """
    from src.ai.voice.wake_word import WakeWordVerifier

    try:
        audio_bytes = await audio.read()

        verifier = WakeWordVerifier()
        result = await verifier.verify_audio(
            audio_bytes=audio_bytes,
            user_id=current_user.id,
        )

        return {
            "success": True,
            **result.to_dict(),
        }

    except Exception as e:
        logger.error(f"[VoiceProactivity] Wake-word verification error: {e}", exc_info=True)
        return {
            "success": False,
            "verified": False,
            "error": str(e),
        }


# Nudge Preferences

@router.get("/nudge/settings")
async def get_nudge_settings(
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config),
):
    """Get the user's voice nudge preferences."""
    from src.services.voice_proactivity import VoiceProactivityService

    svc = VoiceProactivityService(config=config)
    prefs = svc.get_preferences(current_user.id)

    return {
        "success": True,
        "preferences": prefs.to_dict(),
    }


@router.put("/nudge/settings")
async def update_nudge_settings(
    settings: Dict[str, Any],
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config),
):
    """Update the user's voice nudge preferences."""
    from src.services.voice_proactivity import (
        VoiceProactivityService,
        NudgePreferences,
    )

    svc = VoiceProactivityService(config=config)
    prefs = NudgePreferences.from_dict(settings)
    updated = svc.update_preferences(current_user.id, prefs)

    return {
        "success": True,
        "preferences": updated.to_dict(),
    }


# Proactive Nudge WebSocket

@router.websocket("/ws/proactive")
async def websocket_proactive_nudge(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_async_db),
    config=Depends(get_config),
):
    """
    Persistent WebSocket for receiving voice nudge notifications.

    The server periodically evaluates proactive triggers and pushes
    nudge messages to the client. The client can accept a nudge to
    initiate a voice session.

    Client messages:
        {"type": "auth", "token": "..."}      — authenticate
        {"type": "ack",  "nudge_id": "..."}   — acknowledge nudge
        {"type": "dismiss", "nudge_id": "..."} — dismiss nudge

    Server messages:
        {"type": "voice_nudge", ...}           — proactive nudge
        {"type": "authenticated"}              — auth success
        {"type": "error", "message": "..."}    — error
    """
    await websocket.accept()
    logger.info("[VoiceProactivity] Nudge WebSocket connected")

    try:
        # --- Authenticate ---
        from api.dependencies import AppState

        token = websocket.query_params.get("token")
        if not token:
            try:
                auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
                if auth_msg.get("type") == "auth":
                    token = auth_msg.get("token")
            except Exception:
                pass

        auth_service = AppState.get_auth_service(db)
        user = None
        if token:
            user = await auth_service.validate_session_token(token)

        if not user:
            await websocket.send_json({"type": "error", "message": "Authentication required."})
            await websocket.close(code=4003)
            return

        await websocket.send_json({"type": "authenticated", "user_id": user.id})
        logger.info(f"[VoiceProactivity] User {user.id} authenticated for nudges")

        # --- Nudge loop ---
        from src.services.voice_proactivity import VoiceProactivityService

        svc = VoiceProactivityService(config=config)
        check_interval = 30  # seconds between nudge checks

        async def nudge_check_loop():
            while True:
                try:
                    nudges = await svc.check_proactive_triggers(user.id)
                    for nudge in nudges:
                        await websocket.send_json(nudge.to_dict())
                        svc.record_nudge_delivered(user.id)
                        logger.info(f"[VoiceProactivity] Nudge delivered: {nudge.trigger_type.value}")
                except Exception as e:
                    logger.debug(f"[VoiceProactivity] Nudge check error: {e}")

                await asyncio.sleep(check_interval)

        # Run nudge checker in background while listening for client messages
        check_task = asyncio.create_task(nudge_check_loop())

        try:
            while True:
                message = await websocket.receive_json()
                msg_type = message.get("type")

                if msg_type == "ack":
                    logger.info(f"[VoiceProactivity] Nudge acknowledged")
                elif msg_type == "dismiss":
                    logger.info(f"[VoiceProactivity] Nudge dismissed")
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

        except WebSocketDisconnect:
            logger.info(f"[VoiceProactivity] User {user.id} disconnected from nudge WS")
        finally:
            check_task.cancel()

    except Exception as e:
        logger.error(f"[VoiceProactivity] WebSocket error: {e}", exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
