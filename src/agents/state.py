"""
Agent State Management for LangGraph

Defines the unified state structure for the Clavr agent's LangGraph workflows.
This is the single source of truth for agent state used by the orchestrator.

Architecture:
- Uses TypedDict for type safety and IDE support
- Fields are optional (total=False) to allow gradual state building
- Follows LangGraph best practices: state is immutable, nodes return new state
- State is passed between nodes in the LangGraph workflow
- Supports both Orchestrator and AutonomousOrchestrator workflows

State Flow:
1. analyze_query_node: Sets intent, entities, complexity, confidence
2. plan_execution_node: Creates steps, sets planning_complete=True
3. execute_step_node: Executes steps, updates results
4. validate_result_node: Validates results, sets execution_complete=True
5. synthesize_response_node: Generates final answer from results

Example:
    initial_state = AgentState(
        messages=[HumanMessage(content="Find emails and schedule meeting")],
        query="Find emails and schedule meeting",
        steps=[],
        current_step=0,
        results=[],
        context={},
        planning_complete=False,
        execution_complete=False
    )
"""
from typing import TypedDict, List, Optional, Any, Dict, Annotated
from datetime import datetime



# ========================================================================
# Sub-structures (TypedDicts)
# ========================================================================

class SupervisorPlanStep(TypedDict, total=False):
    """
    Single step in the Supervisor's high-level plan.
    """
    step: int
    domain: str
    action: str
    query: str
    reasoning: str


class ExecutionStep(TypedDict, total=False):
    """
    Single step in the execution plan.
    """
    id: str
    step_index: int  # Explicit order tracking
    tool_name: str
    action: str
    query: str
    domain: str
    dependencies: List[str]
    status: str  # 'pending', 'in_progress', 'completed', 'failed'
    result_id: Optional[str]
    retry_count: int
    metadata: Dict[str, Any]  # Flexible metadata from agents


class StepResult(TypedDict, total=False):
    """
    Result from a single execution step.
    """
    step_id: str
    tool: str
    domain: str
    success: bool
    result: Any
    execution_time: float
    error: Optional[str]
    timestamp: str


class ReasoningLog(TypedDict, total=False):
    """
    Log entry for reasoning decisions.
    """
    step_number: int
    step_id: str
    tool_name: str
    query: str
    reasoning: str
    expected_outcome: str
    alternatives_considered: List[str]
    confidence: float
    timestamp: str


class CacheStats(TypedDict, total=False):
    """
    Cache performance statistics.
    """
    hits: int
    misses: int
    hit_rate: float


class AgentContext(TypedDict, total=False):
    """
    Context passed between steps.
    """
    complexity_level: str
    complexity_score: float
    estimated_steps: int
    is_multi_step: bool
    domains: List[str]
    execution_strategy: str
    primary_domain: str
    use_orchestration: bool
    sentiment: Optional[str]
    sentiment_score: Optional[float]
    retry_count: int
    use_fallback: bool
    total_steps: int
    final_response: Optional[str]


