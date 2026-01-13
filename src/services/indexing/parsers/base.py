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


    def _parse_json_response(self, response: Any) -> Dict[str, Any]:
        """
        Parse JSON from LLM response, handling markdown blocks
        
        Args:
            response: LLM response object or string
            
        Returns:
            Dict containing parsed data, or empty dict on failure
        """
        try:
            # Extract text from response
            if hasattr(response, 'content'):
                text = response.content
            else:
                text = str(response)
            
            # Clean markdown code blocks
            import re
            json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
            
            # Parse JSON
            import json
            return json.loads(text)
        except Exception:
            return {}

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """
        Normalize date string to YYYY-MM-DD format.
        
        Handles malformed dates by trying multiple parsing strategies:
        1. Try standard formats
        2. Try dateparser for fuzzy parsing
        3. Try to extract date components from malformed strings
        
        Args:
            date_str: Date string that may be malformed
            
        Returns:
            Normalized date in YYYY-MM-DD format, or None if unparseable
        """
        if not date_str or not isinstance(date_str, str):
            return None
        
        date_str = date_str.strip()
        
        # Try standard formats first
        standard_formats = [
            '%Y-%m-%d',           # 2025-12-02
            '%m/%d/%Y',            # 12/02/2025
            '%d/%m/%Y',            # 02/12/2025
            '%Y/%m/%d',            # 2025/12/02
            '%m-%d-%Y',            # 12-02-2025
            '%d-%m-%Y',            # 02-12-2025
            '%B %d, %Y',           # December 02, 2025
            '%b %d, %Y',           # Dec 02, 2025
            '%d %B %Y',            # 02 December 2025
            '%d %b %Y',            # 02 Dec 2025
        ]
        
        for fmt in standard_formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        # Try dateparser for fuzzy parsing
        try:
            import dateparser
            parsed = dateparser.parse(date_str)
            if parsed:
                return parsed.strftime('%Y-%m-%d')
        except (ImportError, Exception):
            pass
        
        # Try to extract date from strings
        import re
        date_patterns = [
            r'(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})',  # DD-MM-YY
            r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',    # YYYY-MM-DD
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, date_str)
            if match:
                parts = match.groups()
                try:
                    # Heuristic parsing logic (same as in ReceiptParser)
                    if len(parts[2]) == 4:
                        year, month, day = int(parts[2]), int(parts[1]), int(parts[0])
                    elif len(parts[0]) == 4:
                        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                    else:
                        year = int(parts[2]) + (2000 if int(parts[2]) < 50 else 1900)
                        month, day = int(parts[1]), int(parts[0])
                    
                    if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
                        return datetime(year, month, day).strftime('%Y-%m-%d')
                except (ValueError, IndexError):
                    continue
        
        return None


class Entity(BaseModel):
    """Extracted entity from text"""
    entity_type: str = Field(description="Entity type (person, date, company, topic, etc)")
    value: str = Field(description="Entity value")
    confidence: float = Field(default=1.0, description="Extraction confidence (0-1)")
    context: Optional[str] = Field(default=None, description="Surrounding context")


class LeadInfo(BaseModel):
    """Business lead information extracted from text"""
    name: str = Field(description="Lead name or company")
    interest_level: float = Field(default=0.5, description="Level of interest (0-1)")
    potential_value: Optional[float] = Field(default=None, description="Potential business value")
    topic: Optional[str] = Field(default=None, description="Main topic of interest")
    notes: Optional[str] = Field(default=None, description="Additional context or notes")


class ExtractedIntents(BaseModel):
    """
    Intents and entities extracted from text using LLM
    """
    action_items: List[str] = Field(default_factory=list, description="Action items mentioned")
    intents: List[str] = Field(default_factory=list, description="Intent types")
    entities: List[Entity] = Field(default_factory=list, description="Extracted entities")
    topics: List[str] = Field(default_factory=list, description="Main topics discussed")
    questions: List[str] = Field(default_factory=list, description="Questions asked")
    leads: List[LeadInfo] = Field(default_factory=list, description="Extracted business leads")
    financial_info: Optional[Dict[str, Any]] = Field(default=None, description="Extracted financial info (is_receipt, amount, merchant)")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "action_items": self.action_items,
            "intents": self.intents,
            "entities": [e.dict() for e in self.entities],
            "topics": self.topics,
            "questions": self.questions,
            "leads": [l.dict() for l in self.leads],
            "financial_info": self.financial_info
        }
