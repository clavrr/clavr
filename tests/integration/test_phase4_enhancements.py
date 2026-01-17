"""
Phase 4 Integration Test
Tests the enhancement modules (intent_cache, complexity_cache, response_formatter)
and their integration with ClavrAgent.
"""
import pytest
import asyncio
from datetime import datetime
from src.agent.intent_cache import IntentPatternsCache
from src.agent.complexity_cache import ComplexityAwareCache
from src.agent.response_formatter import ResponseFormatter


class TestIntentPatternsCache:
    """Test request-level caching of intent_patterns calls"""
    
    def test_new_request_clears_cache(self):
        """Test that new request clears the cache"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        # Set some data
        cache.set_complexity("test query", {"level": "low"})
        assert cache.get_complexity("test query") is not None
        
        # New request should clear
        cache.new_request("req_2")
        assert cache.get_complexity("test query") is None
    
    def test_complexity_caching(self):
        """Test caching of complexity analysis"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        query = "Schedule a meeting tomorrow"
        complexity = {"complexity_level": "medium", "estimated_steps": 3}
        
        # First call is a miss
        result = cache.get_complexity(query)
        assert result is None
        
        # Cache it
        cache.set_complexity(query, complexity)
        
        # Second call is a hit
        result = cache.get_complexity(query)
        assert result == complexity
    
    def test_entities_caching(self):
        """Test caching of entity extraction"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        query = "Email John about project Alpha"
        entities = {"entities": ["John", "project Alpha"], "types": ["person", "project"]}
        
        # Cache miss
        assert cache.get_entities(query) is None
        
        # Cache and retrieve
        cache.set_entities(query, entities)
        assert cache.get_entities(query) == entities
    
    def test_intent_caching(self):
        """Test caching of intent classification"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        query = "Show my calendar"
        intent = {"domain": "calendar", "action": "view"}
        
        cache.set_intent(query, intent)
        assert cache.get_intent(query) == intent
    
    def test_tools_caching(self):
        """Test caching of tool recommendations"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        query = "Create a task and send email"
        tools = ["task_tool", "email_tool"]
        
        cache.set_tools(query, tools)
        assert cache.get_tools(query) == tools
    
    def test_strategy_caching(self):
        """Test caching of execution strategy"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        query = "Complex multi-step query"
        strategy = {"approach": "parallel", "steps": 3}
        
        cache.set_strategy(query, strategy)
        assert cache.get_strategy(query) == strategy
    
    def test_orchestration_decision_caching(self):
        """Test caching of orchestration decisions"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        query = "Simple query"
        
        # Cache miss
        assert cache.get_orchestration_decision(query) is None
        
        # Cache decision
        cache.set_orchestration_decision(query, False)
        assert cache.get_orchestration_decision(query) is False
        
        # Different query
        complex_query = "Complex multi-step query"
        cache.set_orchestration_decision(complex_query, True)
        assert cache.get_orchestration_decision(complex_query) is True
    
    def test_cache_statistics(self):
        """Test cache hit/miss statistics"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        query = "Test query"
        
        # Initial stats
        stats = cache.get_stats()
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        
        # Miss
        cache.get_complexity(query)
        stats = cache.get_stats()
        assert stats["cache_misses"] == 1
        
        # Set and hit
        cache.set_complexity(query, {"level": "low"})
        cache.get_complexity(query)
        
        stats = cache.get_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["hit_rate_percent"] == 50.0
    
    def test_multiple_cache_types(self):
        """Test using multiple cache types in same request"""
        cache = IntentPatternsCache()
        cache.new_request("req_1")
        
        query = "Schedule meeting and send email"
        
        # Set multiple types
        cache.set_complexity(query, {"level": "medium"})
        cache.set_entities(query, {"entities": ["meeting", "email"]})
        cache.set_intent(query, {"domain": "productivity"})
        cache.set_orchestration_decision(query, True)
        
        # Retrieve all
        assert cache.get_complexity(query)["level"] == "medium"
        assert len(cache.get_entities(query)["entities"]) == 2
        assert cache.get_intent(query)["domain"] == "productivity"
        assert cache.get_orchestration_decision(query) is True
        
        # Check stats - 4 hits
        stats = cache.get_stats()
        assert stats["cache_hits"] == 4


