"""
Autonomous Orchestrator - LangGraph + LangChain Integration

A highly autonomous agent using:
- LangGraph StateGraph for workflow management
- LangChain ReAct agent for intelligent tool selection
- Self-correction and error recovery
- Quality validation and result refinement

This module is kept separate for clarity and optional usage.
"""

from datetime import datetime
from typing import List, Any, Optional, TYPE_CHECKING

from ....utils.logger import setup_logger
from ...state import AgentState
from .base import OrchestrationResult
from ..components.query_decomposer import QueryDecomposer
from ..components.execution_planner import ExecutionPlanner
from ..components.context_synthesizer import ContextSynthesizer
from ..config.autonomous_config import AutonomousOrchestratorConfig

# LangGraph imports
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

# LangChain imports
from langchain.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig

# Utils imports
from ...utils import extract_query_entities, get_query_domain, format_multi_step_response

# Import intent_patterns
from ...intent import (
    classify_query_intent,
    extract_entities,
    analyze_query_complexity,
    get_execution_strategy,
    should_use_orchestration,
    recommend_tools
)

# Import enhancement modules
from ...caching import IntentPatternsCache, ComplexityAwareCache
from ..components.context_synthesizer import ContextSynthesizer
from ..config import LOG_INFO, LOG_ERROR, LOG_OK, LOG_WARNING
from ....ai.llm_factory import LLMFactory

logger = setup_logger(__name__)


