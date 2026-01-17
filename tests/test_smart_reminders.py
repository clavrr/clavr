"""
Tests for Smart Reminder System.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from src.services.extraction.actionable_item_extractor import ActionableItemExtractor, ExtractedItem
from src.services.reminders.daily_digest import DailyDigestGenerator
from src.database.models import ActionableItem

@pytest.fixture
def mock_config():
    return MagicMock()

@pytest.fixture
def extractor(mock_config):
    with patch('src.services.extraction.actionable_item_extractor.LLMFactory') as mock_factory:
        mock_llm = AsyncMock()
        mock_factory.create_llm.return_value = mock_llm
        extractor = ActionableItemExtractor(mock_config)
        extractor.llm = mock_llm
        yield extractor

@pytest.fixture
def digest_generator(mock_config):
    mock_graph = AsyncMock()
    return DailyDigestGenerator(mock_config, mock_graph)

@pytest.mark.asyncio
async def test_extractor_bill(extractor):
    """Test extraction of a bill."""
    email_text = "Please pay the invoice of $450.00 by 2023-12-25."
    
    # Mock LLM response
    mock_response = '''
    [
        {
            "title": "Pay invoice",
            "item_type": "bill",
            "due_date": "2023-12-25T00:00:00",
            "amount": 450.00,
            "urgency": "high",
            "suggested_action": "Pay"
        }
    ]
    '''
    extractor.llm.generate.return_value = mock_response
    
    items = await extractor.extract_from_text(email_text, "test:1")
    
    assert len(items) == 1
    item = items[0]
    assert item.item_type == "bill"
    assert item.amount == 450.00
    assert item.due_date == "2023-12-25T00:00:00"

@pytest.mark.asyncio
async def test_extractor_no_items(extractor):
    """Test extraction with no actionable items."""
    extractor.llm.generate.return_value = "[]"
    items = await extractor.extract_from_text("Just saying hello!", "test:2")
    assert len(items) == 0

@pytest.mark.asyncio
async def test_digest_generation(digest_generator):
    """Test daily digest generation logic."""
    # Mock _get_actionable_items and _get_today_schedule
    
    mock_items = [
        {
            'title': 'Urgent Bill',
            'item_type': 'bill',
            'due_date': datetime.utcnow().isoformat(),
            'urgency': 'high'
        },
        {
            'title': 'Later Task',
            'item_type': 'task',
            'due_date': (datetime.utcnow() + timedelta(days=5)).isoformat(),
            'urgency': 'low'
        }
    ]
    
    mock_schedule = [
        {'title': 'Standup', 'time': '10:00 AM', 'location': 'Zoom'}
    ]
    
    with patch.object(digest_generator, '_get_actionable_items', return_value=mock_items), \
         patch.object(digest_generator, '_get_today_schedule', return_value=mock_schedule):
        
        digest = await digest_generator.generate_digest(1)
        
        assert "date" in digest
        assert len(digest['top_of_mind']) == 1
        assert digest['top_of_mind'][0]['title'] == 'Urgent Bill'
        
        assert len(digest['upcoming']) == 1
        assert digest['upcoming'][0]['title'] == 'Later Task'
        
        assert len(digest['schedule']) == 1

def test_actionable_item_model():
    """Test SQL model instantiation."""
    item = ActionableItem(
        id="test_1",
        title="Test Item",
        due_date=datetime.now(),
        item_type="bill",
        status="pending"
    )
    assert item.status == 'pending'
