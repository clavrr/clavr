"""
Agents Module

This module provides the core agent infrastructure for the Clavr platform.

Key Components:
- ClavrAgent: Main autonomous agent orchestrator (src/agents/clavr.py)
- SupervisorAgent: Multi-agent routing and coordination (src/agents/supervisor.py)
- Domain Agents: Email, Calendar, Task, Notion agents
- Intent: Query classification and entity extraction
- Roles: Specialized agent roles (Analyzer, Orchestrator, Synthesizer, etc.)
- Capabilities: NLP, Pattern Recognition, Predictive Execution, Personalization

Example Usage:
    from src.agents import SupervisorAgent
    from src.tools import EmailTool, CalendarTool, TaskTool
    
    agent = SupervisorAgent(
        tools=[EmailTool(), CalendarTool(), TaskTool()],
        config=config
    )
    
    result = await agent.execute("Find budget emails and schedule a meeting")
"""

# Core Agent
# ClavrAgent is deprecated/removed. Use SupervisorAgent.

# Supervisor
from .supervisor import SupervisorAgent

# Base Agent
from .base import BaseAgent

# State Management
from .state import AgentState, create_initial_state, validate_state

# Formatting
from ..ai.formatting import ResponseFormatter

# Intent
try:
    from ..ai.intent import (
        classify_query_intent,
        extract_entities,
        analyze_query_complexity,
    )
except ImportError:
    classify_query_intent = None
    extract_entities = None
    analyze_query_complexity = None

# Capabilities
try:
    from ..ai.capabilities import (
        NLPProcessor,
        ResponsePersonalizer,
        PatternRecognition
    )
except ImportError:
    NLPProcessor = None
    ResponsePersonalizer = None
    PatternRecognition = None

# Caching
try:
    from ..ai.caching import ComplexityAwareCache, IntentPatternsCache
except ImportError:
    ComplexityAwareCache = None
    IntentPatternsCache = None

# Schemas
try:
    from ..ai.schemas import (
        StepDecompositionSchema,
        QueryDecompositionSchema,
        ContextExtractionSchema
    )
except ImportError:
    StepDecompositionSchema = None
    QueryDecompositionSchema = None
    ContextExtractionSchema = None

# Domain Agents
try:
    from .email.agent import EmailAgent
except ImportError:
    EmailAgent = None

try:
    from .calendar.agent import CalendarAgent
except ImportError:
    CalendarAgent = None

try:
    from .tasks.agent import TaskAgent
except ImportError:
    TaskAgent = None

try:
    from .notion.agent import NotionAgent
except ImportError:
    NotionAgent = None

try:
    from .keep.agent import KeepAgent
except ImportError:
    KeepAgent = None

try:
    from .research.agent import ResearchAgent
except ImportError:
    ResearchAgent = None

try:
    from .asana.agent import AsanaAgent
except ImportError:
    AsanaAgent = None

__all__ = [
    # Core
    'SupervisorAgent',
    'BaseAgent',
    
    # State
    'AgentState',
    'create_initial_state',
    'validate_state',
    
    # Formatting
    'ResponseFormatter',
    
    # Intent
    'classify_query_intent',
    'extract_entities',
    'analyze_query_complexity',
    
    # Caching
    'ComplexityAwareCache',
    'IntentPatternsCache',
    
    # Schemas
    'StepDecompositionSchema',
    'QueryDecompositionSchema',
    'ContextExtractionSchema',
    
    # Domain Agents
    'EmailAgent',
    'CalendarAgent',
    'TaskAgent',
    'NotionAgent',
    'KeepAgent',
    'ResearchAgent',
    'AsanaAgent',
    
    # Capabilities
    'NLPProcessor',
    'ResponsePersonalizer',
    'PatternRecognition',
]

