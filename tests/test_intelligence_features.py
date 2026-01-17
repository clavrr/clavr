"""
Intelligence Features Test Suite

Comprehensive tests for the enhanced intelligence components:
1. PatternLearningAgent - 6 pattern types
2. ConflictDetectorAgent - 4 conflict types
3. TemporalPatternAgent - 4 temporal analyses
4. GraphObserverService - correlation, anomaly, prioritization
5. InteractionSession - context tracking
6. TemporalIndexer - heatmap, episode importance
"""
import asyncio
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, '/Users/maniko/Documents/clavr')


# ============================================================================
# Mock Classes
# ============================================================================

class MockConfig:
    """Mock configuration."""
    def __init__(self):
        self.LLM_PROVIDER = "mock"
        self.LLM_MODEL = "mock-model"
        
    def get(self, key, default=None):
        return default


class MockGraphManager:
    """Mock knowledge graph manager."""
    
    def __init__(self):
        self.query_results = []
        self.nodes_created = []
        self.relationships_created = []
        
    async def execute_query(self, query: str, params: Dict = None) -> List[Dict]:
        return self.query_results
        
    async def create_node(self, node_type, properties: Dict) -> str:
        node_id = f"node_{len(self.nodes_created)}"
        self.nodes_created.append({"type": node_type, "properties": properties})
        return node_id
        
    async def create_relationship(self, from_id: str, to_id: str, relation_type, properties: Dict = None):
        self.relationships_created.append({
            "from": from_id, "to": to_id, 
            "type": relation_type, "properties": properties
        })
        
    def set_query_results(self, results: List[Dict]):
        self.query_results = results


# ============================================================================
# Pattern Learning Tests
# ============================================================================

async def test_pattern_learning_time_of_day():
    """Test time-of-day pattern detection."""
    print("\n📊 Testing PatternLearningAgent - Time of Day Patterns...")
    
    from src.services.reasoning.agents.pattern_learning import PatternLearningAgent, PatternType
    
    config = MockConfig()
    graph = MockGraphManager()
    agent = PatternLearningAgent(config, graph)
    
    # Mock data: emails concentrated at 9 AM
    mock_events = [
        {"type": "Email", "timestamp": f"2024-01-{i:02d}T09:00:00Z"}
        for i in range(1, 20)
    ] + [
        {"type": "Email", "timestamp": f"2024-01-{i:02d}T14:00:00Z"}
        for i in range(1, 5)
    ]
    graph.set_query_results(mock_events)
    
    # Run detection
    results = await agent._detect_time_of_day_patterns(user_id=1)
    
    assert len(results) > 0, "Should detect at least one time-of-day pattern"
    
    # Check pattern structure
    pattern = results[0]
    assert pattern.type == "pattern", "Result type should be 'pattern'"
    assert pattern.content["pattern_type"] == PatternType.TIME_OF_DAY.value
    assert "hour" in pattern.content
    assert "concentration" in pattern.content
    
    print(f"  ✅ Detected {len(results)} time-of-day patterns")
    print(f"     Peak hour: {pattern.content.get('hour')}:00 ({pattern.content.get('period')})")
    return True


async def test_pattern_learning_day_of_week():
    """Test day-of-week pattern detection."""
    print("\n📊 Testing PatternLearningAgent - Day of Week Patterns...")
    
    from src.services.reasoning.agents.pattern_learning import PatternLearningAgent, PatternType
    
    config = MockConfig()
    graph = MockGraphManager()
    agent = PatternLearningAgent(config, graph)
    
    # Mock: "Team Standup" happens every Monday (4 occurrences)
    mock_events = [
        {"type": "CalendarEvent", "title": "Team Standup", "timestamp": "2024-01-01T09:00:00Z"},  # Mon
        {"type": "CalendarEvent", "title": "Team Standup", "timestamp": "2024-01-08T09:00:00Z"},  # Mon
        {"type": "CalendarEvent", "title": "Team Standup", "timestamp": "2024-01-15T09:00:00Z"},  # Mon
        {"type": "CalendarEvent", "title": "Team Standup", "timestamp": "2024-01-22T09:00:00Z"},  # Mon
    ]
    graph.set_query_results(mock_events)
    
    results = await agent._detect_day_of_week_patterns(user_id=1)
    
    assert len(results) > 0, "Should detect day-of-week pattern"
    
    pattern = results[0]
    assert pattern.content["pattern_type"] == PatternType.DAY_OF_WEEK.value
    assert "day_of_week" in pattern.content
    
    print(f"  ✅ Detected recurring event on {pattern.content.get('day_of_week')}")
    return True


