
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from src.agents.perception.agent import PerceptionAgent
from src.agents.perception.types import PerceptionEvent, Trigger

class TestPerceptionAgent:
    @pytest.fixture
    def mock_config(self):
        return MagicMock()

    @pytest.fixture
    def agent(self, mock_config):
        with patch('src.memory.orchestrator.get_memory_orchestrator', return_value=MagicMock()):
            return PerceptionAgent(mock_config)

    @pytest.mark.asyncio
    async def test_perceive_event_noise(self, agent):
        # Mock grounding to say it's blocked
        agent._ground_event = AsyncMock(return_value={"is_blocked": True})
        
        event = PerceptionEvent(
            type="email",
            source_id="123",
            content={"from": "spam@example.com", "subject": "Buy now!"},
            timestamp="2024-01-01T10:00:00"
        )
        
        trigger = await agent.perceive_event(event, user_id=1)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_perceive_event_signal(self, agent):
        # Mock grounding to say it's VIP
        agent._ground_event = AsyncMock(return_value={"is_vip": True, "is_blocked": False})
        
        # Mock LLM to return actionable signal
        agent._generate_structured = AsyncMock(return_value={
            "is_actionable": True,
            "priority": "high",
            "category": "urgent_email",
            "reason": "VIP sender detected",
            "confidence": 0.9
        })
        
        event = PerceptionEvent(
            type="email",
            source_id="123",
            content={"from": "boss@example.com", "subject": "Urgent meeting"},
            timestamp="2024-01-01T10:00:00"
        )
        
        trigger = await agent.perceive_event(event, user_id=1)
        
        assert trigger is not None
        assert trigger.priority == "high"
        assert trigger.category == "urgent_email"
        assert "VIP" in trigger.reason
