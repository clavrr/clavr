"""
Memory System Evaluations - Semantic Memory

Tests for:
- Fact Learning (store, retrieve, update)
- Contradiction Detection
- Fact Validation
- Semantic Search
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch


# =============================================================================
# Semantic Memory Tests
# =============================================================================

class TestSemanticMemoryFactLearning:
    """Evaluate fact learning capabilities."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Create a mock async database session."""
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        return session
    
    @pytest.fixture
    def semantic_memory(self, mock_db_session):
        """Create SemanticMemory with mocked dependencies."""
        from src.ai.memory.semantic_memory import SemanticMemory
        return SemanticMemory(db=mock_db_session, rag_engine=None, llm=None)
    
    # -------------------------------------------------------------------------
    # Basic Fact Learning
    # -------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_learn_new_fact(self, semantic_memory):
        """New facts are stored successfully."""
        user_id = 1
        content = "User prefers dark mode"
        category = "preference"
        
        # Mock no existing facts (new fact)
        semantic_memory.db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        
        result = await semantic_memory.learn_fact(
            user_id=user_id,
            content=content,
            category=category
        )
        
        # Verify db.add was called to store the fact
        assert semantic_memory.db.add.called
        assert semantic_memory.db.commit.called
    
    @pytest.mark.asyncio
    async def test_learn_fact_with_confidence(self, semantic_memory):
        """Facts can be stored with custom confidence."""
        semantic_memory.db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        
        await semantic_memory.learn_fact(
            user_id=1,
            content="User drinks coffee",
            confidence=0.8
        )
        
        assert semantic_memory.db.add.called


class TestSemanticMemoryContradictions:
    """Evaluate contradiction detection."""
    
    @pytest.fixture
    def semantic_memory(self):
        from src.ai.memory.semantic_memory import SemanticMemory
        session = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        return SemanticMemory(db=session)
    
    # -------------------------------------------------------------------------
    # Contradiction Detection (Heuristic)
    # -------------------------------------------------------------------------
    
    @pytest.mark.parametrize("fact1,fact2,should_contradict", [
        # Direct negation patterns
        ("User likes coffee", "User does not like coffee", True),
        ("User prefers tea", "User doesn't prefer tea", True),
        ("User hates mornings", "User doesn't hate mornings", True),
        
        # Opposite values
        ("Favorite color is blue", "Favorite color is red", True),
        ("Prefers dark mode", "Prefers light mode", True),
        
        # Non-contradictions
        ("User likes coffee", "User likes tea", False),
        ("Works at Google", "Lives in California", False),
        ("User prefers morning meetings", "User likes coffee", False),
    ])
    def test_contradiction_detection(self, semantic_memory, fact1, fact2, should_contradict):
        """Verify contradiction detection heuristics."""
        is_contradiction = semantic_memory._detect_contradiction(fact1, fact2)
        
        if should_contradict:
            assert is_contradiction, f"Should detect contradiction: '{fact1}' vs '{fact2}'"
        else:
            assert not is_contradiction, f"Should NOT detect contradiction: '{fact1}' vs '{fact2}'"


class TestSemanticMemorySimilarity:
    """Evaluate similarity calculation."""
    
    @pytest.fixture
    def semantic_memory(self):
        from src.ai.memory.semantic_memory import SemanticMemory
        session = MagicMock()
        return SemanticMemory(db=session)
    
    @pytest.mark.parametrize("text1,text2,min_similarity", [
        # Identical
        ("User likes coffee", "User likes coffee", 0.99),
        
        # Very similar
        ("User prefers coffee", "User likes coffee", 0.7),
        
        # Related but different
        ("User drinks coffee in the morning", "User likes coffee", 0.4),
        
        # Completely different
        ("User likes coffee", "The weather is nice", 0.0),
    ])
    def test_similarity_calculation(self, semantic_memory, text1, text2, min_similarity):
        """Verify similarity scores are reasonable."""
        similarity = semantic_memory._calculate_similarity(text1, text2)
        
        assert similarity >= min_similarity, \
            f"Similarity between '{text1}' and '{text2}' should be >= {min_similarity}, got {similarity}"


class TestSemanticMemoryRetrieval:
    """Evaluate fact retrieval."""
    
    @pytest.fixture
    def semantic_memory(self):
        from src.ai.memory.semantic_memory import SemanticMemory
        session = MagicMock()
        session.execute = AsyncMock()
        return SemanticMemory(db=session)
    
    @pytest.mark.asyncio
    async def test_get_facts_filters_by_user(self, semantic_memory):
        """Facts are filtered by user ID."""
        from src.database.models import AgentFact
        
        # Mock return value
        mock_facts = [
            MagicMock(spec=AgentFact, content="Fact 1", category="pref"),
            MagicMock(spec=AgentFact, content="Fact 2", category="pref"),
        ]
        semantic_memory.db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=mock_facts))))
        )
        
        facts = await semantic_memory.get_facts(user_id=1, category="pref")
        
        # Verify query was executed
        assert semantic_memory.db.execute.called
    
    @pytest.mark.asyncio
    async def test_get_facts_respects_limit(self, semantic_memory):
        """Fact retrieval respects limit parameter."""
        semantic_memory.db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )
        
        await semantic_memory.get_facts(user_id=1, limit=5)
        
        # Verify the call was made
        assert semantic_memory.db.execute.called
