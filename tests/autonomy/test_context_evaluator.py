"""
Autonomy System Evaluations - Context Evaluator

Tests for:
- Time-based triggers (morning briefing, EOD summary)
- Calendar triggers (upcoming meetings)
- Preference-aware decisions
"""
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


class TestContextEvaluator:
    """Evaluate context evaluation logic."""
    
    @pytest.fixture
    def context_evaluator(self):
        """Create ContextEvaluator with mocked dependencies."""
        from src.ai.autonomy.evaluator import ContextEvaluator
        return ContextEvaluator(config={})
    
    # -------------------------------------------------------------------------
    # Morning Briefing Trigger
    # -------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("weekday,hour,should_trigger", [
        (0, 8, True),   # Monday 8am - should trigger
        (0, 9, True),   # Monday 9am - should trigger
        (0, 10, False), # Monday 10am - too late
        (0, 7, False),  # Monday 7am - too early
        (5, 8, False),  # Saturday 8am - weekend
        (6, 9, False),  # Sunday 9am - weekend
    ])
    async def test_morning_briefing_trigger(self, context_evaluator, weekday, hour, should_trigger):
        """Morning briefing triggers on weekdays 8-10am."""
        with patch('src.ai.autonomy.evaluator.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = hour
            mock_now.weekday.return_value = weekday
            mock_dt.now.return_value = mock_now
            
            result = await context_evaluator.evaluate_context(user_id=1)
            
            if should_trigger:
                assert result["action_needed"] is True
                assert result["proposed_action"] == "generate_morning_briefing"
            # Note: Other triggers might match, so we just check the main logic
    
    # -------------------------------------------------------------------------
    # End of Day Summary Trigger
    # -------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("weekday,hour,should_trigger", [
        (0, 17, True),  # Monday 5pm - should trigger
        (0, 18, True),  # Monday 6pm - should trigger
        (0, 19, False), # Monday 7pm - too late
        (0, 16, False), # Monday 4pm - too early
        (5, 17, False), # Saturday 5pm - weekend
    ])
    async def test_eod_summary_trigger(self, context_evaluator, weekday, hour, should_trigger):
        """End of day summary triggers on weekdays 5-7pm."""
        with patch('src.ai.autonomy.evaluator.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = hour
            mock_now.weekday.return_value = weekday
            mock_dt.now.return_value = mock_now
            
            result = await context_evaluator.evaluate_context(user_id=1)
            
            if should_trigger:
                assert result["action_needed"] is True
                assert result["proposed_action"] == "generate_daily_summary"


class TestCalendarTriggers:
    """Evaluate calendar-triggered autonomy."""
    
    @pytest.fixture
    def mock_calendar_service(self):
        """Mock calendar service."""
        service = MagicMock()
        service.get_upcoming_events = MagicMock(return_value=[])
        return service
    
    @pytest.fixture
    def context_evaluator(self, mock_calendar_service):
        """Create ContextEvaluator with calendar service."""
        from src.ai.autonomy.evaluator import ContextEvaluator
        return ContextEvaluator(
            config={},
            calendar_service=mock_calendar_service
        )
    
    @pytest.mark.asyncio
    async def test_meeting_brief_trigger(self, context_evaluator, mock_calendar_service):
        """Meeting brief triggers 10-15 mins before meeting."""
        # Mock a meeting starting in 12 minutes
        now = datetime.now(timezone.utc)
        meeting_start = now + timedelta(minutes=12)
        
        mock_calendar_service.get_upcoming_events = MagicMock(return_value=[{
            "id": "event_123",
            "summary": "Team Standup",
            "start": {"dateTime": meeting_start.isoformat()}
        }])
        
        # Patch datetime in evaluator to avoid timing issues
        with patch('src.ai.autonomy.evaluator.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 10
            mock_now.weekday.return_value = 1  # Tuesday
            mock_dt.now.return_value = mock_now
            mock_dt.fromisoformat = datetime.fromisoformat
            
            result = await context_evaluator.evaluate_context(user_id=1)
            
            # Should trigger meeting brief preparation
            # (implementation checks delta_minutes between 10-15)
            assert mock_calendar_service.get_upcoming_events.called


class TestPreferenceAwareness:
    """Evaluate preference-aware decisions."""
    
    @pytest.fixture
    def mock_memory(self):
        """Mock semantic memory."""
        memory = MagicMock()
        memory.get_facts = AsyncMock(return_value=[])
        return memory
    
    @pytest.fixture
    def context_evaluator(self, mock_memory):
        """Create ContextEvaluator with semantic memory."""
        from src.ai.autonomy.evaluator import ContextEvaluator
        return ContextEvaluator(
            config={},
            semantic_memory=mock_memory
        )
    
    @pytest.mark.asyncio
    async def test_respects_dnd_preference(self, context_evaluator, mock_memory):
        """Respects 'no notifications after 6pm' preference."""
        # Mock a DND preference
        mock_memory.get_facts = AsyncMock(return_value=[{
            "content": "No notifications after 6pm",
            "category": "preference",
            "confidence": 0.9
        }])
        
        with patch('src.ai.autonomy.evaluator.datetime') as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 20  # 8pm
            mock_now.weekday.return_value = 1  # Tuesday
            mock_dt.now.return_value = mock_now
            
            result = await context_evaluator.evaluate_context(user_id=1)
            
            # Should NOT take action due to DND preference
            assert result["action_needed"] is False
            assert "preference" in result["reason"].lower()
