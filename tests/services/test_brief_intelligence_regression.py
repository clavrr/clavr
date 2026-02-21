"""
Regression tests for the Brief Service Intelligence Engine (V2).
Tests VIP scoring, goal alignment, keyword urgency, and recency decay.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from src.services.dashboard.brief_service import BriefService

@pytest.fixture
def mock_config():
    return MagicMock()

@pytest.fixture
def brief_service(mock_config):
    service = BriefService(config=mock_config)
    # Mock LLM generation and db fetching to isolate scoring logic
    service._get_llm_classified_reminders = AsyncMock(return_value=[])
    service._generate_greeting = AsyncMock(return_value="Hello there.")
    service._extract_actionable_summary = AsyncMock(return_value="Actionable summary")
    return service

@pytest.mark.asyncio
async def test_intelligence_scoring_vip_override(brief_service):
    """Test that emails from Inner Circle VIPs get highest priority (+50)."""
    now = datetime.now()
    emails = []
    urgent_emails = [
        {
            "id": "vip_msg_1",
            "subject": "Just checking in", # No urgent keywords
            "from": "CEO <ceo@company.com>",
            "snippet": "Let's sync up.",
            "received_at": now - timedelta(hours=1)
        },
        {
            "id": "normal_msg_1",
            "subject": "Weekly Newsletter",
            "from": "marketing@spam.com",
            "snippet": "Here is what happened this week.",
            "received_at": now - timedelta(hours=1)
        }
    ]
    people = {
        "inner_circle": [
            {"email": "ceo@company.com"}
        ]
    }
    
    result = await brief_service._generate_smart_reminders(
        user_id=1,
        user_name="Test",
        emails=emails,
        todos=[],
        meetings=[],
        urgent_emails=urgent_emails,
        people=people
    )
    
    items = result.get("items", [])
    assert len(items) == 1
    assert items[0]["id"] == "vip_msg_1"
    assert "Inner Circle" in items[0]["subtitle"]
    assert items[0]["urgency"] == "high"


@pytest.mark.asyncio
async def test_intelligence_scoring_goal_alignment(brief_service):
    """Test that emails aligning with active tasks get priority (+30)."""
    now = datetime.now()
    emails = []
    urgent_emails = [
        {
            "id": "goal_msg_1",
            "subject": "Thoughts on Q3 Roadmap",
            "from": "Colleague <colleague@company.com>",
            "snippet": "Can we review the Q3 roadmap document today?",
            "received_at": now - timedelta(hours=1)
        }
    ]
    # Active task matches "Q3" and "Roadmap"
    todos = [
        {"title": "Finalize Q3 Roadmap"}
    ]
    
    result = await brief_service._generate_smart_reminders(
        user_id=1,
        user_name="Test",
        emails=emails,
        todos=todos,
        meetings=[],
        urgent_emails=urgent_emails,
        people={}
    )
    
    items = result.get("items", [])
    # Verify the email made it into the reminders due to goal alignment (since it lacks impact keywords)
    assert len(items) >= 1
    email_reminder = next((i for i in items if i["id"] == "goal_msg_1"), None)
    assert email_reminder is not None
    assert "Related to active task" in email_reminder["subtitle"]
    # Score 30 is boundary for high/medium, it results in medium in the code (score > 30 = high, score 30 = medium)
    assert email_reminder["urgency"] in ("high", "medium")


@pytest.mark.asyncio
async def test_intelligence_scoring_recency_decay(brief_service):
    """Test that older emails get penalized and fall below threshold."""
    now = datetime.now()
    emails = []
    # Both have the same keyword, but one is very old.
    urgent_emails = [
        {
            "id": "fresh_urgent",
            "subject": "Urgent Server Issue",
            "from": "Alerts <alerts@company.com>",
            "snippet": "Server is down.",
            "received_at": now - timedelta(hours=1) # Score: 20
        },
        {
            "id": "stale_urgent",
            "subject": "Urgent Server Issue",
            "from": "Alerts <alerts@company.com>",
            "snippet": "Server is down.",
            "received_at": now - timedelta(hours=25) # Score: 20 - 23 = -3 (should drop out)
        }
    ]
    
    result = await brief_service._generate_smart_reminders(
        user_id=1,
        user_name="Test",
        emails=emails,
        todos=[],
        meetings=[],
        urgent_emails=urgent_emails,
        people={}
    )
    
    items = result.get("items", [])
    email_ids = [item["id"] for item in items if item["type"] == "email"]
    
    assert "fresh_urgent" in email_ids
    assert "stale_urgent" not in email_ids # Should have decayed below 0
    
@pytest.mark.asyncio
async def test_action_oriented_summarization(brief_service):
    """Test that high priority emails trigger the LLM action extraction."""
    now = datetime.now()
    emails = []
    urgent_emails = [
        {
            "id": "action_msg",
            "subject": "Check in",
            "from": "Boss <boss@company.com>",
            "body": "Please review the Q3 marketing presentation by EOD today.",
            "received_at": now - timedelta(hours=1)
        }
    ]
    people = {
        "inner_circle": [{"email": "boss@company.com"}] # Force high priority
    }
    
    # We mocked _extract_actionable_summary to return "Actionable summary"
    result = await brief_service._generate_smart_reminders(
        user_id=1,
        user_name="Test",
        emails=emails,
        todos=[],
        meetings=[],
        urgent_emails=urgent_emails,
        people=people
    )
    
    items = result.get("items", [])
    email_reminder = next((i for i in items if i["id"] == "action_msg"), None)
    
    assert email_reminder is not None
    # Action summary extraction should have replaced the title
    assert email_reminder["title"] == "Actionable summary"
