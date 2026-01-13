"""
Memory Persistence Models

SQLAlchemy models and Data Classes for the memory system.
"""
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Boolean
from src.database.models import Base

# SQLAlchemy Models
class QueryPattern(Base):
    """Simple query pattern storage"""
    __tablename__ = 'query_patterns'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    pattern = Column(String(500), nullable=False)
    intent = Column(String(100), nullable=False)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    confidence = Column(Float, default=0.5)
    last_used = Column(DateTime, default=datetime.now)
    created_at = Column(DateTime, default=datetime.now)
    
class ExecutionMemory(Base):
    """Simple execution memory storage"""
    __tablename__ = 'execution_memory'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    query = Column(Text, nullable=False)
    tools_used = Column(Text, nullable=False)  # JSON string
    success = Column(Boolean, nullable=False)
    execution_time = Column(Float, default=0.0)
    step_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)

# Data Classes
@dataclass
class MemoryPattern:
    """Simple memory pattern for learning with entity and complexity awareness"""
    pattern: str
    intent: str
    success_count: int = 0
    failure_count: int = 0
    confidence: float = 0.5
    last_used: Optional[datetime] = None
    tools_used: Optional[List[str]] = None
    # New fields for Phase 2 integration
    complexity_level: Optional[str] = None  # low, medium, high
    estimated_steps: Optional[int] = None
    domains_detected: Optional[List[str]] = None
    entities: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.last_used is None:
            self.last_used = datetime.now()
        if self.tools_used is None:
            self.tools_used = []
        if self.domains_detected is None:
            self.domains_detected = []
        if self.entities is None:
            self.entities = {}

@dataclass
class UserPreference:
    """User preference pattern"""
    user_id: int
    preference_type: str
    pattern: str
    frequency: int = 1
    confidence: float = 0.5
    last_used: Optional[datetime] = None
    
    def __post_init__(self):
        if self.last_used is None:
            self.last_used = datetime.now()

@dataclass
class UnifiedContext:
    """
    Combines:
    - Behavioral memory (patterns, tools, preferences)
    - Semantic memory (Qdrant documents)
    - Conversational memory (PostgreSQL chat history)
    """
    # Behavioral layer (from SimplifiedMemorySystem)
    recommended_tools: List[str] = field(default_factory=list)
    similar_patterns: List[MemoryPattern] = field(default_factory=list)
    user_preferences: List[UserPreference] = field(default_factory=list)
    
    # Semantic layer (from Qdrant)
    relevant_documents: List[Dict[str, Any]] = field(default_factory=list)
    semantic_summary: str = ""
    
    # Conversational layer (from PostgreSQL)
    recent_messages: List[Dict[str, Any]] = field(default_factory=list)
    conversation_summary: str = ""
    mentioned_entities: List[str] = field(default_factory=list)
    
    # Metadata
    confidence: float = 0.5
    retrieval_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "recommended_tools": self.recommended_tools,
            "similar_patterns": [
                {"pattern": p.pattern, "intent": p.intent, "confidence": p.confidence}
                for p in self.similar_patterns
            ],
            "user_preferences": [
                {"pattern": p.pattern, "frequency": p.frequency}
                for p in self.user_preferences
            ],
            "relevant_documents": self.relevant_documents,
            "semantic_summary": self.semantic_summary,
            "recent_messages": self.recent_messages,
            "conversation_summary": self.conversation_summary,
            "mentioned_entities": self.mentioned_entities,
            "confidence": self.confidence,
            "retrieval_time_ms": self.retrieval_time_ms
        }
