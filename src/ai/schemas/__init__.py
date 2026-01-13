"""
Schemas Module - Pydantic schemas for structured LLM output

Provides type-safe schemas for all agent operations:
- Supervisor Planning: ExecutionStepSchema, SupervisorPlanSchema, DomainRoutingSchema
- Step Decomposition: StepDecompositionSchema, QueryDecompositionSchema
- Context Extraction: ContextExtractionSchema
- Classification: EmailClassificationSchema, TaskClassificationSchema, CalendarClassificationSchema
- Response: AgentResponseSchema, StreamingChunkSchema
"""

from .schemas import (
    # Supervisor Planning
    ExecutionStepSchema,
    SupervisorPlanSchema,
    DomainRoutingSchema,
    
    # Step Decomposition
    StepDecompositionSchema,
    QueryDecompositionSchema,
    EmailStepDecompositionSchema,
    EmailStepsSchema,
    
    # Context Extraction
    ContextExtractionSchema,
    
    # Classification
    BaseClassificationSchema,
    EmailClassificationSchema,
    TaskClassificationSchema,
    CalendarClassificationSchema,
    NotionClassificationSchema,
    
    # Response
    AgentResponseSchema,
    StreamingChunkSchema,
)

__all__ = [
    # Supervisor Planning
    'ExecutionStepSchema',
    'SupervisorPlanSchema',
    'DomainRoutingSchema',
    
    # Step Decomposition
    'StepDecompositionSchema',
    'QueryDecompositionSchema',
    'EmailStepDecompositionSchema',
    'EmailStepsSchema',
    
    # Context Extraction
    'ContextExtractionSchema',
    
    # Classification
    'BaseClassificationSchema',
    'EmailClassificationSchema',
    'TaskClassificationSchema',
    'CalendarClassificationSchema',
    'NotionClassificationSchema',
    
    # Response
    'AgentResponseSchema',
    'StreamingChunkSchema',
]

