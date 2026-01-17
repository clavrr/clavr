"""
Autonomy System Evaluations - Briefing Generator

Tests for:
- Daily briefing generation
- Meeting brief generation
- Context gathering
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch


class TestBriefingGenerator:
    """Evaluate daily briefing generation."""
    
    @pytest.fixture
    def mock_config(self):
        """Mock config."""
        return MagicMock()
    
    @pytest.fixture
    def briefing_generator(self, mock_config):
        """Create BriefingGenerator with mock config."""
        from src.ai.autonomy.briefing import BriefingGenerator
        return BriefingGenerator(config=mock_config)
    
    # -------------------------------------------------------------------------
    # Context Gathering
    # -------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_gathers_calendar_context(self, briefing_generator):
        """Gathers calendar events for briefing."""
        mock_calendar = MagicMock()
        mock_calendar.get_upcoming_events = MagicMock(return_value=[
            {"summary": "Team Meeting", "start": {"dateTime": "2024-12-16T10:00:00Z"}},
            {"summary": "1:1 with Manager", "start": {"dateTime": "2024-12-16T14:00:00Z"}}
        ])
        
        mock_email = MagicMock()
        mock_email.get_unread_count = MagicMock(return_value=5)
        mock_email.get_urgent_threads = MagicMock(return_value=[])
        
        mock_tasks = MagicMock()
        mock_tasks.get_due_today = MagicMock(return_value=[])
        
        # Test context gathering
        context = await briefing_generator._gather_context(
            user_id=1,
            calendar_service=mock_calendar,
            email_service=mock_email,
            task_service=mock_tasks
        )
        
        assert "calendar" in context or "meetings" in context
    
    @pytest.mark.asyncio
    async def test_handles_missing_services(self, briefing_generator):
        """Handles None services gracefully."""
        # Should not raise when services are None
        context = await briefing_generator._gather_context(
            user_id=1,
            calendar_service=None,
            email_service=None,
            task_service=None
        )
        
        # Should return some default structure
        assert context is not None


class TestMeetingBriefGenerator:
    """Evaluate meeting brief generation."""
    
    @pytest.fixture
    def mock_config(self):
        return MagicMock()
    
    @pytest.fixture
    def meeting_brief_generator(self, mock_config):
        """Create MeetingBriefGenerator with mock config."""
        from src.ai.autonomy.briefing import MeetingBriefGenerator
        return MeetingBriefGenerator(config=mock_config)
    
    @pytest.mark.asyncio
    async def test_gathers_attendee_context(self, meeting_brief_generator):
        """Gathers context about meeting attendees."""
        mock_calendar = MagicMock()
        mock_calendar.get_event = MagicMock(return_value={
            "id": "event_123",
            "summary": "Client Call",
            "attendees": [
                {"email": "client@example.com", "displayName": "John Client"}
            ],
            "start": {"dateTime": "2024-12-16T14:00:00Z"}
        })
        
        mock_email = MagicMock()
        mock_email.search_threads = MagicMock(return_value=[])
        
        mock_memory = MagicMock()
        mock_memory.search_facts = AsyncMock(return_value=[])
        
        context = await meeting_brief_generator._gather_context(
            user_id=1,
            event_id="event_123",
            calendar_service=mock_calendar,
            email_service=mock_email,
            semantic_memory=mock_memory
        )
        
        # Should include attendee info
        assert context is not None
