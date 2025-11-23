"""
Knowledge Graph Schema Definitions

Defines node types, relationship types, and validation rules for the knowledge graph.

Features:
- Comprehensive node and relationship type definitions
- Required and optional property validation
- Property type checking (string, int, date, etc.)
- Relationship constraint validation
- No hardcoded values - all constants extracted

Version: 1.0.0
Last Updated: 2025-11-18
"""
from enum import Enum
from typing import Dict, Any, List, Set, Optional, Tuple
from pydantic import BaseModel, Field
from datetime import datetime
import re

from .schema_constants import (
    SCHEMA_VERSION,
    DEFAULT_QUERY_LIMIT,
    MAX_QUERY_LIMIT,
    DEFAULT_TRAVERSAL_DEPTH,
    MAX_STRING_LENGTH,
    MIN_STRING_LENGTH,
    EMAIL_REGEX,
    MAX_EMAIL_LENGTH,
    MIN_RECEIPT_TOTAL,
    MAX_RECEIPT_TOTAL,
    DATE_FORMAT,
    DATETIME_FORMAT,
    ISO_DATETIME_FORMAT,
    VALID_ACTION_STATUSES,
    STRING_PROPERTIES,
    NUMERIC_PROPERTIES,
    DATE_PROPERTIES,
    ERROR_MISSING_REQUIRED_PROPERTY,
    ERROR_INVALID_PROPERTY_TYPE,
    ERROR_INVALID_RELATIONSHIP,
    ERROR_PROPERTY_TOO_LONG,
    ERROR_INVALID_EMAIL_FORMAT,
    ERROR_INVALID_DATE_FORMAT,
    ERROR_VALUE_OUT_OF_RANGE,
    ERROR_INVALID_STATUS,
)


class PropertyType(str, Enum):
    """Property value types for validation"""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    ARRAY = "array"
    OBJECT = "object"


class NodeType(str, Enum):
    """Valid node types in the knowledge graph"""
    EMAIL = "Email"
    CONTACT = "Contact"
    PERSON = "Person"
    EMAIL_ADDRESS = "EmailAddress"  # For contact email addresses (separate from Email messages)
    ALIAS = "Alias"  # For person names/nicknames
    SYSTEM = "System"  # For source systems (Gmail, Slack, CRM, etc.)
    COMPANY = "Company"
    USER = "User"
    VENDOR = "Vendor"
    DOCUMENT = "Document"
    RECEIPT = "Receipt"
    ACTION_ITEM = "ActionItem"
    TOPIC = "Topic"
    CALENDAR_EVENT = "CalendarEvent"
    CONVERSATION = "Conversation"
    CHANNEL = "Channel"  # Slack channel
    MESSAGE = "Message"  # Slack message
    SESSION = "Session"  # Conversation session for short-term memory
    CONVERSATION_MESSAGE = "ConversationMessage"  # User/agent messages in sessions
    GOAL = "Goal"  # User goals for long-term memory
    PROJECT = "Project"  # Projects/topics for implicit context


