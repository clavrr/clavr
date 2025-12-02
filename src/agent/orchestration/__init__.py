"""
Orchestration Module - Multi-step reasoning and autonomous execution

This module provides two orchestration strategies:

1. **Orchestrator** - Pattern-based orchestration
   - Uses pattern matching and dependency resolution
   - Lower overhead, predictable behavior
   - Ideal for standard multi-step workflows

2. **AutonomousOrchestrator** - LangGraph + LangChain orchestration
   - Uses LangGraph state machine for workflow management
   - LangChain ReAct agent for intelligent tool selection
   - Self-correction, quality validation, error recovery
   - Ideal for complex, autonomous tasks

Example Usage:
    from agent.orchestration import create_orchestrator, create_autonomous_orchestrator
    
    # Pattern-based
    orch = create_orchestrator(tools, config)
    result = await orch.execute_query("Find emails about budget")
    
    # Autonomous
    auto_orch = create_autonomous_orchestrator(tools, config)
    result = await auto_orch.execute_query("Find emails and create tasks")

Module Structure:
    - core/          : Main orchestrators and base classes
    - components/    : Reusable orchestration components
    - handlers/      : Specialized query handlers
    - config/        : Configuration classes
    - domain/        : Domain detection and routing
"""

# Import from refactored structure (backward compatible)
from .core import (
    ExecutionStep,
    ExecutionStatus,
    ToolDependency,
    OrchestrationResult,
    ContextEnrichment,
    Orchestrator,
    AutonomousOrchestrator,
    create_orchestrator,
    create_autonomous_orchestrator
)

from .config import (
    OrchestratorConfig,
    AutonomousOrchestratorConfig,
    SynthesisConfig,
    CrossDomainConfig,
    DomainValidationConfig
)

from .components import (
    QueryDecomposer,
    ExecutionPlanner,
    ContextSynthesizer
)

from .handlers import (
    CrossDomainHandler,
    ScheduleQueryHandler,
    TimeQueryHandler
)

from .domain import (
    Domain,
    DomainValidator,
    ToolDomainConfig,
    get_tool_domain_config,
    get_routing_analytics,
    RoutingOutcome
)

# Public API
__all__ = [
    # Base types
    'ExecutionStep',
    'ExecutionStatus',
    'ToolDependency',
    'OrchestrationResult',
    'ContextEnrichment',
    
    # Configuration
    'OrchestratorConfig',
    'AutonomousOrchestratorConfig',
    'SynthesisConfig',
    'CrossDomainConfig',
    'DomainValidationConfig',
    
    # Components
    'QueryDecomposer',
    'ExecutionPlanner',
    'ContextSynthesizer',
    
    # Handlers
    'CrossDomainHandler',
    'ScheduleQueryHandler',
    'TimeQueryHandler',
    
    # Domain
    'Domain',
    'DomainValidator',
    'ToolDomainConfig',
    'get_tool_domain_config',
    'get_routing_analytics',
    'RoutingOutcome',
    
    # Orchestrators
    'Orchestrator',
    'AutonomousOrchestrator',
    
    # Factory functions (recommended)
    'create_orchestrator',
    'create_autonomous_orchestrator'
]
