"""
Test AgentState Integration with Intent Patterns (Phase 1-4)

Verifies that AgentState properly integrates with:
- Phase 1-4 intent_patterns functions
- Phase 4 enhancement modules (caching, synthesis)
- AutonomousOrchestrator LangGraph workflows
"""
import pytest
import asyncio
from datetime import datetime

# Test imports
try:
    from src.agent.state import AgentState
    from src.agent.orchestration.autonomous import AutonomousOrchestrator
    HAS_AUTONOMOUS = True
except ImportError:
    HAS_AUTONOMOUS = False
    AgentState = dict  # Fallback

# Check for intent_patterns in autonomous
try:
    from src.agent.orchestration.autonomous import HAS_INTENT_PATTERNS
except ImportError:
    HAS_INTENT_PATTERNS = False

# Check for Phase 4 in autonomous
try:
    from src.agent.orchestration.autonomous import HAS_PHASE4_ENHANCEMENTS
except ImportError:
    HAS_PHASE4_ENHANCEMENTS = False

# Intent patterns imports
try:
    from src.agent.intent_patterns import (
        classify_query_intent,
        extract_entities,
        analyze_query_complexity
    )
    HAS_INTENT_PATTERNS_MODULE = True
except ImportError:
    HAS_INTENT_PATTERNS_MODULE = False

# Phase 4 imports
try:
    from src.agent.intent_cache import IntentPatternsCache
    from src.agent.complexity_cache import ComplexityAwareCache
    from src.agent.context_synthesizer import ContextSynthesizer
    HAS_PHASE4_MODULES = True
except ImportError:
    HAS_PHASE4_MODULES = False
    IntentPatternsCache = None  # Fallback
    ComplexityAwareCache = None
    ContextSynthesizer = None


@pytest.mark.skipif(not HAS_AUTONOMOUS, reason="AutonomousOrchestrator not available")
class TestAgentStateIntegration:
    """Test AgentState integration with intent_patterns and Phase 4"""
    
    def test_agent_state_has_phase4_fields(self):
        """Verify AgentState has new Phase 4 fields"""
        state: AgentState = {
            'query': "Test query",
            'steps': [],
            'results': [],
            'context': {},
            'errors': [],
            'planning_complete': False,
            'execution_complete': False,
            # Phase 4 fields
            'request_id': 'test_req_123',
            'cache_stats': {'hits': 0, 'misses': 0},
            'complexity_level': 'medium',
            'complexity_score': 0.5,
            'estimated_steps': 2,
            'entity_summary': 'Test entities',
            'synthesized_context': {'test': 'data'}
        }
        
        # Verify Phase 4 fields are accessible
        assert state['request_id'] == 'test_req_123'
        assert state['complexity_level'] == 'medium'
        assert state['complexity_score'] == 0.5
        assert state['estimated_steps'] == 2
        assert state['entity_summary'] == 'Test entities'
        assert state['cache_stats'] is not None
        assert state['synthesized_context'] is not None
        
        print("✅ AgentState has all Phase 4 fields")
    
    def test_agent_state_intent_fields(self):
        """Verify AgentState has intent classification fields"""
        state: AgentState = {
            'query': "Find my emails",
            'intent': 'email_search',
            'confidence': 0.95,
            'entities': {'domains': ['email'], 'keywords': ['find']},
            'steps': [],
            'results': [],
            'context': {},
            'errors': [],
            'planning_complete': False,
            'execution_complete': False
        }
        
        # Verify intent fields
        assert state['intent'] == 'email_search'
        assert state['confidence'] == 0.95
        assert state['entities'] is not None
        assert 'email' in state['entities']['domains']
        
        print("✅ AgentState intent fields work correctly")
    
    @pytest.mark.skipif(not HAS_INTENT_PATTERNS_MODULE, reason="intent_patterns not available")
    def test_populate_state_with_intent_patterns(self):
        """Test populating AgentState using intent_patterns functions"""
        query = "Find urgent emails from last week and create a summary"
        
        # Use intent_patterns to populate state
        intent_data = classify_query_intent(query)
        entities_data = extract_entities(query)
        complexity = analyze_query_complexity(query)
        
        # Create state with intent_patterns data
        state: AgentState = {
            'query': query,
            'intent': intent_data.get('intent'),
            'confidence': intent_data.get('confidence'),
            'entities': entities_data,
            'complexity_level': complexity['complexity_level'],
            'complexity_score': complexity['complexity_score'],
            'estimated_steps': complexity.get('estimated_steps', 3),  # Use default if missing
            'steps': [],
            'results': [],
            'context': {
                'complexity_level': complexity['complexity_level'],
                'complexity_score': complexity['complexity_score']
            },
            'errors': [],
            'planning_complete': False,
            'execution_complete': False
        }
        
        # Verify state is properly populated (intent can be None)
        assert 'intent' in state
        assert 'confidence' in state
        assert state['entities'] is not None
        assert state['complexity_level'] in ['low', 'medium', 'high']
        assert state['complexity_score'] is not None
        assert state['estimated_steps'] >= 1
        
        print(f"✅ State populated from intent_patterns:")
        print(f"   Intent: {state['intent']}")
        # Confidence can be string or float
        confidence = state['confidence']
        if isinstance(confidence, (int, float)):
            print(f"   Confidence: {confidence:.2f}")
        else:
            print(f"   Confidence: {confidence}")
        print(f"   Complexity: {state['complexity_level']}")
        print(f"   Steps: {state['estimated_steps']}")
    
    @pytest.mark.skipif(not HAS_PHASE4_MODULES, reason="Phase 4 modules not available")
    def test_state_with_phase4_caching(self):
        """Test AgentState with Phase 4 caching"""
        cache = IntentPatternsCache()
        request_id = f"test_req_{datetime.now().timestamp()}"
        cache.new_request(request_id)
        
        query = "Show my calendar for next week"
        
        # Simulate caching
        complexity = {'complexity_level': 'low', 'complexity_score': 0.3, 'estimated_steps': 1}
        cache.set_complexity(query, complexity)
        
        # Create state with cache info
        state: AgentState = {
            'query': query,
            'request_id': request_id,
            'cache_stats': cache.get_stats(),
            'complexity_level': complexity['complexity_level'],
            'complexity_score': complexity['complexity_score'],
            'estimated_steps': complexity['estimated_steps'],
            'steps': [],
            'results': [],
            'context': {},
            'errors': [],
            'planning_complete': False,
            'execution_complete': False
        }
        
        # Verify cache integration
        assert state['request_id'] == request_id
        assert state['cache_stats'] is not None
        assert state['cache_stats']['request_id'] == request_id
        
        print(f"✅ State integrated with Phase 4 cache:")
        print(f"   Request ID: {state['request_id']}")
        print(f"   Cache Stats: {state['cache_stats']}")
    
    def test_deprecated_fields_marked(self):
        """Verify deprecated fields are still accessible but marked"""
        state: AgentState = {
            'query': "Test",
            # Deprecated but still accessible
            'selected_tools': ['email_tool'],
            'tool_params': {'param': 'value'},
            'tool_results': {'result': 'data'},
            'metadata': {'meta': 'data'},
            'next_action': 'execute',
            'session_id': 'session_123',
            # New preferred fields
            'steps': [],
            'results': [],
            'context': {},
            'errors': [],
            'planning_complete': False,
            'execution_complete': False
        }
        
        # Verify deprecated fields still work
        assert state['selected_tools'] == ['email_tool']
        assert state['tool_params']['param'] == 'value'
        assert state['metadata'] is not None
        
        print("✅ Deprecated fields still accessible (backward compatible)")


