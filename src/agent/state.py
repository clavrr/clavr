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


class AgentState(TypedDict, total=False):
    """
    Unified state structure for the Clavr LangGraph agent.
    
    This state is used by both Orchestrator and AutonomousOrchestrator to manage
    multi-step query execution. The state flows through the graph nodes:
    
    - analyze_query_node: Analyzes query intent, entities, complexity
    - plan_execution_node: Creates execution plan with steps
    - execute_step_node: Executes individual steps sequentially
    - validate_result_node: Validates step results
    - synthesize_response_node: Generates final response from results
    
    All fields are optional to allow gradual state building as the workflow progresses.
    
    Fields are organized into logical groups:
    - Core Query & Messages: Basic query information
    - Planning & Execution: Step planning and execution tracking
    - Results & Context: Execution results and context passing
    - Query Understanding: Intent, entities, complexity analysis
    - Response Generation: Final answer and synthesis
    - Error Handling: Error tracking and recovery
    - User & Session: User context and session tracking
    - Performance & Analytics: Caching, timing, metrics
    """
    
    # ========================================================================
    # Core Query & Messages
    # ========================================================================
    messages: Annotated[List[Any], "Conversation messages (HumanMessage, AIMessage, etc.)"]
    """List of conversation messages for LangChain/LangGraph compatibility"""
    
    query: str
    """Original user query text"""
    
    timestamp: Optional[str]
    """ISO timestamp when the query was received"""
    
    # ========================================================================
    # Planning & Execution Control
    # ========================================================================
    steps: List[Dict[str, Any]]
    """Execution plan steps (from query decomposition). Each step is a dict with:
    - id: Unique step identifier
    - tool_name: Tool to execute (e.g., 'email', 'calendar', 'notion')
    - action: Action to perform (e.g., 'search', 'create', 'update')
    - query: Natural language query for this step
    - domain: Domain classification (e.g., 'email', 'task', 'calendar', 'notion')
    - dependencies: List of step IDs this step depends on
    - status: Execution status ('pending', 'in_progress', 'completed', 'failed')
    """
    
    current_step: int
    """Current step index (0-based) being executed"""
    
    planning_complete: bool
    """Whether planning phase is complete (all steps created)"""
    
    execution_complete: bool
    """Whether all steps have been executed"""
    
    # ========================================================================
    # Results & Context Passing
    # ========================================================================
    results: List[Dict[str, Any]]
    """Results from each executed step. Each result dict contains:
    - success: bool - Whether step executed successfully
    - result: Any - Step execution result
    - step_id: str - ID of the step that produced this result
    - execution_time: float - Time taken to execute (seconds)
    - domain: str - Domain of the step (e.g., 'email', 'calendar')
    - tool: str - Tool name used
    """
    
    context: Dict[str, Any]
    """Context extracted and passed between steps. Contains:
    - complexity_level: str - Query complexity ('low', 'medium', 'high')
    - complexity_score: float - Numeric complexity score (0.0-1.0)
    - estimated_steps: int - Estimated number of execution steps
    - is_multi_step: bool - Whether query requires multiple steps
    - domains: List[str] - Detected domains (e.g., ['email', 'calendar'])
    - execution_strategy: str - Execution strategy ('parallel', 'sequential', etc.)
    - primary_domain: str - Primary domain detected
    - use_orchestration: bool - Whether orchestration should be used
    - sentiment: Optional[str] - Sentiment detected in query
    - sentiment_score: Optional[float] - Sentiment score
    - retry_count: int - Number of retry attempts
    - use_fallback: bool - Whether fallback strategy is being used
    - total_steps: int - Total number of steps in plan
    - final_response: Optional[str] - Final synthesized response
    """
    
    # ========================================================================
    # Query Understanding
    # ========================================================================
    intent: Optional[str]
    """What the user is trying to do (e.g., 'search', 'create', 'schedule')"""
    
    entities: Optional[Dict[str, Any]]
    """Important pieces extracted from the query. Contains:
    - time_references: List[str] - Time expressions found
    - priorities: List[str] - Priority indicators found
    - actions: List[str] - Actions detected
    - domains: List[str] - Domains detected
    - Additional domain-specific entities (e.g., 'sender', 'subject' for email)
    """
    
    confidence: Optional[float]
    """How confident we are about the intent (0.0-1.0)"""
    
    domains: Optional[List[str]]
    """List of domains detected in the query (e.g., ['email', 'calendar', 'notion'])"""
    
    sentiment: Optional[str]
    """Sentiment detected in query (e.g., 'positive', 'negative', 'neutral')"""
    
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
    """Summary of entities found in the query (for context-aware responses)"""
    
    synthesized_context: Optional[Dict[str, Any]]
    """Context synthesized from entities and step results for better responses.
    Contains cross-domain enrichments and extracted context from results."""
    
    # ========================================================================
    # Error Handling & Recovery
    # ========================================================================
    error: Optional[str]
    """Current error message (single error at a time)"""
    
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
    
    cache_stats: Optional[Dict[str, Any]]
    """How many cache hits/misses we've had. Contains:
    - hits: int - Number of cache hits
    - misses: int - Number of cache misses
    - hit_rate: float - Cache hit rate (0.0-1.0)
    """
    
    execution_time: Optional[float]
    """Total execution time in seconds"""
    
    # ========================================================================
    # Deprecated Fields (kept for backward compatibility, will be removed)
    # ========================================================================
    selected_tools: Optional[List[str]]
    """DEPRECATED: Tools now tracked in steps. Use steps[].tool_name instead."""
    
    tool_params: Optional[Dict[str, Any]]
    """DEPRECATED: Params now in steps. Use steps[].query and steps[].action instead."""
    
    tool_results: Optional[Dict[str, Any]]
    """DEPRECATED: Results now in results list. Use results[] instead."""
    
    metadata: Optional[Dict[str, Any]]
    """DEPRECATED: Extra metadata. Use context instead."""
    
    next_action: Optional[str]
    """DEPRECATED: LangGraph manages routing automatically."""
    
    needs_clarification: Optional[bool]
    """DEPRECATED: Not used in current implementation."""
    
    clarification_prompt: Optional[str]
    """DEPRECATED: Not used in current implementation."""


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
        messages: Optional list of LangChain messages (will create HumanMessage if not provided)
        
    Returns:
        Initialized AgentState with default values
        
    Example:
        state = create_initial_state(
            query="Find emails about budget",
            user_id=123,
            session_id="session_456"
        )
    """
    try:
        from langchain_core.messages import HumanMessage
    except ImportError:
        # Fallback if langchain not available
        class HumanMessage:
            def __init__(self, content: str):
                self.content = content
    
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
        
        # Results & Context
        'results': [],
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
        
        # Deprecated (kept for compatibility)
        'selected_tools': [],
        'tool_params': {},
        'tool_results': {},
        'metadata': None,
        'next_action': None,
        'needs_clarification': False,
        'clarification_prompt': None,
    }


def validate_state(state: AgentState) -> tuple[bool, Optional[str]]:
    """
    Validate AgentState structure and values.
    
    Args:
        state: AgentState to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        is_valid, error = validate_state(state)
        if not is_valid:
            logger.error(f"Invalid state: {error}")
    """
    # Check required fields
    if 'query' not in state or not state['query']:
        return False, "Missing required field: query"
    
    if 'steps' not in state:
        return False, "Missing required field: steps"
    
    if 'results' not in state:
        return False, "Missing required field: results"
    
    if 'context' not in state:
        return False, "Missing required field: context"
    
    # Validate step structure
    for i, step in enumerate(state.get('steps', [])):
        if not isinstance(step, dict):
            return False, f"Step {i} is not a dictionary"
        
        if 'id' not in step:
            return False, f"Step {i} missing 'id' field"
        
        if 'tool_name' not in step:
            return False, f"Step {i} missing 'tool_name' field"
    
    # Validate results structure
    for i, result in enumerate(state.get('results', [])):
        if not isinstance(result, dict):
            return False, f"Result {i} is not a dictionary"
    
    # Validate context is dict
    if not isinstance(state.get('context', {}), dict):
        return False, "Context must be a dictionary"
    
    # Validate complexity score range
    complexity_score = state.get('complexity_score')
    if complexity_score is not None:
        if not isinstance(complexity_score, (int, float)):
            return False, "complexity_score must be numeric"
        if not (0.0 <= complexity_score <= 1.0):
            return False, f"complexity_score must be between 0.0 and 1.0, got {complexity_score}"
    
    # Validate confidence range
    confidence = state.get('confidence')
    if confidence is not None:
        if not isinstance(confidence, (int, float)):
            return False, "confidence must be numeric"
        if not (0.0 <= confidence <= 1.0):
            return False, f"confidence must be between 0.0 and 1.0, got {confidence}"
    
    return True, None
