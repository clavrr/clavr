# Voice Interface Implementation Example

This document provides code examples showing how the voice interface would be implemented, following the existing codebase patterns.

## Example 1: WebSocket Voice Endpoint

```python
# api/routers/voice.py
"""
Voice Interface Router
Handles WebSocket connections for voice interactions
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import json
import asyncio
import base64

from src.database import get_async_db
from src.utils.logger import setup_logger
from src.integrations.voice.stt_service import STTService
from src.integrations.voice.tts_service import TTSService
from src.agent import ClavrAgent
from src.ai.conversation_memory import ConversationMemory
from api.dependencies import AppState, get_config
from api.auth import get_current_user_required
from src.database.models import User

logger = setup_logger(__name__)
router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.websocket("/stream")
async def voice_stream(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_async_db)
):
    """
    WebSocket endpoint for bidirectional voice streaming
    
    Flow:
    1. Client connects and sends auth token
    2. Server validates and establishes session
    3. Client sends audio chunks
    4. Server processes and streams audio responses
    """
    await websocket.accept()
    
    # Initialize services
    config = get_config()
    stt_service = STTService(config)
    tts_service = TTSService(config)
    
    # Get user from session (set by middleware)
    user = None
    session_id = None
    
    try:
        # Receive authentication message
        auth_message = await websocket.receive_text()
        auth_data = json.loads(auth_message)
        
        if auth_data.get("type") != "auth":
            await websocket.send_json({
                "type": "error",
                "message": "Authentication required"
            })
            await websocket.close()
            return
        
        # Validate session token
        from api.middleware import get_session_from_token
        session = get_session_from_token(auth_data.get("token"))
        
        if not session:
            await websocket.send_json({
                "type": "error",
                "message": "Invalid session token"
            })
            await websocket.close()
            return
        
        user = session.user
        session_id = f"voice_{user.id}_{session.id}"
        
        # Initialize agent
        memory = ConversationMemory(db, rag_engine=AppState.get_rag_engine())
        tools = [
            AppState.get_task_tool(user_id=user.id, request=None),
            AppState.get_calendar_tool(user_id=user.id, request=None),
            AppState.get_email_tool(user_id=user.id, request=None),
        ]
        agent = ClavrAgent(tools=tools, config=config, memory=memory)
        
        # Send ready message
        await websocket.send_json({
            "type": "ready",
            "message": "Voice session established"
        })
        
        # Audio buffer for STT
        audio_buffer = []
        is_listening = False
        
        # Main loop: receive audio chunks and process
        while True:
            try:
                # Receive message (audio chunk or control)
                message = await websocket.receive()
                
                if "text" in message:
                    # Control message
                    data = json.loads(message["text"])
                    
                    if data.get("type") == "start_listening":
                        is_listening = True
                        audio_buffer = []
                        await websocket.send_json({
                            "type": "listening_started",
                            "message": "I'm listening..."
                        })
                    
                    elif data.get("type") == "stop_listening":
                        is_listening = False
                        # Process accumulated audio
                        if audio_buffer:
                            await process_voice_query(
                                websocket, agent, stt_service, tts_service,
                                audio_buffer, user.id, session_id
                            )
                            audio_buffer = []
                
                elif "bytes" in message:
                    # Audio chunk
                    if is_listening:
                        audio_buffer.append(message["bytes"])
                
            except WebSocketDisconnect:
                logger.info(f"Voice session disconnected: {session_id}")
                break
            except Exception as e:
                logger.error(f"Error in voice stream: {e}", exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
    
    except Exception as e:
        logger.error(f"Voice session error: {e}", exc_info=True)
        try:
            await websocket.close()
        except:
            pass


async def process_voice_query(
    websocket: WebSocket,
    agent: ClavrAgent,
    stt_service: STTService,
    tts_service: TTSService,
    audio_chunks: list,
    user_id: int,
    session_id: str
):
    """
    Process voice query: STT → Agent → TTS → Stream audio
    """
    try:
        # Send processing status
        await websocket.send_json({
            "type": "processing",
            "message": "Let me check that for you..."
        })
        
        # Convert audio to text (STT)
        transcript = await stt_service.transcribe(audio_chunks)
        
        if not transcript:
            await websocket.send_json({
                "type": "error",
                "message": "Could not understand audio"
            })
            return
        
        # Send transcript confirmation
        await websocket.send_json({
            "type": "transcript",
            "text": transcript
        })
        
        # Process query through agent
        response_text = await agent.execute(
            query=transcript,
            user_id=user_id,
            session_id=session_id
        )
        
        # Format response for voice
        from src.agent.formatting.voice_formatter import VoiceFormatter
        formatter = VoiceFormatter()
        voice_response = formatter.format(response_text)
        
        # Convert text to speech (TTS)
        audio_response = await tts_service.synthesize(voice_response)
        
        # Stream audio response
        chunk_size = 4096  # 4KB chunks
        for i in range(0, len(audio_response), chunk_size):
            chunk = audio_response[i:i + chunk_size]
            await websocket.send_bytes(chunk)
            await asyncio.sleep(0.01)  # Small delay for smooth streaming
        
        # Send completion
        await websocket.send_json({
            "type": "complete",
            "message": "Response complete"
        })
    
    except Exception as e:
        logger.error(f"Error processing voice query: {e}", exc_info=True)
        await websocket.send_json({
            "type": "error",
            "message": f"Error: {str(e)}"
        })
```

