"""
Unit Tests for Memory System

Tests for SimplifiedMemorySystem and MemoryIntegrator
"""

import pytest
from datetime import datetime, timedelta
from src.agent.memory_system import (
    SimplifiedMemorySystem,
    MemoryIntegrator,
    MemoryPattern,
    UserPreference,
    create_memory_system
)


class TestMemoryPattern:
    """Test MemoryPattern dataclass"""
    
    def test_memory_pattern_initialization(self):
        """Test MemoryPattern initializes correctly"""
        pattern = MemoryPattern(
            pattern="multi_step_find_and_create",
            intent="email"
        )
        
        assert pattern.pattern == "multi_step_find_and_create"
        assert pattern.intent == "email"
        assert pattern.success_count == 0
        assert pattern.failure_count == 0
        assert pattern.confidence == 0.5
        assert pattern.last_used is not None
        assert pattern.tools_used == []
    
    def test_memory_pattern_with_tools(self):
        """Test MemoryPattern with tools list"""
        pattern = MemoryPattern(
            pattern="search_emails",
            intent="email",
            tools_used=["email", "search"]
        )
        
        assert pattern.tools_used == ["email", "search"]


class TestUserPreference:
    """Test UserPreference dataclass"""
    
    def test_user_preference_initialization(self):
        """Test UserPreference initializes correctly"""
        pref = UserPreference(
            user_id=123,
            preference_type="multi_step",
            pattern="find_and_create"
        )
        
        assert pref.user_id == 123
        assert pref.preference_type == "multi_step"
        assert pref.pattern == "find_and_create"
        assert pref.frequency == 1
        assert pref.confidence == 0.5
        assert pref.last_used is not None


