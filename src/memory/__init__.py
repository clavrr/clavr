"""
Memory Module - Agent learning and pattern memory

Provides:
- SimplifiedMemorySystem: Basic memory system for query pattern learning
- MemoryIntegrator: Integrates memory with orchestrator execution
- create_memory_system: Factory function for creating memory systems

Perfect Memory Components (P0-P1):
- WorkingMemory: Session-scoped turn context and entity tracking
- WorkingMemoryManager: Manages working memory instances
- MemoryOrchestrator: Unified memory interface for all agents
- AssembledContext: Context assembled from all memory layers
- SalienceScorer: Memory prioritization based on multiple factors
- GoalTracker: Long-running goal and intent tracking

Domain Learning (P2):
- AgentMemoryLane: Domain-specific memory per agent
- ProactiveInjector: Push memories to agents before they ask

Long-term Polish (P3):
- MemoryConsolidationWorker: Background memory optimization
"""

from .memory_system import (
    SimplifiedMemorySystem,
    MemoryIntegrator,
    create_memory_system,
    create_memory_integrator
)

from .working_memory import (
    WorkingMemory,
    WorkingMemoryManager,
    Turn,
    PendingFact,
    get_working_memory_manager,
    init_working_memory_manager
)

from .orchestrator import (
    MemoryOrchestrator,
    AssembledContext,
    get_memory_orchestrator,
    init_memory_orchestrator
)

from .salience_scorer import (
    SalienceScorer,
    ScoredMemory,
    get_salience_scorer,
    init_salience_scorer
)

from .goal_tracker import (
    GoalTracker,
    Goal,
    GoalStatus,
    GoalPriority,
    DetectedGoal,
    get_goal_tracker,
    init_goal_tracker
)

from .agent_memory_lane import (
    AgentMemoryLane,
    AgentMemoryLaneManager,
    LearnedPattern,
    AgentFact,
    ToolUsageStats,
    get_agent_memory_lane_manager,
    init_agent_memory_lane_manager
)

from .proactive_injector import (
    ProactiveInjector,
    ProactiveMemory,
    InjectionContext,
    InjectionReason,
    get_proactive_injector,
    init_proactive_injector
)

from .consolidation_worker import (
    MemoryConsolidationWorker,
    ConsolidationResult,
    get_consolidation_worker,
    init_consolidation_worker
)

__all__ = [
    # Legacy memory system
    'SimplifiedMemorySystem',
    'MemoryIntegrator',
    'create_memory_system',
    'create_memory_integrator',
    # Perfect Memory - Working Memory
    'WorkingMemory',
    'WorkingMemoryManager',
    'Turn',
    'PendingFact',
    'get_working_memory_manager',
    'init_working_memory_manager',
    # Perfect Memory - Orchestrator
    'MemoryOrchestrator',
    'AssembledContext',
    'get_memory_orchestrator',
    'init_memory_orchestrator',
    # Perfect Memory - Salience Scoring
    'SalienceScorer',
    'ScoredMemory',
    'get_salience_scorer',
    'init_salience_scorer',
    # Perfect Memory - Goal Tracking
    'GoalTracker',
    'Goal',
    'GoalStatus',
    'GoalPriority',
    'DetectedGoal',
    'get_goal_tracker',
    'init_goal_tracker',
    # Perfect Memory - Agent Memory Lane (P2)
    'AgentMemoryLane',
    'AgentMemoryLaneManager',
    'LearnedPattern',
    'AgentFact',
    'ToolUsageStats',
    'get_agent_memory_lane_manager',
    'init_agent_memory_lane_manager',
    # Perfect Memory - Proactive Injection (P2)
    'ProactiveInjector',
    'ProactiveMemory',
    'InjectionContext',
    'InjectionReason',
    'get_proactive_injector',
    'init_proactive_injector',
    # Perfect Memory - Consolidation (P3)
    'MemoryConsolidationWorker',
    'ConsolidationResult',
    'get_consolidation_worker',
    'init_consolidation_worker',
]