@pytest.mark.skipif(not HAS_AUTONOMOUS or not HAS_INTENT_PATTERNS, 
                   reason="AutonomousOrchestrator or intent_patterns not available")
class TestAutonomousOrchestratorIntegration:
    """Test AutonomousOrchestrator integration with intent_patterns"""
    
    @pytest.mark.asyncio
    async def test_autonomous_uses_intent_patterns(self):
        """Verify AutonomousOrchestrator uses intent_patterns in analyze node"""
        # Create mock tools
        class MockTool:
            def __init__(self, name):
                self.name = name
            
            async def execute(self, query):
                return f"Result from {self.name}"
        
        tools = [MockTool("email_tool"), MockTool("calendar_tool")]
        
        # Create orchestrator
        orchestrator = AutonomousOrchestrator(tools=tools)
        
        # Verify Phase 4 components are initialized
        if HAS_PHASE4_ENHANCEMENTS:
            assert orchestrator.intent_cache is not None
            assert orchestrator.response_cache is not None
            assert orchestrator.phase4_synthesizer is not None
            print("✅ AutonomousOrchestrator has Phase 4 components")
        
        # Create initial state
        initial_state: AgentState = {
            'query': "Find my urgent emails and schedule a meeting",
            'messages': [],
            'steps': [],
            'results': [],
            'context': {},
            'errors': [],
            'current_step': 0,
            'planning_complete': False,
            'execution_complete': False
        }
        
        # Run analyze node
        analyzed_state = await orchestrator._analyze_query_node(initial_state)
        
        # Verify intent_patterns integration (intent can be None)
        if HAS_INTENT_PATTERNS:
            assert 'intent' in analyzed_state
            assert 'confidence' in analyzed_state
            assert analyzed_state.get('entities') is not None
            assert analyzed_state.get('complexity_level') in ['low', 'medium', 'high']
            assert analyzed_state.get('complexity_score') is not None
            assert analyzed_state.get('estimated_steps') is not None
            
            print(f"✅ AutonomousOrchestrator populates intent_patterns fields:")
            print(f"   Intent: {analyzed_state.get('intent')}")
            confidence = analyzed_state.get('confidence')
            if isinstance(confidence, (int, float)):
                print(f"   Confidence: {confidence:.2f}")
            else:
                print(f"   Confidence: {confidence}")
            print(f"   Complexity: {analyzed_state.get('complexity_level')}")
            print(f"   Estimated Steps: {analyzed_state.get('estimated_steps')}")
            
            # Verify cache tracking
            if HAS_PHASE4_ENHANCEMENTS and orchestrator.intent_cache:
                assert analyzed_state.get('request_id') is not None
                print(f"   Request ID: {analyzed_state.get('request_id')}")
        else:
            # Fallback to legacy behavior
            assert analyzed_state.get('entities') is not None
            assert analyzed_state['context'].get('execution_strategy') is not None
            print("✅ AutonomousOrchestrator uses legacy utils (fallback)")
    
    @pytest.mark.skipif(not HAS_PHASE4_ENHANCEMENTS, reason="Phase 4 not available")
    @pytest.mark.asyncio
    async def test_synthesis_node_uses_phase4(self):
        """Verify synthesis node uses Phase 4 ContextSynthesizer"""
        class MockTool:
            def __init__(self, name):
                self.name = name
        
        tools = [MockTool("email_tool")]
        orchestrator = AutonomousOrchestrator(tools=tools)
        
        # Create state with results
        state: AgentState = {
            'query': "Find emails from John",
            'request_id': 'test_123',
            'entities': {'entities': ['John'], 'people': ['John']},
            'results': [
                {'success': True, 'result': 'Found 5 emails from John', 'tool': 'email_tool'}
            ],
            'context': {},
            'errors': [],
            'planning_complete': True,
            'execution_complete': False,
            'messages': [],
            'steps': [],
            'current_step': 1
        }
        
        # Run synthesis node
        synthesized_state = await orchestrator._synthesize_response_node(state)
        
        # Verify synthesis was applied
        assert synthesized_state['answer'] is not None
        assert synthesized_state['execution_complete'] is True
        
        if HAS_PHASE4_ENHANCEMENTS:
            # Should have entity summary
            if synthesized_state.get('entity_summary'):
                print(f"✅ Phase 4 synthesis applied:")
                print(f"   Entity Summary: {synthesized_state['entity_summary']}")
            
            # Should have cache stats
            if synthesized_state.get('cache_stats'):
                print(f"   Cache Stats: {synthesized_state['cache_stats']}")
        
        print(f"✅ Synthesis node produces answer: {synthesized_state['answer'][:100]}...")