class AgentState(TypedDict, total=False):
    """
    Unified state structure for the Clavr LangGraph agent.
    
    This state is used by both Orchestrator and AutonomousOrchestrator to manage
    multi-step query execution.
    """
    
    # ========================================================================
    # Core Query & Messages
    # ========================================================================
    messages: Annotated[List[Any], "Conversation messages"]
    """List of conversation messages for LangChain/LangGraph compatibility"""
    
    query: str
    """Original user query text"""
    
    timestamp: Optional[str]
    """ISO timestamp when the query was received"""
    
    # ========================================================================
    # Planning & Execution Control
    # ========================================================================
    steps: List[ExecutionStep]
    """Execution plan steps"""
    
    current_step: int
    """Current step index (0-based) being executed"""
    
    planning_complete: bool
    """Whether planning phase is complete"""
    
    execution_complete: bool
    """Whether all steps have been executed"""
    
    supervisor_plan: List[SupervisorPlanStep]
    """High-level plan from SupervisorAgent"""
    
    active_agent: Optional[str]
    """Currently active domain agent (e.g. 'email', 'tasks')"""
    
    agent_outputs: Dict[str, Any]
    """Latest outputs from each domain agent"""
    
    # ========================================================================
    # Results & Context Passing
    # ========================================================================
    results: List[StepResult]
    """Results from each executed step"""
    
    reasoning_chain: List[ReasoningLog]
    """Chain of reasoning steps recorded during execution"""
    
    context: AgentContext
    """Context extracted and passed between steps"""
    
    # ========================================================================
    # Query Understanding
    # ========================================================================
    intent: Optional[str]
    """What the user is trying to do"""
    
    entities: Optional[Dict[str, Any]]
    """Important pieces extracted from the query"""
    
    confidence: Optional[float]
    """How confident we are about the intent (0.0-1.0)"""
    
    domains: Optional[List[str]]
    """List of domains detected in the query"""
    
    sentiment: Optional[str]
    """Sentiment detected in query"""
    
    sentiment_score: Optional[float]
    """Sentiment score (-1.0 to 1.0)"""
    
    # ========================================================================
    # Query Complexity
    # ========================================================================
    complexity_level: Optional[str]
    """How complex is this query? ('low', 'medium', 'high')"""
    
    complexity_score: Optional[float]
    """Numeric complexity score (0.0-1.0)"""
    
    estimated_steps: Optional[int]
    """How many steps we think this will take"""
    
    # ========================================================================
    # Response Generation
    # ========================================================================
    answer: Optional[str]
    """Final answer to return to the user"""
    
    entity_summary: Optional[str]
    """Summary of entities found in the query"""
    
    synthesized_context: Optional[Dict[str, Any]]
    """Context synthesized from entities and step results"""
    
    # ========================================================================
    # Error Handling & Recovery
    # ========================================================================
    error: Optional[str]
    """Current error message"""
    
    errors: List[str]
    """All errors encountered during execution"""
    
    has_partial_results: bool
    """Whether we have partial results despite errors"""
    
    can_recover: bool
    """Whether execution can recover and continue"""
    
    retry_count: Optional[int]
    """Number of retry attempts made"""
    
    # ========================================================================
    # User & Session Context
    # ========================================================================
    user_id: Optional[int]
    """User ID for context and permissions"""
    
    session_id: Optional[str]
    """Session ID for tracking conversations"""
    
    # ========================================================================
    # Caching & Performance
    # ========================================================================
    request_id: Optional[str]
    """Unique ID for tracking this request in the cache"""
    
    cache_stats: Optional[CacheStats]
    """How many cache hits/misses we've had"""
    
    execution_time: Optional[float]
    """Total execution time in seconds"""


def create_initial_state(
    query: str,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    messages: Optional[List[Any]] = None
) -> AgentState:
    """
    Create initial AgentState for a new query execution.
    
    Args:
        query: User query text
        user_id: Optional user ID
        session_id: Optional session ID
        messages: Optional list of LangChain messages
        
    Returns:
        Initialized AgentState with default values
    """
    # Import HumanMessage with fallback
    HumanMessage = None
    try:
        from langchain_core.messages import HumanMessage as LangChainHumanMessage
        HumanMessage = LangChainHumanMessage
    except ImportError:
        # Fallback if langchain not available
        class FallbackHumanMessage:
            def __init__(self, content: str):
                self.content = content
        HumanMessage = FallbackHumanMessage
    
    if messages is None:
        messages = [HumanMessage(content=query)]
    
    return {
        'query': query,
        'messages': messages,
        'user_id': user_id,
        'session_id': session_id,
        'timestamp': datetime.now().isoformat(),
        
        # Planning & Execution
        'steps': [],
        'current_step': 0,
        'planning_complete': False,
        'execution_complete': False,
        
        # Multi-Agent State
        'supervisor_plan': [],
        'active_agent': None,
        'agent_outputs': {},
        
        # Results & Context
        'results': [],
        'reasoning_chain': [],
        'context': {},
        
        # Query Understanding
        'intent': None,
        'entities': {},
        'confidence': None,
        'domains': None,
        'sentiment': None,
        'sentiment_score': None,
        
        # Complexity
        'complexity_level': None,
        'complexity_score': None,
        'estimated_steps': None,
        
        # Response Generation
        'answer': None,
        'entity_summary': None,
        'synthesized_context': None,
        
        # Error Handling
        'error': None,
        'errors': [],
        'has_partial_results': False,
        'can_recover': True,
        'retry_count': 0,
        
        # Performance
        'request_id': None,
        'cache_stats': None,
        'execution_time': None,
    }


