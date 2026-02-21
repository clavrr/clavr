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

@pytest.fixture(autouse=True)
def mock_get_timezone():
    with patch('src.services.dashboard.brief_service.get_timezone', return_value='UTC') as mock:
        yield mock

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
    mock_services['calendar_service'].list_events.return_value = []
    
    briefs = await service.get_dashboard_briefs(1)
    
    assert briefs['emails'] == []
    assert briefs['todos'] == []
    assert briefs['meetings'] == []
    assert 'items' in briefs['reminders']
    assert briefs['reminders']['items'] == []

@pytest.mark.asyncio
async def test_get_briefs_aggregation(mock_config, mock_services):
    """Test aggregation logic."""
    service = BriefService(mock_config, **mock_services)
    
    # 1. Emails
    mock_services['email_service'].search_emails.return_value = [{
        'id': 'msg1', 'subject': 'Important', 'sender': 'boss@co.com', 'snippet': 'Read this'
    }]
    
    # 2. Tasks (Google)
    mock_services['task_service'].list_tasks.return_value = [{
        'id': 't1', 'title': 'Overdue Task', 'due': '2023-01-01'
    }]
    
    # 3. Calendar
    now = datetime.now()
    mock_services['calendar_service'].list_events.return_value = [{
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

@pytest.mark.asyncio
async def test_get_recent_important_emails_with_vips(mock_config, mock_services):
    """Test that VIPs from people dictionary are injected into the Gmail query."""
    service = BriefService(mock_config, **mock_services)
    
    mock_services['email_service'].search_emails.return_value = []
    
    people = {
        "inner_circle": [
            {"email": "vip1@company.com"},
            {"email": "vip2@startup.io"}
        ]
    }
    
    await service._get_recent_important_emails(user_id=1, people=people)
    
    # Verify the query passed to search_emails includes both keyword and VIP OR clauses
    mock_services['email_service'].search_emails.assert_called_once()
    kwargs = mock_services['email_service'].search_emails.call_args.kwargs
    query = kwargs.get('query', '')
    
    assert "from:vip1@company.com" in query
    assert "from:vip2@startup.io" in query
    assert "newer_than:2d" in query

@pytest.mark.asyncio
async def test_get_recent_important_emails_no_vips(mock_config, mock_services):
    """Test query fallback when no VIPs are present."""
    service = BriefService(mock_config, **mock_services)
    mock_services['email_service'].search_emails.return_value = []
    
    await service._get_recent_important_emails(user_id=1, people={})
    
    mock_services['email_service'].search_emails.assert_called_once()
    kwargs = mock_services['email_service'].search_emails.call_args.kwargs
    query = kwargs.get('query', '')
    
    assert "from:" not in query
    assert "newer_than:2d" in query

@pytest.mark.asyncio
async def test_get_briefs_intelligence_integration(mock_config, mock_services):
    """Test the full flow from get_dashboard_briefs through intelligence scoring."""
    service = BriefService(mock_config, **mock_services)
    
    now = datetime.now()
    # Mock data to trigger the scoring engine
    
    # 1. Emails: one from VIP
    mock_services['email_service'].search_emails.return_value = [{
        'id': 'msg_vip', 
        'subject': 'Check in', 
        'sender': 'ceo@company.com', 
        'snippet': 'Can we talk?',
        'date': now.isoformat()
    }]
    
    # 2. Tasks: active goal for alignment
    mock_services['task_service'].list_tasks.return_value = [{
        'id': 't1', 
        'title': 'Q3 Roadmap Planning', 
        'status': 'needsAction'
    }]
    mock_services['task_service'].get_overdue_tasks.return_value = []
    
    mock_services['calendar_service'].get_upcoming_events.return_value = []
    
    # Mock DB Context
    with patch('src.services.dashboard.brief_service.get_db_context') as mock_db_ctx:
        mock_session = MagicMock()
        mock_db_ctx.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        
        # We need to explicitly mock _get_people to return our CRM data
        with patch.object(service, '_get_people', new_callable=AsyncMock) as mock_get_people:
            mock_get_people.return_value = {
                "inner_circle": [{"email": "ceo@company.com"}],
                "fading_contacts": []
            }
            
            # Mock LLM generation to avoid hitting real API in unit test
            service._generate_greeting = AsyncMock(return_value="Greetings.")
            service._extract_actionable_summary = AsyncMock(return_value="Action summary.")
            
            # Execute full pipeline
            briefs = await service.get_dashboard_briefs(1)
            
            # Verify integration
            assert "people" in briefs
            assert len(briefs["people"].get("inner_circle", [])) == 1
            
            # Verify reminders
            reminders = briefs.get("reminders", {}).get("items", [])
            assert len(reminders) > 0, "Should have generated a reminder for the VIP email"
            
            vip_reminder = next((r for r in reminders if r["id"] == "msg_vip"), None)
            assert vip_reminder is not None
            assert "Inner Circle" in vip_reminder["subtitle"]
            assert vip_reminder["urgency"] == "high"
