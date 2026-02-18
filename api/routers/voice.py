"""
Voice Interface Router
Handles voice input: STT → Analyzer normalization → Orchestrator → Response
"""
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
import json
import asyncio
import base64
from typing import Dict, Any

import re

from src.database import get_async_db
from src.utils.logger import setup_logger
from src.utils import extract_first_name
from api.dependencies import get_config, AppState, get_auth_service, get_integration_service
from src.database.models import User
from src.services.voice_service import VoiceService
from src.utils.audio_transcoder import StreamingTranscoder
from src.services.service_constants import ServiceConstants
from api.auth import get_current_user_required

logger = setup_logger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/introduction")
async def get_voice_introduction(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_async_db),
    config = Depends(get_config)
) -> Dict[str, Any]:
    """
    Get initialization data for the voice interface.
    
    Returns:
        - User details (name, context)
        - Connected integrations
        - Proactive reminders/suggestions for the greeting
        - Capability summary
    """
    try:
        voice_service = VoiceService(db, config)
        config_data = await voice_service.get_voice_configuration(current_user)
        
        return {
            "success": True,
            "introduction": config_data
        }
    except Exception as e:
        logger.error(f"[VoiceAPI] Error getting introduction: {e}", exc_info=True)
        # Return partial/fallback data on error instead of 500
        return {
            "success": False,
            "error": str(e),
            "introduction": {
                "user_name": extract_first_name(current_user.name, current_user.email),
                "proactive_reminder": ""
            }
        }


@router.websocket("/ws/transcribe")
async def websocket_transcribe(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_async_db),
    config = Depends(get_config)
):
    """
    WebSocket endpoint for real-time voice interaction using Gemini Live API.
    Refactored to use VoiceService for core logic.
    """
    await websocket.accept()
    logger.info("[WS] Client connected for Gemini Live session")
    
    try:
        # 1. Authenticate user
        token = websocket.query_params.get("token")
        if not token:
            try:
                auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=3.0)
                if auth_msg.get("type") == "auth":
                    token = auth_msg.get("token")
            except Exception as e:
                logger.debug(f"[WS] Auth message receive error: {e}")
        
        auth_service = AppState.get_auth_service(db)
        user = None
        if token:
            user = await auth_service.validate_session_token(token)
        
        if not user:
            logger.warning("[WS] Authentication failed")
            await websocket.send_json({"type": "error", "message": "Authentication required."})
            await websocket.close(code=4003)
            return

        logger.info(f"[WS] Authenticated user: {user.id}")

        # 2. Initialize processing components
        voice_service = VoiceService(db, config)
        transcoder = StreamingTranscoder()
        
        try:
             transcoder.start()
        except Exception as e:
             logger.error(f"[WS] Failed to start transcoder: {e}")
             await websocket.close(code=1011)
             return

        # 3. Define Audio Generator
        async def audio_generator():
            try:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                    
                    if "bytes" in message:
                        transcoder.process_chunk(message["bytes"])
                        for pcm_chunk in transcoder.get_exhaust_chunks():
                            # Noise Gate: Skip very low-energy chunks
                            energy = StreamingTranscoder.calculate_rms(pcm_chunk)
                            # Lower threshold to 100 to catch more audio
                            if energy >= ServiceConstants.VOICE_ENERGY_THRESHOLD:
                                yield pcm_chunk
                            # Log occasionally to track activity
                            if not hasattr(audio_generator, '_chunk_count'):
                                audio_generator._chunk_count = 0
                                audio_generator._yielded = 0
                            audio_generator._chunk_count += 1
                            if energy >= ServiceConstants.VOICE_ENERGY_THRESHOLD:
                                audio_generator._yielded += 1
                            if audio_generator._chunk_count <= 5 or audio_generator._chunk_count % 100 == 0:
                                logger.info(f"[AudioGen] Chunk {audio_generator._chunk_count}: energy={energy:.0f}, yielded={audio_generator._yielded}")
                                
                    elif "text" in message:
                        data = json.loads(message["text"])
                        if data.get("type") == "stop":
                            break
            except Exception as e:
                logger.error(f"[WS] audio_generator error: {e}")
            finally:
                transcoder.stop()

        # 4. Signal readiness and start processing
        # Check if this session was triggered by wake-word
        trigger = websocket.query_params.get("trigger", "manual")
        wake_word_extras = ""
        if trigger == "wake_word":
            try:
                from src.services.voice_proactivity import VoiceProactivityService
                from src.ai.prompts.voice_prompts import WAKE_WORD_GREETING_TEMPLATE
                
                proactivity_svc = VoiceProactivityService(config=config)
                nudges = await proactivity_svc.check_proactive_triggers(user.id)
                proactive_context = nudges[0].spoken_text if nudges else "No pending items."
                wake_word_extras = WAKE_WORD_GREETING_TEMPLATE.format(
                    proactive_context=proactive_context
                )
            except Exception as e:
                logger.debug(f"[WS] Wake-word context injection error: {e}")

        await websocket.send_json({
            "type": "ready",
            "message": "Connected to Gemini Live",
            "trigger": trigger
        })

        await voice_service.process_voice_stream(
            user=user,
            audio_generator=audio_generator(),
            websocket=websocket,
            system_extras=wake_word_extras if wake_word_extras else None
        )
                    
    except Exception as e:
        logger.error(f"[WS] Session error: {e}", exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception as e:
            logger.debug(f"[WS] Error closing websocket: {e}")