async def test_pattern_learning_duration():
    """Test duration pattern detection."""
    print("\n📊 Testing PatternLearningAgent - Duration Patterns...")
    
    from src.services.reasoning.agents.pattern_learning import PatternLearningAgent, PatternType
    
    config = MockConfig()
    graph = MockGraphManager()
    agent = PatternLearningAgent(config, graph)
    
    # Mock: "1:1" meetings consistently last 30 minutes
    mock_events = [
        {"title": "1:1 with Bob", "start": "2024-01-01T10:00:00Z", "end": "2024-01-01T10:30:00Z"},
        {"title": "1:1 with Bob", "start": "2024-01-08T10:00:00Z", "end": "2024-01-08T10:30:00Z"},
        {"title": "1:1 with Bob", "start": "2024-01-15T10:00:00Z", "end": "2024-01-15T10:30:00Z"},
        {"title": "1:1 with Bob", "start": "2024-01-22T10:00:00Z", "end": "2024-01-22T10:30:00Z"},
    ]
    graph.set_query_results(mock_events)
    
    results = await agent._detect_duration_patterns(user_id=1)
    
    assert len(results) > 0, "Should detect duration pattern"
    
    pattern = results[0]
    assert pattern.content["pattern_type"] == PatternType.DURATION.value
    assert pattern.content.get("avg_duration_minutes") == 30
    
    print(f"  ✅ Detected meeting duration of {pattern.content.get('avg_duration_minutes')} minutes")
    return True


# ============================================================================
# Conflict Detector Tests
# ============================================================================

async def test_conflict_detector_calendar_overlap():
    """Test calendar overlap detection."""
    print("\n⚠️  Testing ConflictDetectorAgent - Calendar Overlaps...")
    
    from src.services.reasoning.agents.conflict_detector import ConflictDetectorAgent
    
    config = MockConfig()
    graph = MockGraphManager()
    agent = ConflictDetectorAgent(config, graph)
    
    # Mock: Two overlapping meetings
    tomorrow = (datetime.utcnow() + timedelta(days=1)).isoformat()
    tomorrow_2h = (datetime.utcnow() + timedelta(days=1, hours=2)).isoformat()
    tomorrow_1h = (datetime.utcnow() + timedelta(days=1, hours=1)).isoformat()
    tomorrow_3h = (datetime.utcnow() + timedelta(days=1, hours=3)).isoformat()
    
    mock_events = [
        {"id": "event1", "title": "Team Meeting", "start": tomorrow, "end": tomorrow_2h},
        {"id": "event2", "title": "Client Call", "start": tomorrow_1h, "end": tomorrow_3h},
    ]
    graph.set_query_results(mock_events)
    
    results = await agent._detect_calendar_overlaps(user_id=1)
    
    assert len(results) > 0, "Should detect calendar overlap"
    
    conflict = results[0]
    assert conflict.type == "insight"
    assert conflict.content["conflict_type"] == "calendar_overlap"
    assert conflict.content.get("overlap_minutes", 0) > 0
    
    print(f"  ✅ Detected overlap of {conflict.content.get('overlap_minutes')} minutes")
    return True


async def test_conflict_detector_deadline_cluster():
    """Test deadline cluster detection."""
    print("\n⚠️  Testing ConflictDetectorAgent - Deadline Clusters...")
    
    from src.services.reasoning.agents.conflict_detector import ConflictDetectorAgent
    
    config = MockConfig()
    graph = MockGraphManager()
    agent = ConflictDetectorAgent(config, graph)
    
    # Mock: 4 tasks due on same day
    future_date = (datetime.utcnow() + timedelta(days=2)).date().isoformat()
    mock_tasks = [
        {"id": f"task{i}", "title": f"Task {i}", "due_date": f"{future_date}T17:00:00Z", "priority": "high"}
        for i in range(1, 5)
    ]
    graph.set_query_results(mock_tasks)
    
    results = await agent._detect_deadline_conflicts(user_id=1)
    
    assert len(results) > 0, "Should detect deadline cluster"
    
    conflict = results[0]
    assert conflict.content["conflict_type"] == "deadline_cluster"
    assert conflict.content.get("task_count", 0) >= 3
    
    print(f"  ✅ Detected {conflict.content.get('task_count')} tasks due on same day")
    return True


