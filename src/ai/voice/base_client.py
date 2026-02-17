"""
Base Voice Client Interface
Defines the standard interface for all voice providers (Gemini, ElevenLabs, etc.)
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, List, Any, Dict

class BaseVoiceClient(ABC):
    """
    Abstract base class for voice interaction clients.
    """
    
    @abstractmethod
    async def stream_audio(
        self, 
        audio_stream: AsyncGenerator[bytes, None],
        system_instruction_extras: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream audio to the provider and receive responses.
        
        Args:
            audio_stream: Async generator yielding raw PCM bytes.
            system_instruction_extras: Additional context for the assistant.
            
        Yields:
            Dictionary containing response parts (audio, text, tool_call, etc.)
        """
    async def warmup(self) -> None:
        """
        Optional warmup method to prepare the client (e.g. pre-fetch auth tokens).
        This can be called in parallel with other initialization tasks.
        """
        pass

