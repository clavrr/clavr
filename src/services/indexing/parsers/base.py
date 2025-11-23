"""
Base Parser Classes for Knowledge Graph Construction

This module provides the foundation for intelligent data parsing.
Instead of chunking text arbitrarily, we parse data into structured nodes
that form a knowledge graph.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import hashlib


class Relationship(BaseModel):
    """
    Represents a directed relationship between two nodes in the knowledge graph
    
    Examples:
        Email -[:FROM]-> Contact
        Receipt -[:FROM_STORE]-> Company
        Email -[:CONTAINS]-> ActionItem
    """
    from_node: str = Field(description="Source node ID")
    to_node: str = Field(description="Target node ID")
    rel_type: str = Field(description="Relationship type (e.g., FROM, CONTAINS, HAS_ATTACHMENT)")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Additional relationship metadata")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ParsedNode(BaseModel):
    """
    Base class for all parsed nodes in the knowledge graph
    
    This is the fundamental "chunk" unit - not arbitrary text splits,
    but semantically complete objects.
    """
    node_id: str = Field(description="Unique node identifier")
    node_type: str = Field(description="Node type (Email, Contact, Receipt, ActionItem, etc)")
    properties: Dict[str, Any] = Field(description="Node properties/attributes")
    relationships: List[Relationship] = Field(default_factory=list, description="Relationships to other nodes")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    # Semantic search support (optional text for vector embedding)
    searchable_text: Optional[str] = Field(default=None, description="Text to embed for semantic search")
    
    class Config:
        # Allow arbitrary types for flexibility
        arbitrary_types_allowed = True


class BaseParser(ABC):
    """
    Abstract base class for all parsers
    
    Each parser is responsible for transforming raw data into structured
    ParsedNode objects that can be added to the knowledge graph.
    """
    
    @abstractmethod
    async def parse(self, raw_data: Dict[str, Any]) -> ParsedNode:
        """
        Parse raw data into a structured node
        
        Args:
            raw_data: Raw data dictionary (e.g., email data, attachment data)
            
        Returns:
            ParsedNode with extracted structure and relationships
        """
        pass
    
    def generate_node_id(self, node_type: str, unique_key: str) -> str:
        """
        Generate a deterministic node ID
        
        Args:
            node_type: Type of node (Email, Contact, etc)
            unique_key: Unique identifier for this instance
            
        Returns:
            Node ID in format: NodeType_hash
        """
        hash_obj = hashlib.md5(unique_key.encode())
        short_hash = hash_obj.hexdigest()[:12]
        return f"{node_type}_{short_hash}"
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        # Remove excessive whitespace
        text = " ".join(text.split())
        return text.strip()


class Entity(BaseModel):
    """Extracted entity from text"""
    entity_type: str = Field(description="Entity type (person, date, company, topic, etc)")
    value: str = Field(description="Entity value")
    confidence: float = Field(default=1.0, description="Extraction confidence (0-1)")
    context: Optional[str] = Field(default=None, description="Surrounding context")


class ExtractedIntents(BaseModel):
    """
    Intents and entities extracted from text using LLM
    
    This is what makes the parser "intelligent" - we don't just index text,
    we understand what it means.
    """
    action_items: List[str] = Field(default_factory=list, description="Action items mentioned")
    intents: List[str] = Field(default_factory=list, description="Intent types (schedule_meeting, request_info, etc)")
    entities: List[Entity] = Field(default_factory=list, description="Extracted entities")
    topics: List[str] = Field(default_factory=list, description="Main topics discussed")
    questions: List[str] = Field(default_factory=list, description="Questions asked")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "action_items": self.action_items,
            "intents": self.intents,
            "entities": [e.dict() for e in self.entities],
            "topics": self.topics,
            "questions": self.questions
        }
