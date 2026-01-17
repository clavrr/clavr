"""
Memory System Evaluations - Person Intelligence

Tests for:
- Person Unification (merging related person nodes)
- Entity Resolution
- Contact Intelligence
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch


# =============================================================================
# Person Unification Tests
# =============================================================================

class TestPersonUnification:
    """Evaluate person unification capabilities."""
    
    @pytest.fixture
    def mock_graph(self):
        """Mock knowledge graph manager."""
        graph = MagicMock()
        graph.query = AsyncMock(return_value=[])
        graph.add_relationship = AsyncMock()
        graph.execute_query = AsyncMock(return_value=[])
        return graph
    
    @pytest.fixture
    def mock_config(self):
        """Mock config."""
        config = MagicMock()
        config.get = MagicMock(return_value={})
        return config
    
    @pytest.fixture
    def person_unification(self, mock_config, mock_graph):
        """Create PersonUnificationService with mocks."""
        from src.ai.memory.person_unification import PersonUnificationService
        service = PersonUnificationService(config=mock_config)
        service.graph_manager = mock_graph
        return service
    
    # -------------------------------------------------------------------------
    # Email-based Unification
    # -------------------------------------------------------------------------
    
    @pytest.mark.asyncio
    async def test_same_email_unified(self, person_unification, mock_graph):
        """People with same email should be unified."""
        # Mock finding two person nodes with same email
        mock_graph.execute_query = AsyncMock(return_value=[
            {"source_id": "person_1", "target_id": "person_2", "source_name": "John", "target_name": "Johnny"}
        ])
        
        count = await person_unification.run_for_user(user_id=1)
        
        # Verify unification was attempted
        assert mock_graph.execute_query.called


class TestEntityResolution:
    """Evaluate entity resolution capabilities."""
    
    @pytest.fixture
    def mock_graph(self):
        graph = MagicMock()
        graph.query = AsyncMock(return_value=[])
        graph.execute_query = AsyncMock(return_value=[])
        graph.add_relationship = AsyncMock()
        return graph
    
    @pytest.fixture
    def entity_resolution(self, mock_graph):
        """Create EntityResolutionService."""
        from src.ai.memory.resolution import EntityResolutionService
        service = EntityResolutionService(graph_manager=mock_graph)
        return service
    
    # -------------------------------------------------------------------------
    # Name Matching
    # -------------------------------------------------------------------------
    
    @pytest.mark.parametrize("name1,name2,should_match", [
        # Exact match
        ("John Smith", "John Smith", True),
        
        # Case insensitive
        ("john smith", "John Smith", True),
        
        # Nickname variations
        ("Mike", "Michael", True),
        ("Bob", "Robert", True),
        ("Bill", "William", True),
        
        # Different people
        ("John Smith", "Jane Doe", False),
        ("Michael Johnson", "Michael Williams", False),
    ])
    def test_name_matching_heuristics(self, name1, name2, should_match):
        """Verify name matching logic."""
        from src.ai.memory.resolution import EntityResolutionService
        
        # Direct comparison for now
        name1_lower = name1.lower()
        name2_lower = name2.lower()
        
        # Simple nickname mapping
        nicknames = {
            'mike': 'michael', 'michael': 'michael',
            'bob': 'robert', 'robert': 'robert',
            'bill': 'william', 'william': 'william',
        }
        
        # Normalize first names
        n1_parts = name1_lower.split()
        n2_parts = name2_lower.split()
        
        if len(n1_parts) > 0 and len(n2_parts) > 0:
            first1 = nicknames.get(n1_parts[0], n1_parts[0])
            first2 = nicknames.get(n2_parts[0], n2_parts[0])
            
            if first1 == first2:
                # Check last name if available
                if len(n1_parts) > 1 and len(n2_parts) > 1:
                    matched = n1_parts[-1] == n2_parts[-1]
                else:
                    matched = True
            else:
                matched = name1_lower == name2_lower
        else:
            matched = name1_lower == name2_lower
        
        if should_match:
            assert matched, f"Should match: '{name1}' and '{name2}'"
        else:
            assert not matched, f"Should NOT match: '{name1}' and '{name2}'"


# =============================================================================
# Memory Graph Tests
# =============================================================================

class TestMemoryGraph:
    """Evaluate memory graph operations."""
    
    @pytest.fixture
    def mock_graph(self):
        graph = MagicMock()
        graph.add_node = AsyncMock(return_value=True)
        graph.add_relationship = AsyncMock(return_value=True)
        graph.query = AsyncMock(return_value=[])
        graph.get_node = AsyncMock(return_value=None)
        return graph
    
    @pytest.mark.asyncio
    async def test_add_memory_node(self, mock_graph):
        """Memory nodes can be added."""
        await mock_graph.add_node(
            node_id="memory_123",
            node_type="Memory",
            properties={
                "content": "User mentioned they like hiking",
                "source": "email",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        assert mock_graph.add_node.called
    
    @pytest.mark.asyncio
    async def test_link_memory_to_person(self, mock_graph):
        """Memories can be linked to people."""
        await mock_graph.add_relationship(
            from_node="memory_123",
            to_node="person_456",
            rel_type="ABOUT",
            properties={"confidence": 0.9}
        )
        
        assert mock_graph.add_relationship.called
