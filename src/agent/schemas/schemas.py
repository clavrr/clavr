"""
Structured Output Schemas for Agent Operations

Pydantic schemas for type-safe LLM responses in agent operations.
These schemas ensure consistent, validated data structures across all LLM calls.

Organization:
- Step Decomposition: Schemas for breaking queries into execution steps
- Context Extraction: Schemas for extracting context from results
- Classification: Schemas for query classification and intent detection
"""
from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field, field_validator
import re


# STEP DECOMPOSITION SCHEMAS

class StepDecompositionSchema(BaseModel):
    """
    Schema for query decomposition into execution steps.
    
    Used when breaking down multi-step queries into individual steps
    that can be executed sequentially.
    """
    step_number: int = Field(
        description="Sequential step number (1, 2, 3...)",
        ge=1
    )
    intent: Literal["email", "calendar", "task", "summarize", "general"] = Field(
        description="The domain/tool for this step",
        examples=["email", "calendar", "task"]
    )
    action: str = Field(
        description="The specific action to perform (search, send, schedule, create, etc.)",
        examples=["search", "send", "schedule", "create"]
    )
    query: str = Field(
        description="The specific part of the query for this step",
        min_length=1
    )
    description: str = Field(
        description="Brief description of what this step does",
        min_length=1
    )


class QueryDecompositionSchema(BaseModel):
    """
    Schema for complete query decomposition result.
    
    Contains a list of steps that should be executed sequentially.
    """
    steps: List[StepDecompositionSchema] = Field(
        description="List of execution steps",
        default_factory=list
    )


class EmailStepDecompositionSchema(BaseModel):
    """
    Schema for email query step decomposition.
    
    Used when breaking down complex email queries into sequential steps.
    This is a specialized version for email-specific operations.
    """
    description: str = Field(
        description="What this step does",
        min_length=1
    )
    operation: str = Field(
        description="Which operation to use (search_emails, list_emails, summarize_content, send_email, etc.)",
        examples=["search_emails", "list_emails", "summarize_content", "send_email"]
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters for the operation"
    )


class EmailStepsSchema(BaseModel):
    """
    Schema for complete email query decomposition.
    
    Contains a list of steps for email operations.
    """
    steps: List[EmailStepDecompositionSchema] = Field(
        description="List of email operation steps",
        default_factory=list
    )


# CONTEXT EXTRACTION SCHEMAS


class ContextExtractionSchema(BaseModel):
    """
    Schema for context extraction from step results.
    
    Used to extract structured information from step execution results
    for passing context to subsequent steps.
    """
    search_topic: Optional[str] = Field(
        default=None,
        description="The main topic being searched for (if applicable)"
    )
    key_findings: Optional[str] = Field(
        default=None,
        description="Important points or details found (brief summary)"
    )
    relevant_count: Optional[int] = Field(
        default=None,
        description="Number of items found (if mentioned)",
        ge=0
    )
    subjects: List[str] = Field(
        default_factory=list,
        description="List of email subjects or item titles (if any)"
    )
    important_entities: Optional[str] = Field(
        default=None,
        description="People, dates, projects mentioned (brief)"
    )
    emails: List[str] = Field(
        default_factory=list,
        description="Email addresses found in the result"
    )
    dates: List[str] = Field(
        default_factory=list,
        description="Date/time expressions found"
    )
    
    @field_validator('emails', mode='before')
    @classmethod
    def validate_emails(cls, v: Any) -> List[str]:
        """Validate and filter email addresses."""
        if not isinstance(v, list):
            return []
        
        # Basic email pattern validation
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        valid_emails = []
        for email in v:
            if isinstance(email, str) and email_pattern.match(email.strip()):
                valid_emails.append(email.strip())
        return valid_emails


# CLASSIFICATION SCHEMAS

class EmailClassificationSchema(BaseModel):
    """
    Schema for email query classification.
    
    Used to classify email-related queries and extract entities.
    Matches the pattern used by CalendarClassificationSchema.
    
    Example:
        >>> schema = EmailClassificationSchema(
        ...     intent="search",
        ...     confidence=0.95,
        ...     entities={"sender": "john@example.com", "subject": "budget"},
        ...     filters=["unread", "important"],
        ...     limit=10
        ... )
    """
    intent: Literal[
        "search",
        "send",
        "summarize",
        "list",
        "analyze",
        "delete",
        "move",
        "mark_read",
        "mark_unread"
    ] = Field(
        description="The email action intent",
        examples=["search", "send", "summarize", "list", "analyze"]
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities (sender, recipient, subject, date_range, body, attachments, etc.)"
    )
    filters: List[str] = Field(
        default_factory=list,
        description="Filters to apply (unread, starred, important, has_attachments, etc.)"
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=100
    )


class TaskClassificationSchema(BaseModel):
    """
    Schema for task query classification.
    
    Used to classify task-related queries and extract entities.
    Matches the pattern used by CalendarClassificationSchema.
    
    Example:
        >>> schema = TaskClassificationSchema(
        ...     intent="create",
        ...     confidence=0.92,
        ...     entities={"title": "Review budget", "due_date": "2025-11-20", "priority": "high"},
        ...     filters=["pending", "high_priority"],
        ...     limit=10
        ... )
    """
    intent: Literal[
        "list",
        "create",
        "update",
        "delete",
        "complete",
        "search",
        "prioritize"
    ] = Field(
        description="The task action intent",
        examples=["list", "create", "update", "delete", "complete", "search"]
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities (title, description, due_date, priority, tags, assignee, etc.)"
    )
    filters: List[str] = Field(
        default_factory=list,
        description="Filters to apply (completed, pending, overdue, today, high_priority, etc.)"
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=100
    )


class CalendarClassificationSchema(BaseModel):
    """
    Schema for calendar query classification.
    
    Used to classify calendar-related queries and extract entities.
    """
    intent: Literal[
        "list",
        "create",
        "update",
        "delete",
        "search",
        "schedule",
        "reschedule"
    ] = Field(
        description="The calendar action intent",
        examples=["list", "create", "update", "delete", "search"]
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities (title, start_time, end_time, attendees, location, etc.)"
    )
    filters: List[str] = Field(
        default_factory=list,
        description="Filters to apply (upcoming, past, today, etc.)"
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=100
    )
