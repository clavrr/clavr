"""
Wake-Word Verifier

Server-side verification of wake-word audio snippets using Gemini's
audio understanding. Implements the second stage of the two-stage
wake-word detection pipeline:

  Stage 1 (Client): Fast keyword spotting via Web Speech API / local model
  Stage 2 (Server): Gemini-based audio classification for reliability

Success Metric: Reliable wake-word trigger with <1% false positive rate.
"""
import os
import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, List

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


# Constants

DEFAULT_WAKE_PHRASES = ["hey clavr", "hey clevr", "okay clavr", "hey clover", "clavr", "clevr"]
DEFAULT_CONFIDENCE_THRESHOLD = 0.85
MAX_AUDIO_SECONDS = 3
VERIFICATION_TIMEOUT = 2.0  # seconds
COOLDOWN_SECONDS = 2  # minimum gap between accepted triggers


# Data classes

@dataclass
class WakeWordResult:
    """Result of a wake-word verification attempt."""
    verified: bool
    confidence: float = 0.0
    detected_phrase: Optional[str] = None
    latency_ms: float = 0.0
    rejection_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "confidence": self.confidence,
            "detected_phrase": self.detected_phrase,
            "latency_ms": self.latency_ms,
            "rejection_reason": self.rejection_reason,
        }


# WakeWordVerifier

