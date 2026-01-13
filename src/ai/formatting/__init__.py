"""
Agent Formatting Modules

Provides formatters for different output modes:
- ResponseFormatter: Entity-aware response formatting (system-level)
- VoiceFormatter: TTS-optimized text formatting
- VoiceConfig: Configuration for voice formatting

For user-preference-based formatting (personalization), see:
    src/ai/capabilities/response_personalizer.py
"""

from .voice_formatter import VoiceFormatter
from .voice_config import VoiceConfig
from .response_formatter import ResponseFormatter

__all__ = [
    'VoiceFormatter',
    'VoiceConfig', 
    'ResponseFormatter',
]
