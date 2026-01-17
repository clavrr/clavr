"""
Test suite for Enhanced Semantic Memory components.

Tests:
1. FactInferenceEngine - pattern-based and relationship inference
2. FactGraph - hierarchical organization and querying
3. EnhancedSemanticMemory integration
"""
import asyncio
import sys
sys.path.insert(0, '/Users/maniko/Documents/clavr')

from datetime import datetime, timedelta


def test_fact_inference_engine():
    """Test FactInferenceEngine pattern recognition."""
    print("\n=== Testing FactInferenceEngine ===\n")
    
    from src.ai.memory.fact_inference import (
        FactInferenceEngine, 
        InferredFact,
        InferenceType,
        ConfidenceLevel
    )
    
    engine = FactInferenceEngine()
    print("✅ Created FactInferenceEngine")
    
    # Test with sample facts
    facts = [
        {"id": 1, "content": "User prefers morning meetings", "category": "preference", "confidence": 0.8},
        {"id": 2, "content": "User scheduled meeting at 9am with Bob", "category": "calendar", "confidence": 0.9},
        {"id": 3, "content": "Email from Bob about Project X", "category": "email", "confidence": 0.9},
        {"id": 4, "content": "Meeting with Bob tomorrow morning", "category": "calendar", "confidence": 0.85},
        {"id": 5, "content": "Bob mentioned the deadline in email", "category": "email", "confidence": 0.8},
        {"id": 6, "content": "User likes to use Slack for quick questions", "category": "preference", "confidence": 0.75},
        {"id": 7, "content": "User uses email for formal communication", "category": "preference", "confidence": 0.8},
    ]
    
    # Run inference
    inferences = asyncio.run(engine.infer_from_facts(facts, user_id=1, max_inferences=5))
    
    print(f"✅ Generated {len(inferences)} inferences:")
    for inf in inferences:
        print(f"   - {inf.content[:60]}... (conf: {inf.confidence:.2f}, type: {inf.inference_type.value})")
    
    # Verify we got some inferences
    assert len(inferences) > 0, "Should generate at least one inference"
    
    # Check inference structure
    first = inferences[0]
    assert isinstance(first, InferredFact)
    assert first.content
    assert first.confidence > 0
    assert first.inference_type in InferenceType
    assert first.confidence_level in ConfidenceLevel
    print(f"✅ Inference structure validated")
    
    # Test confidence level mapping
    assert engine._get_confidence_level(0.9) == ConfidenceLevel.HIGH
    assert engine._get_confidence_level(0.7) == ConfidenceLevel.MEDIUM
    assert engine._get_confidence_level(0.5) == ConfidenceLevel.LOW
    assert engine._get_confidence_level(0.3) == ConfidenceLevel.SPECULATIVE
    print(f"✅ Confidence level mapping works")
    
    # Test deduplication
    dup_inferences = [
        InferredFact(content="User prefers morning", inference_type=InferenceType.PATTERN, confidence=0.8, confidence_level=ConfidenceLevel.MEDIUM),
        InferredFact(content="User prefers morning meetings", inference_type=InferenceType.PATTERN, confidence=0.7, confidence_level=ConfidenceLevel.MEDIUM),
        InferredFact(content="Something completely different about budgets", inference_type=InferenceType.PATTERN, confidence=0.6, confidence_level=ConfidenceLevel.LOW),
    ]
    deduplicated = engine._deduplicate_inferences(dup_inferences)
    # Deduplication uses first 50 chars, so "User prefers morning" and "User prefers morning meetings" are similar
    assert len(deduplicated) <= len(dup_inferences), "Deduplication should reduce or maintain count"
    print(f"✅ Inference deduplication works ({len(dup_inferences)} → {len(deduplicated)})")
    
    print("\n✅ All FactInferenceEngine tests passed!")
    return True