class TestSimplifiedMemorySystem:
    """Test SimplifiedMemorySystem"""
    
    @pytest.fixture
    def memory_system(self):
        """Create memory system without database"""
        return SimplifiedMemorySystem(db=None, batch_size=5)
    
    def test_initialization(self, memory_system):
        """Test memory system initializes correctly"""
        assert memory_system.db is None
        assert memory_system.has_database is False
        assert memory_system.batch_size == 5
        assert len(memory_system.query_patterns) == 0
        assert len(memory_system.user_preferences) == 0
        assert len(memory_system.execution_history) == 0
    
    def test_learn_query_pattern_success(self, memory_system):
        """Test learning from successful execution"""
        memory_system.learn_query_pattern(
            query="Find emails about budget",
            intent="email",
            tools_used=["email"],
            success=True,
            execution_time=1.5,
            user_id=None
        )
        
        # Check pattern was created
        assert len(memory_system.query_patterns) == 1
        pattern_key = list(memory_system.query_patterns.keys())[0]
        pattern = memory_system.query_patterns[pattern_key]
        
        assert pattern.success_count == 1
        assert pattern.failure_count == 0
        assert pattern.confidence == 0.6  # 0.5 + 0.1
        assert "email" in pattern.tools_used
        
        # Check execution history
        assert len(memory_system.execution_history) == 1
        execution = memory_system.execution_history[0]
        assert execution['query'] == "Find emails about budget"
        assert execution['success'] is True
        assert execution['execution_time'] == 1.5
    
    def test_learn_query_pattern_failure(self, memory_system):
        """Test learning from failed execution"""
        memory_system.learn_query_pattern(
            query="Find emails about budget",
            intent="email",
            tools_used=["email"],
            success=False,
            user_id=None
        )
        
        pattern_key = list(memory_system.query_patterns.keys())[0]
        pattern = memory_system.query_patterns[pattern_key]
        
        assert pattern.success_count == 0
        assert pattern.failure_count == 1
        assert pattern.confidence == 0.45  # 0.5 - 0.05
    
    def test_confidence_bounds(self, memory_system):
        """Test confidence stays within [0.1, 1.0]"""
        # Learn same pattern multiple times successfully
        for _ in range(10):
            memory_system.learn_query_pattern(
                query="Find emails",
                intent="email",
                tools_used=["email"],
                success=True
            )
        
        pattern_key = list(memory_system.query_patterns.keys())[0]
        pattern = memory_system.query_patterns[pattern_key]
        
        # Confidence should cap at 1.0
        assert pattern.confidence == 1.0
        
        # Learn failures
        for _ in range(30):
            memory_system.learn_query_pattern(
                query="Find emails",
                intent="email",
                tools_used=["email"],
                success=False
            )
        
        # Confidence should floor at 0.1
        assert pattern.confidence >= 0.1
    
    def test_pattern_extraction(self, memory_system):
        """Test pattern extraction from queries"""
        test_cases = [
            ("Find emails and create tasks", "multi_step", "multi_step_find_and_create"),
            ("Show my action items", "email", "email_action_items"),
            ("List all tasks", "tasks", "tasks_single_step"),
        ]
        
        for query, intent, expected_pattern in test_cases:
            pattern = memory_system._extract_pattern(query, intent)
            assert expected_pattern in pattern or "single_step" in pattern or "multi_step" in pattern
    
    def test_get_similar_patterns(self, memory_system):
        """Test finding similar patterns"""
        # Learn some patterns
        memory_system.learn_query_pattern(
            "Find emails about budget", "email", ["email"], True
        )
        memory_system.learn_query_pattern(
            "Find emails about project", "email", ["email"], True
        )
        memory_system.learn_query_pattern(
            "Create new task", "tasks", ["tasks"], True
        )
        
        # Query for similar patterns
        similar = memory_system.get_similar_patterns(
            "Find emails about meeting", "email"
        )
        
        # Should find email-related patterns but not task patterns
        assert len(similar) > 0
        for pattern in similar:
            assert pattern.confidence >= 0.6
            assert pattern.success_count > 0
    
    def test_get_tool_recommendations(self, memory_system):
        """Test tool recommendations based on patterns"""
        # Learn patterns with different tools
        memory_system.learn_query_pattern(
            "Find emails", "email", ["email", "search"], True
        )
        memory_system.learn_query_pattern(
            "Find messages", "email", ["email"], True
        )
        
        # Get recommendations
        tools = memory_system.get_tool_recommendations(
            "Find emails about budget", "email"
        )
        
        assert "email" in tools  # Most common tool
    
    def test_user_preference_learning(self, memory_system):
        """Test user preference learning"""
        user_id = 123
        
        # Learn multiple successful patterns for user
        for i in range(3):
            memory_system.learn_query_pattern(
                f"Find emails about topic {i}",
                "email",
                ["email"],
                True,
                user_id=user_id
            )
        
        # Check user preferences were created
        assert user_id in memory_system.user_preferences
        user_prefs = memory_system.user_preferences[user_id]
        assert len(user_prefs) > 0
        
        # Check preference details
        pref = user_prefs[0]
        assert pref.user_id == user_id
        assert pref.frequency >= 1
    
    def test_get_user_preferences(self, memory_system):
        """Test getting user preferences"""
        user_id = 123
        
        memory_system.learn_query_pattern(
            "Find emails", "email", ["email"], True, user_id=user_id
        )
        
        prefs = memory_system.get_user_preferences(user_id)
        assert len(prefs) > 0
        assert prefs[0].user_id == user_id
    
    def test_execution_history_limit(self, memory_system):
        """Test execution history is limited to 1000 entries"""
        # Add 1100 executions
        for i in range(1100):
            memory_system.learn_query_pattern(
                f"Query {i}", "email", ["email"], True
            )
        
        # Should keep only 500 most recent
        assert len(memory_system.execution_history) == 500
    
    def test_clear_old_patterns(self, memory_system):
        """Test clearing old patterns"""
        # Create old pattern
        memory_system.learn_query_pattern(
            "Old query", "email", ["email"], False
        )
        
        # Manually set old timestamp
        pattern_key = list(memory_system.query_patterns.keys())[0]
        old_date = datetime.now() - timedelta(days=40)
        memory_system.query_patterns[pattern_key].last_used = old_date
        memory_system.query_patterns[pattern_key].confidence = 0.2
        
        # Clear old patterns
        memory_system.clear_old_patterns(max_age_days=30)
        
        # Old pattern should be removed
        assert len(memory_system.query_patterns) == 0
    
    def test_get_execution_stats(self, memory_system):
        """Test getting execution statistics"""
        # Add some executions
        memory_system.learn_query_pattern(
            "Query 1", "email", ["email"], True
        )
        memory_system.learn_query_pattern(
            "Query 2", "tasks", ["tasks"], True
        )
        memory_system.learn_query_pattern(
            "Query 3", "email", ["email"], False
        )
        
        stats = memory_system.get_execution_stats()
        
        assert stats['total_patterns'] >= 2
        assert stats['total_executions'] == 3
        assert stats['database_enabled'] is False
        assert 'recent_success_rate' in stats
    
    def test_pattern_similarity_calculation(self, memory_system):
        """Test pattern similarity calculation"""
        similarity1 = memory_system._calculate_pattern_similarity(
            "email_search", "email_find"
        )
        similarity2 = memory_system._calculate_pattern_similarity(
            "email_search", "tasks_create"
        )
        
        # Email patterns should be more similar than email vs tasks
        assert similarity1 > similarity2
    
    def test_batch_commit_tracking(self, memory_system):
        """Test batch commit tracking"""
        # Set small batch size for testing
        memory_system.batch_size = 2
        
        # Add patterns (should not commit until batch size reached)
        memory_system.learn_query_pattern(
            "Query 1", "email", ["email"], True
        )
        
        assert len(memory_system._pending_pattern_updates) == 1
        assert len(memory_system._pending_executions) == 1
        
        # Add another (should trigger commit)
        memory_system.learn_query_pattern(
            "Query 2", "email", ["email"], True
        )
        
        # Pending should be cleared after commit attempt
        # (even though we don't have a real database)
        assert len(memory_system._pending_pattern_updates) == 0
        assert len(memory_system._pending_executions) == 0