## Example 2: STT Service

```python
# src/integrations/voice/stt_service.py
"""
Speech-to-Text Service
Handles conversion of audio to text using various providers
"""
from typing import List, Optional
from google.cloud import speech_v1
from google.oauth2 import service_account
import os

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


class STTService:
    """Speech-to-Text service wrapper"""
    
    def __init__(self, config: Config):
        self.config = config
        self.provider = config.get("voice.stt.provider", "google")
        self.language = config.get("voice.stt.language", "en-US")
        self.sample_rate = config.get("voice.stt.sample_rate", 16000)
        
        if self.provider == "google":
            self._init_google_client()
    
    def _init_google_client(self):
        """Initialize Google Cloud Speech client"""
        try:
            credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if credentials_path:
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_path
                )
                self.client = speech_v1.SpeechClient(credentials=credentials)
            else:
                # Use default credentials
                self.client = speech_v1.SpeechClient()
            logger.info("[OK] Google Cloud Speech client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Google Speech client: {e}")
            raise
    
    async def transcribe(self, audio_chunks: List[bytes]) -> Optional[str]:
        """
        Transcribe audio chunks to text
        
        Args:
            audio_chunks: List of audio byte chunks
            
        Returns:
            Transcribed text or None if failed
        """
        if self.provider == "google":
            return await self._transcribe_google(audio_chunks)
        else:
            raise ValueError(f"Unsupported STT provider: {self.provider}")
    
    async def _transcribe_google(self, audio_chunks: List[bytes]) -> Optional[str]:
        """Transcribe using Google Cloud Speech-to-Text"""
        try:
            # Combine audio chunks
            audio_content = b"".join(audio_chunks)
            
            # Configure recognition
            config = speech_v1.RecognitionConfig(
                encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.language,
                enable_automatic_punctuation=True,
            )
            
            audio = speech_v1.RecognitionAudio(content=audio_content)
            
            # Perform recognition
            response = self.client.recognize(config=config, audio=audio)
            
            # Extract transcript
            if response.results:
                transcript = response.results[0].alternatives[0].transcript
                logger.info(f"[STT] Transcribed: {transcript[:50]}...")
                return transcript
            
            return None
        
        except Exception as e:
            logger.error(f"STT transcription error: {e}", exc_info=True)
            return None
```

## Example 3: TTS Service

