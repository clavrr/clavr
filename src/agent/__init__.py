"""
Agent and Orchestration Module

This module provides the core agent infrastructure for the Clavr platform, implementing
autonomous multi-step task execution using LangGraph and LangChain.

Key Components:
- ClavrAgent: Main autonomous agent orchestrator
- Orchestration: Multi-step workflow execution engines
- Roles: Specialized agent roles (Analyzer, Orchestrator, Synthesizer, Memory, etc.)
- Capabilities: Advanced capabilities (NLP, Predictive, Pattern Recognition, Personalization)
- Parsers: Domain-specific query parsers (email, calendar, task, notion)
- State Management: Unified state structure for LangGraph workflows

Architecture:
The agent follows industry-leading patterns:
- LangGraph state machines for multi-step workflows
- Pure node functions with immutable state
- Autonomous execution without user confirmation
- Intelligent context passing between steps
- Graceful error recovery and partial results
- Role-based architecture with capabilities
- Parser-based query understanding

Example Usage:
    from src.agent import ClavrAgent
    from src.tools import EmailTool, CalendarTool, TaskTool
    
    agent = ClavrAgent(
        tools=[EmailTool(), CalendarTool(), TaskTool()],
        config=config
    )
    
    result = await agent.execute("Find budget emails and schedule a meeting")
"""

# Core Agent
from .clavr_agent import ClavrAgent
from .state import AgentState, create_initial_state, validate_state
from .formatting import ResponseFormatter

# Caching
from .caching import ComplexityAwareCache, IntentPatternsCache

# Memory
from .memory import SimplifiedMemorySystem, MemoryIntegrator, create_memory_system

# Intent
from .intent import (
    classify_query_intent,
    extract_entities,
    analyze_query_complexity,
    recommend_tools,
    should_use_orchestration,
    get_execution_strategy
)

# Utilities
from .utils import (
    extract_query_entities,
    get_query_domain,
    get_query_domains,
    format_multi_step_response,
    clean_response_text,
    has_task_keywords,
    has_calendar_keywords,
    has_email_keywords,
    has_notion_keywords,
    is_multi_domain_query,
    should_not_decompose_query,
    truncate_text,
    normalize_query
)

# Events
from .events import WorkflowEventEmitter, WorkflowEventType, create_workflow_emitter

# Schemas
from .schemas import (
    StepDecompositionSchema,
    QueryDecompositionSchema,
    ContextExtractionSchema
)

# Orchestration (import only what's needed to avoid circular imports)
try:
    from .orchestration import (
        Orchestrator,
        AutonomousOrchestrator,
        create_orchestrator,
        create_autonomous_orchestrator,
        OrchestratorConfig,
        ExecutionStep,
        OrchestrationResult
    )
except ImportError as e:
    # Graceful fallback if orchestration not available
    Orchestrator = None
    AutonomousOrchestrator = None
    create_orchestrator = None
    create_autonomous_orchestrator = None
    OrchestratorConfig = None
    ExecutionStep = None
    OrchestrationResult = None

# Roles (import only what's needed)
try:
    from .roles import (
        AnalyzerRole,
        OrchestratorRole,
        SynthesizerRole,
        MemoryRole,
        ResearcherRole,
        ContactResolverRole,
        DomainSpecialistRole,
        EmailSpecialistRole,
        CalendarSpecialistRole,
        TaskSpecialistRole,
        NotionSpecialistRole
    )
except ImportError as e:
    # Graceful fallback
    AnalyzerRole = None
    OrchestratorRole = None
    SynthesizerRole = None
    MemoryRole = None
    ResearcherRole = None
    ContactResolverRole = None
    DomainSpecialistRole = None
    EmailSpecialistRole = None
    CalendarSpecialistRole = None
    TaskSpecialistRole = None
    NotionSpecialistRole = None

# Capabilities (import only what's needed)
try:
    from .capabilities import (
        NLPProcessor,
        PredictiveExecutor,
        PatternRecognition,
        ResponsePersonalizer
    )
except ImportError as e:
    # Graceful fallback
    NLPProcessor = None
    PredictiveExecutor = None
    PatternRecognition = None
    ResponsePersonalizer = None

# Parsers (import only what's needed)
try:
    from .parsers import (
        BaseParser,
        EmailParser,
        CalendarParser,
        TaskParser,
        NotionParser
    )
except ImportError as e:
    # Graceful fallback
    BaseParser = None
    EmailParser = None
    CalendarParser = None
    TaskParser = None
    NotionParser = None

__all__ = [
    # Core Agent
    'ClavrAgent',
    'AgentState',
    'create_initial_state',
    'validate_state',
    'ResponseFormatter',
    
    # Caching
    'ComplexityAwareCache',
    'IntentPatternsCache',
    
    # Memory
    'SimplifiedMemorySystem',
    'MemoryIntegrator',
    'create_memory_system',
    
    # Intent
    'classify_query_intent',
    'extract_entities',
    'analyze_query_complexity',
    'recommend_tools',
    'should_use_orchestration',
    'get_execution_strategy',
    
    # Events
    'WorkflowEventEmitter',
    'WorkflowEventType',
    'create_workflow_emitter',
    
    # Schemas
    'StepDecompositionSchema',
    'QueryDecompositionSchema',
    'ContextExtractionSchema',
    'NotionClassificationSchema',
    
    # Orchestration
    'Orchestrator',
    'AutonomousOrchestrator',
    'create_orchestrator',
    'create_autonomous_orchestrator',
    'OrchestratorConfig',
    'ExecutionStep',
    'OrchestrationResult',
    
    # Roles
    'AnalyzerRole',
    'OrchestratorRole',
    'SynthesizerRole',
    'MemoryRole',
    'ResearcherRole',
    'ContactResolverRole',
    'DomainSpecialistRole',
    'EmailSpecialistRole',
    'CalendarSpecialistRole',
    'TaskSpecialistRole',
    'NotionSpecialistRole',
    
    # Capabilities
    'NLPProcessor',
    'PredictiveExecutor',
    'PatternRecognition',
    'ResponsePersonalizer',
    
    # Parsers
    'BaseParser',
    'EmailParser',
    'CalendarParser',
    'TaskParser',
    'NotionParser',
    
    # Utilities
    'extract_query_entities',
    'get_query_domain',
    'get_query_domains',
    'format_multi_step_response',
    'clean_response_text',
    'has_task_keywords',
    'has_calendar_keywords',
    'has_email_keywords',
    'has_notion_keywords',
    'is_multi_domain_query',
    'should_not_decompose_query',
]