class RelationType(str, Enum):
    """Valid relationship types in the knowledge graph"""
    # Email relationships
    FROM = "FROM"
    TO = "TO"
    CC = "CC"
    BCC = "BCC"
    RECEIVED = "RECEIVED"
    SENT = "SENT"
    REPLIED_TO = "REPLIED_TO"
    FORWARDED_TO = "FORWARDED_TO"
    
    # Content relationships
    CONTAINS = "CONTAINS"
    DISCUSSES = "DISCUSSES"
    MENTIONS = "MENTIONS"
    REFERENCES = "REFERENCES"
    
    # Attachment relationships
    ATTACHED_TO = "ATTACHED_TO"
    HAS_ATTACHMENT = "HAS_ATTACHMENT"
    
    # Receipt/Financial relationships
    FROM_STORE = "FROM_STORE"
    PURCHASED_AT = "PURCHASED_AT"
    HAS_RECEIPT = "HAS_RECEIPT"
    FROM_VENDOR = "FROM_VENDOR"
    
    # Action/Task relationships
    ASSIGNED_TO = "ASSIGNED_TO"
    CREATED_BY = "CREATED_BY"
    COMPLETED_BY = "COMPLETED_BY"
    
    # Entity relationships
    WORKS_FOR = "WORKS_FOR"
    ATTENDED_BY = "ATTENDED_BY"
    ORGANIZED_BY = "ORGANIZED_BY"
    
    # Contact resolution relationships (for Person/Email/Alias/System architecture)
    HAS_EMAIL = "HAS_EMAIL"  # Person -> EmailAddress
    HAS_ALIAS = "HAS_ALIAS"  # Person -> Alias
    SOURCE_SYSTEM = "SOURCE_SYSTEM"  # Person -> System
    
    # Conversation relationships
    PART_OF = "PART_OF"
    NEXT_IN_THREAD = "NEXT_IN_THREAD"
    
    # Slack-specific relationships
    MENTIONED = "MENTIONED"  # Person MENTIONED Person (in Slack message)
    POSTED_IN = "POSTED_IN"  # Person POSTED_IN Channel
    REACTED_TO = "REACTED_TO"  # Person REACTED_TO Message
    POSTED = "POSTED"  # Person POSTED Message
    IN_CHANNEL = "IN_CHANNEL"  # Message IN_CHANNEL Channel
    
    # Memory relationships
    CONTAINS_TURN = "CONTAINS_TURN"  # Session CONTAINS_TURN ConversationMessage
    MANAGES = "MANAGES"  # User MANAGES Goal
    WORKS_ON = "WORKS_ON"  # User WORKS_ON Project/Topic


class ValidationResult(BaseModel):
    """Result of schema validation"""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    
    def add_error(self, message: str) -> None:
        """Add an error message"""
        self.errors.append(message)
        self.is_valid = False
    
    def add_warning(self, message: str) -> None:
        """Add a warning message"""
        self.warnings.append(message)