```python
# src/integrations/voice/tts_service.py
"""
Text-to-Speech Service
Handles conversion of text to audio using various providers
"""
from typing import Optional
from google.cloud import texttospeech
from google.oauth2 import service_account
import os

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


class TTSService:
    """Text-to-Speech service wrapper"""
    
    def __init__(self, config: Config):
        self.config = config
        self.provider = config.get("voice.tts.provider", "google")
        self.voice = config.get("voice.tts.voice", "en-US-Neural2-D")
        self.language = config.get("voice.tts.language", "en-US")
        self.speaking_rate = config.get("voice.tts.speaking_rate", 1.0)
        
        if self.provider == "google":
            self._init_google_client()
    
    def _init_google_client(self):
        """Initialize Google Cloud Text-to-Speech client"""
        try:
            credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if credentials_path:
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_path
                )
                self.client = texttospeech.TextToSpeechClient(credentials=credentials)
            else:
                # Use default credentials
                self.client = texttospeech.TextToSpeechClient()
            logger.info("[OK] Google Cloud TTS client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Google TTS client: {e}")
            raise
    
    async def synthesize(self, text: str) -> Optional[bytes]:
        """
        Synthesize text to audio
        
        Args:
            text: Text to convert to speech
            
        Returns:
            Audio bytes (PCM format) or None if failed
        """
        if self.provider == "google":
            return await self._synthesize_google(text)
        else:
            raise ValueError(f"Unsupported TTS provider: {self.provider}")
    
    async def _synthesize_google(self, text: str) -> Optional[bytes]:
        """Synthesize using Google Cloud Text-to-Speech"""
        try:
            # Configure synthesis
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.language,
                name=self.voice,
            )
            
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                speaking_rate=self.speaking_rate,
            )
            
            # Perform synthesis
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            logger.info(f"[TTS] Synthesized {len(text)} characters to {len(response.audio_content)} bytes")
            return response.audio_content
        
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}", exc_info=True)
            return None
```

## Example 4: Voice Formatter