def validate_state(state: AgentState) -> tuple[bool, Optional[str]]:
    """
    Validate AgentState structure and values.
    
    Args:
        state: AgentState to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check required fields
    required_fields = ['query', 'steps', 'results', 'context']
    for field in required_fields:
        if field not in state:
            return False, f"Missing required field: {field}"
    
    if not state.get('query'):
        return False, "Query cannot be empty"
    
    # Validate step structure (basic check)
    for i, step in enumerate(state.get('steps', [])):
        if not isinstance(step, dict):
            return False, f"Step {i} is not a dictionary"
        if 'id' not in step:
            return False, f"Step {i} missing 'id' field"
    
    # Validate context is dict
    if not isinstance(state.get('context', {}), dict):
        return False, "Context must be a dictionary"
    
    # Validate numeric ranges
    for field in ['complexity_score', 'confidence']:
        val = state.get(field)
        if val is not None:
            if not isinstance(val, (int, float)):
                return False, f"{field} must be numeric"
            if not (0.0 <= val <= 1.0):
                return False, f"{field} must be between 0.0 and 1.0, got {val}"
    
    # Logical Validation
    
    # 1. If execution_complete, suggest all steps should be done (warning mostly, but good to check)
    if state.get('execution_complete'):
        pending_steps = [s for s in state.get('steps', []) if s.get('status') == 'pending']
        if pending_steps:
             # This might be valid if we errored out, so we just log/allow it, 
             # but let's check if we claimed success without running steps.
             pass

    return True, None


# State Mutation Helpers (Functional Style)

def update_step_status(
    state: AgentState, 
    step_id: str, 
    status: str, 
    result_id: Optional[str] = None,
    error: Optional[str] = None
) -> AgentState:
    """
    Safely update the status of an execution step.
    Returns a NEW state dictionary (simulating immutability).
    """
    new_state = state.copy()
    steps = new_state.get('steps', [])
    updated_steps = []
    
    for step in steps:
        if step.get('id') == step_id:
            new_step = step.copy()
            new_step['status'] = status
            if result_id:
                new_step['result_id'] = result_id
            
            # If failed, maybe add to metadata
            if error and status == 'failed':
                meta = new_step.get('metadata', {}).copy()
                meta['error'] = error
                new_step['metadata'] = meta
                
            updated_steps.append(new_step)
        else:
            updated_steps.append(step)
            
    new_state['steps'] = updated_steps
    return new_state


def add_error(
    state: AgentState, 
    error_msg: str, 
    recoverable: bool = True
) -> AgentState:
    """
    Add an error to the state and update recovery flags.
    """
    new_state = state.copy()
    
    # Add to specific error field
    new_state['error'] = error_msg
    
    # Append to error list
    errors = new_state.get('errors', [])[:]
    if error_msg not in errors:
        errors.append(error_msg)
    new_state['errors'] = errors
    
    # Update recoverability
    new_state['can_recover'] = recoverable
    
    return new_state


def set_active_agent(state: AgentState, agent_name: str) -> AgentState:
    """Set the currently active domain agent."""
    new_state = state.copy()
    new_state['active_agent'] = agent_name
    return new_state


def merge_agent_output(state: AgentState, agent_name: str, output: Any) -> AgentState:
    """Merge an agent's output into the collective agent_outputs registry."""
    new_state = state.copy()
    outputs = new_state.get('agent_outputs', {}).copy()
    outputs[agent_name] = output
    new_state['agent_outputs'] = outputs
    return new_state