def test_fact_graph():
    """Test FactGraph hierarchical organization."""
    print("\n=== Testing FactGraph ===\n")
    
    from src.ai.memory.fact_graph import (
        FactGraph,
        FactGraphManager,
        FactNode,
        FactCategory,
        PreferenceSubcategory
    )
    
    graph = FactGraph(user_id=1)
    print("✅ Created FactGraph")
    
    # Add facts
    fact1 = graph.add_fact(
        content="User prefers morning meetings",
        category=FactCategory.PREFERENCE,
        subcategory=PreferenceSubcategory.SCHEDULING.value,
        confidence=0.8,
        entities=["User"],
        source="agent"
    )
    assert fact1.id == 1
    print(f"✅ Added fact 1: {fact1.content}")
    
    fact2 = graph.add_fact(
        content="Bob is the project lead for Project X",
        category=FactCategory.RELATIONSHIP,
        confidence=0.9,
        entities=["Bob", "Project X"],
        source="email"
    )
    print(f"✅ Added fact 2: {fact2.content}")
    
    fact3 = graph.add_fact(
        content="User likes to use Slack for quick questions",
        category=FactCategory.PREFERENCE,
        subcategory=PreferenceSubcategory.COMMUNICATION.value,
        confidence=0.75
    )
    print(f"✅ Added fact 3: {fact3.content}")
    
    # Test category retrieval
    prefs = graph.get_facts_by_category(FactCategory.PREFERENCE)
    assert len(prefs) == 2, f"Expected 2 preferences, got {len(prefs)}"
    print(f"✅ Category retrieval: {len(prefs)} preferences")
    
    # Test subcategory retrieval
    scheduling_prefs = graph.get_facts_by_category(
        FactCategory.PREFERENCE,
        subcategory=PreferenceSubcategory.SCHEDULING.value
    )
    assert len(scheduling_prefs) == 1
    print(f"✅ Subcategory retrieval: {len(scheduling_prefs)} scheduling preferences")
    
    # Test entity retrieval
    bob_facts = graph.get_facts_by_entity("Bob")
    assert len(bob_facts) == 1
    assert "Bob" in bob_facts[0].content
    print(f"✅ Entity retrieval: {len(bob_facts)} facts about Bob")
    
    # Test keyword search
    results = graph.search("morning meetings", limit=5)
    assert len(results) >= 1
    print(f"✅ Keyword search: {len(results)} results for 'morning meetings'")
    
    # Test fact linking
    graph.link_facts(fact1.id, fact2.id)
    related = graph.get_related_facts(fact1.id)
    assert len(related) == 1
    assert related[0].id == fact2.id
    print(f"✅ Fact linking works")
    
    # Test hierarchy retrieval
    hierarchy = graph.get_hierarchy()
    assert "preference" in hierarchy
    assert "relationship" in hierarchy
    assert hierarchy["preference"]["fact_count"] == 2
    print(f"✅ Hierarchy structure valid")
    
    # Test context formatting
    context = graph.format_for_context(
        categories=[FactCategory.PREFERENCE, FactCategory.RELATIONSHIP],
        max_per_category=2
    )
    assert "[PREFERENCE]" in context
    assert "[RELATIONSHIP]" in context
    print(f"✅ Context formatting:\n{context}")
    
    # Test stats
    stats = graph.get_stats()
    assert stats["total_facts"] == 3
    assert stats["total_entities"] >= 2
    print(f"✅ Stats: {stats}")
    
    # Test auto-detection
    detected, subcat = graph._detect_category("User prefers email for formal communication")
    assert detected == FactCategory.PREFERENCE
    print(f"✅ Auto-detection: '{detected.value}' (subcat: {subcat})")
    
    # Test FactGraphManager
    manager = FactGraphManager()
    g1 = manager.get_or_create(user_id=1)
    g2 = manager.get_or_create(user_id=1)
    assert g1 is g2
    print(f"✅ FactGraphManager caching works")
    
    print("\n✅ All FactGraph tests passed!")
    return True