class TestComplexityAwareCache:
    """Test complexity-aware response caching"""
    
    def test_simple_sync_caching(self):
        """Test caching with sync function"""
        cache = ComplexityAwareCache()
        call_count = 0
        
        def expensive_operation():
            nonlocal call_count
            call_count += 1
            return "result"
        
        # First call executes
        result1 = cache.get_or_execute("test query", expensive_operation, "low")
        assert result1 == "result"
        assert call_count == 1
        
        # Second call uses cache
        result2 = cache.get_or_execute("test query", expensive_operation, "low")
        assert result2 == "result"
        assert call_count == 1  # Not called again
    
    @pytest.mark.asyncio
    async def test_async_caching(self):
        """Test caching with async function"""
        cache = ComplexityAwareCache()
        call_count = 0
        
        async def expensive_async_operation():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return "async result"
        
        # First call executes
        result1 = await cache.get_or_execute_async("test query", expensive_async_operation, "low")
        assert result1 == "async result"
        assert call_count == 1
        
        # Second call uses cache
        result2 = await cache.get_or_execute_async("test query", expensive_async_operation, "low")
        assert result2 == "async result"
        assert call_count == 1  # Not called again
    
    def test_complexity_based_ttl(self):
        """Test that different complexity levels have different TTLs"""
        cache = ComplexityAwareCache()
        
        assert cache.TTL_CONFIG["low"] == 3600      # 1 hour
        assert cache.TTL_CONFIG["medium"] == 900    # 15 min
        assert cache.TTL_CONFIG["high"] == 300      # 5 min
    
    def test_high_complexity_no_cache(self):
        """Test that high complexity queries are not cached by default"""
        cache = ComplexityAwareCache(enable_high_complexity_cache=False)
        call_count = 0
        
        def expensive_operation():
            nonlocal call_count
            call_count += 1
            return "result"
        
        # First call
        cache.get_or_execute("complex query", expensive_operation, "high")
        assert call_count == 1
        
        # Second call - should execute again (no cache)
        cache.get_or_execute("complex query", expensive_operation, "high")
        assert call_count == 2
    
    def test_user_specific_caching(self):
        """Test user-specific cache keys"""
        cache = ComplexityAwareCache()
        
        def user1_result():
            return "user 1 result"
        
        def user2_result():
            return "user 2 result"
        
        # Cache for different users
        result1 = cache.get_or_execute("same query", user1_result, "low", user_id=1)
        result2 = cache.get_or_execute("same query", user2_result, "low", user_id=2)
        
        assert result1 == "user 1 result"
        assert result2 == "user 2 result"
    
    def test_cache_statistics(self):
        """Test cache statistics tracking"""
        cache = ComplexityAwareCache()
        
        cache.get_or_execute("query1", lambda: "result1", "low")
        cache.get_or_execute("query1", lambda: "result1", "low")  # Hit
        cache.get_or_execute("query2", lambda: "result2", "medium")
        
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 33.33
    
    def test_invalidation(self):
        """Test cache invalidation"""
        cache = ComplexityAwareCache()
        
        result1 = cache.get_or_execute("test", lambda: "result1", "low")
        assert result1 == "result1"
        
        # Invalidate
        cache.invalidate("test")
        
        # Should execute again
        call_count = 0
        def new_operation():
            nonlocal call_count
            call_count += 1
            return "result2"
        
        result2 = cache.get_or_execute("test", new_operation, "low")
        assert result2 == "result2"
        assert call_count == 1


class TestResponseFormatter:
    """Test entity-aware response formatting"""
    
    def test_basic_synthesis(self):
        """Test basic response formatting"""
        formatter = ResponseFormatter()
        
        result = formatter.synthesize(
            query="Show my emails",
            results={"summary": "Email list: 1. From John..."},
            entities={"entities": ["emails"], "types": ["data"]}
        )
        
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_with_entities(self):
        """Test formatting with entities"""
        formatter = ResponseFormatter()
        
        result = formatter.synthesize(
            query="Complex multi-step query",
            results={"items": ["item1", "item2"]},
            entities={"entities": ["task1", "task2"], "domains": ["email", "calendar"]}
        )
        
        assert result is not None
    
    def test_empty_entities(self):
        """Test formatting without entities"""
        formatter = ResponseFormatter()
        
        result = formatter.synthesize(
            query="Simple query",
            results={"items": ["result1"]},
            entities=None
        )
        
        assert result is not None


class TestIntegration:
    """Test integration of all Phase 4 components"""
    
    @pytest.mark.asyncio
    async def test_full_caching_flow(self):
        """Test complete caching flow with all components"""
        intent_cache = IntentPatternsCache()
        response_cache = ComplexityAwareCache()
        formatter = ResponseFormatter()
        
        # Simulate request
        query = "Schedule a meeting tomorrow at 2pm"
        request_id = f"req_{datetime.now().timestamp()}"
        intent_cache.new_request(request_id)
        
        # Simulate intent analysis (would be cached)
        intent_cache.set_complexity(query, {"complexity_level": "medium", "estimated_steps": 2})
        intent_cache.set_entities(query, {"entities": ["meeting", "tomorrow", "2pm"]})
        intent_cache.set_orchestration_decision(query, True)
        
        # Simulate execution with response cache
        execution_count = 0
        
        async def execute_query():
            nonlocal execution_count
            execution_count += 1
            await asyncio.sleep(0.01)
            return "Meeting scheduled for tomorrow at 2pm"
        
        # First execution
        result1 = await response_cache.get_or_execute_async(
            query=query,
            execute_fn=execute_query,
            complexity_level="medium"
        )
        assert execution_count == 1
        
        # Second execution - cached
        result2 = await response_cache.get_or_execute_async(
            query=query,
            execute_fn=execute_query,
            complexity_level="medium"
        )
        assert execution_count == 1  # Not executed again
        assert result1 == result2
        
        # Synthesize with context
        entities = intent_cache.get_entities(query)
        final_result = formatter.synthesize(
            query=query,
            results={"items": [result2]},
            entities=entities
        )
        
        assert final_result is not None
        
        # Check cache stats
        intent_stats = intent_cache.get_stats()
        assert intent_stats["cache_hits"] == 1  # get_entities was a hit
        
        response_stats = response_cache.get_stats()
        assert response_stats["hits"] == 1
        assert response_stats["misses"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
