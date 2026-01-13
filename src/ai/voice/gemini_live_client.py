"""
Gemini Live Client for bidirectional audio streaming.
"""
import os
import io
import asyncio
import json
import base64
import logging
from typing import Optional, List, Any, Dict, AsyncGenerator
from google import genai
from google.genai.types import (
    LiveConnectConfig,
    Content,
    Part,
    Blob,
    PrebuiltVoiceConfig,
    VoiceConfig,
    SpeechConfig,
    Tool,
    FunctionDeclaration,
    Schema,
    Type,
    FunctionResponse,
    ContextWindowCompressionConfig,
    SlidingWindow
)

from src.utils.logger import setup_logger
from src.utils.config import load_config
from src.ai.voice.base_client import BaseVoiceClient
from src.ai.prompts.voice_prompts import VOICE_SYSTEM_INSTRUCTION

logger = setup_logger(__name__)

class GeminiLiveClient(BaseVoiceClient):
    """
    Client for Gemini Live API (Multimodal Live).
    Handles bidirectional streaming of audio and tool calls.
    """
    def __init__(self, tools: Optional[List[Any]] = None):
        # Allow passing config or loading it
        config = load_config()
        self.api_key = config.ai.api_key
        
        if not self.api_key:
            # Fallback to env var
            self.api_key = os.environ.get("GOOGLE_API_KEY")
            
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set in config or env")
        
        # Initialize client with v1beta as Live API uses this version
        self.client = genai.Client(api_key=self.api_key, http_options={'api_version': 'v1beta'})
        self.tools = tools or []
        self.tool_map = {t.name: t for t in self.tools}
        # Use VOICE_AI_MODEL from env, fallback to the native audio preview model.
        # Handshake tests confirmed this model is required for current voice implementation.
        model_name = os.environ.get("VOICE_AI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
        
        # Ensure 'models/' prefix is present as some versions of the SDK/API require it
        if not model_name.startswith("models/"):
            self.model = f"models/{model_name}"
        else:
            self.model = model_name
        
        logger.info(f"[GEMINI_LIVE] Initialized with model: {self.model}")
        
    async def stream_audio(
        self, 
        audio_stream: AsyncGenerator[bytes, None],
        system_instruction_extras: Optional[str] = None,
        dynamic_variables: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Connect to Gemini Live and stream audio bidirectionally.
        
        Args:
            audio_stream: Generator yielding input audio bytes (PCM 16kHz or similar)
            system_instruction_extras: Optional text to append to system instruction (e.g. context)
            dynamic_variables: Optional dict to populate {{variable}} placeholders in system instruction
            
        Yields:
            Dicts with:
            - 'audio': base64 encoded audio chunk
            - 'text': text transcript/response
            - 'type': 'audio' or 'text' or 'tool_call'
        """
        gemini_tools = self._get_gemini_tools()
        
        # 1. Prepare Base Prompt
        raw_prompt = VOICE_SYSTEM_INSTRUCTION
        
        # 2. Inject Dynamic Variables (ElevenLabs style {{var}} -> Python style {var})
        if dynamic_variables:
            try:
                # Convert '{{var}}' to '{var}' for Python formatting
                # Note: We assume the prompt doesn't use single braces for other things (it shouldn't, as it's text)
                # If it does, we'd need a more robust regex replacer.
                # For now, simple replacement of double braces is safe for our specific prompt file.
                formatted_prompt = raw_prompt.replace("{{", "{").replace("}}", "}")
                
                # Check for missing keys to avoid KeyError
                # We fill missing keys with empty string or placeholders
                # But assume dynamic_variables has everything from voice_service
                full_system_instruction = formatted_prompt.format(**dynamic_variables)
                logger.debug("[GEMINI_LIVE] Successfully formatted prompt with dynamic variables")
            except Exception as e:
                logger.error(f"[GEMINI_LIVE] Failed to format prompt variables: {e}")
                full_system_instruction = raw_prompt # Fallback to raw (ElevenLabs style curlies will remain)
        else:
            full_system_instruction = raw_prompt

        # 3. Append Extras (Context, Integration Status, Memory)
        if system_instruction_extras:
            full_system_instruction += f"\n\nCONTEXT & MEMORY:\n{system_instruction_extras}"
        
        # REINFORCE CRITICAL RULES AT THE VERY END
        full_system_instruction += "\n\nREMINDER: DO NOT USE MARKDOWN headers or format suggestions. JUST SPEAK THE RESPONSE DIRECTLY."
        
        config = LiveConnectConfig(
            response_modalities=["AUDIO"],  # We want audio back
            system_instruction=Content(parts=[Part(text=full_system_instruction)]),
            # Enable context window compression for longer sessions
            context_window_compression=ContextWindowCompressionConfig(
                sliding_window=SlidingWindow()
            ),
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=PrebuiltVoiceConfig(
                        voice_name="Zephyr"
                    )
                )
            ),
            tools=gemini_tools
        )
        
        try:
            logger.info(f"[GEMINI_LIVE] Attempting to connect to multimodal live API with model: {self.model}")
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                logger.info(f"[GEMINI_LIVE] Successfully connected to {self.model}")
                
                # Create a task to send audio
                async def send_audio_loop():
                    try:
                        async for chunk in audio_stream:
                            if chunk:
                                # logger.info(f"[GEMINI_LIVE] Sending {len(chunk)} bytes")
                                await session.send_realtime_input(audio={"data": chunk, "mime_type": "audio/pcm"})
                    except Exception as e:
                        # Log sending errors but don't necessarily kill the whole session if it's transient
                        logger.error(f"[GEMINI_LIVE] Error sending audio: {e}")
                
                # Start sending task
                send_task = asyncio.create_task(send_audio_loop())
                
                # Receive loop
                # The session.receive() async generator yielded by the SDK exhausts after each turn (turn_complete).
                # To maintain a long-lived session, we wrap it in a while loop.
                try:
                    logger.info("[GEMINI_LIVE] Entering persistent receive loop...")
                    while True:
                        try:
                            async for response in session.receive():
                                # 1. Handle Server Content FIRST (Audio, Text, Interruption)
                                # This must come before go_away so audio in the same response is yielded
                                if response.server_content:
                                    # Check for interruption
                                    if response.server_content.interrupted:
                                        logger.info("[GEMINI_LIVE] Interruption detected")
                                        yield {"type": "interrupted"}
                                    
                                    # Process model turn (Text and Audio Parts)
                                    if response.server_content.model_turn:
                                        for part in response.server_content.model_turn.parts:
                                            if part.inline_data:
                                                # Audio chunk
                                                audio_data = part.inline_data.data
                                                logger.info(f"[GEMINI_LIVE] Received audio chunk: {len(audio_data)} bytes, mime: {getattr(part.inline_data, 'mime_type', 'unknown')}")
                                                yield {
                                                    "type": "audio",
                                                    "data": base64.b64encode(audio_data).decode('utf-8')
                                                }
                                            if part.text:
                                                # Text chunk (transcript/thought)
                                                yield {
                                                    "type": "text",
                                                    "text": part.text
                                                }
                                            if part.function_call:
                                                logger.info(f"[GEMINI_LIVE] Tool call (in turn): {part.function_call.name}")
                                                function_response = await self._handle_tool_call(part.function_call)
                                                await session.send_tool_response(function_responses=[function_response])

                                    # Handle turn completion
                                    if response.server_content.turn_complete:
                                        logger.info("[GEMINI_LIVE] Turn complete")
                                        yield {"type": "turn_complete"}

                                # 2. Handle Top-level Tool Call
                                if hasattr(response, 'tool_call') and response.tool_call:
                                    logger.info(f"[GEMINI_LIVE] Tool call (top-level)")
                                    function_responses = []
                                    for fc in response.tool_call.function_calls:
                                            logger.info(f"[GEMINI_LIVE] Tool call: {fc.name}")
                                            function_response = await self._handle_tool_call(fc)
                                            function_responses.append(function_response)
                                    
                                    await session.send_tool_response(function_responses=function_responses)
                                
                                # 3. Handle Session Resumption
                                if hasattr(response, 'session_resumption_update') and response.session_resumption_update:
                                    update = response.session_resumption_update
                                    if update.resumable and update.new_handle:
                                        logger.info(f"[GEMINI_LIVE] Session resumable. Handle: {update.new_handle}")
                                
                                # 4. Handle go_away LAST (after processing audio/text in this response)
                                # This ensures we don't lose audio data that comes with the go_away signal
                                if hasattr(response, 'go_away') and response.go_away:
                                    time_left_str = str(response.go_away.time_left)
                                    logger.warning(f"[GEMINI_LIVE] Received GOAWAY. Time left: {time_left_str}. Breaking after this response.")
                                    
                                    # Parse time_left string (e.g., '50s', '30s', '0s')
                                    try:
                                        if time_left_str.endswith('s'):
                                            time_left_seconds = int(time_left_str[:-1])
                                        else:
                                            time_left_seconds = int(time_left_str)
                                    except (ValueError, TypeError):
                                        time_left_seconds = 0
                                    
                                    # Signal that session is expiring and frontend should reconnect
                                    yield {"type": "session_expiring", "time_left_seconds": time_left_seconds, "reconnect": True}
                                    
                                    # Now break - we've processed all data in this response
                                    logger.warning("[GEMINI_LIVE] Breaking session due to GOAWAY - frontend should reconnect NOW")
                                    raise StopAsyncIteration("GOAWAY received")
                            
                            # If the session.receive() loop finishes normally, it means the turn stream ended.
                            # We logging this and continue the 'while True' loop to wait for the next turn.
                            # logger.debug("[GEMINI_LIVE] Turn stream finished, waiting for next client input...")
                        
                        except StopAsyncIteration:
                            # GOAWAY was received - break gracefully
                            logger.info("[GEMINI_LIVE] Exiting receive loop due to GOAWAY")
                            break
                            
                        except Exception as e:
                            error_str = str(e).lower()
                            
                            # Handle 1011 "service unavailable" gracefully - signal reconnection
                            if "1011" in str(e) or "unavailable" in error_str:
                                logger.warning(f"[GEMINI_LIVE] Service unavailable (1011) - signaling reconnect: {e}")
                                yield {"type": "session_expiring", "time_left_seconds": 0, "reconnect": True, "reason": "service_unavailable"}
                                break
                            
                            # If we get a specific error that implies the session is dead (e.g. ConnectionClosed)
                            # we should break the while loop.
                            if "closed" in error_str or "disconnected" in error_str or "handshake" in error_str:
                                logger.warning(f"[GEMINI_LIVE] Session connection likely closed: {e}")
                                yield {"type": "session_expiring", "time_left_seconds": 0, "reconnect": True, "reason": "connection_closed"}
                                break
                            
                            logger.error(f"[GEMINI_LIVE] Error in receive turn: {e}", exc_info=True)
                            yield {"type": "error", "message": f"Receive turn error: {str(e)}"}
                            # Depending on the error, we might want to break or continue.
                            # For now, let's break on any error to avoid tight loops.
                            break

                    logger.info("[GEMINI_LIVE] Persistent receive loop exited")

                except Exception as e:
                    logger.error(f"[GEMINI_LIVE] Critical receive error: {e}", exc_info=True)
                    yield {"type": "error", "message": f"Critical receive error: {str(e)}"}
                
                finally:
                    send_task.cancel()
                    logger.info("[GEMINI_LIVE] Session closed")
                
        except Exception as e:
            logger.error(f"[GEMINI_LIVE] Connection failed: {e}")
            yield {"type": "error", "message": str(e)}

    def _get_gemini_tools(self) -> Optional[List[Tool]]:
        """Convert LangChain tools to Gemini tools with robust schema generation"""
        if not self.tools:
            return None
            
        from src.ai.voice.tool_converter import convert_to_gemini_tools
        
        # Get raw JSON schemas from utility
        json_tools = convert_to_gemini_tools(self.tools)
        
        funcs = []
        for tool_def in json_tools:
            # Map JSON schema back to Gemini objects
            schema_dict = tool_def.get("parameters", {})
            properties = {}
            required_fields = schema_dict.get("required", [])

            # Iterate over properties in the JSON schema
            for prop_name, prop_def in schema_dict.get("properties", {}).items():
                # Map JSON types to Gemini Types
                t_map = {
                    "string": Type.STRING,
                    "integer": Type.INTEGER,
                    "number": Type.NUMBER,
                    "boolean": Type.BOOLEAN,
                    "array": Type.ARRAY,
                    "object": Type.OBJECT
                }
                
                # Create the Schema object for this property
                prop_schema = Schema(
                    type=t_map.get(prop_def.get("type"), Type.STRING),
                    description=prop_def.get("description", "")
                )
                
                # Handle array items if applicable
                if prop_def.get("type") == "array" and "items" in prop_def:
                    item_type = prop_def["items"].get("type", "string")
                    prop_schema.items = Schema(type=t_map.get(item_type, Type.STRING))

                properties[prop_name] = prop_schema
            
            # Create the final Schema for the tool
            parameters_schema = Schema(
                type=Type.OBJECT,
                properties=properties,
                required=required_fields if required_fields else None
            )
            
            funcs.append(FunctionDeclaration(
                name=tool_def["name"],
                description=tool_def["description"],
                parameters=parameters_schema
            ))
            
        return [Tool(function_declarations=funcs)]

    async def _handle_tool_call(self, function_call: Any) -> FunctionResponse:
        """Execute tool and return response content"""
        try:
            name = function_call.name
            args = function_call.args
            
            tool = self.tool_map.get(name)
            if not tool:
                response_args = {"result": f"Error: Tool '{name}' not found"}
                return FunctionResponse(
                    name=name,
                    id=getattr(function_call, 'id', None),
                    response=response_args
                )
            
            # Execute tool
            try:
                # Convert args to dict if it's not
                if hasattr(args, 'items'):
                    tool_input = dict(args.items())
                else:
                    tool_input = args
                
                logger.info(f"[GEMINI_LIVE] Executing {name} with input: {tool_input}")
                
                # Handle special parameter mapping
                if name == "summarize" and "content" in tool_input:
                    result = await tool.arun(tool_input["content"])
                else:
                    # Pass as a single argument (dict or string)
                    # If it's a simple string but the tool expects a dict (has args_schema),
                    # wrap it in a search action for better compatibility.
                    if isinstance(tool_input, str) and getattr(tool, 'args_schema', None):
                        logger.info(f"[GEMINI_LIVE] Wrapping string input into search action for {name}")
                        tool_input = {"action": "search", "query": tool_input}
                        
                    result = await tool.arun(tool_input)
                    
            except Exception as e:
                logger.error(f"Tool execution failed: {e}", exc_info=True)
                result = f"Error executing tool: {str(e)}"
            
            # Format response
            f_response = FunctionResponse(
                name=name,
                id=getattr(function_call, 'id', None),
                response={"result": str(result)}
            )
            # LOG THE RESPONSE PAYLOAD
            logger.info(f"[GEMINI_LIVE] Sending Tool Response: name={name}, id={f_response.id}, success={not str(result).startswith('Error')}")
            return f_response
                
        except Exception as e:
             logger.error(f"Tool handling error: {e}")
             # Fallback
             return FunctionResponse(
                name=function_call.name if hasattr(function_call, 'name') else "unknown",
                id=getattr(function_call, 'id', None),
                response={"result": f"Critical error: {str(e)}"}
             )