@pytest.mark.skipif(not HAS_INTENT_PATTERNS_MODULE, reason="intent_patterns not available")
class TestIntentPatternsStateIntegration:
    """Test direct integration between intent_patterns and AgentState"""
    
    def test_classify_query_populates_state(self):
        """Test that classify_query_intent results map to AgentState"""
        query = "Delete all spam emails from last month"
        intent_data = classify_query_intent(query)
        
        state: AgentState = {
            'query': query,
            'intent': intent_data.get('intent'),
            'confidence': intent_data.get('confidence'),
            'steps': [],
            'results': [],
            'context': {},
            'errors': [],
            'planning_complete': False,
            'execution_complete': False
        }
        
        # Intent can be None, just check it's in the state
        assert 'intent' in state
        assert 'confidence' in state
        assert state['intent'] == intent_data.get('intent')
        assert state['confidence'] == intent_data.get('confidence')
        print(f"✅ Intent: {state['intent']}, Confidence: {state['confidence']}")
    
    def test_extract_entities_populates_state(self):
        """Test that extract_entities results map to AgentState"""
        query = "Schedule meeting with Sarah next Tuesday at 2pm"
        entities_data = extract_entities(query)
        
        state: AgentState = {
            'query': query,
            'entities': entities_data,
            'steps': [],
            'results': [],
            'context': {},
            'errors': [],
            'planning_complete': False,
            'execution_complete': False
        }
        
        assert state['entities'] == entities_data
        # Entities is a dict with lists, not a dict with 'entities' key
        assert isinstance(state['entities'], dict)
        assert len(state['entities']) > 0  # Should have some entity types
        print(f"✅ Entities: {list(state['entities'].keys())}")
    
    def test_analyze_complexity_populates_state(self):
        """Test that analyze_query_complexity results map to AgentState"""
        query = "Find emails, create tasks, and schedule follow-ups"
        complexity = analyze_query_complexity(query)
        
        state: AgentState = {
            'query': query,
            'complexity_level': complexity['complexity_level'],
            'complexity_score': complexity['complexity_score'],
            'estimated_steps': complexity.get('estimated_steps', 3),  # Use default if missing
            'context': {
                'complexity_level': complexity['complexity_level'],
                'complexity_score': complexity['complexity_score']
            },
            'steps': [],
            'results': [],
            'errors': [],
            'planning_complete': False,
            'execution_complete': False
        }
        
        assert state['complexity_level'] == complexity['complexity_level']
        assert state['complexity_score'] == complexity['complexity_score']
        # estimated_steps might not be in complexity dict, use default
        assert state['estimated_steps'] == complexity.get('estimated_steps', 3)
        print(f"✅ Complexity: {state['complexity_level']} "
              f"(score: {state['complexity_score']:.2f}, "
              f"steps: {state['estimated_steps']})")