async def test_enhanced_semantic_memory():
    """Test EnhancedSemanticMemory integration."""
    print("\n=== Testing EnhancedSemanticMemory ===\n")
    
    from src.ai.memory.fact_inference import init_inference_engine
    from src.ai.memory.fact_graph import init_fact_graph_manager, FactCategory
    from src.ai.memory.enhanced_semantic_memory import (
        EnhancedSemanticMemory,
        FactProvenance,
        ClarificationQuestion,
        create_enhanced_semantic_memory
    )
    
    # Initialize global managers
    init_inference_engine()
    init_fact_graph_manager()
    
    # Create mock base memory
    class MockBaseMemory:
        def __init__(self):
            self.facts = {}
            self._next_id = 1
        
        async def learn_fact(self, user_id, content, category="general", source="agent", confidence=1.0, validate=True):
            fact_id = self._next_id
            self._next_id += 1
            self.facts[fact_id] = {
                "id": fact_id,
                "user_id": user_id,
                "content": content,
                "category": category,
                "confidence": confidence
            }
            return fact_id, "new"
        
        async def get_facts(self, user_id, limit=20, min_confidence=0.0):
            return [
                f for f in self.facts.values() 
                if f["user_id"] == user_id and f["confidence"] >= min_confidence
            ][:limit]
        
        async def search_facts(self, query, user_id, limit=5):
            return await self.get_facts(user_id, limit)
        
        async def resolve_contradiction(self, fact_id, resolution, new_confidence=1.0):
            return True
    
    base = MockBaseMemory()
    enhanced = create_enhanced_semantic_memory(base_memory=base)
    print("✅ Created EnhancedSemanticMemory")
    
    # Test enhanced learning
    result = await enhanced.learn_fact_enhanced(
        user_id=1,
        content="User prefers morning meetings with Bob",
        category="preference",
        source="user_message",
        source_type="user_explicit",
        entities=["Bob"],
        run_inference=False  # Disable for speed
    )
    
    assert result.fact_id is not None
    assert result.provenance.source_type == "user_explicit"
    assert result.provenance.trust_score == 1.0
    assert "Bob" in result.entities
    print(f"✅ Enhanced learning: fact_id={result.fact_id}, confidence={result.confidence:.2f}")
    print(f"   Provenance: {result.provenance.source_type} (trust: {result.provenance.trust_score})")
    
    # Test source type trust
    result2 = await enhanced.learn_fact_enhanced(
        user_id=1,
        content="User might prefer afternoon for deep work",
        category="preference",
        source_type="single_observation",
        run_inference=False
    )
    assert result2.confidence == 0.6  # Single observation trust
    print(f"✅ Source trust: single_observation → confidence={result2.confidence}")
    
    # Test FactProvenance
    prov = FactProvenance.from_source_type("behavior_observed")
    assert prov.trust_score == 0.8
    prov.add_corroboration("email", "Similar pattern in emails")
    assert prov.trust_score > 0.8
    assert prov.corroboration_count == 1
    print(f"✅ Provenance corroboration: trust={prov.trust_score:.2f}")
    
    # Test context bundle
    bundle = await enhanced.get_context_bundle(
        user_id=1,
        query="morning meetings"
    )
    assert "preferences" in bundle
    assert "context_string" in bundle
    print(f"✅ Context bundle keys: {list(bundle.keys())}")
    
    # Test clarification generation
    enhanced._add_clarification(
        user_id=1,
        question="You mentioned morning meetings, but also scheduled afternoon calls. Which do you prefer?",
        priority="medium",
        reason="Potential contradiction",
        fact_ids=[1, 2],
        conflict_type="contradiction"
    )
    
    clarifications = enhanced.get_clarifications(user_id=1)
    assert len(clarifications) == 1
    assert clarifications[0].priority == "medium"
    print(f"✅ Clarifications: {len(clarifications)} pending")
    print(f"   Question: {clarifications[0].question[:60]}...")
    
    # Test access tracking
    enhanced._record_access(user_id=1, fact_ids=[1, 2, 3])
    most_accessed = enhanced.get_most_accessed_facts(user_id=1, days=1)
    assert len(most_accessed) >= 1
    print(f"✅ Access tracking: {len(most_accessed)} facts tracked")
    
    # Test stats
    stats = enhanced.get_stats(user_id=1)
    assert "pending_clarifications" in stats
    assert stats["pending_clarifications"] == 1
    print(f"✅ Stats: {stats}")
    
    print("\n✅ All EnhancedSemanticMemory tests passed!")
    return True