class WakeWordVerifier:
    """
    Verifies whether an audio snippet contains a valid wake-word phrase.

    Uses Gemini's audio understanding for classification rather than a
    dedicated keyword-spotting model, keeping the dependency footprint
    small while providing high reliability.
    """

    def __init__(
        self,
        wake_phrases: Optional[List[str]] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.wake_phrases = [p.lower() for p in (wake_phrases or DEFAULT_WAKE_PHRASES)]
        self.confidence_threshold = confidence_threshold
        self.cooldown_seconds = cooldown_seconds

        # Track last accepted trigger per user to enforce cooldown
        self._last_trigger: dict[int, float] = {}

        # Lazy-loaded Gemini client
        self._client = None


    # Public API

    async def verify_audio(
        self,
        audio_bytes: bytes,
        user_id: int,
        sample_rate: int = 16000,
    ) -> WakeWordResult:
        """
        Verify whether *audio_bytes* contains a valid wake-word.

        Args:
            audio_bytes: Raw PCM S16LE audio (mono).
            user_id:     Authenticated user ID (for cooldown tracking).
            sample_rate: Sample rate of the audio.

        Returns:
            WakeWordResult with verification outcome.
        """
        start = time.monotonic()

        # ---- Guard: cooldown ----
        now = time.monotonic()
        last = self._last_trigger.get(user_id, 0)
        if now - last < self.cooldown_seconds:
            return WakeWordResult(
                verified=False,
                latency_ms=_elapsed_ms(start),
                rejection_reason="cooldown_active",
            )

        # ---- Guard: audio length ----
        duration_s = _audio_duration(audio_bytes, sample_rate)
        if duration_s > MAX_AUDIO_SECONDS:
            return WakeWordResult(
                verified=False,
                latency_ms=_elapsed_ms(start),
                rejection_reason="audio_too_long",
            )

        if len(audio_bytes) < 640:  # < 20ms at 16kHz
            return WakeWordResult(
                verified=False,
                latency_ms=_elapsed_ms(start),
                rejection_reason="audio_too_short",
            )

        # ---- Verify with Gemini ----
        try:
            result = await asyncio.wait_for(
                self._classify_audio(audio_bytes, sample_rate),
                timeout=VERIFICATION_TIMEOUT,
            )
            result.latency_ms = _elapsed_ms(start)

            if result.verified:
                self._last_trigger[user_id] = time.monotonic()

            return result

        except asyncio.TimeoutError:
            logger.warning("[WakeWord] Verification timed out")
            return WakeWordResult(
                verified=False,
                latency_ms=_elapsed_ms(start),
                rejection_reason="verification_timeout",
            )
        except Exception as e:
            logger.error(f"[WakeWord] Verification error: {e}", exc_info=True)
            return WakeWordResult(
                verified=False,
                latency_ms=_elapsed_ms(start),
                rejection_reason=f"error: {str(e)}",
            )

    def clear_cooldown(self, user_id: int) -> None:
        """Clear cooldown for a specific user (useful in tests)."""
        self._last_trigger.pop(user_id, None)

    # Internal

    def _get_client(self):
        """Lazy-load the Gemini client and resolve the model name from config."""
        if self._client is None:
            from google import genai
            from src.utils.config import load_config

            config = load_config()
            api_key = config.ai.api_key or os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("GOOGLE_API_KEY not configured")
            self._client = genai.Client(api_key=api_key)
            # Resolve model from config (AI_MODEL env var → config.ai.model)
            self._model = config.ai.model
        return self._client

    async def _classify_audio(
        self,
        audio_bytes: bytes,
        sample_rate: int,
    ) -> WakeWordResult:
        """
        Ask Gemini to classify whether the audio contains a wake phrase.

        We send a short prompt + audio blob and expect a JSON-like response
        with ``phrase`` and ``confidence`` fields.
        """
        import base64
        import json

        client = self._get_client()

        phrases_str = ", ".join(f'"{p}"' for p in self.wake_phrases)

        prompt = (
            "Listen to this short audio clip. Determine if the speaker says "
            f"one of these wake phrases: {phrases_str}.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"phrase": "<detected phrase or null>", "confidence": <0.0 to 1.0>}\n\n'
            "If no wake phrase is detected, set phrase to null and confidence to 0.0. "
            "Be strict — only match if the phrase is clearly spoken."
        )

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        try:
            from google.genai.types import Content, Part, Blob

            response = await client.aio.models.generate_content(
                model=self._model,
                contents=Content(parts=[
                    Part(text=prompt),
                    Part(inline_data=Blob(
                        mime_type=f"audio/pcm;rate={sample_rate}",
                        data=audio_bytes,
                    )),
                ]),
            )

            return self._parse_response(response.text)

        except Exception as e:
            logger.error(f"[WakeWord] Gemini classify error: {e}")
            return WakeWordResult(verified=False, rejection_reason=f"classify_error: {e}")

    def _parse_response(self, raw_text: str) -> WakeWordResult:
        """Parse Gemini's JSON response into a WakeWordResult."""
        import json

        try:
            # Strip markdown code fences if present
            text = raw_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                text = text.rsplit("```", 1)[0].strip()

            data = json.loads(text)
            phrase = data.get("phrase")
            confidence = float(data.get("confidence", 0.0))

            # Normalize — coerce to string to handle non-string returns
            if phrase is not None:
                phrase = str(phrase).lower().strip()

            # Validate against known phrases
            is_valid = (
                phrase is not None
                and phrase in self.wake_phrases
                and confidence >= self.confidence_threshold
            )

            return WakeWordResult(
                verified=is_valid,
                confidence=confidence,
                detected_phrase=phrase if is_valid else None,
                rejection_reason=None if is_valid else "below_threshold",
            )

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"[WakeWord] Failed to parse response: {raw_text[:200]}")
            return WakeWordResult(
                verified=False,
                rejection_reason=f"parse_error: {e}",
            )


# Helpers

def _elapsed_ms(start: float) -> float:
    """Milliseconds elapsed since *start* (monotonic)."""
    return round((time.monotonic() - start) * 1000, 2)


def _audio_duration(audio_bytes: bytes, sample_rate: int, bytes_per_sample: int = 2) -> float:
    """Duration in seconds of raw PCM audio."""
    if sample_rate <= 0 or bytes_per_sample <= 0:
        return 0.0
    return len(audio_bytes) / (sample_rate * bytes_per_sample)
