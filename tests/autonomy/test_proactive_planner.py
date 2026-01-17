"""
Autonomy System Evaluations - Proactive Planner

Tests for:
- Goal-State matching
- Action plan generation
- Free time detection
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


class TestProactivePlanner:
    """Evaluate proactive planning logic."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock async database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session
    
    @pytest.fixture
    def mock_config(self):
        """Mock config."""
        config = MagicMock()
        return config
    
    @pytest.fixture
    def planner(self, mock_db_session, mock_config):
        """Create ProactivePlanner with mock db and config."""
        from src.ai.autonomy.planner import ProactivePlanner
        return ProactivePlanner(db_session=mock_db_session, config=mock_config)
    
    # -------------------------------------------------------------------------
    # Goal-State Matching
    # -------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_generates_plan_for_pending_goal(self, planner, mock_db_session):
        """Plans are generated for pending goals using LLM mock."""
        # Mock a pending goal
        mock_goal = MagicMock()
        mock_goal.id = 1
        mock_goal.title = "Learn Python"
        mock_goal.description = "Practice Python every day"
        mock_goal.status = "pending"
        mock_goal.deadline = None
        mock_goal.priority = "high"
        
        # Explicitly configure the db mock
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_goal]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute.return_value = mock_result
        
        mock_calendar = MagicMock()
        mock_calendar.find_free_time = MagicMock(return_value=[{"start": "2024-01-01T10:00:00"}])
        
        # Mock LLM calls
        with patch.object(planner, '_generate_structured', new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = [
                {"goal": "Learn Python", "reasoning": "Priority", "goal_id": 1}, # Selection
                {
                    "plan": [
                        {"type": "search", "description": "Search for Python courses", "params": {"query": "best python courses"}},
                        {"type": "block_time", "description": "Focus Time: Learn Python", "params": {"duration": 60}}
                    ]
                } # Multi-step Planning
            ]
            
            plans = await planner.check_goals_against_state(user_id=1, calendar_service=mock_calendar)
            
            assert len(plans) == 2
            assert plans[0]["type"] == "search"
            assert plans[1]["type"] == "block_time"
            assert plans[0]["goal_id"] == 1
            assert plans[1]["goal_id"] == 1
    
    @pytest.mark.asyncio
    async def test_no_plan_when_no_goals(self, planner, mock_db_session):
        """No plans when user has no active goals."""
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        
        mock_calendar = MagicMock()
        
        plans = await planner.check_goals_against_state(user_id=1, calendar_service=mock_calendar)
        
        assert len(plans) == 0


class TestActionPlanStructure:
    """Evaluate ActionPlan structure."""
    
    def test_action_plan_fields(self):
        """ActionPlan has required fields."""
        from src.ai.autonomy.planner import ActionPlan
        
        plan = ActionPlan(
            type="block_time",
            goal_id=1,
            description="Focus Time: Study",
            params={"duration_minutes": 60}
        )
        
        assert plan["type"] == "block_time"
        assert plan["goal_id"] == 1
        assert plan["description"] == "Focus Time: Study"
        assert plan["params"]["duration_minutes"] == 60