```python
# src/agent/formatting/voice_formatter.py
"""
Voice Response Formatter
Converts text responses to voice-optimized format
"""
import re
from typing import Optional

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class VoiceFormatter:
    """Formats responses for voice output"""
    
    def __init__(self, max_length: int = 500):
        self.max_length = max_length
    
    def format(self, text: str) -> str:
        """
        Format text response for voice output
        
        Transformations:
        - Remove markdown formatting
        - Convert lists to natural speech
        - Add conversational fillers
        - Shorten if too long
        """
        if not text:
            return text
        
        # Remove markdown
        text = self._remove_markdown(text)
        
        # Convert lists to natural speech
        text = self._convert_lists(text)
        
        # Add conversational elements
        text = self._add_conversational_elements(text)
        
        # Truncate if too long
        if len(text) > self.max_length:
            text = self._truncate_intelligently(text)
        
        return text
    
    def _remove_markdown(self, text: str) -> str:
        """Remove markdown formatting"""
        # Remove bold/italic
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        
        # Remove code blocks
        text = re.sub(r'`([^`]+)`', r'\1', text)
        
        # Remove headers
        text = re.sub(r'#+\s*', '', text)
        
        # Remove links
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        
        return text
    
    def _convert_lists(self, text: str) -> str:
        """Convert bullet points and numbered lists to natural speech"""
        lines = text.split('\n')
        result = []
        in_list = False
        
        for line in lines:
            # Detect list items
            if re.match(r'^[\s]*[•\-\*]\s+', line) or re.match(r'^\d+\.\s+', line):
                if not in_list:
                    result.append("Here's what I found:")
                    in_list = True
                
                # Remove bullet/number
                item = re.sub(r'^[\s]*[•\-\*]\s+', '', line)
                item = re.sub(r'^\d+\.\s+', '', item)
                
                # Add natural connector
                if result and result[-1].endswith(':'):
                    result.append(f"First, {item}")
                elif any(result[-1].startswith(conn) for conn in ["First", "Second", "Third"]):
                    # Determine next connector
                    if "First" in result[-1]:
                        result.append(f"Second, {item}")
                    elif "Second" in result[-1]:
                        result.append(f"Third, {item}")
                    else:
                        result.append(f"And {item}")
                else:
                    result.append(f"And {item}")
            else:
                if in_list:
                    in_list = False
                result.append(line)
        
        return '\n'.join(result)
    
    def _add_conversational_elements(self, text: str) -> str:
        """Add conversational fillers and confirmations"""
        # Add confirmation for actions
        if any(keyword in text.lower() for keyword in ["created", "scheduled", "sent", "added"]):
            if not text.startswith(("I've", "I have", "Got it")):
                text = f"I've {text.lower()}"
        
        # Add friendly opening
        if text.startswith(("You have", "You've got")):
            text = text.replace("You have", "You've got")
        
        return text
    
    def _truncate_intelligently(self, text: str) -> str:
        """Truncate text at sentence boundary"""
        if len(text) <= self.max_length:
            return text
        
        # Find last sentence boundary before max_length
        truncated = text[:self.max_length]
        last_period = truncated.rfind('.')
        last_exclamation = truncated.rfind('!')
        last_question = truncated.rfind('?')
        
        cutoff = max(last_period, last_exclamation, last_question)
        
        if cutoff > self.max_length * 0.7:  # Only if we keep at least 70%
            return truncated[:cutoff + 1] + " That's the main information."
        else:
            return truncated + "..."
```

## Example 5: Voice Parser (Quick Capture Mode)

```python
# src/agent/parsers/voice/quick_capture.py
"""
Quick Task Capture Parser
Handles "Quick task:" prefix for fast task creation
"""
from typing import Dict, Any, Optional
import re

from src.agent.parsers.base_parser import BaseParser
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class QuickCaptureParser(BaseParser):
    """Parser for quick task capture mode"""
    
    QUICK_TASK_PREFIXES = [
        r"quick\s+task:?\s*",
        r"quick\s+task\s+",
        r"task:?\s*",
    ]
    
    def parse(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parse quick task capture query
        
        Example: "Quick task: Call the professor about the syllabus changes by Friday"
        """
        query_lower = query.lower().strip()
        
        # Check if it's a quick task
        is_quick_task = any(
            re.match(prefix, query_lower, re.IGNORECASE)
            for prefix in self.QUICK_TASK_PREFIXES
        )
        
        if not is_quick_task:
            return {
                "intent": None,
                "confidence": 0.0
            }
        
        # Extract task description
        task_text = query_lower
        for prefix in self.QUICK_TASK_PREFIXES:
            task_text = re.sub(prefix, "", task_text, flags=re.IGNORECASE).strip()
        
        # Extract due date
        due_date = self._extract_due_date(task_text)
        if due_date:
            # Remove due date from task text
            task_text = re.sub(
                r'\s+by\s+' + re.escape(due_date),
                '',
                task_text,
                flags=re.IGNORECASE
            ).strip()
        
        return {
            "intent": "create_task",
            "confidence": 0.95,  # High confidence for quick capture
            "action": "create",
            "domain": "task",
            "entities": {
                "task_title": task_text,
                "due_date": due_date,
            },
            "mode": "quick_capture",  # Signal to bypass full orchestration
        }
    
    def _extract_due_date(self, text: str) -> Optional[str]:
        """Extract due date from text"""
        # Simple pattern matching (can be enhanced with date parser)
        patterns = [
            r"by\s+(friday|monday|tuesday|wednesday|thursday|saturday|sunday)",
            r"by\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"by\s+(today|tomorrow|next\s+week)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
```

## Example 6: Integration with Existing Agent

```python
# Example: How voice queries integrate with ClavrAgent
# (No changes needed to ClavrAgent itself)

# In voice router:
agent = ClavrAgent(
    tools=tools,
    config=config,
    memory=memory,
    user_first_name=user_first_name
)

# Voice query goes through same execute() method
response = await agent.execute(
    query=transcript,  # Text from STT
    user_id=user_id,
    session_id=session_id
)

# Response is then formatted for voice
formatter = VoiceFormatter()
voice_response = formatter.format(response)

# Convert to audio and stream
audio = await tts_service.synthesize(voice_response)
```

## Key Points

1. **Minimal Changes**: ClavrAgent and orchestrator work unchanged
2. **Reuse Infrastructure**: Auth, memory, tools all reused
3. **Voice-Specific**: Parser and formatter handle voice optimizations
4. **Streaming**: WebSocket enables real-time bidirectional communication
5. **Modular**: Each component (STT, TTS, parser, formatter) is independent

This approach provides a clean separation of concerns while maximizing code reuse.