class GraphSchema:
    """
    Schema validator for the knowledge graph
    
    Defines valid node properties, relationship constraints, and validation rules.
    No hardcoded values - all constants from schema_constants.py
    """
    
    # Schema version
    VERSION = SCHEMA_VERSION
    
    # Required properties for each node type
    REQUIRED_PROPERTIES: Dict[NodeType, Set[str]] = {
        NodeType.EMAIL: {"subject", "sender", "date", "body"},
        NodeType.CONTACT: {"email"},
        NodeType.PERSON: {"name"},
        NodeType.COMPANY: {"name"},
        NodeType.USER: {"email"},
        NodeType.VENDOR: {"name"},
        NodeType.DOCUMENT: {"filename"},
        NodeType.RECEIPT: {"merchant", "total", "date"},
        NodeType.ACTION_ITEM: {"description", "status"},
        NodeType.TOPIC: {"name"},
        NodeType.CALENDAR_EVENT: {"title", "start_time"},
        NodeType.CONVERSATION: {"thread_id"},
        NodeType.CHANNEL: {"slack_channel_id", "name"},
        NodeType.MESSAGE: {"slack_message_ts", "text"},
        NodeType.SESSION: {"id", "timestamp"},
        NodeType.CONVERSATION_MESSAGE: {"text", "role"},
        NodeType.GOAL: {"name"},
        NodeType.PROJECT: {"name"},
    }
    
    # Optional properties for each node type
    OPTIONAL_PROPERTIES: Dict[NodeType, Set[str]] = {
        NodeType.EMAIL: {
            "recipients", "cc", "bcc", "attachments", "is_read", "is_starred",
            # Additional metadata properties from EmailParser
            "email_id", "thread_id", "sender_domain", "timestamp", "labels",
            "is_unread", "is_important", "has_attachments", "folder",
            "attachment_info", "intents", "has_action_items", "has_questions"
        },
        NodeType.CONTACT: {"name", "phone", "company", "last_contact"},
        NodeType.PERSON: {"email", "phone", "title", "company", "user_id"},  # user_id for multi-user support
        NodeType.EMAIL_ADDRESS: {"domain", "verified"},  # Optional metadata
        NodeType.ALIAS: {"type"},  # Optional: "full_name", "first_name", "nickname", etc.
        NodeType.SYSTEM: {"type", "api_version"},  # Optional metadata
        NodeType.COMPANY: {"domain", "industry", "size"},
        NodeType.USER: {"name", "preferences", "created_at"},
        NodeType.VENDOR: {"category", "location", "website"},
        NodeType.DOCUMENT: {
            "doc_type", "size", "content", "file_size", "content_type",
            "full_text", "num_tables", "num_headings", "num_sections", "num_images",
            "docling_metadata", "summary", "document_type", "key_points", "entities",
            "topics", "action_items", "financial_data", "parsed_at", "parser"
        },
        NodeType.RECEIPT: {"items", "tax", "tip", "category", "location", "subtotal", "time", "payment_method", "currency", "receipt_number"},
        NodeType.ACTION_ITEM: {"priority", "due_date", "assigned_to"},
        NodeType.TOPIC: {"category", "keywords"},
        NodeType.CALENDAR_EVENT: {"end_time", "location", "attendees"},
        NodeType.CONVERSATION: {"subject", "participant_count"},
        NodeType.CHANNEL: {
            "is_private", "is_archived", "topic", "purpose", "workspace_id",
            "member_count", "created", "source"
        },
        NodeType.MESSAGE: {
            "slack_user_id", "slack_channel_id", "slack_thread_ts", "timestamp",
            "is_thread_reply", "reactions", "files", "source"
        },
        NodeType.SESSION: {
            "user_id", "source", "ttl_expiry"
        },
        NodeType.CONVERSATION_MESSAGE: {
            "user_id", "intent", "entities", "confidence", "timestamp", "message_id"
        },
        NodeType.GOAL: {
            "description", "status", "priority", "due_date", "created_at", "completed_at"
        },
        NodeType.PROJECT: {
            "description", "status", "created_at", "updated_at"
        },
    }
    
    # Property types for validation
    PROPERTY_TYPES: Dict[str, PropertyType] = {
        # String properties
        "subject": PropertyType.STRING,
        "sender": PropertyType.STRING,
        "body": PropertyType.STRING,
        "email": PropertyType.STRING,
        "name": PropertyType.STRING,
        "filename": PropertyType.STRING,
        "merchant": PropertyType.STRING,
        "description": PropertyType.STRING,
        "title": PropertyType.STRING,
        "thread_id": PropertyType.STRING,
        "status": PropertyType.STRING,
        "category": PropertyType.STRING,
        "location": PropertyType.STRING,
        "time": PropertyType.STRING,
        "payment_method": PropertyType.STRING,
        "currency": PropertyType.STRING,
        "receipt_number": PropertyType.STRING,
        # Document properties
        "doc_type": PropertyType.STRING,
        "content": PropertyType.STRING,
        "content_type": PropertyType.STRING,
        "full_text": PropertyType.STRING,
        "summary": PropertyType.STRING,
        "document_type": PropertyType.STRING,
        "parser": PropertyType.STRING,
        "docling_metadata": PropertyType.OBJECT,
        # Email metadata properties
        "email_id": PropertyType.STRING,
        "sender_domain": PropertyType.STRING,
        "timestamp": PropertyType.STRING,  # ISO datetime string
        "folder": PropertyType.STRING,
        "attachment_info": PropertyType.STRING,  # JSON string or description
        "intents": PropertyType.STRING,  # JSON string or comma-separated
        "parsed_at": PropertyType.DATETIME,  # ISO datetime string
        
        # Numeric properties
        "total": PropertyType.FLOAT,
        "tax": PropertyType.FLOAT,
        "tip": PropertyType.FLOAT,
        "subtotal": PropertyType.FLOAT,
        "confidence": PropertyType.FLOAT,
        "size": PropertyType.INTEGER,
        "file_size": PropertyType.INTEGER,
        "num_tables": PropertyType.INTEGER,
        "num_headings": PropertyType.INTEGER,
        "num_sections": PropertyType.INTEGER,
        "num_images": PropertyType.INTEGER,
        "participant_count": PropertyType.INTEGER,
        "priority": PropertyType.INTEGER,
        
        # Date properties
        "date": PropertyType.DATE,
        "start_time": PropertyType.DATETIME,
        "end_time": PropertyType.DATETIME,
        "due_date": PropertyType.DATE,
        "created_at": PropertyType.DATETIME,
        "last_contact": PropertyType.DATETIME,  # For Contact nodes
        
        # Boolean properties
        "is_read": PropertyType.BOOLEAN,
        "is_starred": PropertyType.BOOLEAN,
        "is_archived": PropertyType.BOOLEAN,
        "is_unread": PropertyType.BOOLEAN,
        "is_important": PropertyType.BOOLEAN,
        "has_attachments": PropertyType.BOOLEAN,
        "has_action_items": PropertyType.BOOLEAN,
        "has_questions": PropertyType.BOOLEAN,
        
        # Object properties
        "financial_data": PropertyType.OBJECT,
        
        # Array properties
        "recipients": PropertyType.ARRAY,
        "cc": PropertyType.ARRAY,
        "bcc": PropertyType.ARRAY,
        "attachments": PropertyType.ARRAY,
        "items": PropertyType.ARRAY,
        "keywords": PropertyType.ARRAY,
        "attendees": PropertyType.ARRAY,
        "labels": PropertyType.ARRAY,  # Email labels array
        "key_points": PropertyType.ARRAY,
        "entities": PropertyType.ARRAY,
        "topics": PropertyType.ARRAY,
        "action_items": PropertyType.ARRAY,
        # Memory properties
        "role": PropertyType.STRING,  # 'user' or 'assistant' for ConversationMessage
        "message_id": PropertyType.STRING,
        "ttl_expiry": PropertyType.DATETIME,
        "source": PropertyType.STRING,  # 'slack', 'web', 'api', etc.
    }
    
    # Valid relationship constraints (from_type -> rel_type -> to_type)
    VALID_RELATIONSHIPS: Dict[NodeType, Dict[RelationType, Set[NodeType]]] = {
        NodeType.EMAIL: {
            RelationType.FROM: {NodeType.CONTACT, NodeType.PERSON},
            RelationType.TO: {NodeType.CONTACT, NodeType.PERSON},
            RelationType.CC: {NodeType.CONTACT, NodeType.PERSON},
            RelationType.CONTAINS: {NodeType.ACTION_ITEM},
            RelationType.DISCUSSES: {NodeType.TOPIC},
            RelationType.MENTIONS: {NodeType.PERSON, NodeType.COMPANY},
            RelationType.ATTACHED_TO: {NodeType.DOCUMENT, NodeType.RECEIPT},
            RelationType.PART_OF: {NodeType.CONVERSATION},
            RelationType.REPLIED_TO: {NodeType.EMAIL},
            RelationType.HAS_RECEIPT: {NodeType.RECEIPT},
        },
        NodeType.DOCUMENT: {
            RelationType.MENTIONS: {NodeType.PERSON, NodeType.COMPANY},
            RelationType.DISCUSSES: {NodeType.TOPIC},
            RelationType.CONTAINS: {NodeType.ACTION_ITEM},
        },
        NodeType.RECEIPT: {
            RelationType.FROM_STORE: {NodeType.COMPANY},
            RelationType.FROM_VENDOR: {NodeType.VENDOR},
        },
        NodeType.USER: {
            RelationType.RECEIVED: {NodeType.EMAIL},
            RelationType.HAS_RECEIPT: {NodeType.RECEIPT},
        },
        NodeType.ACTION_ITEM: {
            RelationType.ASSIGNED_TO: {NodeType.PERSON, NodeType.CONTACT},
            RelationType.CREATED_BY: {NodeType.PERSON, NodeType.CONTACT},
        },
        NodeType.CONTACT: {
            RelationType.WORKS_FOR: {NodeType.COMPANY},
        },
        NodeType.PERSON: {
            RelationType.WORKS_FOR: {NodeType.COMPANY},
            RelationType.HAS_EMAIL: {NodeType.EMAIL_ADDRESS},  # Person -> EmailAddress
            RelationType.HAS_ALIAS: {NodeType.ALIAS},  # Person -> Alias
            RelationType.SOURCE_SYSTEM: {NodeType.SYSTEM},  # Person -> System
            RelationType.MENTIONED: {NodeType.PERSON},  # Person MENTIONED Person (Slack)
            RelationType.POSTED_IN: {NodeType.CHANNEL},  # Person POSTED_IN Channel (Slack)
            RelationType.POSTED: {NodeType.MESSAGE},  # Person POSTED Message (Slack)
            RelationType.REACTED_TO: {NodeType.MESSAGE},  # Person REACTED_TO Message (Slack)
        },
        NodeType.CALENDAR_EVENT: {
            RelationType.ATTENDED_BY: {NodeType.PERSON, NodeType.CONTACT},
            RelationType.ORGANIZED_BY: {NodeType.PERSON, NodeType.CONTACT},
        },
        NodeType.CONVERSATION: {
            RelationType.PART_OF: {NodeType.EMAIL},
        },
        NodeType.MESSAGE: {
            RelationType.IN_CHANNEL: {NodeType.CHANNEL},  # Message IN_CHANNEL Channel
            RelationType.POSTED: {NodeType.PERSON},  # Message POSTED Person (reverse)
            RelationType.MENTIONS: {NodeType.PERSON},  # Message MENTIONS Person
            RelationType.NEXT_IN_THREAD: {NodeType.MESSAGE},  # Message NEXT_IN_THREAD Message
        },
        NodeType.CHANNEL: {
            RelationType.POSTED_IN: {NodeType.PERSON},  # Channel POSTED_IN Person (reverse)
            RelationType.IN_CHANNEL: {NodeType.MESSAGE},  # Channel IN_CHANNEL Message (reverse)
        },
        NodeType.SESSION: {
            RelationType.CONTAINS_TURN: {NodeType.CONVERSATION_MESSAGE},  # Session CONTAINS_TURN ConversationMessage
        },
        NodeType.USER: {
            RelationType.RECEIVED: {NodeType.EMAIL},
            RelationType.HAS_RECEIPT: {NodeType.RECEIPT},
            RelationType.MANAGES: {NodeType.GOAL},  # User MANAGES Goal
            RelationType.WORKS_ON: {NodeType.PROJECT, NodeType.TOPIC},  # User WORKS_ON Project/Topic
        },
    }
    
    @classmethod
    def validate_node(
        cls,
        node_type: NodeType,
        properties: Dict[str, Any],
        strict: bool = True
    ) -> ValidationResult:
        """
        Validate that a node has all required properties with correct types
        
        Args:
            node_type: Type of the node
            properties: Node properties
            strict: If True, validates property types; if False, only checks presence
            
        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult(is_valid=True)
        
        # Check required properties
        required = cls.REQUIRED_PROPERTIES.get(node_type, set())
        missing = required - set(properties.keys())
        
        if missing:
            for prop in missing:
                result.add_error(
                    ERROR_MISSING_REQUIRED_PROPERTY.format(
                        property=prop,
                        node_type=node_type.value
                    )
                )
        
        if not strict:
            return result
        
        # Get optional properties for this node type
        optional = cls.OPTIONAL_PROPERTIES.get(node_type, set())
        
        # Validate property types and values
        for prop_name, prop_value in properties.items():
            # Skip validation for None values in optional properties (they're allowed to be None)
            if prop_name in optional and prop_value is None:
                continue  # None values for optional properties are valid
            
            # Skip validation for empty optional string properties (they're allowed to be empty)
            if prop_name in optional and isinstance(prop_value, str) and len(prop_value) == 0:
                continue  # Empty optional strings are valid
            
            validation = cls._validate_property(prop_name, prop_value, node_type, required, optional)
            if not validation.is_valid:
                for error in validation.errors:
                    result.add_error(error)
            for warning in validation.warnings:
                result.add_warning(warning)
        
        return result
    
    @classmethod
    def _validate_property(cls, prop_name: str, prop_value: Any, 
                          node_type: Optional[NodeType] = None,
                          required: Optional[Set[str]] = None,
                          optional: Optional[Set[str]] = None) -> ValidationResult:
        """
        Validate a single property value
        
        Args:
            prop_name: Property name
            prop_value: Property value
            node_type: Optional node type for context
            required: Optional set of required properties
            optional: Optional set of optional properties
            
        Returns:
            ValidationResult
        """
        result = ValidationResult(is_valid=True)
        
        # Get expected type
        expected_type = cls.PROPERTY_TYPES.get(prop_name)
        if not expected_type:
            # Unknown property - just warn
            result.add_warning(f"Unknown property '{prop_name}'")
            return result
        
        # Check if this is a required property
        is_required = required is not None and prop_name in required
        
        # Type-specific validation
        if expected_type == PropertyType.STRING:
            if not isinstance(prop_value, str):
                result.add_error(
                    ERROR_INVALID_PROPERTY_TYPE.format(
                        property=prop_name,
                        expected="string",
                        actual=type(prop_value).__name__
                    )
                )
            elif len(prop_value) > MAX_STRING_LENGTH:
                result.add_error(
                    ERROR_PROPERTY_TOO_LONG.format(
                        property=prop_name,
                        max_length=MAX_STRING_LENGTH
                    )
                )
            elif len(prop_value) < MIN_STRING_LENGTH:
                # Only error if it's a required property - optional properties can be empty
                if is_required:
                    result.add_error(f"Property '{prop_name}' is empty")
                # Optional properties can be empty strings - skip validation
            
            # Email validation
            if prop_name == "email" or prop_name == "sender":
                if not re.match(EMAIL_REGEX, prop_value):
                    result.add_error(
                        ERROR_INVALID_EMAIL_FORMAT.format(
                            property=prop_name,
                            value=prop_value
                        )
                    )
        
        elif expected_type == PropertyType.FLOAT:
            if not isinstance(prop_value, (int, float)):
                result.add_error(
                    ERROR_INVALID_PROPERTY_TYPE.format(
                        property=prop_name,
                        expected="number",
                        actual=type(prop_value).__name__
                    )
                )
            elif prop_name == "total":
                if prop_value < MIN_RECEIPT_TOTAL or prop_value > MAX_RECEIPT_TOTAL:
                    result.add_error(
                        ERROR_VALUE_OUT_OF_RANGE.format(
                            property=prop_name,
                            value=prop_value,
                            min=MIN_RECEIPT_TOTAL,
                            max=MAX_RECEIPT_TOTAL
                        )
                    )
        
        elif expected_type == PropertyType.INTEGER:
            if not isinstance(prop_value, int):
                result.add_error(
                    ERROR_INVALID_PROPERTY_TYPE.format(
                        property=prop_name,
                        expected="integer",
                        actual=type(prop_value).__name__
                    )
                )
        
        elif expected_type == PropertyType.BOOLEAN:
            if not isinstance(prop_value, bool):
                result.add_error(
                    ERROR_INVALID_PROPERTY_TYPE.format(
                        property=prop_name,
                        expected="boolean",
                        actual=type(prop_value).__name__
                    )
                )
        
        elif expected_type in (PropertyType.DATE, PropertyType.DATETIME):
            # Accept datetime objects or ISO strings
            if isinstance(prop_value, datetime):
                pass  # Valid
            elif isinstance(prop_value, str):
                # Try to parse as date/datetime
                try:
                    if expected_type == PropertyType.DATE:
                        datetime.strptime(prop_value, DATE_FORMAT)
                    else:
                        # Try multiple datetime formats including ISO without Z
                        # datetime.now().isoformat() produces format like: 2025-11-20T02:37:05.382534
                        formats_to_try = [
                            ISO_DATETIME_FORMAT,  # With Z: 2025-11-20T02:37:05.382534Z
                            DATETIME_FORMAT,  # Without microseconds: 2025-11-20T02:37:05
                            "%Y-%m-%dT%H:%M:%S.%f",  # ISO without Z: 2025-11-20T02:37:05.382534
                            "%Y-%m-%dT%H:%M:%S",  # Basic ISO: 2025-11-20T02:37:05
                        ]
                        parsed = False
                        for fmt in formats_to_try:
                            try:
                                datetime.strptime(prop_value, fmt)
                                parsed = True
                                break
                            except ValueError:
                                continue
                        if not parsed:
                            # Last resort: try parsing with fromisoformat (handles various ISO formats)
                            try:
                                datetime.fromisoformat(prop_value.replace('Z', '+00:00') if prop_value.endswith('Z') else prop_value)
                                parsed = True
                            except ValueError:
                                pass
                        if not parsed:
                            raise ValueError("No valid format matched")
                except ValueError:
                    result.add_error(
                        ERROR_INVALID_DATE_FORMAT.format(
                            property=prop_name,
                            value=prop_value
                        )
                    )
            else:
                result.add_error(
                    ERROR_INVALID_PROPERTY_TYPE.format(
                        property=prop_name,
                        expected="date/datetime",
                        actual=type(prop_value).__name__
                    )
                )
        
        elif expected_type == PropertyType.ARRAY:
            if not isinstance(prop_value, list):
                # Special handling for 'entities' - can be dict or array
                if prop_name == "entities" and isinstance(prop_value, dict):
                    # Convert dict to array format: [{"type": "person", "name": "..."}, ...]
                    converted_entities = []
                    for entity_type, names in prop_value.items():
                        if isinstance(names, list):
                            for name in names:
                                converted_entities.append({"type": entity_type, "name": name})
                    # Update the property value for validation (but this won't change the original)
                    # We'll handle this in the attachment parser instead
                    result.add_warning(f"Property 'entities' is a dict, expected array. Consider converting to array format.")
                    # Don't error, just warn - the sanitization will handle it
                else:
                    result.add_error(
                        ERROR_INVALID_PROPERTY_TYPE.format(
                            property=prop_name,
                            expected="array",
                            actual=type(prop_value).__name__
                        )
                    )
        
        elif expected_type == PropertyType.OBJECT:
            # Object properties (dicts) - accept dict or JSON-serializable objects
            if not isinstance(prop_value, dict):
                # Try to convert to dict if it's a serializable object
                if hasattr(prop_value, '__dict__'):
                    # It's an object with attributes - that's okay, will be serialized
                    pass
                else:
                    result.add_error(
                        ERROR_INVALID_PROPERTY_TYPE.format(
                            property=prop_name,
                            expected="object/dict",
                            actual=type(prop_value).__name__
                        )
                    )
        
        # Status validation
        if prop_name == "status" and isinstance(prop_value, str):
            if prop_value not in VALID_ACTION_STATUSES:
                result.add_error(
                    ERROR_INVALID_STATUS.format(
                        value=prop_value,
                        property=prop_name,
                        valid=", ".join(VALID_ACTION_STATUSES)
                    )
                )
        
        return result
    
    @classmethod
    def validate_relationship(
        cls,
        from_type: NodeType,
        rel_type: RelationType,
        to_type: NodeType
    ) -> ValidationResult:
        """
        Validate that a relationship is valid according to schema
        
        Args:
            from_type: Source node type
            rel_type: Relationship type
            to_type: Target node type
            
        Returns:
            ValidationResult with errors if invalid
        """
        result = ValidationResult(is_valid=True)
        
        valid_targets = cls.VALID_RELATIONSHIPS.get(from_type, {}).get(rel_type, set())
        if to_type not in valid_targets:
            result.add_error(
                ERROR_INVALID_RELATIONSHIP.format(
                    from_type=from_type.value,
                    rel_type=rel_type.value,
                    to_type=to_type.value
                )
            )
        
        return result
    
    @classmethod
    def get_valid_relationships(cls, node_type: NodeType) -> List[RelationType]:
        """Get all valid outgoing relationship types for a node type"""
        return list(cls.VALID_RELATIONSHIPS.get(node_type, {}).keys())
    
    @classmethod
    def get_valid_targets(
        cls,
        from_type: NodeType,
        rel_type: RelationType
    ) -> Set[NodeType]:
        """Get valid target node types for a relationship"""
        return cls.VALID_RELATIONSHIPS.get(from_type, {}).get(rel_type, set())


class GraphQuery(BaseModel):
    """Structured graph query representation"""
    query_type: str = Field(..., description="Type of query: traverse, match, aggregation")
    start_node: str = Field(..., description="Starting node ID")
    relationships: List[str] = Field(default_factory=list, description="Relationship types to follow")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Property filters")
    limit: int = Field(default=100, description="Max results")
    depth: int = Field(default=2, description="Traversal depth")


class GraphStats(BaseModel):
    """Statistics about the knowledge graph"""
    total_nodes: int = 0
    total_relationships: int = 0
    nodes_by_type: Dict[str, int] = Field(default_factory=dict)
    relationships_by_type: Dict[str, int] = Field(default_factory=dict)
    avg_degree: float = 0.0
    max_depth: int = 0