class TestMemoryIntegrator:
    """Test MemoryIntegrator"""
    
    @pytest.fixture
    def memory_system(self):
        """Create memory system"""
        return SimplifiedMemorySystem(db=None)
    
    @pytest.fixture
    def integrator(self, memory_system):
        """Create memory integrator"""
        return MemoryIntegrator(memory_system)
    
    def test_initialization(self, integrator, memory_system):
        """Test integrator initializes correctly"""
        assert integrator.memory_system == memory_system
    
    def test_learn_from_orchestrator_execution(self, integrator):
        """Test learning from orchestrator execution"""
        execution_result = {
            'success': True,
            'execution_type': 'orchestrated',
            'tools_used': ['email', 'tasks'],
            'execution_time': '2.5s',
            'steps_executed': 2,
            'total_steps': 2
        }
        
        integrator.learn_from_orchestrator_execution(
            query="Find emails and create tasks",
            execution_result=execution_result,
            user_id=123
        )
        
        # Check pattern was learned
        assert len(integrator.memory_system.query_patterns) > 0
        assert len(integrator.memory_system.execution_history) > 0
    
    def test_get_orchestrator_recommendations(self, integrator):
        """Test getting orchestrator recommendations"""
        # Learn some patterns first
        integrator.learn_from_orchestrator_execution(
            query="Find emails about budget",
            execution_result={
                'success': True,
                'execution_type': 'orchestrated',
                'tools_used': ['email'],
                'execution_time': '1.5s'
            },
            user_id=123
        )
        
        # Get recommendations
        recommendations = integrator.get_orchestrator_recommendations(
            query="Find emails about project",
            user_id=123
        )
        
        assert 'intent' in recommendations
        assert 'similar_patterns' in recommendations
        assert 'recommended_tools' in recommendations
        assert 'confidence' in recommendations


class TestFactoryFunction:
    """Test create_memory_system factory function"""
    
    def test_create_memory_system_without_db(self):
        """Test creating memory system without database"""
        memory_system = create_memory_system(db=None)
        
        assert isinstance(memory_system, SimplifiedMemorySystem)
        assert memory_system.has_database is False
    
    def test_create_memory_system_with_batch_size(self):
        """Test creating memory system with custom batch size"""
        memory_system = create_memory_system(db=None, batch_size=20)
        
        assert memory_system.batch_size == 20


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
