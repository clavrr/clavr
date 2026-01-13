"""
Voice Module - AI Voice Clients

Exports the main clients for Voice-to-Voice interaction.
"""

from .base_client import BaseVoiceClient
from .elevenlabs_client import ElevenLabsLiveClient
from .gemini_live_client import GeminiLiveClient

__all__ = ["BaseVoiceClient", "ElevenLabsLiveClient", "GeminiLiveClient"]
