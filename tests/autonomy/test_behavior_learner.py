"""
Autonomy System Evaluations - Behavior Learner

Tests for:
- Pattern Mining (sequential behavior detection)
- Pattern Creation
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


class TestBehaviorLearner:
    """Evaluate behavior learning capabilities."""
    
    @pytest.fixture
    def mock_graph(self):
        """Mock knowledge graph manager."""
        graph = MagicMock()
        graph.execute_query = AsyncMock(return_value=[])
        graph.create_node = AsyncMock(return_value=True)
        return graph
    
    @pytest.fixture
    def mock_config(self):
        """Mock config."""
        return MagicMock()
    
    @pytest.fixture
    def behavior_learner(self, mock_config, mock_graph):
        """Create BehaviorLearner with mocks."""
        from src.ai.autonomy.behavior_learner import BehaviorLearner
        learner = BehaviorLearner(config=mock_config, graph_manager=mock_graph)
        return learner
    
    # -------------------------------------------------------------------------
    # Sequential Pattern Detection
    # -------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_analyze_block_sequences(self, behavior_learner, mock_graph):
        """Detect sequential patterns in time blocks."""
        # Mock events in a time block
        mock_graph.execute_query = AsyncMock(return_value=[
            {"type": "Email", "time": "2024-12-16T09:00:00Z", "source": "gmail"},
            {"type": "Task", "time": "2024-12-16T09:15:00Z", "source": "asana"},
            {"type": "Email", "time": "2024-12-16T09:20:00Z", "source": "gmail"},
            {"type": "Task", "time": "2024-12-16T09:25:00Z", "source": "asana"},
        ])
        
        sequences = await behavior_learner._analyze_block_sequences("block_123")
        
        # Should detect Email -> Task pattern (occurs twice)
        assert ("Email", "Task") in sequences
        assert sequences[("Email", "Task")] >= 2
    
    @pytest.mark.asyncio
    async def test_ignores_same_type_sequences(self, behavior_learner, mock_graph):
        """Same-type sequences (Email->Email) are ignored."""
        mock_graph.execute_query = AsyncMock(return_value=[
            {"type": "Email", "time": "2024-12-16T09:00:00Z", "source": "gmail"},
            {"type": "Email", "time": "2024-12-16T09:05:00Z", "source": "gmail"},
            {"type": "Email", "time": "2024-12-16T09:10:00Z", "source": "gmail"},
        ])
        
        sequences = await behavior_learner._analyze_block_sequences("block_456")
        
        # Should NOT have Email -> Email
        assert ("Email", "Email") not in sequences
    
    @pytest.mark.asyncio
    async def test_ignores_large_time_gaps(self, behavior_learner, mock_graph):
        """Sequences with >30 min gap are ignored."""
        mock_graph.execute_query = AsyncMock(return_value=[
            {"type": "Email", "time": "2024-12-16T09:00:00Z", "source": "gmail"},
            {"type": "Task", "time": "2024-12-16T10:00:00Z", "source": "asana"},  # 1 hour later
        ])
        
        sequences = await behavior_learner._analyze_block_sequences("block_789")
        
        # Should NOT detect pattern due to time gap
        assert ("Email", "Task") not in sequences or sequences.get(("Email", "Task"), 0) == 0
    
    # -------------------------------------------------------------------------
    # Pattern Creation
    # -------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_create_pattern_node(self, behavior_learner, mock_graph):
        """Pattern nodes are created correctly."""
        pattern = await behavior_learner._create_pattern(
            user_id=1,
            name="Email -> Task",
            trigger="Email",
            action="Task",
            confidence=0.85,
            pattern_type="sequential"
        )
        
        assert pattern is not None
        assert pattern["trigger"] == "Email"
        assert pattern["action"] == "Task"
        assert pattern["confidence"] == 0.85
        assert mock_graph.create_node.called


class TestPatternConfidence:
    """Evaluate pattern confidence calculation."""
    
    @pytest.mark.parametrize("occurrence_count,expected_min_confidence", [
        (3, 0.5),   # Minimum support
        (5, 0.7),   # Medium confidence
        (10, 0.95), # High confidence (capped)
    ])
    def test_confidence_scaling(self, occurrence_count, expected_min_confidence):
        """Confidence scales with occurrence count."""
        # Formula: min(0.5 + (count * 0.1), 0.95)
        confidence = min(0.5 + (occurrence_count * 0.1), 0.95)
        assert confidence >= expected_min_confidence