class AutonomousOrchestrator:
    """
    Highly Autonomous Agent Orchestrator
    
    Features:
    - LangGraph StateGraph for autonomous workflow
    - LangChain ReAct agent for tool selection
    - Self-correction and error recovery
    - Adaptive execution planning
    - Quality validation and refinement
    """
    
    def __init__(self,
                 tools: List[Any],
                 config=None,
                 db: Optional[Any] = None,
                 memory_system: Optional[Any] = None,
                 checkpointer: Optional[AsyncPostgresSaver] = None,
                 rag_engine: Optional[Any] = None,
                 graph_manager: Optional[Any] = None):
        self.tools = {tool.name: tool for tool in tools}
        self.tools_list = tools
        self.config = config
        self.db = db
        self.memory_system = memory_system
        self.checkpointer = checkpointer
        
        # Initialize LLM client
        self.llm_client = self._init_llm_client()
        
        # Initialize RAG engine and graph manager if not provided
        self.rag_engine = rag_engine or self._init_rag_engine()
        self.graph_manager = graph_manager or self._init_graph_manager()
        
        # Initialize components
        self.query_decomposer = QueryDecomposer(self.llm_client)
        self.context_synthesizer = ContextSynthesizer(llm_client=self.llm_client)
        self.execution_planner = ExecutionPlanner(self.tools)
        
        # Initialize AnalyzerRole with NLPProcessor capability
        try:
            from ...roles.analyzer_role import AnalyzerRole
            self.analyzer_role = AnalyzerRole(config=config)
            logger.info(f"{LOG_OK} AnalyzerRole with capabilities initialized")
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Could not initialize AnalyzerRole: {e}")
            self.analyzer_role = None
        
        # Initialize ResearcherRole for knowledge base queries
        try:
            from ...roles.researcher_role import ResearcherRole
            self.researcher_role = ResearcherRole(
                rag_engine=self.rag_engine,
                graph_manager=self.graph_manager,
                config=config
            )
            logger.info(f"{LOG_OK} ResearcherRole initialized")
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Could not initialize ResearcherRole: {e}")
            self.researcher_role = None
        
        # Initialize ContactResolverRole for contact resolution
        try:
            from ...roles.contact_resolver_role import ContactResolverRole
            # Get email_service from email_tool if available
            email_service = None
            email_tool = self.tools.get('email')
            if email_tool and hasattr(email_tool, 'email_service'):
                email_service = email_tool.email_service
            
            self.contact_resolver_role = ContactResolverRole(
                slack_client=None,  # Can be set later if Slack integration is available
                graph_manager=self.graph_manager,
                email_service=email_service,
                config=config
            )
            logger.info(f"{LOG_OK} ContactResolverRole initialized")
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Could not initialize ContactResolverRole: {e}")
            self.contact_resolver_role = None
        
        # Initialize tool adapter after roles are set up
        from .tool_adapter import ToolAdapter
        self.tool_adapter = ToolAdapter(
            tools=self.tools,
            contact_resolver_role=self.contact_resolver_role,
            researcher_role=self.researcher_role
        )
        
        # Initialize OrchestratorRole with PredictiveExecutor capability for planning
        try:
            from ...roles.orchestrator_role import OrchestratorRole
            self.orchestrator_role = OrchestratorRole(
                config=config,
                tools=list(self.tools.values())
            )
            logger.info(f"{LOG_OK} OrchestratorRole with capabilities initialized")
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Could not initialize OrchestratorRole: {e}")
            self.orchestrator_role = None
        
        # Initialize SynthesizerRole with capabilities for response personalization
        try:
            from ...roles.synthesizer_role import SynthesizerRole
            self.synthesizer_role = SynthesizerRole(config=config)
            logger.info(f"{LOG_OK} SynthesizerRole with capabilities initialized")
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Could not initialize SynthesizerRole: {e}")
            self.synthesizer_role = None
        
        # Initialize MemoryRole with PatternRecognition capability
        try:
            from ...roles.memory_role import MemoryRole
            self.memory_role = MemoryRole(config=config, db=db)
            logger.info(f"{LOG_OK} MemoryRole with PatternRecognition capability initialized")
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Could not initialize MemoryRole: {e}")
            self.memory_role = None
        
        # Initialize cross-domain handler for multi-domain queries
        try:
            from .cross_domain_handler import CrossDomainHandler
            self.cross_domain_handler = CrossDomainHandler(
                enable_parallel_execution=True,
                synthesizer_role=self.synthesizer_role,
                analyzer_role=self.analyzer_role,
                config=config
            )
            logger.info(f"{LOG_OK} Cross-domain handler initialized")
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Could not initialize CrossDomainHandler: {e}")
            self.cross_domain_handler = None
        
        # Initialize enhancement modules
        self.intent_cache = IntentPatternsCache()
        self.response_cache = ComplexityAwareCache(enable_high_complexity_cache=False)
        # Note: Using same ContextSynthesizer instance (no separate enhanced version needed)
        logger.info(f"{LOG_OK} Enhancements enabled for LangGraph orchestrator")
        
        # Build LangGraph workflow
        self.workflow = self._build_langgraph_workflow()
        
        logger.info(f"{LOG_OK} AutonomousOrchestrator initialized with {len(tools)} tools and all agent roles")
    
    def _init_llm_client(self):
        """Initialize LLM client using AutonomousOrchestratorConfig"""
        return LLMFactory.get_llm_for_provider(
            self.config,
            temperature=AutonomousOrchestratorConfig.LLM_TEMPERATURE,
            max_tokens=AutonomousOrchestratorConfig.LLM_MAX_TOKENS
        )
    
    def _init_rag_engine(self):
        """Initialize RAG engine if available"""
        try:
            from api.dependencies import AppState
            return AppState.get_rag_engine()
        except Exception as e:
            logger.debug(f"RAG engine not available: {e}")
            return None
    
    def _init_graph_manager(self):
        """Initialize graph manager if available"""
        try:
            from ...services.indexing.graph.manager import KnowledgeGraphManager
            return KnowledgeGraphManager(config=self.config)
        except Exception as e:
            logger.debug(f"Graph manager not available: {e}")
            return None
    
    def _build_langgraph_workflow(self):
        """Build LangGraph state machine"""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("analyze_query", self._analyze_query_node)
        workflow.add_node("plan_execution", self._plan_execution_node)
        workflow.add_node("execute_step", self._execute_step_node)
        workflow.add_node("validate_result", self._validate_result_node)
        workflow.add_node("error_recovery", self._error_recovery_node)
        workflow.add_node("synthesize_response", self._synthesize_response_node)
        
        # Set entry point
        workflow.set_entry_point("analyze_query")
        
        # Add conditional edges
        workflow.add_conditional_edges(
            "analyze_query",
            self._route_after_analysis,
            {
                "single_step": "execute_step",
                "multi_step": "plan_execution",
                "error": "error_recovery"
            }
        )
        
        workflow.add_edge("plan_execution", "execute_step")
        
        workflow.add_conditional_edges(
            "execute_step",
            self._route_after_execution,
            {
                "continue": "validate_result",
                "retry": "execute_step",
                "error": "error_recovery",
                "next_step": "execute_step",
                "done": "validate_result"
            }
        )
        
        workflow.add_conditional_edges(
            "validate_result",
            self._route_after_validation,
            {
                "accept": "synthesize_response",
                "refine": "execute_step",
                "retry": "error_recovery",
                "done": "synthesize_response"
            }
        )
        
        workflow.add_edge("error_recovery", "execute_step")
        workflow.add_edge("synthesize_response", END)
        
        # Compile workflow
        if self.checkpointer:
            return workflow.compile(checkpointer=self.checkpointer)
        else:
            return workflow.compile()
    
    # LangGraph Nodes
    async def _analyze_query_node(self, state: AgentState) -> AgentState:
        """Analyze query to determine execution strategy"""
        logger.info(f"{LOG_INFO} [ANALYZE] Analyzing query")
        
        # Initialize errors list if not present
        if 'errors' not in state:
            state['errors'] = []
        
        # Initialize context dict if not present
        if 'context' not in state:
            state['context'] = {}
        
        try:
            query = state['query']
            
            # Pre-processing: Text normalization (first line of defense)
            try:
                from ...preprocessing.text_normalizer import TextNormalizer
                normalizer = TextNormalizer()
                normalization_result = normalizer.normalize(query)
                
                if normalization_result['was_modified']:
                    logger.info(
                        f"{LOG_INFO} [NORMALIZE] Query normalized: "
                        f"'{normalization_result['original_text']}' -> "
                        f"'{normalization_result['normalized_text']}' "
                        f"(confidence: {normalization_result['confidence']:.2f})"
                    )
                    # Use normalized text for processing
                    query = normalization_result['normalized_text']
                    state['query'] = query
                    state['context']['normalization_applied'] = True
                    state['context']['normalization_result'] = normalization_result
                else:
                    state['context']['normalization_applied'] = False
            except Exception as e:
                logger.debug(f"Text normalization failed (non-critical): {e}")
                state['context']['normalization_applied'] = False
            
            # Initialize request-level cache
            request_id = f"req_{datetime.now().timestamp()}"
            self.intent_cache.new_request(request_id)
            state['request_id'] = request_id
            logger.info(f"{LOG_INFO} [CACHE] Request cache initialized: {request_id}")
            
            # Use AnalyzerRole for query analysis if available
            query_analysis = None
            if self.analyzer_role:
                try:
                    query_analysis = await self.analyzer_role.analyze(query)
                    # Store analysis results in state
                    state['intent'] = query_analysis.intent
                    state['confidence'] = query_analysis.confidence
                    state['entities'] = {
                        'entities': query_analysis.extracted_entities,
                        'keywords': query_analysis.keywords
                    }
                    state['complexity_level'] = 'high' if query_analysis.complexity_score > 0.7 else 'medium' if query_analysis.complexity_score > 0.4 else 'low'
                    state['complexity_score'] = query_analysis.complexity_score
                    state['estimated_steps'] = len(query_analysis.domains) if query_analysis.is_multi_step else 1
                    state['context']['complexity_level'] = state['complexity_level']
                    state['context']['complexity_score'] = state['complexity_score']
                    state['context']['estimated_steps'] = state['estimated_steps']
                    state['context']['is_multi_step'] = query_analysis.is_multi_step
                    state['context']['domains'] = query_analysis.domains
                    state['context']['sentiment'] = query_analysis.sentiment
                    state['context']['sentiment_score'] = query_analysis.sentiment_score
                    
                    logger.info(
                        f"{LOG_OK} [ANALYZE] AnalyzerRole: intent={query_analysis.intent}, "
                        f"domains={query_analysis.domains}, complexity={query_analysis.complexity_score:.2f}"
                    )
                except Exception as e:
                    logger.debug(f"AnalyzerRole analysis failed (non-critical): {e}")
            
            # Use intent_patterns for analysis if AnalyzerRole didn't provide results
            if not query_analysis:
                # Cache-aware intent classification
                cached_intent = self.intent_cache.get_intent(query)
                if cached_intent:
                    intent_data = cached_intent
                else:
                    intent_data = classify_query_intent(query)
                    self.intent_cache.set_intent(query, intent_data)
                
                state['intent'] = intent_data.get('intent')
                state['confidence'] = intent_data.get('confidence')
                
                # Cache-aware entity extraction
                cached_entities = self.intent_cache.get_entities(query)
                if cached_entities:
                    entities_data = cached_entities
                else:
                    entities_data = extract_entities(query)
                    self.intent_cache.set_entities(query, entities_data)
                
                state['entities'] = entities_data
                
                # Cache-aware complexity analysis
                cached_complexity = self.intent_cache.get_complexity(query)
                if cached_complexity:
                    complexity = cached_complexity
                else:
                    complexity = analyze_query_complexity(query)
                    self.intent_cache.set_complexity(query, complexity)
                
                state['complexity_level'] = complexity.get('complexity_level', 'medium')
                state['complexity_score'] = complexity.get('complexity_score', AutonomousOrchestratorConfig.DEFAULT_COMPLEXITY_SCORE)
                state['estimated_steps'] = complexity.get('estimated_steps', AutonomousOrchestratorConfig.DEFAULT_ESTIMATED_STEPS)
                state['context']['complexity_level'] = complexity.get('complexity_level', 'medium')
                state['context']['complexity_score'] = complexity.get('complexity_score', AutonomousOrchestratorConfig.DEFAULT_COMPLEXITY_SCORE)
                state['context']['estimated_steps'] = complexity.get('estimated_steps', AutonomousOrchestratorConfig.DEFAULT_ESTIMATED_STEPS)
                
                # Execution strategy
                strategy = get_execution_strategy(query)
                state['context']['execution_strategy'] = strategy['strategy']
                state['context']['primary_domain'] = strategy['primary_domain']
                state['context']['is_multi_step'] = complexity['estimated_steps'] > 1
                
                # Orchestration decision
                use_orchestration = should_use_orchestration(query)
                state['context']['use_orchestration'] = use_orchestration
                
                logger.info(
                    f"{LOG_OK} [ANALYZE] Intent: {state['intent']}, "
                    f"Confidence: {state.get('confidence', 0):.2f}, "
                    f"Complexity: {state['complexity_level']}, "
                    f"Steps: {state['estimated_steps']}"
                )
            
            return state
        except Exception as e:
            logger.error(f"{LOG_ERROR} [ANALYZE] Failed: {e}")
            # state['errors'] and state['context'] are guaranteed to exist (initialized before try block)
            state['errors'].append(f"Analysis error: {str(e)}")
            state['context']['execution_strategy'] = 'error'
            return state
    
    async def _plan_execution_node(self, state: AgentState) -> AgentState:
        """Create adaptive execution plan using LLM-based Chain-of-Thought planning"""
        logger.info(f"{LOG_INFO} [PLAN] Creating plan with Chain-of-Thought")
        
        try:
            query = state['query']
            
            # Use LLM-based planning with master prompt 
            if self.llm_client:
                try:
                    from ....ai.prompts.orchestrator_prompts import get_orchestrator_master_prompt
                    from langchain_core.messages import SystemMessage, HumanMessage
                    
                    # Get orchestrator master prompt
                    system_prompt = get_orchestrator_master_prompt(tools=self.tools_list)
                    
                    # Create planning prompt with normalization reminder
                    normalization_note = ""
                    if state['context'].get('normalization_applied'):
                        norm_result = state['context'].get('normalization_result', {})
                        original = norm_result.get('original_text', query)
                        normalized = norm_result.get('normalized_text', query)
                        normalization_note = f"\n\nNote: Query was normalized from '{original}' to '{normalized}'. Please acknowledge this in your normalization step."
                    
                    planning_prompt = f"""User Query: "{query}"

Current Context:
- Intent: {state.get('intent', 'general')}
- Domains: {state['context'].get('domains', ['general'])}
- Entities: {state.get('entities', {})}
{normalization_note}

Generate your plan using the <PLAN> tags, then make your first tool call using <TOOL_CALL> tags.

Remember:
1. ALWAYS start your plan with a normalization step if the input contains typos, grammatical errors, or informal language
2. Always use Contact Resolver before scheduling (via calendar tool)
3. Plan before acting
4. One tool call at a time"""
                    
                    messages = [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=planning_prompt)
                    ]
                    
                    # Get LLM response with plan and first tool call
                    response = self.llm_client.invoke(messages)
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    # Parse PLAN and TOOL_CALL from response
                    plan_text = self._extract_xml_tag(response_text, 'PLAN')
                    tool_call_text = self._extract_xml_tag(response_text, 'TOOL_CALL')
                    
                    if plan_text:
                        logger.info(f"{LOG_OK} [PLAN] LLM generated plan: {plan_text[:200]}...")
                        state['context']['llm_plan'] = plan_text
                    
                    if tool_call_text:
                        # Parse tool call
                        tool_name, parameters = self._parse_tool_call(tool_call_text)
                        if tool_name:
                            # Extract query from parameters or use original query
                            tool_query = parameters.get('query', query)
                            if not tool_query or tool_query == query:
                                # If no query in parameters, use original query
                                tool_query = query
                            
                            # Create step from tool call
                            state['steps'] = [{
                                'id': 'step_1',
                                'tool_name': tool_name,
                                'query': tool_query,  # Use query from parameters or original
                                'intent': state.get('intent', 'general'),
                                'action': parameters.get('action', 'execute'),
                                'parameters': parameters,
                                'dependencies': [],
                                'status': 'pending',
                                'domain': self._get_domain_from_tool(tool_name)
                            }]
                            state['current_step'] = 0
                            state['context']['total_steps'] = 1
                            state['planning_complete'] = True
                            state['context']['use_llm_planning'] = True
                            
                            logger.info(f"{LOG_OK} [PLAN] LLM selected tool: {tool_name} with query: {tool_query[:100]}")
                            return state
                    
                except Exception as e:
                    logger.debug(f"LLM-based planning failed, falling back: {e}")
            
            # Use OrchestratorRole for planning if available
            if self.orchestrator_role:
                try:
                    intent = state.get('intent', 'general')
                    domains = state['context'].get('domains', ['general'])
                    entities = state.get('entities', {})
                    
                    # Convert entities format if needed
                    if isinstance(entities, dict) and 'entities' in entities:
                        entities_dict = {e.get('type', 'unknown'): e.get('value', '') for e in entities.get('entities', [])}
                    else:
                        entities_dict = entities if isinstance(entities, dict) else {}
                    
                    execution_plan = await self.orchestrator_role.create_plan(
                        query=query,
                        intent=intent,
                        domains=domains,
                        entities=entities_dict
                    )
                    
                    # Convert ExecutionPlan steps to state format
                    state['steps'] = [
                        {
                            'id': step.step_id,
                            'tool_name': self._map_domain_to_tool(step.domain),
                            'query': query,  # Use original query or step-specific query if available
                            'intent': intent,
                            'action': step.action,
                            'dependencies': step.dependencies,
                            'status': 'pending',
                            'domain': step.domain
                        }
                        for step in execution_plan.steps
                    ]
                    state['current_step'] = 0
                    state['context']['total_steps'] = len(execution_plan.steps)
                    state['planning_complete'] = True
                    
                    logger.info(f"{LOG_OK} [PLAN] OrchestratorRole created {len(execution_plan.steps)} steps")
                except Exception as e:
                    logger.debug(f"OrchestratorRole planning failed, falling back to execution_planner: {e}")
            
            # Fallback to execution_planner if OrchestratorRole not available or failed
            if not state.get('planning_complete'):
                decomposed_steps = self.query_decomposer.decompose_query(query)
                execution_steps = await self.execution_planner.create_execution_plan(decomposed_steps)
                
                # Store plan in steps
                state['steps'] = [
                    {
                        'id': step.id,
                        'tool_name': step.tool_name,
                        'query': step.query,
                        'intent': step.intent,
                        'action': step.action,
                        'dependencies': step.dependencies,
                        'status': step.status.value
                    }
                    for step in execution_steps
                ]
                state['current_step'] = 0
                state['context']['total_steps'] = len(execution_steps)
                state['planning_complete'] = True
                
                logger.info(f"{LOG_OK} [PLAN] Created {len(execution_steps)} steps (fallback)")
            
            return state
        except Exception as e:
            logger.error(f"{LOG_ERROR} [PLAN] Failed: {e}")
            state['errors'].append(f"Planning error: {str(e)}")
            return state
    
    async def _execute_step_node(self, state: AgentState) -> AgentState:
        """Execute step with intelligent tool selection and research context"""
        logger.info(f"{LOG_INFO} [EXECUTE] Executing step")
        
        try:
            # Gather research context before execution if ResearcherRole is available
            research_context = None
            if self.researcher_role:
                try:
                    query = state['query']
                    research_result = await self.researcher_role.research(
                        query=query,
                        limit=3,
                        use_vector=True,
                        use_graph=True
                    )
                    if research_result.success and research_result.combined_results:
                        research_context = research_result.get_top_results(2)
                        # Store research context in state for tool execution
                        state['context']['research_context'] = research_context
                        logger.info(f"{LOG_INFO} [EXECUTE] Research found {len(research_context)} contextual results")
                except Exception as e:
                    logger.debug(f"Research context gathering failed (non-critical): {e}")
            
            # Check if multi-step execution
            is_multi_step = state['context'].get('is_multi_step', False)
            
            if is_multi_step:
                current_step = state.get('current_step', 0)
                steps = state.get('steps', [])
                
                if current_step >= len(steps):
                    state['context']['all_steps_complete'] = True
                    state['execution_complete'] = True
                    return state
                
                step_info = steps[current_step]
                query = step_info['query']
                tool_name = step_info['tool_name']
                domain = step_info.get('domain', 'general')
                parameters = step_info.get('parameters', {})
            else:
                query = state['query']
                domain = state['context'].get('domain', 'general')
                tool_name = self._map_domain_to_tool(domain)
                parameters = {}
            
            # Execute tool - use tool adapter if available (handles both actual tools and aliases)
            start_time = datetime.now()
            
            if hasattr(self, 'tool_adapter'):
                # Use tool adapter which handles both actual tool names and aliases
                if not parameters:
                    # Build parameters from query and step info
                    parameters = {'query': query}
                    if is_multi_step:
                        # Merge with step_info parameters if available
                        step_params = step_info.get('parameters', {})
                        if step_params:
                            parameters.update(step_params)
                            # If action is specified, use it
                            if 'action' in step_params:
                                parameters['action'] = step_params['action']
                
                result = await self.tool_adapter.execute_formal_tool(tool_name, parameters)
            else:
                # Fallback: Use direct tool execution
                tool = self.tools.get(tool_name)
                if not tool:
                    state['errors'].append(f"Tool {tool_name} not found")
                    return state
                
                result = await self._execute_tool_directly(tool, query)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # Store result
            step_result = {
                'step_index': state.get('current_step', 0),
                'query': query,
                'tool': tool_name,
                'result': result,
                'execution_time': execution_time,
                'success': True,
                'domain': domain
            }
            
            # Add to results
            state['results'].append(step_result)
            
            # If using LLM-based planning, get next tool call from LLM
            if state['context'].get('use_llm_planning') and self.llm_client:
                try:
                    from ....ai.prompts.orchestrator_prompts import get_orchestrator_master_prompt
                    from langchain_core.messages import SystemMessage, HumanMessage
                    
                    # Get orchestrator master prompt
                    system_prompt = get_orchestrator_master_prompt(tools=self.tools_list)
                    
                    # Build conversation history with tool results
                    conversation_history = f"""Previous Plan:
{state['context'].get('llm_plan', 'N/A')}

Tool Execution Results:
- Tool: {tool_name}
- Result: {result[:500]}  # Limit result length
"""
                    
                    # Create prompt for next tool call
                    next_step_prompt = f"""User Query: "{state['query']}"

{conversation_history}

Based on the tool result above, update your plan if needed and make the next tool call.
If all steps are complete, respond with <PLAN>All steps completed</PLAN> without a <TOOL_CALL>."""
                    
                    messages = [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=next_step_prompt)
                    ]
                    
                    # Get LLM response
                    response = self.llm_client.invoke(messages)
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    # Parse next tool call
                    tool_call_text = self._extract_xml_tag(response_text, 'TOOL_CALL')
                    
                    if tool_call_text:
                        # Parse and add next step
                        next_tool_name, next_parameters = self._parse_tool_call(tool_call_text)
                        if next_tool_name:
                            # Extract query from parameters or use original query
                            next_query = next_parameters.get('query', state['query'])
                            if not next_query:
                                next_query = state['query']
                            
                            # Add next step
                            next_step = {
                                'id': f"step_{len(state.get('steps', [])) + 1}",
                                'tool_name': next_tool_name,
                                'query': next_query,  # Use query from parameters or original
                                'intent': state.get('intent', 'general'),
                                'action': next_parameters.get('action', 'execute'),
                                'parameters': next_parameters,
                                'dependencies': [step_result.get('step_index', 0)],
                                'status': 'pending',
                                'domain': self._get_domain_from_tool(next_tool_name)
                            }
                            
                            if 'steps' not in state:
                                state['steps'] = []
                            state['steps'].append(next_step)
                            state['context']['total_steps'] = len(state['steps'])
                            
                            logger.info(f"{LOG_OK} [EXECUTE] LLM selected next tool: {next_tool_name} with query: {next_query[:100]}")
                    else:
                        # No more tool calls - mark as complete
                        state['context']['all_steps_complete'] = True
                        logger.info(f"{LOG_OK} [EXECUTE] LLM indicated all steps complete")
                        
                except Exception as e:
                    logger.debug(f"LLM-based next step selection failed: {e}")
            
            # Update current step
            if is_multi_step:
                state['current_step'] = current_step + 1
            
            logger.info(f"{LOG_OK} [EXECUTE] Completed in {execution_time:.2f}s")
            
            return state
        except Exception as e:
            logger.error(f"{LOG_ERROR} [EXECUTE] Failed: {e}")
            state['errors'].append(f"Execution error: {str(e)}")
            retry_count = state['context'].get('retry_count', 0)
            state['context']['retry_count'] = retry_count + 1
            return state
    
    async def _validate_result_node(self, state: AgentState) -> AgentState:
        """Validate execution results"""
        logger.info(f"{LOG_INFO} [VALIDATE] Validating")
        
        try:
            step_results = state.get('results', [])
            
            if not step_results:
                state['context']['validation_status'] = 'retry'
                return state
            
            # Calculate quality
            total_quality = sum(self._calculate_quality(r) for r in step_results)
            avg_quality = total_quality / len(step_results)
            state['context']['overall_quality_score'] = avg_quality
            
            retry_count = state['context'].get('retry_count', 0)
            if avg_quality >= AutonomousOrchestratorConfig.QUALITY_VALIDATION_THRESHOLD:
                state['context']['validation_status'] = 'accept'
            elif avg_quality >= AutonomousOrchestratorConfig.QUALITY_PARTIAL_THRESHOLD and retry_count < AutonomousOrchestratorConfig.MAX_RETRY_STEPS:
                state['context']['validation_status'] = 'refine'
            else:
                state['context']['validation_status'] = 'accept'
            
            logger.info(f"{LOG_OK} [VALIDATE] Quality: {avg_quality:.2f}")
            
            return state
        except Exception as e:
            logger.error(f"{LOG_ERROR} [VALIDATE] Failed: {e}")
            state['context']['validation_status'] = 'accept'
            return state
    
    async def _error_recovery_node(self, state: AgentState) -> AgentState:
        """Self-correction and error recovery"""
        logger.info(f"{LOG_INFO} [RECOVERY] Recovering")
        
        try:
            retry_count = state['context'].get('retry_count', 0)
            
            if retry_count >= AutonomousOrchestratorConfig.MAX_RETRIES:
                state['context']['use_fallback'] = True
                state['context']['validation_status'] = 'accept'
                return state
            
            # Simplify strategy on repeated failures
            if state['context'].get('is_multi_step') and retry_count > 1:
                state['context']['is_multi_step'] = False
                state['context']['execution_strategy'] = 'single_step'
            
            state['context']['retry_count'] = retry_count + 1
            
            logger.info(f"{LOG_OK} [RECOVERY] Retry {retry_count + 1}/{AutonomousOrchestratorConfig.MAX_RETRIES}")
            
            return state
        except Exception as e:
            logger.error(f"{LOG_ERROR} [RECOVERY] Failed: {e}")
            state['context']['use_fallback'] = True
            return state
    
    async def _synthesize_response_node(self, state: AgentState) -> AgentState:
        """Synthesize final response with context enhancement"""
        logger.info(f"{LOG_INFO} [SYNTHESIZE] Finalizing")
        
        try:
            step_results = state.get('results', [])
            
            if not step_results:
                state['answer'] = f"{LOG_ERROR} No results"
                state['context']['final_response'] = state['answer']
                return state
            
            # Use SynthesizerRole for response synthesis if available
            final_response = None
            user_id = state.get('user_id')
            
            if self.synthesizer_role:
                try:
                    query = state.get('query', '')
                    entities = state.get('entities', {})
                    
                    # Convert step_results to specialist_results format
                    specialist_results = {}
                    for result in step_results:
                        domain = result.get('domain', result.get('tool', 'general'))
                        # Create a simple SpecialistResult-like object
                        class SimpleResult:
                            def __init__(self, data, success=True):
                                self.data = data
                                self.success = success
                        
                        specialist_results[domain] = SimpleResult(
                            data=result.get('result', result),
                            success=result.get('success', True)
                        )
                    
                    # Use SynthesizerRole for synthesis with personalization
                    synthesized = await self.synthesizer_role.synthesize(
                        query=query,
                        specialist_results=specialist_results,
                        context=state.get('context', {}),
                        user_id=user_id
                    )
                    
                    final_response = synthesized.response_text
                    logger.info(f"{LOG_OK} [SYNTHESIZE] SynthesizerRole synthesis applied")
                except Exception as e:
                    logger.debug(f"SynthesizerRole synthesis failed (non-critical): {e}")
            
            # Use ContextSynthesizer for cross-domain context enrichment
            if not final_response and self.context_synthesizer:
                entities = state.get('entities', {})
                query = state.get('query', '')
                steps = state.get('steps', [])
                
                # Extract context from step results
                extracted_contexts = {}
                for step_result in step_results:
                    if step_result and isinstance(step_result, dict):
                        result_text = str(step_result.get('result', step_result.get('data', '')))
                        if result_text:
                            extracted = await self.context_synthesizer.extract_context_from_result(
                                result_text,
                                use_llm=True
                            )
                            if extracted:
                                extracted_contexts.update(extracted)
                
                # Synthesize enriched context using orchestration ContextSynthesizer
                current_context = {
                    'query': query,
                    'entities': entities,
                    'step_results': step_results,
                    **extracted_contexts
                }
                synthesized_context = await self.context_synthesizer.synthesize_context(
                    execution_steps=steps,
                    current_context=current_context
                )
                
                # Store synthesized context
                state['synthesized_context'] = synthesized_context
                logger.info(f"{LOG_OK} [SYNTHESIZE] Context synthesis applied with {len(synthesized_context)} enriched fields")
                
                # Use enriched context to build response if available
                if synthesized_context.get('enriched_context'):
                    final_response = str(synthesized_context.get('enriched_context', ''))
            
            # Use utils.py formatter
            if not final_response:
                formatted_results = [
                    {
                        'success': r.get('success', False),
                        'result': r.get('result', ''),
                        'execution_time': r.get('execution_time', 0),
                        'action': r.get('tool', 'unknown')
                    }
                    for r in step_results
                ]
                final_response = format_multi_step_response(formatted_results)
            else:
                final_response = f"{LOG_OK} Completed!\n\n"
                for i, result in enumerate(step_results, 1):
                    final_response += f"Step {i}: {result.get('result', 'No result')}\n"
            
            state['answer'] = final_response
            state['context']['final_response'] = final_response
            state['context']['completed'] = True
            state['execution_complete'] = True
            
            # Update MemoryRole with PatternRecognition capability
            if self.memory_role:
                try:
                    execution_time_ms = state['context'].get('execution_time_ms', 0)
                    intent = state.get('intent', 'general')
                    domains = state['context'].get('domains', ['general'])
                    
                    # Use asyncio to call async method
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Create task if loop is running
                        asyncio.create_task(
                            self.memory_role.learn_from_execution(
                                query=state.get('query', ''),
                                intent=intent,
                                domains=domains,
                                execution_time_ms=execution_time_ms,
                                success=state['context'].get('completed', False),
                                user_id=user_id
                            )
                        )
                    else:
                        loop.run_until_complete(
                            self.memory_role.learn_from_execution(
                                query=state.get('query', ''),
                                intent=intent,
                                domains=domains,
                                execution_time_ms=execution_time_ms,
                                success=state['context'].get('completed', False),
                                user_id=user_id
                            )
                        )
                except Exception as e:
                    logger.debug(f"Could not update MemoryRole: {e}")
            
            # Log cache statistics
            if state.get('request_id') and self.intent_cache:
                cache_stats = self.intent_cache.get_stats()
                state['cache_stats'] = cache_stats
                if cache_stats['cache_hits'] > 0:
                    logger.info(
                        f"{LOG_OK} [CACHE] Hits: {cache_stats['cache_hits']}, "
                        f"Misses: {cache_stats['cache_misses']}, "
                        f"Hit Rate: {cache_stats['hit_rate_percent']}%"
                    )
            
            logger.info(f"{LOG_OK} [SYNTHESIZE] Complete")
            
            return state
        except Exception as e:
            logger.error(f"{LOG_ERROR} [SYNTHESIZE] Failed: {e}")
            error_msg = f"{LOG_ERROR} Synthesis failed: {str(e)}"
            state['answer'] = error_msg
            state['context']['final_response'] = error_msg
            state['context']['completed'] = True
            state['execution_complete'] = True
            return state
    
    # Conditional Edges
    def _route_after_analysis(self, state: AgentState) -> str:
        """Route based on analysis"""
        strategy = state['context'].get('execution_strategy', 'single_step')
        return 'error' if strategy == 'error' else strategy
    
    def _route_after_execution(self, state: AgentState) -> str:
        """Route based on execution"""
        if state.get('errors') and state['context'].get('retry_count', 0) < AutonomousOrchestratorConfig.MAX_RETRIES:
            return 'retry'
        
        if state['context'].get('is_multi_step'):
            current = state.get('current_step', 0)
            total = state['context'].get('total_steps', 0)
            return 'next_step' if current < total else 'done'
        
        return 'continue'
    
    def _route_after_validation(self, state: AgentState) -> str:
        """Route based on validation"""
        status = state['context'].get('validation_status', 'accept')
        return 'done' if status == 'accept' else status
    
    # Helper Methods
    async def _execute_tool_directly(self, tool: Any, query: str) -> str:
        """Execute tool directly"""
        try:
            if hasattr(tool, '_run'):
                return tool._run(query)
            elif hasattr(tool, 'run'):
                return tool.run(query)
            else:
                result = await tool.ainvoke({'query': query})
                return result
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _calculate_quality(self, result: dict) -> float:
        """Calculate quality score"""
        quality = AutonomousOrchestratorConfig.QUALITY_BASE_SCORE
        if result.get('result'):
            quality += AutonomousOrchestratorConfig.QUALITY_RESULT_BONUS
        if result.get('success', False):
            quality += AutonomousOrchestratorConfig.QUALITY_SUCCESS_BONUS
        if (AutonomousOrchestratorConfig.OPTIMAL_EXECUTION_TIME_MIN < 
            result.get('execution_time', 0) < 
            AutonomousOrchestratorConfig.OPTIMAL_EXECUTION_TIME_MAX):
            quality += AutonomousOrchestratorConfig.QUALITY_EXECUTION_TIME_BONUS
        return min(quality, 1.0)
    
    def _map_domain_to_tool(self, domain: str) -> str:
        """
        Map domain to tool using ToolDomainConfig.
        
        Uses centralized ToolDomainConfig to ensure consistent mapping.
        """
        from ..domain.tool_domain_config import get_tool_domain_config
        
        config = get_tool_domain_config()
        tool_name = config.map_domain_to_tool(domain, available_tools=self.tools)
        
        # Fallback to email if mapping fails
        if tool_name is None:
            logger.warning(
                f"[AUTONOMOUS] Could not map domain '{domain}' to tool, "
                f"falling back to 'email'. Available tools: {list(self.tools.keys())}"
            )
            return 'email'
        
        return tool_name
    
    def _extract_xml_tag(self, text: str, tag_name: str) -> Optional[str]:
        """Extract content from XML tag"""
        import re
        pattern = f'<{tag_name}>(.*?)</{tag_name}>'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else None
    
    def _parse_tool_call(self, tool_call_text: str) -> tuple[Optional[str], dict]:
        """Parse tool call XML to extract tool name and parameters"""
        import re
        from xml.etree import ElementTree as ET
        
        try:
            # Try parsing as XML
            root = ET.fromstring(f"<root>{tool_call_text}</root>")
            tool_name_elem = root.find('tool_name')
            params_elem = root.find('parameters')
            
            if tool_name_elem is not None:
                tool_name = tool_name_elem.text.strip()
                parameters = {}
                
                if params_elem is not None:
                    for param in params_elem:
                        parameters[param.tag] = param.text.strip() if param.text else ""
                
                return tool_name, parameters
        except Exception as e:
            logger.debug(f"XML parsing failed, trying regex: {e}")
        
        # Fallback to regex
        tool_name_match = re.search(r'<tool_name>(.*?)</tool_name>', tool_call_text, re.IGNORECASE | re.DOTALL)
        if tool_name_match:
            tool_name = tool_name_match.group(1).strip()
            parameters = {}
            
            # Extract parameters
            param_matches = re.findall(r'<(\w+)>(.*?)</\1>', tool_call_text, re.IGNORECASE | re.DOTALL)
            for param_name, param_value in param_matches:
                if param_name != 'tool_name':
                    parameters[param_name] = param_value.strip()
            
            return tool_name, parameters
        
        return None, {}
    
    def _get_domain_from_tool(self, tool_name: str) -> str:
        """Get domain from tool name"""
        tool_name_lower = tool_name.lower()
        if 'email' in tool_name_lower or 'contact' in tool_name_lower:
            return 'email'
        elif 'calendar' in tool_name_lower or 'schedule' in tool_name_lower:
            return 'calendar'
        elif 'task' in tool_name_lower:
            return 'tasks'
        elif 'knowledge' in tool_name_lower or 'search' in tool_name_lower:
            return 'knowledge'
        return 'general'
    
    # Public API
    async def execute_query(self,
                           query: str,
                           user_id: Optional[int] = None,
                           config: Optional[RunnableConfig] = None) -> OrchestrationResult:
        """Execute query using autonomous LangGraph workflow"""
        start_time = datetime.now()
        logger.info(f"{LOG_INFO} [AUTONOMOUS] Starting: {query[:100]}")
        
        try:
            # Initialize state using helper function
            from ...state import create_initial_state
            initial_state: AgentState = create_initial_state(
                query=query,
                user_id=user_id,
                session_id=None  # Could be passed as parameter if needed
            )
            
            # Execute workflow
            final_state = await self.workflow.ainvoke(initial_state, config=config)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # Extract results from state
            step_results = final_state.get('results', [])
            successful_steps = len([r for r in step_results if r.get('success', False)])
            
            return OrchestrationResult(
                success=final_state['context'].get('completed', False),
                final_result=final_state['context'].get('final_response', final_state.get('answer', 'No response')),
                steps_executed=successful_steps,
                total_steps=final_state['context'].get('total_steps', len(step_results)),
                execution_time=execution_time,
                errors=final_state.get('errors', []),
                context_used=final_state.get('context', {})
            )
        except Exception as e:
            logger.error(f"{LOG_ERROR} [AUTONOMOUS] Failed: {e}", exc_info=True)
            execution_time = (datetime.now() - start_time).total_seconds()
            
            return OrchestrationResult(
                success=False,
                final_result=f"{LOG_ERROR} Failed: {str(e)}",
                steps_executed=0,
                total_steps=0,
                execution_time=execution_time,
                errors=[str(e)],
                context_used={}
            )


def create_autonomous_orchestrator(tools: List[Any],
                                   config=None,
                                   db: Optional[Any] = None,
                                   memory_system: Optional[Any] = None,
                                   checkpointer: Optional[AsyncPostgresSaver] = None,
                                   rag_engine: Optional[Any] = None,
                                   graph_manager: Optional[Any] = None) -> AutonomousOrchestrator:
    """
    Factory function to create AutonomousOrchestrator with full agent role integration
    
    Args:
        tools: List of tools available to the orchestrator
        config: Optional configuration object
        db: Optional database session
        memory_system: Optional memory system for learning
        checkpointer: Optional LangGraph checkpointer for state persistence
        rag_engine: Optional RAG engine for ResearcherRole
        graph_manager: Optional graph manager for ResearcherRole and ContactResolverRole
        
    Returns:
        AutonomousOrchestrator instance with all agent roles initialized
    """
    return AutonomousOrchestrator(
        tools=tools,
        config=config,
        db=db,
        memory_system=memory_system,
        checkpointer=checkpointer,
        rag_engine=rag_engine,
        graph_manager=graph_manager
    )
