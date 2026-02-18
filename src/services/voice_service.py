"""
Voice Service
Handles the business logic for voice interactions, including context gathering,
tool initialization, and Gemini Live streaming.
"""
import asyncio
import uuid
import re
import json
import os
from datetime import datetime
from typing import AsyncGenerator, Optional, List, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.logger import setup_logger
from src.utils import extract_first_name
from src.ai.voice.gemini_live_client import GeminiLiveClient
from src.ai.voice.elevenlabs_client import ElevenLabsLiveClient
from src.ai.conversation_memory import ConversationMemory
from src.database.models import User, UserIntegration
from src.services.context_service import get_context_service
from src.ai.prompts.voice_prompts import (
    USER_PERSONALIZATION_TEMPLATE,
    INTEGRATION_STATUS_TEMPLATE,
    MISSING_INTEGRATION_INSTRUCTION
)

logger = setup_logger(__name__)

class VoiceService:
    """
    Service for managing voice interaction sessions.
    """
    
    def __init__(self, db: AsyncSession, config: Any):
        self.db = db
        self.config = config
        self.context_service = get_context_service()

    async def get_voice_context(self, user: User, limit_history: Optional[int] = None) -> str:
        """
        Assemble the full context prompt for a voice session.
        """
        user_first_name = extract_first_name(user.name, user.email)
        
        # 1. Fetch Unified Context (History, Prefs, Graph, Entities)
        # Limit history more strictly for voice to avoid hitting prompt limits
        context_data = await self.context_service.get_unified_context(
            user_id=user.id,
            query="",
            limit_history=limit_history if limit_history is not None else 3 # Default to 3 for voice
        )
        
        # 2. Build Integration Status Context
        integration_context = await self._get_integration_status_context(user)
        
        # 3. Build Personalization Context
        personalization = USER_PERSONALIZATION_TEMPLATE.format(
            user_name=user.name or user_first_name,
            user_email=user.email
        )
        
        # 4. Combine all parts
        context_parts = [
            personalization,
            context_data.get("conversation_context", ""),
            context_data.get("entity_context", ""),
            context_data.get("semantic_context", ""),
            integration_context,
            MISSING_INTEGRATION_INSTRUCTION
        ]
        
        full_context = "\n\n".join([p for p in context_parts if p])
        
        # Log prompt size for debugging quota issues
        logger.info(f"[VoiceService] Generated context size: {len(full_context)} characters")
        if len(full_context) > 7000:
             logger.warning(f"[VoiceService] Large context detected ({len(full_context)} chars). This may cause ElevenLabs issues.")
        
        return full_context
        
    async def _get_integration_status_context(self, user: User) -> str:
        """Fetch active integrations and format the status context."""
        try:
            from src.services.service_constants import SERVICE_CONSTANTS
            stmt = select(UserIntegration.provider).where(UserIntegration.user_id == user.id)
            result = await self.db.execute(stmt)
            active_providers = set(result.scalars().all())
            
            services = SERVICE_CONSTANTS.get_integration_names()
            
            connected = []
            disconnected = []
            
            for provider, name in services.items():
                if provider in active_providers:
                    connected.append(f"{name}: CONNECTED")
                else:
                    disconnected.append(name)
            
            # Add native tools
            connected.extend(["Weather: CONNECTED", "Maps: CONNECTED", "Timezone: CONNECTED"])
            
            from src.core.calendar.utils import get_user_timezone
            import pytz
            tz_name = get_user_timezone(self.config)
            user_tz = pytz.timezone(tz_name)
            now_user = datetime.now(user_tz)
            
            return INTEGRATION_STATUS_TEMPLATE.format(
                current_time=now_user.strftime("%A, %B %d, %Y at %I:%M %p"),
                disconnected_services=", ".join(disconnected) if disconnected else "None",
                connected_services="\n".join(connected)
            )
        except Exception as e:
            logger.error(f"Failed to fetch integration status: {e}")
            return ""
    
    async def get_voice_configuration(self, user: User) -> dict:
        """
        Gather dynamic variables for ElevenLabs personalization.
        These populate {{variable}} placeholders in the ElevenLabs system prompt.
        """
        from src.services.service_constants import SERVICE_CONSTANTS
        
        user_first_name = extract_first_name(user.name, user.email)
        
        # Get connected integrations with detail
        connected = []
        calendar_type = "Google Calendar"  # Default
        email_type = "Gmail"  # Default
        notes_type = ""  # Will be set if connected
        tasks_type = ""  # Will be set if connected
        
        try:
            stmt = select(UserIntegration.provider).where(UserIntegration.user_id == user.id)
            result = await self.db.execute(stmt)
            active_providers = set(result.scalars().all())
            services = SERVICE_CONSTANTS.get_integration_names()
            
            for provider in active_providers:
                name = services.get(provider, provider.replace('_', ' ').title())
                connected.append(name)
                
                # Track specific types
                if 'calendar' in provider.lower():
                    if 'google' in provider.lower():
                        calendar_type = "Google Calendar"
                    elif 'outlook' in provider.lower():
                        calendar_type = "Outlook Calendar"
                    elif 'apple' in provider.lower():
                        calendar_type = "Apple Calendar"
                        
                if 'gmail' in provider.lower():
                    email_type = "Gmail"
                elif 'outlook' in provider.lower() and 'mail' in provider.lower():
                    email_type = "Outlook"
                elif 'apple' in provider.lower() and 'mail' in provider.lower():
                    email_type = "Apple Mail"
                
                # Track notes type
                if 'keep' in provider.lower():
                    notes_type = "Google Keep"
                elif 'notion' in provider.lower():
                    notes_type = "Notion"
                elif 'apple' in provider.lower() and 'notes' in provider.lower():
                    notes_type = "Apple Notes"
                
                # Track tasks type
                if 'tasks' in provider.lower() and 'google' in provider.lower():
                    tasks_type = "Google Tasks"
                elif 'asana' in provider.lower():
                    tasks_type = "Asana"
                elif 'linear' in provider.lower():
                    tasks_type = "Linear"
            
            # Add native tools
            connected.extend(["Weather", "Maps"])

            # Add Reminders if any core integration is active
            if any(p in active_providers for p in ["gmail", "google_calendar", "google_tasks"]):
                connected.append("Reminders")
        except Exception as e:
            logger.warning(f"Failed to fetch integrations for dynamic vars: {e}")
            connected = ["Weather", "Maps"]
        
        # Get user preferences from semantic memory (if available)
        user_preferences = ""
        try:
            context_data = await self.context_service.get_unified_context(
                user_id=user.id,
                query="",
                limit_history=0  # We just want preferences
            )
            user_preferences = context_data.get("semantic_context", "")
        except Exception as e:
            logger.debug(f"Could not fetch preferences for dynamic vars: {e}")
        
        # Build a capabilities summary for the agent
        capabilities = []
        if any('gmail' in c.lower() or 'email' in c.lower() or 'outlook' in c.lower() for c in connected):
            capabilities.append(f"read/send emails via {email_type}")
        if any('calendar' in c.lower() for c in connected):
            capabilities.append(f"check/create events in {calendar_type}")
        if any('task' in c.lower() for c in connected):
            capabilities.append("manage tasks")
        if any('drive' in c.lower() for c in connected):
            capabilities.append("access files in Google Drive")
        if any('notion' in c.lower() for c in connected):
            capabilities.append("access Notion pages")
        if "Weather" in connected:
            capabilities.append("get weather information")
        if "Maps" in connected:
            capabilities.append("get directions and locations")
        
        from src.core.calendar.utils import get_user_timezone
        import pytz
        tz_name = get_user_timezone(self.config)
        user_tz = pytz.timezone(tz_name)
        now_user = datetime.now(user_tz)
        
        # PROACTIVE FEATURE: Get top critical reminder for the opening greeting
        proactive_reminder = None
        try:
            from api.dependencies import AppState
            brief_svc = AppState.get_brief_service(user_id=user.id)
            proactive_reminder = await brief_svc.get_critical_reminder(user_id=user.id)
            if proactive_reminder:
                logger.info(f"[VoiceService] Found proactive reminder: {proactive_reminder}")
        except Exception as e:
            logger.debug(f"Could not fetch proactive reminder: {e}")
        
        return {
            "user_name": user_first_name,
            "user_full_name": user.name or user_first_name,
            "user_email": user.email or "",
            "connected_integrations": ", ".join(connected) if connected else "None",
            "calendar_type": calendar_type,
            "email_type": email_type,
            "notes_type": notes_type or "Not connected",
            "tasks_type": tasks_type or "Not connected",
            "capabilities": "; ".join(capabilities) if capabilities else "basic assistance",
            "user_preferences": user_preferences[:400] if user_preferences else "", # Further truncation
            "timezone": tz_name,
            "current_date": now_user.strftime("%B %d, %Y"),
            "current_time": now_user.strftime("%I:%M %p"),
            "proactive_reminder": proactive_reminder or ""
        }

    async def process_voice_stream(
        self, 
        user: User, 
        audio_generator: AsyncGenerator[bytes, None],
        websocket: Any,
        system_extras: Optional[str] = None
    ):
        """
        Handle the bidirectional audio stream between client and AI providers with fallback.
        Optimized for near-instant latency by parallelizing initialization.
        """
        from api.dependencies import AppState
        import time
        
        start_time = time.time()
        user_first_name = extract_first_name(user.name, user.email)
        
        # 1. Decide provider — Gemini Live is primary (cheaper, lower latency)
        #    ElevenLabs is fallback when configured
        providers_to_try = ["gemini"]
        if os.environ.get("ELEVENLABS_AGENT_ID"):
            providers_to_try.append("elevenlabs")
            
        session_id = f"voice_{user.id}_{uuid.uuid4().hex[:8]}"
        assistant_response_buffer = ""
        
        for provider_name in providers_to_try:
            logger.info(f"[VoiceService] Preparing session with {provider_name}...")
            
            # 2. Instantiate Client Early (empty tools)
            client = None
            if provider_name == "elevenlabs":
                client = ElevenLabsLiveClient(tools=[])
            else:
                client = GeminiLiveClient(tools=[])
            
            # 3. Parallel Initialization (Warmup, Tools, Context, Config)
            # This is the key optimization: Network calls and compute happen concurrently
            
            async def load_tools():
                t0 = time.time()
                # Run sync tool loading in a thread to avoid blocking the loop
                t = await asyncio.to_thread(
                    AppState.get_all_tools, 
                    user_id=user.id, 
                    user_first_name=user_first_name
                )
                logger.debug(f"[Latency] Tools loaded in {(time.time()-t0)*1000:.0f}ms")
                return t
                
            async def load_context():
                t0 = time.time()
                # Use passed system_extras if available, but usually we need full context
                # If system_extras was passed (e.g. from wake word), append it to the full fetch
                base_ctx = await self.get_voice_context(user)
                if system_extras:
                    base_ctx += f"\n\n[Wake Word Interaction]:\n{system_extras}"
                logger.debug(f"[Latency] Context loaded in {(time.time()-t0)*1000:.0f}ms")
                return base_ctx

            async def load_config():
                t0 = time.time()
                c = await self.get_voice_configuration(user)
                if provider_name == "elevenlabs" and c:
                    # Truncate for 11Labs constraints
                    for key, val in c.items():
                        if isinstance(val, str) and len(val) > 1000:
                            c[key] = val[:1000] + "..."
                logger.debug(f"[Latency] Config loaded in {(time.time()-t0)*1000:.0f}ms")
                return c
                
            async def run_warmup():
                t0 = time.time()
                await client.warmup()
                logger.debug(f"[Latency] Client warmup done in {(time.time()-t0)*1000:.0f}ms")
            
            # Execute all tasks concurrently
            tasks = [
                asyncio.create_task(load_tools()),
                asyncio.create_task(load_context()),
                asyncio.create_task(load_config()),
                asyncio.create_task(run_warmup())
            ]
            
            # Wait for all
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Unpack results (handling potential exceptions)
            tools_res, context_res, config_res, _ = results
            
            # Check for critical failures in tool/context loading
            if isinstance(tools_res, Exception):
                logger.error(f"[VoiceService] Failed to load tools: {tools_res}")
                tools_res = [] # Fallback to no tools
            if isinstance(context_res, Exception):
                logger.error(f"[VoiceService] Failed to load context: {context_res}")
                context_res = system_extras or ""
            if isinstance(config_res, Exception):
                logger.error(f"[VoiceService] Failed to load config: {config_res}")
                config_res = {}
            
            # 4. Inject initialized tools into client
            client.tools = tools_res
            client.tool_map = {t.name: t for t in client.tools}
            
            init_duration = (time.time() - start_time) * 1000
            logger.info(f"[VoiceService] Session ready in {init_duration:.0f}ms. Starting stream...")
            
            # 5. Start Streaming
            try:
                async for response in client.stream_audio(
                    audio_generator, 
                    system_instruction_extras=context_res,
                    dynamic_variables=config_res
                ):
                    # Check for quota errors that trigger fallback
                    if response.get("type") == "error" and response.get("error_code") == "quota_exceeded":
                        logger.warning(f"[VoiceService] Provider {provider_name} quota exceeded. Falling back if possible.")
                        if provider_name != providers_to_try[-1]:
                            await websocket.send_json({
                                "type": "text",
                                "chunk": " (Switching to alternate voice service...)",
                                "done": False
                            })
                            break # Try next provider
                        else:
                            await websocket.send_json({"type": "error", "message": "Voice service quota exceeded."})
                            return
                    
                    if response.get("type") == "audio":
                        audio_data = response["data"]
                        sample_rate = 16000 if provider_name == "elevenlabs" else 24000
                        await websocket.send_json({
                            "type": "audio",
                            "data": audio_data,
                            "mime_type": "audio/pcm",
                            "sample_rate": sample_rate,
                            "bit_depth": 16,
                            "channels": 1
                        })
                    elif response.get("type") == "text":
                        text_chunk = response["text"]
                        clean_chunk = re.sub(r'\*\*.*?\*\*', '', text_chunk)
                        clean_chunk = clean_chunk.replace('###', '').strip()
                        if clean_chunk:
                            assistant_response_buffer += clean_chunk
                            await websocket.send_json({
                                "type": "text",
                                "chunk": clean_chunk,
                                "done": False
                            })
                    elif response.get("type") == "user_transcript":
                        user_transcript = response.get("text")
                        if user_transcript:
                            await self._save_to_memory(user.id, session_id, user_transcript, role='user')
                            await websocket.send_json({"type": "user_transcript", "text": user_transcript})
                    elif response.get("type") == "turn_complete":
                        if assistant_response_buffer.strip():
                            await self._save_to_memory(user.id, session_id, assistant_response_buffer.strip(), role='assistant')
                            assistant_response_buffer = ""
                        await websocket.send_json({"type": "turn_complete"})
                    elif response.get("type") == "interrupted":
                        if assistant_response_buffer.strip():
                            # Save partial response before clearing
                            await self._save_to_memory(user.id, session_id, assistant_response_buffer.strip() + "... [interrupted]", role='assistant')
                            assistant_response_buffer = ""
                        await websocket.send_json({"type": "interrupted"})
                    elif response.get("type") == "error":
                        error_msg = response.get("message", "Unknown error")
                        logger.error(f"[VoiceService] Provider error ({provider_name}): {error_msg}")
                        if provider_name != providers_to_try[-1]:
                            break # Try next
                        await websocket.send_json({"type": "error", "message": error_msg})
                        return
                    elif response.get("type") == "session_expiring":
                         await websocket.send_json({
                            "type": "session_expiring",
                            "time_left": response.get("time_left_seconds", 0),
                            "reconnect": response.get("reconnect", True),
                            "reason": response.get("reason", "timeout"),
                            "action": "reconnect",
                            "message": f"Voice session ending ({response.get('reason')}). Reconnecting..."
                        })
                else:
                    # Generator finished normally
                    return
            except Exception as e:
                logger.error(f"[VoiceService] Unhandled error with {provider_name}: {e}")
                if provider_name == providers_to_try[-1]:
                    await websocket.send_json({"type": "error", "message": "Voice service encountered an error."})
                    return
                # Continue loop

    async def _save_to_memory(self, user_id: int, session_id: str, content: str, role: str = 'assistant'):
        """Save a message to conversation memory."""
        try:
            from src.database import get_async_db_context
            async with get_async_db_context() as fresh_db:
                memory = ConversationMemory(fresh_db)
                await memory.add_message(
                    user_id=user_id,
                    session_id=session_id,
                    role=role,
                    content=content,
                    intent='voice_interaction'
                )
            logger.info(f"Saved voice {role} message for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to save voice response to memory: {e}")