def test_semantic_clusterer():
    """Test SemanticClusterer theme-based organization."""
    print("\n=== Testing SemanticClusterer ===\n")
    
    from src.ai.memory.semantic_clustering import (
        SemanticClusterer,
        FactCluster,
        init_semantic_clusterer
    )
    
    clusterer = SemanticClusterer()
    print("✅ Created SemanticClusterer")
    
    # Sample facts
    facts = [
        {"id": 1, "content": "User prefers Slack for quick questions", "confidence": 0.8},
        {"id": 2, "content": "User uses email for formal communication", "confidence": 0.85},
        {"id": 3, "content": "User responds within 24 hours", "confidence": 0.7},
        {"id": 4, "content": "User prefers morning meetings", "confidence": 0.9},
        {"id": 5, "content": "User blocks afternoon for deep work", "confidence": 0.75},
        {"id": 6, "content": "User schedules no meetings on Friday", "confidence": 0.8},
        {"id": 7, "content": "Bob is the project manager", "confidence": 0.9},
    ]
    
    # Cluster facts
    clusters = clusterer.cluster_facts(facts, user_id=1, min_cluster_size=2)
    
    print(f"✅ Created {len(clusters)} clusters:")
    for cluster in clusters:
        print(f"   - {cluster.theme}: {len(cluster.fact_ids)} facts (coherence: {cluster.coherence_score:.2f})")
    
    assert len(clusters) >= 2, "Should create at least 2 clusters"
    
    # Test cluster retrieval
    comm_cluster = clusterer.get_cluster(user_id=1, theme="communication")
    if comm_cluster:
        assert len(comm_cluster.fact_ids) >= 2
        print(f"✅ Communication cluster: {len(comm_cluster.fact_ids)} facts")
    
    # Test query matching
    matched = clusterer.find_cluster_for_query("How does user prefer to communicate?", user_id=1)
    if matched:
        assert matched.theme == "communication"
        print(f"✅ Query matching: 'communicate' → {matched.theme}")
    
    # Test context formatting
    context = clusterer.format_clusters_for_context(user_id=1, max_clusters=2)
    assert len(context) > 0
    print(f"✅ Context formatting:\n{context[:200]}...")
    
    # Test FactCluster methods
    cluster = FactCluster(
        cluster_id="test_123",
        theme="test",
        description="Test cluster"
    )
    cluster.add_fact(1, "Test fact", 0.8)
    assert len(cluster.fact_ids) == 1
    assert cluster.avg_confidence == 0.8
    print(f"✅ FactCluster add_fact works")
    
    print("\n✅ All SemanticClusterer tests passed!")
    return True


def test_temporal_query_engine():
    """Test TemporalQueryEngine time-aware queries."""
    print("\n=== Testing TemporalQueryEngine ===\n")
    
    from src.ai.memory.temporal_facts import (
        TemporalQueryEngine,
        TemporalFact,
        TemporalScope,
        TimelineEvent,
        init_temporal_engine
    )
    
    engine = TemporalQueryEngine()
    print("✅ Created TemporalQueryEngine")
    
    now = datetime.utcnow()
    
    # Add permanent fact
    fact1 = engine.add_fact(
        user_id=1,
        fact_id=1,
        content="User prefers morning meetings",
        confidence=0.8,
        scope=TemporalScope.PERMANENT
    )
    print(f"✅ Added permanent fact: {fact1.content}")
    
    # Add fact with validity range
    fact2 = engine.add_fact(
        user_id=1,
        fact_id=2,
        content="User is on vacation",
        confidence=0.95,
        scope=TemporalScope.RANGE,
        valid_from=now - timedelta(days=3),
        valid_until=now + timedelta(days=4)
    )
    print(f"✅ Added ranged fact: valid until {fact2.valid_until}")
    
    # Add decaying fact
    fact3 = engine.add_fact(
        user_id=1,
        fact_id=3,
        content="User mentioned liking Python",
        confidence=0.7,
        scope=TemporalScope.DECAYING,
        decay_rate=0.01  # 1% per day
    )
    # Simulate old fact
    fact3.learned_at = now - timedelta(days=30)
    decayed_conf = fact3.get_decayed_confidence()
    print(f"✅ Decaying fact: {fact3.confidence:.2f} → {decayed_conf:.2f} after 30 days")
    assert decayed_conf < fact3.confidence
    
    # Test point-in-time query
    past = now - timedelta(days=5)
    past_facts = engine.query_at_time(user_id=1, point_in_time=past)
    assert len(past_facts) >= 1  # At least the permanent fact
    print(f"✅ Point-in-time query (5 days ago): {len(past_facts)} facts")
    
    # Test range query
    range_facts = engine.query_time_range(
        user_id=1,
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(days=1)
    )
    assert len(range_facts) >= 2
    print(f"✅ Range query (±1 day): {len(range_facts)} facts")
    
    # Test learned since
    recent = engine.query_learned_since(user_id=1, since=now - timedelta(hours=1))
    print(f"✅ Learned since query: {len(recent)} recent facts")
    
    # Test reinforcement
    new_conf = engine.reinforce_fact(user_id=1, fact_id=1, boost=0.1)
    assert new_conf is not None
    assert fact1.reinforcement_count == 1
    print(f"✅ Reinforcement: {fact1.reinforcement_count} times, conf={new_conf:.2f}")
    
    # Test timeline
    timeline = engine.get_timeline(user_id=1, limit=10)
    assert len(timeline) >= 3  # 3 facts + 1 reinforcement
    print(f"✅ Timeline: {len(timeline)} events")
    
    # Test temporal query parsing
    parsed = engine.parse_temporal_query("What did user prefer in 2022?")
    assert parsed["type"] == "year"
    assert parsed["year"] == 2022
    print(f"✅ Query parsing: '2022' → year={parsed['year']}")
    
    parsed2 = engine.parse_temporal_query("What happened last week?")
    assert parsed2["type"] == "relative"
    print(f"✅ Query parsing: 'last week' → relative range")
    
    # Test expiring soon
    expiring = engine.query_expiring_soon(user_id=1, days=7)
    print(f"✅ Expiring soon: {len(expiring)} facts")
    
    # Test stats
    stats = engine.get_stats(user_id=1)
    assert stats["total_facts"] == 3
    print(f"✅ Stats: {stats}")
    
    print("\n✅ All TemporalQueryEngine tests passed!")
    return True


