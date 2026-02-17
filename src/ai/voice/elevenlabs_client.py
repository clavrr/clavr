"""
ElevenLabs Conversational AI Client
Uses raw websockets with signed URL for reliable streaming.
"""
import asyncio
import base64
import json
import os
import websockets
import httpx
from typing import AsyncGenerator, Optional, List, Any, Dict

from src.ai.voice.base_client import BaseVoiceClient
from src.ai.prompts.voice_prompts import VOICE_SYSTEM_INSTRUCTION
from src.utils.logger import setup_logger

from src.ai.voice.tool_converter import convert_to_elevenlabs_tools

logger = setup_logger(__name__)


class ElevenLabsLiveClient(BaseVoiceClient):
    """
    Client for ElevenLabs Conversational AI.
    Uses signed URL for authenticated WebSocket connections.
    """
    
    def __init__(self, tools: Optional[List[Any]] = None):
        self.api_key = os.environ.get("ELEVENLABS_API_KEY")
        self.agent_id = os.environ.get("ELEVENLABS_AGENT_ID")
        
        self.tools = tools or []
        self.tool_map = {t.name: t for t in self.tools}
        self._ws_lock = asyncio.Lock() # Lock for concurrent websocket writes
        self._signed_url_cache = None
             
        logger.info(f"[ELEVENLABS] Initialized for agent: {self.agent_id}")

    async def warmup(self) -> None:
        """Pre-fetch the signed URL to reduce latency when stream_audio starts."""
        try:
            if not self._signed_url_cache:
                self._signed_url_cache = await self._get_signed_url()
                if self._signed_url_cache:
                    logger.info("[ELEVENLABS] Warmup successful: Signed URL cached")
        except Exception as e:
            logger.warning(f"[ELEVENLABS] Warmup failed: {e}")


    async def _get_signed_url(self) -> Optional[str]:
        """Get a signed WebSocket URL from ElevenLabs API."""
        url = f"https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id={self.agent_id}"
        headers = {"xi-api-key": self.api_key}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("signed_url")
            else:
                logger.error(f"[ELEVENLABS] Failed to get signed URL: {response.status_code} - {response.text}")
                return None

    async def stream_audio(
        self, 
        audio_stream: AsyncGenerator[bytes, None],
        system_instruction_extras: Optional[str] = None,
        dynamic_variables: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Connect to ElevenLabs Conversational AI using signed URL.
        """
        if not self.agent_id:
            logger.error("[ELEVENLABS] Missing agent_id. Fallback required.")
            yield {"type": "error", "message": "Missing ElevenLabs Agent ID"}
            return

        # Get signed WebSocket URL (use cache if warmed up)
        ws_url = self._signed_url_cache
        if not ws_url:
            ws_url = await self._get_signed_url()
        
        # Clear cache after use as URLs are one-time or short-lived
        self._signed_url_cache = None
        
        if not ws_url:
            yield {"type": "error", "message": "Failed to get signed URL from ElevenLabs"}
            return
        
        logger.info("[ELEVENLABS] Got signed URL, connecting...")
        conversation_id = None
        
        # Build the full system prompt from unified source
        full_prompt = VOICE_SYSTEM_INSTRUCTION
        if system_instruction_extras:
            full_prompt += f"\n\nCONTEXT & MEMORY:\n{system_instruction_extras}"
        
        # Convert tools to ElevenLabs format
        client_tools = convert_to_elevenlabs_tools(self.tools)
        logger.info(f"[ELEVENLABS] Registering {len(client_tools)} client tools")
        
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info("[ELEVENLABS] Connected to WebSocket")
                
                # Perform manual interpolation of dynamic variables if they exist
                if dynamic_variables:
                    for key, value in dynamic_variables.items():
                        placeholder = "{{" + key + "}}"
                        if placeholder in full_prompt:
                            full_prompt = full_prompt.replace(placeholder, str(value))
                
                # 1. Send Handshake with prompt override and dynamic variables
                # NOTE: Requires "System prompt" override enabled in ElevenLabs Security settings
                init_data = {
                    "type": "conversation_initiation_client_data",
                    "custom_llm_extra_body": {},
                    "conversation_config_override": {
                        "agent": {
                            "prompt": {"prompt": full_prompt},
                            "use_filler_words": True,
                            "client_tools": client_tools  # <--- RE-ENABLED INJECTION
                        },
                        "tts": {
                            "latency_optimization": 3
                        }
                    },
                    "dynamic_variables": dynamic_variables or {},
                }
                await ws.send(json.dumps(init_data))
                logger.info(f"[ELEVENLABS] Handshake sent with prompt override, {len(client_tools)} tools, and {len(dynamic_variables or {})} dynamic variables")
                
                # 2. Wait for conversation_initiation_metadata
                try:
                    init_response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    init_message = json.loads(init_response)
                    
                    if init_message.get("type") == "conversation_initiation_metadata":
                        event = init_message.get("conversation_initiation_metadata_event", {})
                        conversation_id = event.get("conversation_id")
                        logger.info(f"[ELEVENLABS] Session initialized: {conversation_id}")
                    else:
                        logger.warning(f"[ELEVENLABS] Unexpected first message: {init_message.get('type')}")
                except asyncio.TimeoutError:
                    logger.error("[ELEVENLABS] Timeout waiting for handshake response")
                    yield {"type": "error", "message": "Timeout waiting for ElevenLabs handshake"}
                    return

                # 3. Start audio sending task
                chunk_count = 0
                bytes_sent = 0
                async def send_audio():
                    nonlocal chunk_count, bytes_sent
                    try:
                        async for chunk in audio_stream:
                            if chunk and len(chunk) >= 320:
                                chunk_count += 1
                                bytes_sent += len(chunk)
                                payload = {
                                    "user_audio_chunk": base64.b64encode(chunk).decode('utf-8')
                                }
                                async with self._ws_lock:
                                    await ws.send(json.dumps(payload))
                                if chunk_count <= 5 or chunk_count % 50 == 0:
                                    logger.info(f"[ELEVENLABS] Sent audio chunk #{chunk_count}: {len(chunk)} bytes (total: {bytes_sent} bytes)")
                    except websockets.exceptions.ConnectionClosed:
                        logger.debug(f"[ELEVENLABS] Connection closed after {chunk_count} audio chunks")
                    except Exception as e:
                        logger.error(f"[ELEVENLABS] Error sending audio: {e}")

                send_task = asyncio.create_task(send_audio())

                # 4. Receive and process messages
                last_interrupt_id = -1
                try:
                    async for message in ws:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        
                        # Log important messages
                        if msg_type not in ("audio", "vad_score", "internal_vad_score", "internal_tentative_agent_response"):
                            logger.info(f"[ELEVENLABS] Received: {msg_type}")

                        if msg_type == "audio":
                            event = data.get("audio_event", {})
                            event_id = int(event.get("event_id", 0))
                            
                            # Skip audio from before interruption
                            if event_id <= last_interrupt_id:
                                continue
                                
                            audio_b64 = event.get("audio_base_64")
                            if audio_b64:
                                logger.info(f"[ELEVENLABS] Received audio: {len(audio_b64)} chars, event_id={event_id}")
                                yield {
                                    "type": "audio",
                                    "data": audio_b64
                                }
                        
                        elif msg_type == "agent_response":
                            event = data.get("agent_response_event", {})
                            text = event.get("agent_response")
                            if text:
                                logger.info(f"[ELEVENLABS] Agent: {text}")
                                yield {
                                    "type": "text",
                                    "text": text
                                }

                        elif msg_type == "interruption":
                            event = data.get("interruption_event", {})
                            last_interrupt_id = int(event.get("event_id", 0))
                            logger.info(f"[ELEVENLABS] Interruption received (event_id={last_interrupt_id})")
                            yield {"type": "interrupted"}

                        elif msg_type == "client_tool_call":
                            call = data.get("client_tool_call", {})
                            tool_name = call.get("tool_name")
                            call_id = call.get("tool_call_id")
                            args = call.get("parameters", {})
                            
                            logger.info(f"[ELEVENLABS] Tool call received: {tool_name} with args: {args}")
                            # Process tool call in background to avoid blocking the message loop (pings)
                            asyncio.create_task(self._process_tool_call_async(ws, call_id, tool_name, args))

                        elif msg_type == "user_transcript":
                            event = data.get("user_transcription_event", {})
                            transcript = event.get("user_transcript", "")
                            if transcript:
                                logger.info(f"[ELEVENLABS] User: {transcript}")
                                yield {
                                    "type": "user_transcript",
                                    "text": transcript
                                }

                        elif msg_type == "ping":
                            ping_event = data.get("ping_event", {})
                            ping_id = ping_event.get("event_id")
                            pong_payload = {
                                "type": "pong",
                                "event_id": ping_id
                            }
                            async with self._ws_lock:
                                await ws.send(json.dumps(pong_payload))
                            logger.debug(f"[ELEVENLABS] Pong sent (id={ping_id})")

                        elif msg_type == "conversation_initiation_metadata":
                            # Already handled, but might come again
                            pass

                except (websockets.exceptions.ConnectionClosed, websockets.exceptions.InvalidHandshake) as e:
                    error_str = str(e).lower()
                    if "quota" in error_str or "1002" in error_str:
                        logger.error(f"[ELEVENLABS] Quota exceeded or protocol error: {e}")
                        yield {"type": "error", "error_code": "quota_exceeded", "message": "ElevenLabs quota limit reached."}
                    else:
                        logger.warning(f"[ELEVENLABS] Connection error: {e}")
                finally:
                    send_task.cancel()
                    try:
                        await send_task
                    except asyncio.CancelledError:
                        pass
                    
        except Exception as e:
            logger.error(f"[ELEVENLABS] Connection failed: {e}", exc_info=True)
            yield {"type": "error", "message": str(e)}

    async def _handle_tool_call(self, name: str, args: Dict[str, Any]) -> str:
        """Execute tool and return result string."""
        tool = self.tool_map.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"
        
        try:
            logger.info(f"[ELEVENLABS] Executing {name} with {args}")
            
            # Normalize and augment arguments for voice tools
            # Many voice agents omit the 'action' parameter which is mandatory for our tools
            tool_input = args
            if hasattr(tool, 'args_schema') and tool.args_schema:
                # If tool expects 'action' but didn't get one
                if "action" not in tool_input:
                    if name == "finance":
                        # If merchant provided, assume check last transaction
                        if "merchant" in tool_input:
                            tool_input["action"] = "get_last_transaction"
                        else:
                            tool_input["action"] = "aggregate_spending"
                    elif name in ["email", "tasks", "notes", "drive"]:
                        tool_input["action"] = "search"
                    elif name == "reminders":
                        tool_input["action"] = "briefing"
            
            # Add a safety timeout so slow tools don't hang the agent indefinitely
            result = await asyncio.wait_for(tool.arun(tool_input), timeout=10.0)
            return str(result)
        except Exception as e:
            logger.error(f"[ELEVENLABS] Tool {name} failed: {e}")
            return f"Error: {str(e)}"

    async def _process_tool_call_async(self, ws, call_id, tool_name, args):
        """Process tool call in background and send result through websocket."""
        try:
            logger.info(f"[ELEVENLABS] Starting execution of {tool_name} (call_id: {call_id})")
            result = await self._handle_tool_call(tool_name, args)
            
            # The official type for responding to client_tool_call is client_tool_result.
            # We strictly use 'result' to avoid ambiguity.
            response_payload = {
                "type": "client_tool_result",
                "tool_call_id": call_id,
                "result": str(result),
                "is_error": False
            }
            
            async with self._ws_lock:
                await ws.send(json.dumps(response_payload))
                
            logger.info(f"[ELEVENLABS] Tool result sent for {tool_name} (call_id: {call_id}). Payload: {response_payload}")
        except Exception as e:
            logger.error(f"[ELEVENLABS] Error in async tool processing: {e}")
            # Try to send error result so ElevenLabs doesn't wait indefinitely
            try:
                error_payload = {
                    "type": "client_tool_result",
                    "tool_call_id": call_id,
                    "result": f"Error: {str(e)}",
                    "is_error": True
                }
                async with self._ws_lock:
                    await ws.send(json.dumps(error_payload))
            except Exception as send_err:
                logger.debug(f"[ELEVENLABS] Failed to send error payload: {send_err}")
