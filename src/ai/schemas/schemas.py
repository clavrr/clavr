"""
Structured Output Schemas for Agent Operations

Pydantic schemas for type-safe LLM responses in agent operations.
These schemas ensure consistent, validated data structures across all LLM calls.

Organization:
- Supervisor Schemas: Planning and routing for SupervisorAgent
- Step Decomposition: Schemas for breaking queries into execution steps
- Context Extraction: Schemas for extracting context from results
- Classification: Schemas for query classification and intent detection
- Role Schemas: Output schemas for specialized agent roles
"""
from typing import Dict, Any, Optional, List, Literal, Union
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
import re

# Import centralized constants
from src.agents.constants import VALID_DOMAINS, VALID_ACTIONS

# Shared Constants
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


# SUPERVISOR PLANNING SCHEMAS


class ExecutionStepSchema(BaseModel):
    """
    Schema for a single execution step in a multi-step plan.
    
    Used by SupervisorAgent for planning query execution.
    """
    step_id: str = Field(
        description="Unique identifier for this step (e.g., 'step_1', 'step_2')"
    )
    domain: Literal["email", "calendar", "task", "notion", "general"] = Field(
        description="Which domain agent handles this step"
    )
    action: str = Field(
        description="Specific action to perform (search, create, list, etc.)"
    )
    query: str = Field(
        description="The natural language query for this step",
        min_length=1
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="List of step IDs this step depends on"
    )
    priority: int = Field(
        default=1,
        description="Execution priority (1=highest)",
        ge=1,
        le=10
    )


class SupervisorPlanSchema(BaseModel):
    """
    Schema for SupervisorAgent's complete execution plan.
    
    Contains ordered steps for multi-step query execution.
    """
    original_query: str = Field(
        description="The original user query"
    )
    is_multi_step: bool = Field(
        default=False,
        description="Whether this requires multiple steps"
    )
    steps: List[ExecutionStepSchema] = Field(
        default_factory=list,
        description="Ordered list of execution steps"
    )
    estimated_duration_ms: Optional[int] = Field(
        default=None,
        description="Estimated execution time in milliseconds"
    )


class DomainRoutingSchema(BaseModel):
    """
    Schema for SupervisorAgent's domain routing decision.
    
    Determines which domain agent should handle a query.
    """
    domain: Literal["email", "calendar", "task", "notion", "general"] = Field(
        description="Primary domain for this query"
    )
    confidence: float = Field(
        description="Confidence in routing decision (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    reasoning: str = Field(
        description="Brief explanation of routing decision"
    )
    fallback_domain: Optional[str] = Field(
        default=None,
        description="Alternative domain if primary fails"
    )


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
    """
    description: str = Field(
        description="What this step does",
        min_length=1
    )
    operation: str = Field(
        description="Which operation to use",
        examples=["search_emails", "list_emails", "summarize_content", "send_email"]
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters for the operation"
    )


class EmailStepsSchema(BaseModel):
    """Complete email query decomposition."""
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
        description="The main topic being searched for"
    )
    key_findings: Optional[str] = Field(
        default=None,
        description="Important points or details found"
    )
    relevant_count: Optional[int] = Field(
        default=None,
        description="Number of items found",
        ge=0
    )
    subjects: List[str] = Field(
        default_factory=list,
        description="List of email subjects or item titles"
    )
    important_entities: Optional[str] = Field(
        default=None,
        description="People, dates, projects mentioned"
    )
    emails: List[str] = Field(
        default_factory=list,
        description="Email addresses found"
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
        return [
            email.strip() for email in v
            if isinstance(email, str) and EMAIL_PATTERN.match(email.strip())
        ]


# CLASSIFICATION SCHEMAS

class BaseClassificationSchema(BaseModel):
    """Base schema for query classification."""
    confidence: float = Field(
        description="Confidence score (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities"
    )
    filters: List[str] = Field(
        default_factory=list,
        description="Filters to apply"
    )
    limit: int = Field(
        default=10,
        description="Maximum results",
        ge=1,
        le=100
    )


class EmailClassificationSchema(BaseClassificationSchema):
    """Schema for email query classification."""
    intent: Literal[
        "search", "send", "summarize", "list", "analyze",
        "delete", "move", "mark_read", "mark_unread", "reply"
    ] = Field(description="Email action intent")


class TaskClassificationSchema(BaseClassificationSchema):
    """Schema for task query classification."""
    intent: Literal[
        "list", "create", "update", "delete", "complete",
        "search", "prioritize", "get_overdue"
    ] = Field(description="Task action intent")


class CalendarClassificationSchema(BaseClassificationSchema):
    """Schema for calendar query classification."""
    intent: Literal[
        "list", "create", "update", "delete", "search",
        "schedule", "reschedule", "find_free_time"
    ] = Field(description="Calendar action intent")


class NotionClassificationSchema(BaseClassificationSchema):
    """Schema for Notion query classification."""
    intent: Literal[
        "search", "create_page", "update_page", "list_pages",
        "add_to_database", "query_database"
    ] = Field(description="Notion action intent")





# RESPONSE SCHEMAS 

class AgentResponseSchema(BaseModel):
    """Standard response schema for agent operations."""
    success: bool = Field(description="Whether operation succeeded")
    result: Optional[Any] = Field(default=None, description="Operation result")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: Optional[float] = Field(default=None)


class StreamingChunkSchema(BaseModel):
    """Schema for streaming response chunks."""
    chunk_type: Literal["text", "status", "result", "error"] = Field(
        description="Type of chunk"
    )
    content: str = Field(description="Chunk content")
    is_final: bool = Field(default=False)
    metadata: Dict[str, Any] = Field(default_factory=dict)