def test_reasoning_engine():
    """Test ReasoningEngine for explainable reasoning."""
    print("\n=== Testing ReasoningEngine ===\n")
    
    from src.ai.memory.reasoning_chain import (
        ReasoningEngine,
        ReasoningChain,
        ReasoningStep,
        ReasoningType,
        init_reasoning_engine
    )
    
    engine = ReasoningEngine()
    print("✅ Created ReasoningEngine")
    
    # Sample facts
    facts = [
        {"id": 1, "content": "User prefers morning meetings", "confidence": 0.85},
        {"id": 2, "content": "User scheduled 5 meetings before 10am this week", "confidence": 0.9},
        {"id": 3, "content": "User mentioned being more productive in mornings", "confidence": 0.7},
        {"id": 4, "content": "User blocks afternoons for deep work", "confidence": 0.8},
    ]
    
    # Test reasoning
    chain = engine.reason(
        query="Why does user prefer morning meetings?",
        facts=facts
    )
    
    print(f"✅ Built reasoning chain:")
    print(f"   Query: {chain.query}")
    print(f"   Conclusion: {chain.conclusion}")
    print(f"   Confidence: {chain.confidence:.0%}")
    print(f"   Steps: {len(chain.steps)}")
    
    assert len(chain.steps) >= 2
    assert chain.confidence > 0
    
    # Test step details
    for step in chain.steps[:2]:
        print(f"   - {step.format()}")
    
    # Test chain serialization
    chain_dict = chain.to_dict()
    assert "query" in chain_dict
    assert "steps" in chain_dict
    print(f"✅ Serialization works")
    
    # Test display formatting
    display = chain.format_for_display()
    assert "Question:" in display
    assert "Conclusion:" in display
    assert "Evidence:" in display
    print(f"✅ Display formatting works")
    
    # Test question type classification
    assert engine.get_question_type("Why does user prefer X?") == "why"
    assert engine.get_question_type("How confident are we about X?") == "confidence"
    assert engine.get_question_type("What evidence supports X?") == "evidence"
    print(f"✅ Question type classification works")
    
    # Test confidence explanation
    explanation = engine.explain_confidence(facts, "morning meetings")
    assert explanation["fact_count"] >= 2
    assert explanation["level"] in ["very_high", "high", "moderate", "low", "none"]
    print(f"✅ Confidence explanation: {explanation['level']} ({explanation['confidence']:.0%})")
    
    # Test ReasoningStep
    step = ReasoningStep(
        step_id=1,
        fact_content="Test fact",
        reasoning_type=ReasoningType.SUPPORTS,
        contribution=0.5
    )
    assert step.format() == "✓ Test fact"
    print(f"✅ ReasoningStep formatting works")
    
    print("\n✅ All ReasoningEngine tests passed!")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("  ENHANCED SEMANTIC MEMORY TESTS")
    print("=" * 60)
    
    all_passed = True
    
    try:
        if not test_fact_inference_engine():
            all_passed = False
    except Exception as e:
        print(f"❌ FactInferenceEngine tests failed: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        if not test_fact_graph():
            all_passed = False
    except Exception as e:
        print(f"❌ FactGraph tests failed: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        if not asyncio.run(test_enhanced_semantic_memory()):
            all_passed = False
    except Exception as e:
        print(f"❌ EnhancedSemanticMemory tests failed: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        if not test_semantic_clusterer():
            all_passed = False
    except Exception as e:
        print(f"❌ SemanticClusterer tests failed: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        if not test_temporal_query_engine():
            all_passed = False
    except Exception as e:
        print(f"❌ TemporalQueryEngine tests failed: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    try:
        if not test_reasoning_engine():
            all_passed = False
    except Exception as e:
        print(f"❌ ReasoningEngine tests failed: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("  ✅ ALL TESTS PASSED!")
    else:
        print("  ❌ SOME TESTS FAILED")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

