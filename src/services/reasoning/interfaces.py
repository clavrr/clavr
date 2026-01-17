"""
Interfaces for Reasoning Agents and services.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ReasoningResult:
    """Result from a reasoning agent analysis."""
    type: str  # 'pattern', 'hypothesis', 'insight'
    content: Dict[str, Any]
    confidence: float
    source_agent: str

class ReasoningAgent(ABC):
    """
    Abstract base class for all reasoning agents.
    
    Each agent focuses on a specific type of reasoning (e.g., temporal patterns,
    cross-app connections, conflict detection).
    """
    
    def __init__(self, config: Any, graph_manager: Any):
        self.config = config
        self.graph = graph_manager
        
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the agent."""
        raise NotImplementedError("Subclasses must implement name property")
        
    @abstractmethod
    async def analyze(self, user_id: int, context: Optional[Dict[str, Any]] = None) -> List[ReasoningResult]:
        """
        Analyze the graph for the given user and return findings.
        
        Args:
            user_id: User ID to analyze
            context: Optional context to focus analysis (e.g., specific time range)
            
        Returns:
            List of ReasoningResults
        """
        raise NotImplementedError("Subclasses must implement analyze()")
        
    @abstractmethod
    async def verify(self, hypothesis_id: str) -> bool:
        """
        Verify a specific hypothesis.
        
        Args:
            hypothesis_id: ID of the Hypothesis node to verify
            
        Returns:
            True if verified, False if rejected
        """
        raise NotImplementedError("Subclasses must implement verify()")
