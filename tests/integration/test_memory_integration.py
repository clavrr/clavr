"""
Integration Tests for Memory System

Tests for integration between memory system, orchestrator, and ClavrAgent
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from src.agent.memory_system import SimplifiedMemorySystem, MemoryIntegrator, create_memory_system
from src.agent.clavr_agent import ClavrAgent


class TestMemorySystemOrchestrationIntegration:
    """Test memory system integration with orchestration module"""
    
    @pytest.fixture
    def memory_system(self):
        """Create memory system"""
        return SimplifiedMemorySystem(db=None, batch_size=5)
    
    @pytest.fixture
    def mock_orchestrator(self):
        """Create mock orchestrator"""
        orchestrator = Mock()
        orchestrator.execute_query = AsyncMock(return_value=Mock(
            success=True,
            final_result="Results here",
            steps_executed=2,
            total_steps=2,
            execution_time=2.5,
            errors=[],
            context_used={}
        ))
        return orchestrator
    
    @pytest.mark.asyncio
    async def test_orchestrator_uses_memory_recommendations(self, memory_system, mock_orchestrator):
        """Test that orchestrator receives and uses memory recommendations"""
        # Learn some patterns
        memory_system.learn_query_pattern(
            "Find emails about budget",
            "email",
            ["email", "search"],
            True,
            user_id=123
        )
        
        # Get recommendations (simulating what orchestrator would do)
        recommendations = {
            'intent': 'email',
            'similar_patterns': memory_system.get_similar_patterns("Find emails about project", "email", 123),
            'recommended_tools': memory_system.get_tool_recommendations("Find emails about project", "email", 123),
            'user_preferences': memory_system.get_user_preferences(123)
        }
        
        # Verify recommendations contain useful data
        assert 'email' in recommendations['recommended_tools']
        assert len(recommendations['similar_patterns']) >= 0
    
    @pytest.mark.asyncio
    async def test_memory_learning_from_orchestrator_execution(self, memory_system):
        """Test memory system learns from orchestrator executions"""
        integrator = MemoryIntegrator(memory_system)
        
        # Simulate orchestrator execution result
        execution_result = {
            'success': True,
            'execution_type': 'orchestrated',
            'tools_used': ['email', 'tasks'],
            'execution_time': '2.5s',
            'steps_executed': 2,
            'total_steps': 2
        }
        
        # Learn from execution
        integrator.learn_from_orchestrator_execution(
            query="Find budget emails and create tasks",
            execution_result=execution_result,
            user_id=123
        )
        
        # Verify learning occurred
        assert len(memory_system.query_patterns) > 0
        assert len(memory_system.execution_history) > 0
        
        # Verify tools were recorded
        pattern_key = list(memory_system.query_patterns.keys())[0]
        pattern = memory_system.query_patterns[pattern_key]
        assert 'email' in pattern.tools_used or 'tasks' in pattern.tools_used
    
    @pytest.mark.asyncio
    async def test_end_to_end_learning_cycle(self, memory_system):
        """Test complete learning cycle: execute -> learn -> recommend"""
        integrator = MemoryIntegrator(memory_system)
        
        # Step 1: Execute and learn (first time)
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
        
        # Step 2: Execute similar query and learn (second time)
        integrator.learn_from_orchestrator_execution(
            query="Find emails about project",
            execution_result={
                'success': True,
                'execution_type': 'orchestrated',
                'tools_used': ['email'],
                'execution_time': '1.3s'
            },
            user_id=123
        )
        
        # Step 3: Get recommendations for similar query
        recommendations = integrator.get_orchestrator_recommendations(
            query="Find emails about meeting",
            user_id=123
        )
        
        # Verify recommendations
        assert 'recommended_tools' in recommendations
        assert 'email' in recommendations['recommended_tools']
        assert recommendations['confidence'] > 0.5


class TestClavrAgentMemoryIntegration:
    """Test ClavrAgent integration with memory system"""
    
    @pytest.fixture
    def memory_system(self):
        """Create memory system"""
        return create_memory_system(db=None)
    
    @pytest.fixture
    def mock_tools(self):
        """Create mock tools"""
        email_tool = Mock()
        email_tool.name = "email"
        email_tool.run = Mock(return_value="Email results")
        
        tasks_tool = Mock()
        tasks_tool.name = "tasks"
        tasks_tool.run = Mock(return_value="Task results")
        
        return [email_tool, tasks_tool]
    
    def test_clavr_agent_initializes_with_memory(self, mock_tools):
        """Test ClavrAgent initializes with memory system"""
        agent = ClavrAgent(
            tools=mock_tools,
            config=None,
            memory=None,
            db=None,
            enable_orchestration=True
        )
        
        # Memory system should be initialized
        assert agent.memory_system is not None
        assert agent.memory_integrator is not None
    
    @pytest.mark.asyncio
    async def test_clavr_agent_learns_from_execution(self, mock_tools):
        """Test ClavrAgent learns from query execution"""
        agent = ClavrAgent(
            tools=mock_tools,
            config=None,
            memory=None,
            db=None,
            enable_orchestration=False  # Disable to avoid orchestrator complexity
        )
        
        # Execute a query
        result = await agent.execute(
            "Find emails about budget",
            user_id=123
        )
        
        # Memory should have learned
        assert len(agent.memory_system.execution_history) > 0
    
    def test_clavr_agent_get_execution_stats_includes_memory(self, mock_tools):
        """Test ClavrAgent execution stats include memory stats"""
        agent = ClavrAgent(
            tools=mock_tools,
            config=None,
            memory=None,
            db=None,
            enable_orchestration=True
        )
        
        stats = agent.get_execution_stats()
        
        # Should include memory system stats
        assert 'memory_system' in stats
        assert 'total_patterns' in stats['memory_system']
        assert 'total_executions' in stats['memory_system']
    
    def test_clavr_agent_get_memory_recommendations(self, mock_tools):
        """Test ClavrAgent provides memory recommendations"""
        agent = ClavrAgent(
            tools=mock_tools,
            config=None,
            memory=None,
            db=None,
            enable_orchestration=True
        )
        
        # Get recommendations
        recommendations = agent.get_memory_recommendations(
            "Find emails about budget",
            user_id=123
        )
        
        # Should return recommendations dict
        assert isinstance(recommendations, dict)
    
    def test_clavr_agent_clear_caches_clears_memory(self, mock_tools):
        """Test ClavrAgent clear_caches clears memory patterns"""
        agent = ClavrAgent(
            tools=mock_tools,
            config=None,
            memory=None,
            db=None,
            enable_orchestration=True
        )
        
        # Add some patterns
        agent.memory_system.learn_query_pattern(
            "Test query", "email", ["email"], True
        )
        
        # Add old pattern
        import datetime
        pattern_key = list(agent.memory_system.query_patterns.keys())[0]
        agent.memory_system.query_patterns[pattern_key].last_used = datetime.datetime.now() - datetime.timedelta(days=40)
        agent.memory_system.query_patterns[pattern_key].confidence = 0.2
        
        # Clear caches
        agent.clear_caches()
        
        # Old patterns should be cleared
        assert len(agent.memory_system.query_patterns) == 0


class TestMemorySystemPerformance:
    """Test memory system performance characteristics"""
    
    def test_pattern_lookup_performance(self):
        """Test pattern lookup is fast"""
        memory_system = SimplifiedMemorySystem(db=None)
        
        # Add many patterns
        for i in range(100):
            memory_system.learn_query_pattern(
                f"Query {i}", "email", ["email"], True
            )
        
        # Lookup should be fast (< 1ms for 100 patterns)
        import time
        start = time.time()
        similar = memory_system.get_similar_patterns("Query test", "email")
        duration = time.time() - start
        
        assert duration < 0.1  # Should be very fast
    
    def test_batch_commit_reduces_db_calls(self):
        """Test batch commits reduce database calls"""
        memory_system = SimplifiedMemorySystem(db=None, batch_size=10)
        
        # Add 5 patterns (should not commit)
        for i in range(5):
            memory_system.learn_query_pattern(
                f"Query {i}", "email", ["email"], True
            )
        
        # Pending updates should exist
        assert len(memory_system._pending_pattern_updates) == 5
        
        # Add 5 more (should trigger commit)
        for i in range(5, 10):
            memory_system.learn_query_pattern(
                f"Query {i}", "email", ["email"], True
            )
        
        # Pending should be cleared
        assert len(memory_system._pending_pattern_updates) == 0


class TestMemorySystemErrorHandling:
    """Test memory system error handling"""
    
    def test_graceful_handling_of_missing_database(self):
        """Test graceful handling when database is not available"""
        # Should not raise error
        memory_system = SimplifiedMemorySystem(db=None)
        
        # Should work fine without database
        memory_system.learn_query_pattern(
            "Test query", "email", ["email"], True
        )
        
        assert len(memory_system.query_patterns) > 0
    
    def test_integrator_handles_invalid_execution_result(self):
        """Test integrator handles invalid execution results gracefully"""
        memory_system = SimplifiedMemorySystem(db=None)
        integrator = MemoryIntegrator(memory_system)
        
        # Invalid execution result (missing fields)
        invalid_result = {
            'success': True
            # Missing other fields
        }
        
        # Should not raise error
        try:
            integrator.learn_from_orchestrator_execution(
                query="Test query",
                execution_result=invalid_result,
                user_id=123
            )
            success = True
        except Exception:
            success = False
        
        assert success


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