# ============================================================================
# Temporal Pattern Agent Tests
# ============================================================================

async def test_temporal_agent_productivity_windows():
    """Test productivity window detection."""
    print("\n⏰ Testing TemporalPatternAgent - Productivity Windows...")
    
    from src.services.reasoning.agents.temporal_pattern_agent import TemporalPatternAgent
    
    config = MockConfig()
    graph = MockGraphManager()
    agent = TemporalPatternAgent(config, graph)
    
    # Mock: Tasks completed mostly at 10 AM
    mock_tasks = [
        {"completed_at": f"2024-01-{i:02d}T10:00:00Z", "priority": "normal"}
        for i in range(1, 20)
    ]
    graph.set_query_results(mock_tasks)
    
    results = await agent._analyze_productivity_windows(user_id=1)
    
    assert len(results) > 0, "Should detect productivity window"
    
    insight = results[0]
    assert insight.content["insight_type"] == "peak_productivity_window"
    assert insight.content.get("peak_hour") == 10
    
    print(f"  ✅ Detected peak productivity at {insight.content.get('peak_hour')}:00")
    return True


# ============================================================================
# Observer Service Tests
# ============================================================================

async def test_observer_event_correlation():
    """Test event correlation."""
    print("\n🔗 Testing GraphObserverService - Event Correlation...")
    
    from src.ai.memory.observer import GraphObserverService
    
    config = MockConfig()
    graph = MockGraphManager()
    observer = GraphObserverService(config, graph)
    
    # Mock: Multiple emails from same sender
    mock_events = [
        {"from": "bob@example.com", "type": "Email", "subject": "Project Update 1"},
        {"from": "bob@example.com", "type": "Email", "subject": "Project Update 2"},
        {"from": "bob@example.com", "type": "Email", "subject": "Project Update 3"},
    ]
    
    correlations = await observer.correlate_recent_events(mock_events)
    
    assert len(correlations) > 0, "Should find correlations"
    
    correlation = correlations[0]
    assert correlation["pattern"] == "multiple_from_same_sender"
    assert correlation["count"] == 3
    
    print(f"  ✅ Correlated {correlation.get('count')} events from {correlation.get('author')}")
    return True


async def test_observer_insight_prioritization():
    """Test insight prioritization."""
    print("\n🎯 Testing GraphObserverService - Insight Prioritization...")
    
    from src.ai.memory.observer import GraphObserverService
    
    config = MockConfig()
    graph = MockGraphManager()
    observer = GraphObserverService(config, graph)
    
    # Mock insights with different types
    insights = [
        {"type": "suggestion", "confidence": 0.5, "content": "You might like..."},
        {"type": "conflict", "confidence": 0.9, "content": "Double-booked!", "actionable": True},
        {"type": "connection", "confidence": 0.7, "content": "Related to..."},
    ]
    
    prioritized = observer.prioritize_insights(insights)
    
    assert len(prioritized) == 3
    assert prioritized[0]["type"] == "conflict", "Conflicts should be highest priority"
    assert all(p.get("priority_rank") for p in prioritized)
    
    print(f"  ✅ Prioritized {len(prioritized)} insights, top priority: {prioritized[0]['type']}")
    return True


# ============================================================================
# InteractionSession Tests
# ============================================================================

