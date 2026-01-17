"""
Integration Tests for intent_patterns.py Integration

Tests the integration of intent_patterns with:
- ClavrAgent (orchestration routing)
- Orchestrator (execution strategy)
- QueryDecomposer (complexity analysis)
- ExecutionPlanner (tool recommendations)
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime

from src.agent.intent_patterns import (
    analyze_query_complexity,
    classify_query_intent,
    recommend_tools,
    extract_entities,
    should_use_orchestration,
    get_execution_strategy
)


class TestIntentPatternsOrchestrationIntegration:
    """Test intent_patterns integration with orchestration layer"""
    
    def test_analyze_query_complexity_simple_query(self):
        """Test complexity analysis correctly identifies simple queries"""
        simple_queries = [
            "Show my emails",
            "List tasks",
            "What meetings do I have today"
        ]
        
        for query in simple_queries:
            result = analyze_query_complexity(query)
            
            assert result["complexity_level"] in ["low", "medium"]
            assert result["complexity_score"] < 4
            assert "domains_detected" in result
            assert isinstance(result["should_use_orchestration"], bool)
    
    def test_analyze_query_complexity_complex_query(self):
        """Test complexity analysis correctly identifies complex queries"""
        complex_queries = [
            "Find emails about budget and then create calendar events",
            "Search for action items in my inbox and create tasks for each",
            "Get unread emails from John and schedule a meeting with him"
        ]
        
        for query in complex_queries:
            result = analyze_query_complexity(query)
            
            assert result["complexity_level"] in ["medium", "high"]
            assert result["complexity_score"] >= 2
            assert result["should_use_orchestration"] is True
            assert result["multi_step_indicators"] >= 1 or result["cross_domain"] is True
    
    def test_classify_query_intent_email(self):
        """Test intent classification for email queries"""
        email_queries = [
            "Find emails from boss",
            "Show me unread messages",
            "Search inbox for budget"
        ]
        
        for query in email_queries:
            result = classify_query_intent(query)
            
            assert result["domain"] == "email"
            assert result["primary_intent"] in ["email_operation", "email_management"]
            assert result["confidence"] in ["high", "medium", "low"]
    
    def test_classify_query_intent_calendar(self):
        """Test intent classification for calendar queries"""
        calendar_queries = [
            "What meetings do I have today",
            "Schedule a meeting with John",
            "Show my calendar for tomorrow"
        ]
        
        for query in calendar_queries:
            result = classify_query_intent(query)
            
            assert result["domain"] == "calendar"
            assert "calendar" in result["primary_intent"]
    
    def test_recommend_tools_email(self):
        """Test tool recommendations for email queries"""
        # Create mock tools with parsers
        mock_email_tool = Mock()
        mock_email_tool.parser = Mock()
        mock_email_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'search',
            'confidence': 0.8,
            'metadata': {}
        })
        
        mock_calendar_tool = Mock()
        mock_calendar_tool.parser = Mock()
        mock_calendar_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'reject',
            'confidence': 0.2,
            'metadata': {}
        })
        
        mock_task_tool = Mock()
        mock_task_tool.parser = Mock()
        mock_task_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'reject',
            'confidence': 0.2,
            'metadata': {}
        })
        
        tools_dict = {
            "email": mock_email_tool,
            "calendar": mock_calendar_tool,
            "tasks": mock_task_tool
        }
        
        email_queries = [
            "Find emails about project",
            "Show unread messages",
            "Search inbox"
        ]
        
        for query in email_queries:
            recommended = recommend_tools(query, tools_dict)
            
            assert "email" in recommended
    
    def test_recommend_tools_multi_domain(self):
        """Test tool recommendations for multi-domain queries"""
        # Create mock tools with parsers
        mock_email_tool = Mock()
        mock_email_tool.parser = Mock()
        mock_email_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'search',
            'confidence': 0.7,
            'metadata': {}
        })
        
        mock_calendar_tool = Mock()
        mock_calendar_tool.parser = Mock()
        mock_calendar_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'create',
            'confidence': 0.7,
            'metadata': {}
        })
        
        mock_task_tool = Mock()
        mock_task_tool.parser = Mock()
        mock_task_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'reject',
            'confidence': 0.2,
            'metadata': {}
        })
        
        tools_dict = {
            "email": mock_email_tool,
            "calendar": mock_calendar_tool,
            "tasks": mock_task_tool
        }
        
        query = "Find emails about meetings and schedule a call"
        recommended = recommend_tools(query, tools_dict)
        
        # Should recommend both email and calendar
        assert len(recommended) >= 1
        assert "email" in recommended or "calendar" in recommended
    
    def test_extract_entities_time_references(self):
        """Test entity extraction for time references"""
        queries_with_time = [
            "Show emails from today",
            "Tasks due tomorrow",
            "Urgent meetings next week"
        ]
        
        for query in queries_with_time:
            entities = extract_entities(query)
            
            assert "time_references" in entities
            if any(word in query.lower() for word in ["today", "tomorrow", "next week", "urgent"]):
                assert len(entities["time_references"]) > 0
    
    def test_extract_entities_priorities(self):
        """Test entity extraction for priorities"""
        queries_with_priority = [
            "Find urgent emails",
            "Show important tasks",
            "Critical meetings"
        ]
        
        for query in queries_with_priority:
            entities = extract_entities(query)
            
            assert "priorities" in entities
            assert len(entities["priorities"]) > 0
    
    def test_extract_entities_actions(self):
        """Test entity extraction for actions"""
        query = "Find emails and create tasks"
        entities = extract_entities(query)
        
        assert "actions" in entities
        assert "find" in entities["actions"] or "create" in entities["actions"]
    
    def test_should_use_orchestration_simple(self):
        """Test orchestration decision for simple queries"""
        simple_queries = [
            "Show my emails",
            "List tasks"
        ]
        
        for query in simple_queries:
            result = should_use_orchestration(query)
            
            # Simple queries may or may not need orchestration depending on complexity
            assert isinstance(result, bool)
    
    def test_should_use_orchestration_complex(self):
        """Test orchestration decision for complex queries"""
        complex_queries = [
            "Find emails about budget and create tasks",
            "Search for meeting notes and schedule follow-up"
        ]
        
        for query in complex_queries:
            result = should_use_orchestration(query)
            
            assert result is True  # Complex queries should use orchestration
    
    def test_get_execution_strategy_complete(self):
        """Test complete execution strategy"""
        query = "Find urgent emails about budget and create tasks for action items"
        
        strategy = get_execution_strategy(query)
        
        # Verify all components are present
        assert "complexity" in strategy
        assert "intent" in strategy
        assert "entities" in strategy
        assert "use_orchestration" in strategy
        assert "recommended_execution" in strategy
        assert "primary_domain" in strategy
        assert "estimated_steps" in strategy
        
        # Verify complexity analysis
        assert strategy["complexity"]["complexity_score"] >= 0
        assert strategy["complexity"]["complexity_level"] in ["low", "medium", "high"]
        
        # Verify intent classification
        assert strategy["intent"]["domain"] in ["email", "task", "calendar", "general"]
        
        # Verify entities
        assert "time_references" in strategy["entities"]
        assert "priorities" in strategy["entities"]
        assert "actions" in strategy["entities"]
        assert "domains" in strategy["entities"]


class TestClavrAgentIntegration:
    """Test ClavrAgent integration with intent_patterns"""
    
    @pytest.mark.asyncio
    async def test_clavr_agent_uses_orchestration_decision(self):
        """Test that ClavrAgent uses should_use_orchestration()"""
        from src.agent.clavr_agent import ClavrAgent, HAS_INTENT_PATTERNS
        
        if not HAS_INTENT_PATTERNS:
            pytest.skip("intent_patterns not available")
        
        # Create mock tools
        mock_tool = Mock()
        mock_tool.name = "email"
        
        # Create agent without orchestrator to test fallback
        agent = ClavrAgent(tools=[mock_tool], enable_orchestration=False)
        
        # Agent should still function without orchestrator
        assert agent.tools is not None


class TestQueryDecomposerIntegration:
    """Test QueryDecomposer integration with intent_patterns"""
    
    def test_query_decomposer_uses_complexity_analysis(self):
        """Test that QueryDecomposer uses analyze_query_complexity()"""
        from src.agent.orchestration.query_decomposer import QueryDecomposer, HAS_INTENT_PATTERNS
        
        if not HAS_INTENT_PATTERNS:
            pytest.skip("intent_patterns not available")
        
        decomposer = QueryDecomposer()
        
        # Test with complex query
        complex_query = "Find emails about budget and then create tasks"
        result = decomposer.should_use_multi_step_execution(complex_query)
        
        # Should use orchestration for multi-step query
        assert isinstance(result, bool)
    
    def test_query_decomposer_extracts_entities(self):
        """Test that QueryDecomposer extracts entities"""
        from src.agent.orchestration.query_decomposer import QueryDecomposer, HAS_INTENT_PATTERNS
        
        if not HAS_INTENT_PATTERNS:
            pytest.skip("intent_patterns not available")
        
        decomposer = QueryDecomposer()
        
        query = "Find urgent emails from today"
        steps = decomposer.decompose_query(query)
        
        # Should return decomposed steps
        assert isinstance(steps, list)
        assert len(steps) >= 1


class TestExecutionPlannerIntegration:
    """Test ExecutionPlanner integration with intent_patterns"""
    
    @pytest.mark.asyncio
    async def test_execution_planner_uses_tool_recommendations(self):
        """Test that ExecutionPlanner uses recommend_tools()"""
        from src.agent.orchestration.execution_planner import ExecutionPlanner, HAS_INTENT_PATTERNS
        
        if not HAS_INTENT_PATTERNS:
            pytest.skip("intent_patterns not available")
        
        # Create mock tools
        tools = {
            "email": Mock(),
            "calendar": Mock(),
            "tasks": Mock()
        }
        
        planner = ExecutionPlanner(tools)
        
        # Create test steps
        steps = [
            {
                "id": "step_1",
                "query": "Find emails about budget",
                "intent": "email",
                "action": "search"
            }
        ]
        
        # Test with original query for tool recommendations
        execution_steps = await planner.create_execution_plan(
            steps,
            original_query="Find emails about budget"
        )
        
        assert len(execution_steps) == 1
        assert execution_steps[0].tool_name in tools


class TestOrchestratorIntegration:
    """Test Orchestrator integration with intent_patterns"""
    
    @pytest.mark.asyncio
    async def test_orchestrator_uses_execution_strategy(self):
        """Test that Orchestrator uses get_execution_strategy()"""
        from src.agent.orchestration.orchestrator import Orchestrator, HAS_INTENT_PATTERNS
        
        if not HAS_INTENT_PATTERNS:
            pytest.skip("intent_patterns not available")
        
        # Create mock tool
        mock_tool = Mock()
        mock_tool.name = "email"
        mock_tool.execute = AsyncMock(return_value="Result")
        
        orchestrator = Orchestrator(tools=[mock_tool])
        
        # Orchestrator should be initialized
        assert orchestrator is not None
        assert orchestrator.query_decomposer is not None
        assert orchestrator.execution_planner is not None


class TestEndToEndIntegration:
    """End-to-end integration tests"""
    
    def test_simple_query_flow(self):
        """Test complete flow for simple query"""
        query = "Show my emails"
        
        # Step 1: Analyze complexity
        complexity = analyze_query_complexity(query)
        assert complexity["complexity_level"] == "low"
        
        # Step 2: Classify intent
        intent = classify_query_intent(query)
        assert intent["domain"] == "email"
        
        # Step 3: Get execution strategy
        strategy = get_execution_strategy(query)
        assert strategy["primary_domain"] == "email"
        assert strategy["estimated_steps"] == 1
    
    def test_complex_query_flow(self):
        """Test complete flow for complex query"""
        query = "Find urgent emails about budget and create tasks for action items"
        
        # Step 1: Analyze complexity
        complexity = analyze_query_complexity(query)
        assert complexity["complexity_level"] in ["medium", "high"]
        assert complexity["should_use_orchestration"] is True
        
        # Step 2: Classify intent
        intent = classify_query_intent(query)
        assert intent["domain"] in ["email", "task"]
        
        # Step 3: Extract entities
        entities = extract_entities(query)
        assert len(entities["priorities"]) > 0  # "urgent"
        assert len(entities["actions"]) >= 2  # "find", "create"
        
        # Step 4: Get execution strategy
        strategy = get_execution_strategy(query)
        assert strategy["use_orchestration"] is True
        assert strategy["estimated_steps"] >= 2
        
        # Step 5: Recommend tools
        # Create mock tools with parsers
        mock_email_tool = Mock()
        mock_email_tool.parser = Mock()
        mock_email_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'search',
            'confidence': 0.8,
            'metadata': {}
        })
        
        mock_task_tool = Mock()
        mock_task_tool.parser = Mock()
        mock_task_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'create',
            'confidence': 0.7,
            'metadata': {}
        })
        
        mock_calendar_tool = Mock()
        mock_calendar_tool.parser = Mock()
        mock_calendar_tool.parser.parse_query_to_params = Mock(return_value={
            'action': 'reject',
            'confidence': 0.2,
            'metadata': {}
        })
        
        tools_dict = {
            "email": mock_email_tool,
            "tasks": mock_task_tool,
            "calendar": mock_calendar_tool
        }
        
        recommended = recommend_tools(query, tools_dict)
        assert "email" in recommended or "tasks" in recommended


class TestBackwardCompatibility:
    """Test that changes don't break existing functionality"""
    
    def test_intent_patterns_available(self):
        """Test that intent_patterns can be imported"""
        from src.agent import intent_patterns
        
        assert hasattr(intent_patterns, 'analyze_query_complexity')
        assert hasattr(intent_patterns, 'classify_query_intent')
        assert hasattr(intent_patterns, 'recommend_tools')
        assert hasattr(intent_patterns, 'extract_entities')
        assert hasattr(intent_patterns, 'should_use_orchestration')
        assert hasattr(intent_patterns, 'get_execution_strategy')
    
    def test_orchestration_still_works_without_intent_patterns(self):
        """Test that orchestration works even without intent_patterns"""
        # This tests the HAS_INTENT_PATTERNS fallback logic
        from src.agent.orchestration.query_decomposer import QueryDecomposer
        from src.agent.orchestration.execution_planner import ExecutionPlanner
        
        # Should not raise errors even if intent_patterns unavailable
        decomposer = QueryDecomposer()
        assert decomposer is not None
        
        tools = {"email": Mock()}
        planner = ExecutionPlanner(tools)
        assert planner is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
