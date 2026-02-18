"""
Voice Proactivity Layer Tests

Comprehensive test suite covering:
  - Wake-word reliability: correct detection, rejection, thresholds, cooldown
  - Server verification: latency, timeout, confidence scoring
  - Proactive nudges: trigger timing, preferences, cooldown, dedup
  - Integration: wake-word → voice session handoff, nudge delivery
"""
import asyncio
import json
import time
import struct
import math
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import dataclass

import pytest


# ============================================================
# WAKE-WORD VERIFIER TESTS
# ============================================================

class TestWakeWordVerifier:
    """Tests for WakeWordVerifier reliability."""

    def _make_audio(self, duration_s=1.0, sample_rate=16000, frequency=440):
        """Generate synthetic PCM S16LE audio."""
        num_samples = int(sample_rate * duration_s)
        samples = []
        for i in range(num_samples):
            value = int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
            samples.append(value)
        return struct.pack(f"<{len(samples)}h", *samples)

    def _make_silence(self, duration_s=1.0, sample_rate=16000):
        """Generate silent PCM audio."""
        num_samples = int(sample_rate * duration_s)
        return b'\x00' * (num_samples * 2)

    @pytest.mark.asyncio
    async def test_rejects_too_short_audio(self):
        """Audio snippets shorter than 20ms should be rejected."""
        from src.ai.voice.wake_word import WakeWordVerifier
        
        verifier = WakeWordVerifier()
        result = await verifier.verify_audio(
            audio_bytes=b'\x00' * 100,  # ~3ms at 16kHz
            user_id=1,
        )
        assert not result.verified
        assert result.rejection_reason == "audio_too_short"

    @pytest.mark.asyncio
    async def test_rejects_too_long_audio(self):
        """Audio snippets longer than MAX_AUDIO_SECONDS should be rejected."""
        from src.ai.voice.wake_word import WakeWordVerifier, MAX_AUDIO_SECONDS
        
        verifier = WakeWordVerifier()
        # 5 seconds at 16kHz
        long_audio = self._make_audio(duration_s=MAX_AUDIO_SECONDS + 2)
        result = await verifier.verify_audio(
            audio_bytes=long_audio,
            user_id=1,
        )
        assert not result.verified
        assert result.rejection_reason == "audio_too_long"

    @pytest.mark.asyncio
    async def test_cooldown_enforcement(self):
        """Rapid re-triggers within cooldown should be rejected."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier(cooldown_seconds=5)
        audio = self._make_audio(duration_s=1.0)

        # Simulate a successful trigger
        verifier._last_trigger[1] = time.monotonic()

        result = await verifier.verify_audio(audio_bytes=audio, user_id=1)
        assert not result.verified
        assert result.rejection_reason == "cooldown_active"

    @pytest.mark.asyncio
    async def test_cooldown_clears(self):
        """After cooldown period, triggers should be accepted again."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier(cooldown_seconds=0.1)
        verifier._last_trigger[1] = time.monotonic() - 1  # 1 second ago

        audio = self._make_audio(duration_s=1.0)
        
        # Mock the classifier to return a positive result
        async def mock_classify(audio_bytes, sample_rate):
            from src.ai.voice.wake_word import WakeWordResult
            return WakeWordResult(verified=True, confidence=0.95, detected_phrase="hey clavr")

        verifier._classify_audio = mock_classify
        result = await verifier.verify_audio(audio_bytes=audio, user_id=1)
        assert result.verified

    @pytest.mark.asyncio
    async def test_clear_cooldown(self):
        """Manual cooldown clearing should work."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier()
        verifier._last_trigger[1] = time.monotonic()
        assert 1 in verifier._last_trigger

        verifier.clear_cooldown(1)
        assert 1 not in verifier._last_trigger

    @pytest.mark.asyncio
    async def test_verification_timeout(self):
        """Classification taking too long should result in timeout rejection."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier()
        audio = self._make_audio(duration_s=1.0)

        async def slow_classify(audio_bytes, sample_rate):
            await asyncio.sleep(10)  # Way longer than timeout

        verifier._classify_audio = slow_classify
        result = await verifier.verify_audio(audio_bytes=audio, user_id=1)
        assert not result.verified
        assert result.rejection_reason == "verification_timeout"

    def test_parse_response_valid_wake_phrase(self):
        """Valid JSON with a matching phrase should verify."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier(confidence_threshold=0.85)
        result = verifier._parse_response('{"phrase": "hey clavr", "confidence": 0.95}')
        assert result.verified
        assert result.confidence == 0.95
        assert result.detected_phrase == "hey clavr"

    def test_parse_response_below_threshold(self):
        """Confidence below threshold should not verify."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier(confidence_threshold=0.85)
        result = verifier._parse_response('{"phrase": "hey clavr", "confidence": 0.5}')
        assert not result.verified
        assert result.confidence == 0.5

    def test_parse_response_unknown_phrase(self):
        """A phrase not in the wake phrases list should not verify."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier()
        result = verifier._parse_response('{"phrase": "hello world", "confidence": 0.99}')
        assert not result.verified

    def test_parse_response_no_phrase_detected(self):
        """Null phrase should not verify."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier()
        result = verifier._parse_response('{"phrase": null, "confidence": 0.0}')
        assert not result.verified

    def test_parse_response_markdown_fences(self):
        """JSON wrapped in markdown code fences should still parse."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier()
        raw = '```json\n{"phrase": "hey clavr", "confidence": 0.92}\n```'
        result = verifier._parse_response(raw)
        assert result.verified
        assert result.confidence == 0.92

    def test_parse_response_invalid_json(self):
        """Garbled text should not crash, just fail gracefully."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier()
        result = verifier._parse_response("This is not JSON at all")
        assert not result.verified
        assert "parse_error" in result.rejection_reason

    def test_wake_word_result_to_dict(self):
        """WakeWordResult should serialize cleanly."""
        from src.ai.voice.wake_word import WakeWordResult

        result = WakeWordResult(
            verified=True,
            confidence=0.95,
            detected_phrase="hey clavr",
            latency_ms=42.5,
        )
        d = result.to_dict()
        assert d["verified"] is True
        assert d["confidence"] == 0.95
        assert d["detected_phrase"] == "hey clavr"
        assert d["latency_ms"] == 42.5

    def test_multiple_wake_phrase_variants(self):
        """All supported wake phrase variants should be accepted."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier()

        for phrase in ["hey clavr", "hey clevr", "okay clavr", "hey clover", "clavr", "clevr"]:
            result = verifier._parse_response(
                json.dumps({"phrase": phrase, "confidence": 0.95})
            )
            assert result.verified, f"Failed for phrase: {phrase}"

    def test_case_insensitivity(self):
        """Wake phrase matching should be case-insensitive."""
        from src.ai.voice.wake_word import WakeWordVerifier

        verifier = WakeWordVerifier()
        result = verifier._parse_response('{"phrase": "Hey Clavr", "confidence": 0.95}')
        assert result.verified

    @pytest.mark.asyncio
    async def test_latency_tracking(self):
        """Result should include latency measurement."""
        from src.ai.voice.wake_word import WakeWordVerifier, WakeWordResult

        verifier = WakeWordVerifier()
        audio = self._make_audio(duration_s=1.0)

        async def fast_classify(audio_bytes, sample_rate):
            return WakeWordResult(verified=False, confidence=0.0)

        verifier._classify_audio = fast_classify
        result = await verifier.verify_audio(audio_bytes=audio, user_id=1)
        assert result.latency_ms > 0


# ============================================================
# VOICE PROACTIVITY SERVICE TESTS
# ============================================================

class TestVoiceProactivityService:
    """Tests for VoiceProactivityService."""

    def test_default_preferences(self):
        """Default preferences should have all nudge types enabled."""
        from src.services.voice_proactivity import VoiceProactivityService

        svc = VoiceProactivityService()
        prefs = svc.get_preferences(user_id=1)
        assert prefs.enabled is True
        assert prefs.meeting_nudges is True
        assert prefs.email_nudges is True
        assert prefs.ghost_nudges is True
        assert prefs.deadline_nudges is True

    def test_update_preferences(self):
        """User preferences should persist after update."""
        from src.services.voice_proactivity import VoiceProactivityService, NudgePreferences

        svc = VoiceProactivityService()
        new_prefs = NudgePreferences(
            enabled=True,
            meeting_nudges=False,
            email_nudges=True,
            ghost_nudges=False,
            deadline_nudges=True,
            cooldown_minutes=30,
        )
        svc.update_preferences(1, new_prefs)
        
        stored = svc.get_preferences(1)
        assert stored.meeting_nudges is False
        assert stored.ghost_nudges is False
        assert stored.cooldown_minutes == 30

    def test_preferences_from_dict(self):
        """NudgePreferences should deserialize from dict correctly."""
        from src.services.voice_proactivity import NudgePreferences

        data = {
            "enabled": True,
            "meeting_nudges": False,
            "email_nudges": True,
            "ghost_nudges": False,
            "deadline_nudges": True,
            "quiet_hours_start": 23,
            "quiet_hours_end": 8,
            "cooldown_minutes": 20,
            "extra_field": "ignored",
        }
        prefs = NudgePreferences.from_dict(data)
        assert prefs.meeting_nudges is False
        assert prefs.quiet_hours_start == 23
        assert prefs.cooldown_minutes == 20

    def test_preferences_to_dict(self):
        """NudgePreferences should serialize to dict."""
        from src.services.voice_proactivity import NudgePreferences

        prefs = NudgePreferences(enabled=True, cooldown_minutes=10)
        d = prefs.to_dict()
        assert d["enabled"] is True
        assert d["cooldown_minutes"] == 10
        assert "meeting_nudges" in d

    @pytest.mark.asyncio
    async def test_disabled_nudges_returns_empty(self):
        """If nudges are disabled, no triggers should fire."""
        from src.services.voice_proactivity import VoiceProactivityService, NudgePreferences

        svc = VoiceProactivityService()
        svc.update_preferences(1, NudgePreferences(enabled=False))
        
        nudges = await svc.check_proactive_triggers(1)
        assert nudges == []

    @pytest.mark.asyncio
    async def test_cooldown_blocks_nudges(self):
        """Nudges should not fire during cooldown period."""
        from src.services.voice_proactivity import VoiceProactivityService

        svc = VoiceProactivityService()
        svc.record_nudge_delivered(1)

        nudges = await svc.check_proactive_triggers(1)
        assert nudges == []

    @pytest.mark.asyncio
    async def test_deduplication(self):
        """Same nudge should not be delivered twice."""
        from src.services.voice_proactivity import (
            VoiceProactivityService,
            VoiceNudge,
            NudgeTriggerType,
        )

        svc = VoiceProactivityService()
        
        nudge = VoiceNudge(
            trigger_type=NudgeTriggerType.MEETING_IMMINENT,
            title="Meeting: Standup",
            spoken_text="Standup in 5 minutes",
        )

        # First call should include the nudge
        deduped = svc._deduplicate(1, [nudge])
        assert len(deduped) == 1

        # Second call should filter it out
        deduped = svc._deduplicate(1, [nudge])
        assert len(deduped) == 0

    def test_clear_delivered(self):
        """Clearing delivered set should allow re-delivery."""
        from src.services.voice_proactivity import (
            VoiceProactivityService,
            VoiceNudge,
            NudgeTriggerType,
        )

        svc = VoiceProactivityService()
        nudge = VoiceNudge(
            trigger_type=NudgeTriggerType.MEETING_IMMINENT,
            title="Meeting: Standup",
            spoken_text="Test",
        )

        svc._deduplicate(1, [nudge])
        svc.clear_delivered(1)
        deduped = svc._deduplicate(1, [nudge])
        assert len(deduped) == 1

    def test_voice_nudge_to_dict(self):
        """VoiceNudge should serialize with type field."""
        from src.services.voice_proactivity import VoiceNudge, NudgeTriggerType

        nudge = VoiceNudge(
            trigger_type=NudgeTriggerType.URGENT_EMAIL,
            title="Urgent: Project Update",
            spoken_text="You got an urgent email",
            priority=2,
        )
        d = nudge.to_dict()
        assert d["type"] == "voice_nudge"
        assert d["trigger_type"] == "urgent_email"
        assert d["priority"] == 2

    @pytest.mark.asyncio
    async def test_greeting_generic(self):
        """Generic greeting (no trigger) should return empty string."""
        from src.services.voice_proactivity import VoiceProactivityService

        svc = VoiceProactivityService()
        greeting = await svc.get_proactive_greeting(1, trigger_type=None)
        assert greeting == ""

    @pytest.mark.asyncio
    async def test_greeting_ghost_draft(self):
        """Ghost draft greeting should mention the draft."""
        from src.services.voice_proactivity import (
            VoiceProactivityService,
            NudgeTriggerType,
        )

        svc = VoiceProactivityService()
        greeting = await svc.get_proactive_greeting(1, NudgeTriggerType.GHOST_DRAFT_READY)
        assert "draft" in greeting.lower()


# ============================================================
# NUDGE TRIGGER TYPE TESTS
# ============================================================

class TestNudgeTriggerType:
    """Tests for NudgeTriggerType enum."""

    def test_enum_values(self):
        from src.services.voice_proactivity import NudgeTriggerType

        assert NudgeTriggerType.MEETING_IMMINENT.value == "meeting_imminent"
        assert NudgeTriggerType.URGENT_EMAIL.value == "urgent_email"
        assert NudgeTriggerType.GHOST_DRAFT_READY.value == "ghost_draft_ready"
        assert NudgeTriggerType.DEADLINE_APPROACHING.value == "deadline_approaching"

    def test_string_comparison(self):
        from src.services.voice_proactivity import NudgeTriggerType

        assert NudgeTriggerType("meeting_imminent") == NudgeTriggerType.MEETING_IMMINENT


# ============================================================
# SERVICE CONSTANTS TESTS
# ============================================================

class TestVoiceProactivityConstants:
    """Tests for voice proactivity constants in ServiceConstants."""

    def test_wake_word_constants_exist(self):
        """All wake-word constants should be defined."""
        from src.services.service_constants import ServiceConstants

        assert hasattr(ServiceConstants, 'WAKE_WORD_CONFIDENCE_THRESHOLD')
        assert hasattr(ServiceConstants, 'WAKE_WORD_MAX_AUDIO_SECONDS')
        assert hasattr(ServiceConstants, 'WAKE_WORD_VERIFICATION_TIMEOUT')
        assert hasattr(ServiceConstants, 'WAKE_WORD_COOLDOWN_SECONDS')
        assert hasattr(ServiceConstants, 'WAKE_WORD_PHRASES')

    def test_nudge_constants_exist(self):
        """All nudge constants should be defined."""
        from src.services.service_constants import ServiceConstants

        assert hasattr(ServiceConstants, 'NUDGE_MEETING_MINUTES_BEFORE')
        assert hasattr(ServiceConstants, 'NUDGE_DEADLINE_MINUTES_BEFORE')
        assert hasattr(ServiceConstants, 'NUDGE_COOLDOWN_MINUTES')
        assert hasattr(ServiceConstants, 'NUDGE_CHECK_INTERVAL_SECONDS')

    def test_confidence_threshold_reasonable(self):
        """Confidence threshold should be high enough to avoid false positives."""
        from src.services.service_constants import ServiceConstants

        assert 0.5 <= ServiceConstants.WAKE_WORD_CONFIDENCE_THRESHOLD <= 1.0

    def test_wake_phrases_non_empty(self):
        """Wake phrases list should contain at least one phrase."""
        from src.services.service_constants import ServiceConstants

        assert len(ServiceConstants.WAKE_WORD_PHRASES) > 0
        assert "hey clavr" in ServiceConstants.WAKE_WORD_PHRASES


# ============================================================
# VOICE PROMPTS TESTS
# ============================================================

class TestVoicePrompts:
    """Tests for wake-word and nudge greeting prompt templates."""

    def test_wake_word_greeting_template_exists(self):
        from src.ai.prompts.voice_prompts import WAKE_WORD_GREETING_TEMPLATE
        assert "{proactive_context}" in WAKE_WORD_GREETING_TEMPLATE

    def test_nudge_greeting_template_exists(self):
        from src.ai.prompts.voice_prompts import NUDGE_GREETING_TEMPLATE
        assert "{nudge_text}" in NUDGE_GREETING_TEMPLATE

    def test_wake_word_template_formatting(self):
        from src.ai.prompts.voice_prompts import WAKE_WORD_GREETING_TEMPLATE
        
        result = WAKE_WORD_GREETING_TEMPLATE.format(
            proactive_context="Meeting with John in 5 minutes"
        )
        assert "Meeting with John" in result
        assert "wake word" in result.lower()

    def test_nudge_template_formatting(self):
        from src.ai.prompts.voice_prompts import NUDGE_GREETING_TEMPLATE

        result = NUDGE_GREETING_TEMPLATE.format(
            nudge_text="Your standup starts in 3 minutes"
        )
        assert "standup" in result


# ============================================================
# VOICE MODULE EXPORTS TESTS
# ============================================================

class TestVoiceModuleExports:
    """Tests for voice module __init__.py exports."""

    def test_wake_word_verifier_exported(self):
        from src.ai.voice import WakeWordVerifier
        assert WakeWordVerifier is not None

    def test_wake_word_result_exported(self):
        from src.ai.voice import WakeWordResult
        assert WakeWordResult is not None

    def test_base_client_still_exported(self):
        from src.ai.voice import BaseVoiceClient
        assert BaseVoiceClient is not None


# ============================================================
# HELPER FUNCTION TESTS
# ============================================================

class TestHelpers:
    """Tests for helper functions in wake_word module."""

    def test_audio_duration_calculation(self):
        """Audio duration should be correctly calculated."""
        from src.ai.voice.wake_word import _audio_duration

        # 2 seconds of 16kHz mono S16LE = 64000 bytes
        audio = b'\x00' * 64000
        duration = _audio_duration(audio, sample_rate=16000)
        assert abs(duration - 2.0) < 0.01

    def test_audio_duration_zero_rate(self):
        """Zero sample rate should return 0 duration."""
        from src.ai.voice.wake_word import _audio_duration

        assert _audio_duration(b'\x00' * 100, sample_rate=0) == 0.0

    def test_elapsed_ms(self):
        """Elapsed time should be positive."""
        from src.ai.voice.wake_word import _elapsed_ms

        start = time.monotonic()
        time.sleep(0.01)
        ms = _elapsed_ms(start)
        assert ms > 0


# ============================================================
# QUIET HOURS TESTS
# ============================================================

class TestQuietHours:
    """Tests for quiet hours logic."""

    def test_quiet_hours_disabled_when_none(self):
        """No quiet hours should never block."""
        from src.services.voice_proactivity import (
            VoiceProactivityService,
            NudgePreferences,
        )

        svc = VoiceProactivityService()
        prefs = NudgePreferences(quiet_hours_start=None, quiet_hours_end=None)
        assert svc._is_quiet_hours(prefs) is False

    def test_in_cooldown_check(self):
        """Cooldown flag should work correctly."""
        from src.services.voice_proactivity import (
            VoiceProactivityService,
            NudgePreferences,
        )

        svc = VoiceProactivityService()
        svc._last_nudge_time[1] = time.time()
        prefs = NudgePreferences(cooldown_minutes=15)
        assert svc._is_in_cooldown(1, prefs) is True

    def test_not_in_cooldown(self):
        """Expired cooldown should not block."""
        from src.services.voice_proactivity import (
            VoiceProactivityService,
            NudgePreferences,
        )

        svc = VoiceProactivityService()
        svc._last_nudge_time[1] = time.time() - 3600  # 1 hour ago
        prefs = NudgePreferences(cooldown_minutes=15)
        assert svc._is_in_cooldown(1, prefs) is False
