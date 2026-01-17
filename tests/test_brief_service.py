"""
Tests for Brief Service.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from src.services.dashboard.brief_service import BriefService
from src.database.models import ActionableItem

@pytest.fixture
def mock_config():
    return MagicMock()

@pytest.fixture
def mock_services():
    return {
        'email_service': MagicMock(),
        'task_service': MagicMock(),
        'calendar_service': MagicMock()
    }

@pytest.mark.asyncio
async def test_get_briefs_all_empty(mock_config, mock_services):
    """Test getting briefs with no data."""
    service = BriefService(mock_config, **mock_services)
    
    # Setup empty returns
    mock_services['email_service'].search_emails.return_value = []
    mock_services['task_service'].list_tasks.return_value = []
    mock_services['task_service'].get_overdue_tasks.return_value = []
    mock_services['calendar_service'].get_upcoming_events.return_value = []
    
    briefs = await service.get_dashboard_briefs(1)
    
    assert briefs['emails'] == []
    assert briefs['todos'] == []
    assert briefs['meetings'] == []
    assert briefs['reminders'] == []

@pytest.mark.asyncio
async def test_get_briefs_aggregation(mock_config, mock_services):
    """Test aggregation logic."""
    service = BriefService(mock_config, **mock_services)
    
    # 1. Emails
    mock_services['email_service'].search_emails.return_value = [{
        'id': 'msg1', 'subject': 'Important', 'sender': 'boss@co.com', 'snippet': 'Read this'
    }]
    
    # 2. Tasks (Google)
    mock_services['task_service'].get_overdue_tasks.return_value = [{
        'id': 't1', 'title': 'Overdue Task', 'due': '2023-01-01'
    }]
    mock_services['task_service'].list_tasks.return_value = []
    
    # 3. Calendar
    now = datetime.now()
    mock_services['calendar_service'].get_upcoming_events.return_value = [{
        'id': 'evt1', 'summary': 'Meeting', 
        'start': {'dateTime': now.isoformat()},
        'end': {'dateTime': (now + timedelta(hours=1)).isoformat()}
    }]
    
    # 4. Reminders (Mock DB - tricky, maybe mock extraction query or integration)
    # BriefService uses direct DB query for internal reminders.
    # We'll skip DB part for unit test or mock `session.execute` if we patch it.
    
    with patch('src.services.dashboard.brief_service.get_db_context') as mock_db_ctx:
        # Mock DB session for reminders & internal tasks
        mock_session = MagicMock()
        mock_db_ctx.return_value.__enter__.return_value = mock_session
        
        # We won't simulate complex SQL alchemy returns here easily without a real DB fixture.
        # So we'll trust the method gracefully handles empty DB results if loop is empty.
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        
        briefs = await service.get_dashboard_briefs(1)
        
        assert len(briefs['emails']) == 1
        assert briefs['emails'][0]['subject'] == 'Important'
        
        assert len(briefs['todos']) >= 1
        assert briefs['todos'][0]['title'] == 'Overdue Task'
        
        # Calendar logic filters for 'today'. If mock date is correct, it appears.
        # Our mock `now` matches logic.
        assert len(briefs['meetings']) == 1
        assert briefs['meetings'][0]['title'] == 'Meeting'
