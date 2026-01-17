import asyncio
import os
import sys
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.getcwd())

from src.utils.config import Config
from src.tools.brief.tool import BriefTool
from src.services.dashboard.brief_service import BriefService
from src.ai.autonomy.briefing import BriefingGenerator

async def test_brief_tool():
    config = Config()
    
    # Mock services
    mock_email = MagicMock()
    mock_email.search_emails.return_value = [{"subject": "Test Email", "sender": "test@example.com", "snippet": "Hello"}]
    
    mock_task = MagicMock()
    mock_task.list_tasks.return_value = [{"id": "1", "title": "Test Task", "status": "needsAction"}]
    mock_task.get_overdue_tasks.return_value = []
    
    mock_cal = MagicMock()
    mock_cal.list_events.return_value = [{"summary": "Test Meeting", "start": {"dateTime": "2026-01-09T10:00:00Z"}}]
    
    brief_service = BriefService(
        config=config,
        email_service=mock_email,
        task_service=mock_task,
        calendar_service=mock_cal
    )
    
    brief_gen = BriefingGenerator(config=config)
    
    tool = BriefTool(
        config=config,
        user_id=1,
        user_first_name="Anthony",
        brief_service=brief_service,
        brief_generator=brief_gen
    )
    
    print("Testing action='briefing'...")
    res = await tool.arun({"action": "briefing"})
    print(f"Result: {res}\n")
    
    print("Testing action='reminders'...")
    res = await tool.arun({"action": "reminders"})
    print(f"Result: {res}\n")

if __name__ == "__main__":
    asyncio.run(test_brief_tool())