def test_interaction_session_context():
    """Test InteractionSession context tracking."""
    print("\n💬 Testing InteractionSession - Context Tracking...")
    
    from src.database.models import InteractionSession
    
    # Create mock session
    session = InteractionSession()
    session.user_id = 1
    session.interaction_id = "test-123"
    session.started_at = datetime.utcnow()
    session.turn_count = 0
    session.active_topics = []
    session.session_context = {}
    
    # Test record_turn
    session.record_turn(intent="schedule_meeting", topic="calendar")
    assert session.turn_count == 1
    assert session.last_intent == "schedule_meeting"
    assert "calendar" in session.active_topics
    
    # Test update_context
    session.update_context("last_entity", "Bob")
    assert session.session_context.get("last_entity") == "Bob"
    
    # Test duration
    duration = session.get_session_duration_minutes()
    assert isinstance(duration, int)
    
    print(f"  ✅ Turn count: {session.turn_count}, Intent: {session.last_intent}")
    print(f"  ✅ Topics: {session.active_topics}")
    print(f"  ✅ Context: {session.session_context}")
    return True


# ============================================================================
# TemporalIndexer Tests
# ============================================================================

async def test_temporal_indexer_heatmap():
    """Test activity heatmap generation."""
    print("\n🗓️  Testing TemporalIndexer - Activity Heatmap...")
    
    from src.services.indexing.temporal_indexer import TemporalIndexer
    
    config = MockConfig()
    graph = MockGraphManager()
    indexer = TemporalIndexer(config, graph)
    
    # Mock events spread across different days/hours
    mock_events = [
        {"timestamp": "2024-01-08T10:00:00Z", "type": "Email"},  # Monday 10AM
        {"timestamp": "2024-01-08T10:30:00Z", "type": "Email"},  # Monday 10AM
        {"timestamp": "2024-01-09T14:00:00Z", "type": "Meeting"},  # Tuesday 2PM
        {"timestamp": "2024-01-10T10:00:00Z", "type": "Email"},  # Wednesday 10AM
    ]
    graph.set_query_results(mock_events)
    
    heatmap = await indexer.get_user_activity_heatmap(user_id=1, days=30)
    
    assert heatmap["total_events"] == 4
    assert heatmap.get("peak_day") is not None
    assert heatmap.get("peak_hour") is not None
    assert "by_day" in heatmap
    assert "by_hour" in heatmap
    
    print(f"  ✅ Heatmap generated: {heatmap['total_events']} events")
    print(f"     Peak day: {heatmap['peak_day']}")
    print(f"     Peak hour: {heatmap['peak_hour']}")
    return True


def test_temporal_indexer_episode_importance():
    """Test episode importance calculation."""
    print("\n📈 Testing TemporalIndexer - Episode Importance...")
    
    from src.services.indexing.temporal_indexer import TemporalIndexer
    
    config = MockConfig()
    graph = MockGraphManager()
    indexer = TemporalIndexer(config, graph)
    
    # Test episode
    episode = {
        "start_time": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "end_time": (datetime.utcnow() - timedelta(days=1)).isoformat(),
        "event_count": 50,
        "significance": 0.8
    }
    
    importance = indexer.calculate_episode_importance(episode)
    
    assert 0 <= importance <= 1.0
    assert importance > 0.3, "Recent episode with 50 events should have moderate importance"
    
    print(f"  ✅ Episode importance score: {importance:.2f}")
    return True


# ============================================================================
# Main Test Runner
# ============================================================================

async def run_all_tests():
    """Run all intelligence feature tests."""
    print("=" * 60)
    print("🧪 INTELLIGENCE FEATURES TEST SUITE")
    print("=" * 60)
    
    tests = [
        ("PatternLearning - Time of Day", test_pattern_learning_time_of_day),
        ("PatternLearning - Day of Week", test_pattern_learning_day_of_week),
        ("PatternLearning - Duration", test_pattern_learning_duration),
        ("ConflictDetector - Calendar Overlap", test_conflict_detector_calendar_overlap),
        ("ConflictDetector - Deadline Cluster", test_conflict_detector_deadline_cluster),
        ("TemporalPattern - Productivity", test_temporal_agent_productivity_windows),
        ("Observer - Event Correlation", test_observer_event_correlation),
        ("Observer - Insight Priority", test_observer_insight_prioritization),
        ("InteractionSession - Context", test_interaction_session_context),
        ("TemporalIndexer - Heatmap", test_temporal_indexer_heatmap),
        ("TemporalIndexer - Episode Importance", test_temporal_indexer_episode_importance),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            if result:
                passed += 1
        except Exception as e:
            print(f"\n❌ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            
    print("\n" + "=" * 60)
    print(f"📊 RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
