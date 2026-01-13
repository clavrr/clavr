"""
Domain Context definition.

Holds the specialized memory components for a specific agent domain.
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict

from src.memory.agent_memory_lane import AgentMemoryLane
from src.services.indexing.graph.manager import KnowledgeGraphManager

@dataclass
class DomainContext:
    """
    Specialized memory context for an agent.
    
    Contains:
    - memory_lane: The agent's learning path (patterns, facts)
    - vector_store: The vector search engine scoped to the agent's domain
    - graph_manager: The knowledge graph manager
    - graph_scope: List of allowed node types for this agent
    - working_memory: Ephemeral working memory for current task execution
    """
    memory_lane: AgentMemoryLane
    vector_store: Any  # RAGEngine instance
    graph_manager: KnowledgeGraphManager
    graph_scope: List[str]
    working_memory: Dict[str, Any] = field(default_factory=dict)
    
    def get_scoped_patterns(self, trigger: str) -> List[Any]:
        """Get patterns relevant to this domain."""
        return self.memory_lane.get_patterns_for_trigger(trigger)
    
    def get_scoped_facts(self) -> List[Any]:
        """Get facts relevant to this domain."""
        return self.memory_lane.get_facts_for_context()
