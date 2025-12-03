"""
Pattern-Based Orchestrator - Main orchestration logic


Integrates with:
- intent_patterns.py: get_execution_strategy() for intelligent orchestration
- memory_system.py: Learning and optimization
- utils.py: Query detection and response formatting
- orchestrator_constants.py: Pattern-based processing

Use this for:
- Standard multi-step queries
- Predictable workflows
- Lower overhead scenarios
"""

from datetime import datetime
from typing import List, Any, Optional, Dict, Tuple, Union
import json

from ....utils.logger import setup_logger
from .base import ExecutionStep, ExecutionStatus, OrchestrationResult
from ..components.query_decomposer import QueryDecomposer
from ..components.execution_planner import ExecutionPlanner
from ..components.context_synthesizer import ContextSynthesizer
from ..config.orchestrator_config import OrchestratorConfig
from ..handlers.cross_domain_handler import CrossDomainHandler
from ..domain.domain_validator import DomainValidator
from ..domain.routing_analytics import get_routing_analytics, RoutingOutcome
from ..config.domain_validation_config import DomainValidationConfig
from ..config import LOG_INFO, LOG_ERROR, LOG_OK, LOG_WARNING
from ...intent import get_execution_strategy, classify_query_intent, TASK_KEYWORDS
from ...utils import format_multi_step_response, clean_response_text
from ....ai.llm_factory import LLMFactory

logger = setup_logger(__name__)


class Orchestrator:
    """
    Pattern-Based Multi-Step Orchestrator
    
    Integrates all agent components:
    - utils.py: Query detection and response formatting
    - orchestrator_constants.py: Pattern-based processing
    - memory_system.py: Learning and optimization
    - domain_validator.py: Cross-domain routing validation
    """
    
    def __init__(self,
                 tools: List[Any],
                 config=None,
                 db: Optional[Any] = None,
                 memory_system: Optional[Any] = None,
                 workflow_emitter: Optional[Any] = None,
                 rag_engine: Optional[Any] = None,
                 graph_manager: Optional[Any] = None):
        self.tools = {tool.name: tool for tool in tools}
        self.config = config
        self.db = db
        self.memory_system = memory_system
        self.workflow_emitter = workflow_emitter  # For streaming workflow events
        self.rag_engine = rag_engine or self._init_rag_engine()
        self.graph_manager = graph_manager or self._init_graph_manager()
        
        # Initialize components
        self.llm_client = self._init_llm_client()
        self.query_decomposer = QueryDecomposer(self.llm_client)
        self.context_synthesizer = ContextSynthesizer(llm_client=self.llm_client)
        self.execution_planner = ExecutionPlanner(self.tools)
        
        # Initialize roles using factory pattern to reduce boilerplate
        from .role_factory import RoleFactory
        
        self.analyzer_role = RoleFactory.create_analyzer_role(config=config)
        
        # Initialize DomainValidator with AnalyzerRole for enhanced detection
        self.domain_validator = DomainValidator(
            strict_mode=OrchestratorConfig.ENABLE_STRICT_VALIDATION,
            analyzer_role=self.analyzer_role
        )
        
        self.researcher_role = RoleFactory.create_researcher_role(
            rag_engine=self.rag_engine,
            graph_manager=self.graph_manager,
            config=config
        )
        
        email_tool = self.tools.get('email')
        email_service = email_tool.email_service if email_tool and hasattr(email_tool, 'email_service') else None
        self.contact_resolver_role = RoleFactory.create_contact_resolver_role(
            slack_client=None,
            graph_manager=self.graph_manager,
            email_service=email_service,
            config=config
        )
        
        self.orchestrator_role = RoleFactory.create_orchestrator_role(
            config=config,
            tools=list(self.tools.values())
        )
        
        self.synthesizer_role = RoleFactory.create_synthesizer_role(config=config)
        
        self.memory_role = RoleFactory.create_memory_role(
            config=config,
            db=db,
            graph_manager=self.graph_manager
        )
        
        # Initialize cross-domain handler for multi-domain queries
        # Pass synthesizer_role for enhanced result synthesis
        self.cross_domain_handler = CrossDomainHandler(
            enable_parallel_execution=True,
            synthesizer_role=self.synthesizer_role,
            analyzer_role=None,  # AnalyzerRole not available in standard orchestrator
            config=config
        )
        logger.info(f"{LOG_OK} Cross-domain handler initialized")
        
        # Initialize schedule query handler for schedule and time-based queries
        try:
            from ..handlers.schedule_query_handler import ScheduleQueryHandler
            self.schedule_handler = ScheduleQueryHandler(config=config)
            logger.info(f"{LOG_OK} Schedule query handler initialized")
        except ImportError:
            self.schedule_handler = None
            logger.warning(f"{LOG_WARNING} Schedule query handler not available")
        
        # Initialize analytics for tracking routing decisions
        self.analytics = get_routing_analytics()
        logger.info(f"{LOG_OK} Routing analytics initialized")
        
        logger.info(f"{LOG_OK} Orchestrator initialized with {len(tools)} tools")
    
    def _init_llm_client(self) -> Optional[Any]:
        """Initialize LLM client if available"""
        try:
            return LLMFactory.get_llm_for_provider(
                self.config, 
                temperature=OrchestratorConfig.LLM_TEMPERATURE,
                max_tokens=OrchestratorConfig.LLM_MAX_TOKENS
            )
        except Exception as e:
            logger.warning(f"LLM not available: {e}")
            return None
    
    def _init_rag_engine(self) -> Optional[Any]:
        """Initialize RAG engine if available"""
        try:
            from api.dependencies import AppState
            return AppState.get_rag_engine()
        except Exception as e:
            logger.debug(f"RAG engine not available: {e}")
            return None
    
    def _init_graph_manager(self) -> Optional[Any]:
        """Initialize graph manager if available"""
        try:
            from ....services.indexing.graph.manager import KnowledgeGraphManager
            return KnowledgeGraphManager(config=self.config)
        except Exception as e:
            logger.debug(f"Graph manager not available: {e}")
            return None
    
    def _build_conversational_prompt(self, query: str, raw_results: str) -> str:
        """
        Build the conversational prompt for LLM response generation.
        Uses the prompt from ai/prompts/conversational_prompts.py following
        the existing codebase pattern.
        
        Args:
            query: Original user query
            raw_results: Formatted tool execution results
            
        Returns:
            Complete prompt string for LLM
        """
        try:
            from ....ai.prompts.conversational_prompts import get_orchestrator_conversational_prompt
            return get_orchestrator_conversational_prompt(query, raw_results)
        except ImportError:
            # Fallback if import fails
            logger.warning(f"{LOG_WARNING} Could not import orchestrator conversational prompt, using fallback")
            return f"""User asked: "{query}"

Tool execution results:
{raw_results}

Generate a natural, conversational response that sounds like you're talking to a friend, not a robot.

Generate the response:"""
    
    def _get_content_query_phrases(self) -> List[str]:
        """
        Get content query phrases from config.
        
        Returns:
            List of phrases that indicate content queries
        """
        try:
            import yaml
            from pathlib import Path
            
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "intent_keywords.yaml"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                    phrases = config.get('content_query_phrases', [])
                    if phrases:
                        return phrases
        except Exception as e:
            logger.debug(f"Failed to load content query phrases from config: {e}")
        
        # Fallback to default phrases
        return [
            'tell me about', 'tell me more about', 'what is', 'what was', 'what does',
            'summarize', 'explain', 'what did', 'what does it say'
        ]
    
    def _get_title_indicators(self) -> List[str]:
        """
        Get title indicators for quote removal.
        These are context words that indicate a quoted string is likely a title.
        
        Returns:
            List of words that indicate a title context
        """
        # Title indicators are simple enough to keep as constants
        # They're not user-configurable and rarely change
        return [
            'task', 'got', 'have', 'you', 'your', 'list', 'plate', 'tackle',
            'event', 'meeting', 'calendar', 'schedule', 'appointment',
            'email', 'subject', 'from', 'message'
        ]
    
    def _normalize_domain(self, domain: str) -> str:
        """
        Normalize domain name to match synthesizer expectations.
        Removes duplicate domain normalization code.
        
        Args:
            domain: Raw domain name from step
            
        Returns:
            Normalized domain name (tasks, email, calendar)
        """
        if domain == 'task':
            return 'tasks'
        elif domain in ('event', 'meeting'):
            return 'calendar'
        return domain
    
    def _calculate_execution_time(self, start_time: datetime) -> float:
        """
        Calculate execution time from start time.
        Removes duplicate execution time calculations.
        
        Args:
            start_time: Start datetime
            
        Returns:
            Execution time in seconds
        """
        return (datetime.now() - start_time).total_seconds()
    
    async def _emit_workflow_complete(self, message: str, data: Dict[str, Any]):
        """
        Emit workflow complete event if emitter is available.
        Removes duplicate workflow emitter calls.
        
        Args:
            message: Success message
            data: Event data
        """
        if self.workflow_emitter:
            await self.workflow_emitter.emit_workflow_complete(message, data=data)
    
    def _map_domain_to_tool(self, domain: str) -> str:
        """
        Map domain name to tool name using ToolDomainConfig.
        
        This method uses the centralized ToolDomainConfig to ensure consistent
        domain-to-tool mapping across the entire application.
        """
        from ..domain.tool_domain_config import get_tool_domain_config
        
        config = get_tool_domain_config()
        tool_name = config.map_domain_to_tool(domain, available_tools=self.tools)
        
        # Fallback to email if mapping fails
        if tool_name is None:
            logger.warning(
                f"[ORCHESTRATOR] Could not map domain '{domain}' to tool, "
                f"falling back to 'email'. Available tools: {list(self.tools.keys())}"
            )
            return 'email'
        
        return tool_name
    
    async def execute_query(self,
                           query: str,
                           user_id: Optional[int] = None,
                           session_id: Optional[str] = None) -> OrchestrationResult:
        """Execute query with multi-step reasoning and intelligent strategy selection"""
        start_time = datetime.now()
        logger.info(f"{LOG_INFO} Executing: {query[:100]}")
        
        # === PRE-PROMPT MEMORY INJECTION ===
        # Retrieve short-term and long-term memory context before processing query
        memory_context = None
        if self.memory_role and user_id:
            try:
                memory_context = await self.memory_role.get_user_context(
                    user_id=user_id,
                    session_id=session_id
                )
                if memory_context:
                    logger.debug(
                        f"[MEMORY] Retrieved context: "
                        f"{len(memory_context.get('recent_messages', []))} messages, "
                        f"{len(memory_context.get('goals', []))} goals, "
                        f"{len(memory_context.get('preferences', {}))} preferences"
                    )
            except Exception as e:
                logger.debug(f"[MEMORY] Failed to retrieve memory context: {e}")
        
        # Emit reasoning start event
        if self.workflow_emitter:
            await self.workflow_emitter.emit_reasoning_start(
                "Clavr thinking...",
                data={'query': query}
            )
        
        try:
            # === STEP 1: ANALYZE QUERY ===
            # Inject memory context into query analysis if available
            enriched_query = query
            if memory_context:
                # Build context string for LLM
                context_parts = []
                
                # Short-term memory (recent messages)
                recent_messages = memory_context.get('recent_messages', [])
                if recent_messages:
                    from ...memory.memory_constants import SESSION_MESSAGE_LIMIT
                    context_parts.append("<RECENT_CONVERSATION>")
                    for msg in recent_messages[-SESSION_MESSAGE_LIMIT:]:
                        role_label = "User" if msg.get('role') == 'user' else "Assistant"
                        context_parts.append(f"{role_label}: {msg.get('text', '')[:200]}")
                    context_parts.append("</RECENT_CONVERSATION>")
                
                # Long-term memory (preferences, goals)
                preferences = memory_context.get('preferences', {})
                goals = memory_context.get('goals', [])
                if preferences or goals:
                    context_parts.append("<USER_CONTEXT>")
                    if preferences:
                        context_parts.append(f"Preferences: {json.dumps(preferences)}")
                    if goals:
                        active_goals = [g for g in goals if g.get('status') == 'active']
                        if active_goals:
                            context_parts.append(f"Active Goals: {', '.join([g.get('name', '') for g in active_goals[:3]])}")
                    context_parts.append("</USER_CONTEXT>")
                
                if context_parts:
                    enriched_query = "\n".join(context_parts) + "\n\n" + query
                    logger.debug(f"[MEMORY] Enriched query with memory context ({len(context_parts)} parts)")
            
            # Use enriched query for analysis
            analysis_query = enriched_query if memory_context else query
            # Use AnalyzerRole for query analysis (intent, domains, entities, complexity)
            query_analysis = None
            if self.analyzer_role:
                try:
                    query_analysis = await self.analyzer_role.analyze(query)
                    logger.info(
                        f"{LOG_INFO} Query analysis: intent={query_analysis.intent}, "
                        f"domains={query_analysis.domains}, complexity={query_analysis.complexity_score:.2f}"
                    )
                except Exception as e:
                    logger.debug(f"Query analysis failed (non-critical): {e}")
            
            query_lower = query.lower()
            
            # === EMAIL QUERY DETECTION (Priority 0 - Highest) ===
            # CRITICAL: Check for email queries FIRST before schedule queries
            # Use config-based keyword detection instead of hardcoded lists
            from ...intent.intent_patterns import _get_domain_keywords
            domain_keywords = _get_domain_keywords()
            email_keywords = domain_keywords.get('email', [])
            calendar_keywords = domain_keywords.get('calendar', [])
            task_keywords = domain_keywords.get('task', [])
            
            # CRITICAL: Check for explicit task/calendar queries FIRST - they should NOT go to email
            has_task_keywords = any(keyword in query_lower for keyword in task_keywords)
            has_calendar_keywords = any(keyword in query_lower for keyword in calendar_keywords)
            has_email_keywords = any(keyword in query_lower for keyword in email_keywords)
            
            explicit_email_query = has_email_keywords and not has_task_keywords and not has_calendar_keywords
            
            # If query explicitly mentions tasks/calendar but NOT emails, skip email routing entirely
            if (has_task_keywords or has_calendar_keywords) and not has_email_keywords:
                logger.info(f"{LOG_INFO} Task/calendar query detected (not email), skipping email-only routing: '{query}'")
                # Don't route to email - let it go through normal execution flow which will route to tasks/calendar
            elif explicit_email_query:
                # CRITICAL: For email-only queries, skip schedule and cross-domain handlers entirely
                # Route directly to email tool to prevent calendar/tasks from being included
                
                # If email-only (no calendar/task keywords), route directly to email tool
                    logger.info(f"{LOG_INFO} Email-only query detected, routing directly to email tool (skipping schedule/cross-domain)")
                    
                    email_tool = self.tools.get('email') or self.tools.get('email_tool')
                    if email_tool:
                        try:
                            # CRITICAL: Detect if this is a content query (asking about specific email content)
                            # For content queries, use 'search' to find the specific email, then format_email_list will generate summary
                            content_query_phrases = self._get_content_query_phrases()
                            is_content_query = any(phrase in query_lower for phrase in content_query_phrases)
                            
                            # Use 'search' action for content queries to find the specific email
                            # The formatting handler will detect content query and generate summary
                            action = 'search' if is_content_query or 'search' in query_lower or 'find' in query_lower else 'list'
                            
                            logger.info(f"[ORCHESTRATOR] Using action '{action}' for email query (is_content_query: {is_content_query})")
                            
                            # Execute email query directly
                            email_result = email_tool._run(
                                action=action,
                                query=query
                            )
                            
                            execution_time = self._calculate_execution_time(start_time)
                            await self._emit_workflow_complete("Email query completed successfully", {'response': email_result})
                            
                            return OrchestrationResult(
                                success=True,
                                final_result=email_result,
                                steps_executed=1,
                                total_steps=1,
                                execution_time=execution_time,
                                errors=[],
                                context_used={'email_only': True}
                            )
                        except Exception as e:
                            logger.warning(f"{LOG_WARNING} Direct email tool execution failed: {e}, falling back to standard flow")
                            # Fall through to standard execution flow
            
            # === SCHEDULE QUERY DETECTION (Priority 1) ===
            # Check if this is a schedule-related query (time-based questions)
            # CRITICAL: Skip schedule handler if query explicitly mentions tasks OR emails
            from ...intent import TASK_KEYWORDS
            explicit_task_query = any(keyword in query_lower for keyword in TASK_KEYWORDS)
            
            if self.schedule_handler and not explicit_task_query and not explicit_email_query:
                is_schedule, query_type, confidence = self.schedule_handler.is_schedule_query(query)
                if is_schedule and confidence >= 0.7:
                    logger.info(
                        f"{LOG_INFO} Schedule query detected: "
                        f"{query_type} (confidence: {confidence:.2f})"
                    )
                    
                    # Handle as schedule query (requires calendar + tasks, optionally Notion)
                    calendar_tool = self.tools.get('calendar')
                    task_tool = self.tools.get('tasks') or self.tools.get('task')
                    notion_tool = self.tools.get('notion') or self.tools.get('notion_tool')
                    
                    if calendar_tool and task_tool:
                        schedule_result = await self.schedule_handler.handle_schedule_query(
                            query, calendar_tool, task_tool, notion_tool=notion_tool, workflow_emitter=self.workflow_emitter
                        )
                        
                        if schedule_result:
                            execution_time = self._calculate_execution_time(start_time)
                            await self._emit_workflow_complete("Query completed successfully", {'response': schedule_result})
                            
                            return OrchestrationResult(
                                success=True,
                                final_result=schedule_result,
                                steps_executed=1,
                                total_steps=1,
                                execution_time=execution_time,
                                errors=[],
                                context_used={'schedule_query': True, 'query_type': query_type}
                            )
                    else:
                        logger.warning(f"{LOG_WARNING} Schedule query detected but calendar/task tools not available")
            
            # === CROSS-DOMAIN DETECTION ===
            # Check if this is a cross-domain query that requires coordination
            is_cross, domains, confidence = await self.cross_domain_handler.is_cross_domain_query(query)
            
            if is_cross and confidence >= OrchestratorConfig.CROSS_DOMAIN_CONFIDENCE_THRESHOLD:
                logger.info(
                    f"{LOG_INFO} Cross-domain query detected: "
                    f"{[d.value for d in domains]} (confidence: {confidence:.2f})"
                )
                
                    # Cross-domain query detected - no extra event needed
                
                # Handle as cross-domain query
                cross_result = await self.cross_domain_handler.handle_cross_domain_query(
                    query, self.tools, workflow_emitter=self.workflow_emitter, user_id=user_id
                )
                
                execution_time = self._calculate_execution_time(start_time)
                await self._emit_workflow_complete("Cross-domain query completed successfully", {'response': cross_result.get('result', '')})
                
                return OrchestrationResult(
                    success=cross_result.get('successful_count', 0) > 0,
                    final_result=cross_result.get('result', ''),
                    steps_executed=cross_result.get('successful_count', 0),
                    total_steps=cross_result.get('total_count', 0),
                    execution_time=execution_time,
                    errors=[],
                    context_used={'cross_domain': True, 'domains': cross_result.get('domains', [])}
                )
            
            # === STANDARD EXECUTION FLOW ===
            # Get execution strategy from intent_patterns for better orchestration
            strategy = None
            try:
                strategy = get_execution_strategy(query)
                logger.info(
                    f"{LOG_INFO} Execution strategy: "
                    f"complexity={strategy['complexity']['complexity_level']}, "
                    f"domain={strategy['primary_domain']}, "
                    f"estimated_steps={strategy['estimated_steps']}"
                )
                
                # Strategy determined - no extra event needed
            except Exception as e:
                logger.debug(f"[ORCHESTRATOR] Failed to get execution strategy: {e}")
            
            # === STEP 2: RESEARCH CONTEXT ===
            # Use ResearcherRole to gather contextual information before execution
            research_context = None
            if self.researcher_role:
                try:
                    research_result = await self.researcher_role.research(
                        query=query,
                        limit=5,
                        use_vector=True,
                        use_graph=True
                    )
                    if research_result.success and research_result.combined_results:
                        research_context = research_result.get_top_results(3)
                        logger.info(f"{LOG_INFO} Research found {len(research_context)} contextual results")
                except Exception as e:
                    logger.debug(f"Research context gathering failed (non-critical): {e}")
            
            # Get memory recommendations if available
            memory_recommendations = self._get_memory_recommendations(query, user_id)
            if memory_recommendations:
                logger.info(f"{LOG_INFO} Using memory recommendations: {memory_recommendations.get('recommended_tools', [])}")
            
            # === STEP 3: PLAN EXECUTION ===
            # Use OrchestratorRole for planning if available, otherwise fall back to execution_planner
            execution_steps = None
            if self.orchestrator_role and query_analysis:
                try:
                    # Use OrchestratorRole for planning
                    execution_plan = await self.orchestrator_role.create_plan(
                        query=query,
                        intent=query_analysis.intent,
                        domains=query_analysis.domains,
                        entities=query_analysis.entities
                    )
                    # Convert ExecutionPlan steps to ExecutionStep format
                    # Note: ExecutionPlan uses different step structure, so we map it
                    execution_steps = []
                    for plan_step in execution_plan.steps:
                        # Map plan_step to ExecutionStep
                        # plan_step has: step_id, step_type, domain, action, query, dependencies
                        plan_domain = getattr(plan_step, 'domain', 'general')
                        step = ExecutionStep(
                            id=plan_step.step_id,
                            query=getattr(plan_step, 'query', query),
                            tool_name=self._map_domain_to_tool(plan_domain),
                            action=getattr(plan_step, 'action', 'execute'),
                            intent=query_analysis.intent,
                            domain=plan_domain,  # Preserve domain from plan
                            dependencies=getattr(plan_step, 'dependencies', []) or [],
                            context_requirements={}
                        )
                        execution_steps.append(step)
                    logger.info(f"{LOG_INFO} OrchestratorRole created plan with {len(execution_steps)} steps")
                except Exception as e:
                    logger.debug(f"OrchestratorRole planning failed, falling back to execution_planner: {e}")
            
            # Use execution_planner if OrchestratorRole not available or failed
            if not execution_steps:
                # Decompose query with memory context
                decomposed_steps = self.query_decomposer.decompose_query(query, memory_recommendations)
                logger.info(f"{LOG_INFO} Decomposed into {len(decomposed_steps)} steps")
                
                # Create execution plan with tool recommendations
                execution_steps = await self.execution_planner.create_execution_plan(
                    decomposed_steps,
                    recommended_tools=memory_recommendations.get('recommended_tools', []) if memory_recommendations else [],
                    original_query=query
                )
            
            # Execute steps with context synthesis
            results, context = await self._execute_steps_with_context(execution_steps)
            
            # Calculate execution time
            execution_time = self._calculate_execution_time(start_time)
            
            # Synthesize final result with user_id for personalization
            final_result = self._synthesize_final_result(results, context, query, user_id=user_id)
            
            # === POST-EXECUTION MEMORY STORAGE ===
            # Store user message and agent response in Neo4j Session/Message nodes
            if self.memory_role and user_id and session_id:
                try:
                    # Extract intent and entities from query analysis
                    intent = query_analysis.intent if query_analysis else None
                    entities = query_analysis.entities if query_analysis else {}
                    
                    # Store user message
                    await self.memory_role.store_session_message(
                        session_id=session_id,
                        user_id=user_id,
                        role='user',
                        text=query,
                        intent=intent,
                        entities=entities,
                        confidence=query_analysis.complexity_score if query_analysis else None
                    )
                    
                    # Store agent response
                    await self.memory_role.store_session_message(
                        session_id=session_id,
                        user_id=user_id,
                        role='assistant',
                        text=final_result,
                        intent=intent,
                        entities={}
                    )
                    
                    logger.debug(f"[MEMORY] Stored conversation turn in session {session_id}")
                except Exception as e:
                    logger.debug(f"[MEMORY] Failed to store conversation turn: {e}")
            
            # Update memory if available (both memory_system and MemoryRole)
            if self.memory_system:
                self._update_memory(query, execution_steps, True, user_id)
            
            # Also update MemoryRole with PatternRecognition capability
            if self.memory_role:
                try:
                    execution_time_ms = execution_time * 1000
                    # Extract intent and domains from execution steps
                    intent = execution_steps[0].intent if execution_steps else 'general'
                    # Use domain field if available, otherwise infer from tool_name
                    domains = list(set(
                        step.get_domain() if hasattr(step, 'get_domain') else 
                        (step.domain if hasattr(step, 'domain') and step.domain else step.tool_name)
                        for step in execution_steps
                    ))
                    if not domains:
                        domains = ['general']
                    
                    # Use asyncio to call async method
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Create task if loop is running
                        asyncio.create_task(
                            self.memory_role.learn_from_execution(
                                query=query,
                                intent=intent,
                                domains=domains,
                                execution_time_ms=execution_time_ms,
                                success=True,
                                user_id=user_id
                            )
                        )
                    else:
                        loop.run_until_complete(
                            self.memory_role.learn_from_execution(
                                query=query,
                                intent=intent,
                                domains=domains,
                                execution_time_ms=execution_time_ms,
                                success=True,
                                user_id=user_id
                            )
                        )
                except Exception as e:
                    logger.debug(f"Could not update MemoryRole: {e}")
            
            execution_time = self._calculate_execution_time(start_time)
            await self._emit_workflow_complete("Query completed successfully", {'response': final_result})
            
            return OrchestrationResult(
                success=True,
                final_result=final_result,
                steps_executed=len([r for r in results if r.get('success', False)]),
                total_steps=len(execution_steps),
                execution_time=execution_time,
                errors=[r.get('error', '') for r in results if r.get('error')],
                context_used=context
            )
            
        except Exception as e:
            logger.error(f"{LOG_ERROR} Orchestration failed: {e}", exc_info=True)
            execution_time = self._calculate_execution_time(start_time)
            
            # Emit workflow error
            if self.workflow_emitter:
                await self.workflow_emitter.emit_error(
                    'workflow',
                    f"Orchestration failed: {str(e)}",
                    data={'error': str(e)}
                )
            
            return OrchestrationResult(
                success=False,
                final_result=f"{LOG_ERROR} Orchestration failed: {str(e)}",
                steps_executed=0,
                total_steps=0,
                execution_time=execution_time,
                errors=[str(e)],
                context_used={}
            )
    
    async def _execute_steps_with_context(self,
                                         execution_steps: List[ExecutionStep]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Execute steps with context synthesis"""
        results = []
        context = {}
        
        # Group steps by dependency level
        dependency_levels = self._group_by_dependency_level(execution_steps)
        
        for level_steps in dependency_levels:
            level_results = []
            
            for step in level_steps:
                result = await self._execute_single_step(step, context)
                level_results.append(result)
                
                if result.get('success', False):
                    step.status = ExecutionStatus.COMPLETED
                    step.result = result.get('result')
                else:
                    step.status = ExecutionStatus.FAILED
                    step.error = result.get('error')
            
            results.extend(level_results)
            
            # Extract context from step results and synthesize enriched context
            for result in level_results:
                if result.get('success') and result.get('result'):
                    # Extract structured context from result
                    extracted_context = await self.context_synthesizer.extract_context_from_result(
                        str(result.get('result', '')),
                        use_llm=True
                    )
                    if extracted_context:
                        context.update(extracted_context)
            
            # Synthesize cross-domain enriched context
            context = await self.context_synthesizer.synthesize_context(execution_steps, context)
        
        return results, context
    
    def _group_by_dependency_level(self, steps: List[ExecutionStep]) -> List[List[ExecutionStep]]:
        """Group steps by dependency level for proper execution order"""
        levels = []
        remaining_steps = steps.copy()
        completed_step_ids = set()
        
        while remaining_steps:
            current_level = []
            
            for step in remaining_steps[:]:
                if not step.dependencies or all(dep_id in completed_step_ids for dep_id in step.dependencies):
                    current_level.append(step)
                    remaining_steps.remove(step)
                    completed_step_ids.add(step.id)
            
            if not current_level:
                levels.append(remaining_steps)
                break
            
            levels.append(current_level)
        
        return levels
    
    async def _execute_single_step(self,
                                  step: ExecutionStep,
                                  context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single step with the appropriate tool"""
        # Validate routing before execution
        if self.domain_validator:
            validation = await self.domain_validator.validate_routing(
                query=step.query,
                tool_name=step.tool_name
            )
            
            if not validation.valid:
                error_msg = f"Domain validation failed: {validation.reason}"
                logger.error(f"{LOG_ERROR} {error_msg}")
                
                # Record failed validation
                self.analytics.record_domain_validation(
                    query=step.query,
                    detected_domain=validation.detected_domain.value if validation.detected_domain else 'unknown',
                    target_tool=step.tool_name,
                    validation_valid=False,
                    validation_confidence=validation.confidence,
                    detected_confidence=validation.confidence
                )
                
                # Emit validation error
                if self.workflow_emitter:
                    await self.workflow_emitter.emit_error(
                        'validation',
                        error_msg,
                        data={
                            'step_id': step.id,
                            'detected_domain': validation.detected_domain.value if validation.detected_domain else 'unknown',
                            'target_tool': step.tool_name,
                            'suggestions': validation.suggestions
                        }
                    )
                
                return {
                    'success': False,
                    'error': error_msg,
                    'domain_mismatch': True,
                    'suggestions': validation.suggestions
                }
            elif validation.confidence < DomainValidationConfig.MIN_VALIDATION_CONFIDENCE:
                logger.warning(
                    f"{LOG_WARNING} Low confidence routing: {validation.reason} "
                    f"(confidence: {validation.confidence:.2f})"
                )
        
        tool = self.tools.get(step.tool_name)
        if not tool:
            error_msg = f"Tool {step.tool_name} not available"
            logger.error(f"{LOG_ERROR} {error_msg}")
            
            # Emit tool error
            if self.workflow_emitter:
                await self.workflow_emitter.emit_error(
                    'tool',
                    f"Tool {step.tool_name} not available",
                    data={'tool': step.tool_name, 'error': error_msg}
                )
            
            # Record failed routing with ExecutionStep for domain extraction
            self.analytics.record_routing(
                query=step.query,
                routed_tool=step.tool_name,
                detected_domain=step.get_domain() if hasattr(step, 'get_domain') else None,
                confidence=0.0,
                outcome=RoutingOutcome.FAILURE,
                error_message=error_msg,
                execution_step=step  # Pass step for domain extraction
            )
            
            return {'success': False, 'error': error_msg}
        
        try:
            step.status = ExecutionStatus.IN_PROGRESS
            enriched_query = self._apply_context_to_query(step.query, context, step.context_requirements)
            
            # Use tool parser if available to enhance query understanding
            parser_used = False
            if hasattr(tool, 'parser') and tool.parser:
                try:
                    parsed = tool.parser.parse_query_to_params(enriched_query)
                    if parsed.get('confidence', 0) >= 0.6:
                        # Enhance enriched_query with parsed entities if action matches
                        parsed_action = parsed.get('action')
                        if parsed_action and (not step.action or step.action == 'search' or parsed_action == step.action):
                            # Use parsed action if it's more specific
                            if parsed_action != 'search' and parsed_action != 'list':
                                step.action = parsed_action
                                logger.debug(f"[ORCHESTRATOR] Parser enhanced action: {step.action}")
                            parser_used = True
                            
                            # Record parser usage in analytics
                            self.analytics.record_routing(
                                query=step.query,
                                routed_tool=step.tool_name,
                                detected_domain=step.get_domain() if hasattr(step, 'get_domain') else None,
                                confidence=parsed.get('confidence', 0.5),
                                outcome=RoutingOutcome.SUCCESS,
                                parser_used=True
                            )
                except Exception as e:
                    logger.debug(f"[ORCHESTRATOR] Tool parser failed (non-critical): {e}")
            
            # Emit tool call start event
            if self.workflow_emitter:
                await self.workflow_emitter.emit_tool_call_start(
                    step.tool_name,
                    action=step.action,
                    data={'query': enriched_query, 'step_id': step.id, 'parser_used': parser_used}
                )
            
            start_time = datetime.now()
            
            # Execute tool with proper parameter passing
            # Pass workflow_emitter so tools can emit high-level action events
            if hasattr(tool, '_run'):
                # Call with query as a named parameter so the tool can parse it
                result = tool._run(
                    action=step.action, 
                    query=enriched_query,
                    workflow_emitter=self.workflow_emitter
                )
            elif hasattr(tool, 'run'):
                result = tool.run(enriched_query)
            else:
                result = await tool.ainvoke({'query': enriched_query})
            
            execution_time = (datetime.now() - start_time).total_seconds()
            step.execution_time = execution_time
            
            # CRITICAL: Check if result indicates a rejection (e.g., email parser rejecting task queries)
            # If so, retry with task tool if query is about tasks
            if isinstance(result, str) and "[ERROR]" in result and "tasks/calendar" in result.lower():
                query_lower = step.query.lower()
                task_keywords = ['task', 'tasks', 'todo', 'todos', 'reminder', 'deadline']
                has_task_keywords = any(keyword in query_lower for keyword in task_keywords)
                
                if has_task_keywords and step.tool_name != 'tasks':
                    logger.info(f"{LOG_INFO} Tool {step.tool_name} rejected query, retrying with task tool: '{step.query[:50]}'")
                    task_tool = self.tools.get('tasks') or self.tools.get('task_tool')
                    if task_tool:
                        try:
                            # Retry with task tool
                            retry_result = task_tool._run(
                                action='list',
                                query=enriched_query,
                                workflow_emitter=self.workflow_emitter
                            )
                            logger.info(f"{LOG_OK} Retry with task tool succeeded")
                            result = retry_result
                            step.tool_name = 'tasks'  # Update step tool name for correct domain
                            # Update step domain to match task tool
                            if hasattr(step, 'domain'):
                                step.domain = 'tasks'
                            elif hasattr(step, 'set_domain'):
                                step.set_domain('tasks')
                        except Exception as retry_error:
                            logger.warning(f"{LOG_WARNING} Retry with task tool failed: {retry_error}")
                            # Continue with original result (error message)
            
            logger.info(f"{LOG_OK} Step {step.id} completed in {execution_time:.2f}s")
            
            # Emit tool call complete event
            if self.workflow_emitter:
                await self.workflow_emitter.emit_tool_complete(
                    step.tool_name,
                    result_summary=f"Completed {step.action}",
                    data={'step_id': step.id, 'execution_time': execution_time}
                )
            
            # Record successful routing with ExecutionStep for domain extraction
            self.analytics.record_routing(
                query=step.query,
                routed_tool=step.tool_name,
                detected_domain=step.get_domain() if hasattr(step, 'get_domain') else None,
                confidence=1.0,
                outcome=RoutingOutcome.SUCCESS,
                execution_time_ms=execution_time * 1000,
                execution_step=step  # Pass step for domain extraction
            )
            
            # Extract domain from step (critical for synthesizer to route results correctly)
            domain = step.get_domain() if hasattr(step, 'get_domain') else (
                step.domain if hasattr(step, 'domain') and step.domain else 
                step.tool_name  # Fallback to tool_name if domain not available
            )
            
            # Normalize domain to match synthesizer expectations
            domain = self._normalize_domain(domain)
            
            return {
                'success': True,
                'result': result,
                'step_id': step.id,
                'execution_time': execution_time,
                'action': step.action,
                'domain': domain  # CRITICAL: Include domain so synthesizer can route results correctly
            }
            
        except Exception as e:
            logger.error(f"{LOG_ERROR} Step {step.id} failed: {e}")
            
            # Emit tool error
            if self.workflow_emitter:
                await self.workflow_emitter.emit_error(
                    'tool',
                    f"Tool {step.tool_name} failed: {str(e)}",
                    data={'tool': step.tool_name, 'step_id': step.id, 'error': str(e)}
                )
            
            # Record failed routing with error and ExecutionStep for domain extraction
            self.analytics.record_routing(
                query=step.query,
                routed_tool=step.tool_name,
                detected_domain=step.get_domain() if hasattr(step, 'get_domain') else None,
                confidence=0.0,
                outcome=RoutingOutcome.FAILURE,
                error_message=str(e),
                execution_step=step  # Pass step for domain extraction
            )
            
            # Extract domain from step even for failed results
            domain = step.get_domain() if hasattr(step, 'get_domain') else (
                step.domain if hasattr(step, 'domain') and step.domain else 
                step.tool_name  # Fallback to tool_name if domain not available
            )
            
            # Normalize domain to match synthesizer expectations
            domain = self._normalize_domain(domain)
            
            return {
                'success': False,
                'error': str(e),
                'step_id': step.id,
                'action': step.action,
                'domain': domain  # Include domain even for failed results
            }
    
    def _apply_context_to_query(self,
                               query: str,
                               context: Dict[str, Any],
                               requirements: Dict[str, Any]) -> str:
        """Apply context requirements to enhance query"""
        if not context or not requirements:
            return query
        
        enriched_query = query
        
        if requirements.get('needs_previous_results'):
            prev_results = [v for k, v in context.items() if 'result' in k]
            if prev_results:
                enriched_query += f" [Context: {prev_results[-1][:200]}]"
        
        if requirements.get('needs_source_data') and 'source_data' in context:
            enriched_query += f" [Source: {context['source_data'][:200]}]"
        
        return enriched_query
    
    def _synthesize_final_result(self,
                                results: List[Dict[str, Any]],
                                context: Dict[str, Any],
                                original_query: str,
                                user_id: Optional[int] = None) -> str:
        """Synthesize final result using SynthesizerRole with capabilities for personalization"""
        successful_results = [r for r in results if r.get('success', False)]
        failed_results = [r for r in results if not r.get('success', False)]
        
        if not successful_results:
            errors = [r.get('error') for r in failed_results]
            return f"{LOG_ERROR} No successful results. Errors: {errors}"
        
        # CRITICAL: For create/update/delete operations, prioritize action results over search results
        # If we have both a search result and an action result, use only the action result
        action_results = [r for r in successful_results if r.get('action') in ['create', 'update', 'delete']]
        if action_results:
            # Use only action results, ignore search/list results
            successful_results = action_results
            logger.info(f"[ORCHESTRATOR] Prioritizing {len(action_results)} action result(s) over search results for synthesis")
        
        # Use SynthesizerRole with capabilities if available
        if self.synthesizer_role:
            try:
                import asyncio
                # Convert results to specialist_results format
                specialist_results = {}
                for result in successful_results:
                    domain = result.get('domain', 'general')
                    # Create a simple SpecialistResult-like object
                    class SimpleResult:
                        def __init__(self, data, success=True):
                            self.data = data
                            self.success = success
                    
                    specialist_results[domain] = SimpleResult(
                        data=result.get('result', result),
                        success=True
                    )
                
                # Use SynthesizerRole for synthesis with personalization
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If loop is running, create a task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            lambda: asyncio.run(
                                self.synthesizer_role.synthesize(
                                    query=original_query,
                                    specialist_results=specialist_results,
                                    context=context,
                                    user_id=user_id
                                )
                            )
                        )
                        synthesized = future.result()
                        return synthesized.response_text
                else:
                    synthesized = loop.run_until_complete(
                        self.synthesizer_role.synthesize(
                            query=original_query,
                            specialist_results=specialist_results,
                            context=context,
                            user_id=user_id
                        )
                    )
                    return synthesized.response_text
            except Exception as e:
                logger.debug(f"Could not use SynthesizerRole, falling back to LLM: {e}")
        
        # Generate conversational response using LLM with AGENT_SYSTEM_PROMPT
        if self.llm_client:
            try:
                # CRITICAL: Use absolute import to avoid module resolution issues
                try:
                    from src.ai.prompts.agent_prompts import get_agent_system_prompt
                except ImportError:
                    # Fallback to relative import if absolute fails
                    # From src/agent/orchestration/core/ to src/ai/prompts/ requires 4 dots (....)
                    from ....ai.prompts.agent_prompts import get_agent_system_prompt
                from langchain_core.messages import SystemMessage, HumanMessage
                
                # Format raw results for LLM (use filtered successful_results, not all results)
                raw_results = format_multi_step_response(successful_results)
                
                # Create conversational prompt using extracted method
                prompt = self._build_conversational_prompt(original_query, raw_results)
                
                system_prompt = get_agent_system_prompt(user_first_name=None)
                if not system_prompt or not isinstance(system_prompt, str):
                    logger.warning(f"{LOG_WARNING} get_agent_system_prompt returned invalid value, using fallback")
                    system_prompt = "You are Clavr, an intelligent personal assistant. Provide helpful, natural, conversational responses."
                
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=prompt)
                ]
                
                response = self.llm_client.invoke(messages)
                was_truncated = False
                
                # Check for truncation (finish_reason='length')
                if hasattr(response, 'response_metadata') and response.response_metadata:
                    metadata = response.response_metadata
                    if 'finish_reason' in metadata and metadata['finish_reason'] == 'length':
                        was_truncated = True
                        logger.warning(f"{LOG_WARNING} LLM response was TRUNCATED (finish_reason: length), retrying with higher max_tokens")
                        
                        # Retry with higher max_tokens
                        try:
                            retry_llm = LLMFactory.get_llm_for_provider(
                                self.config,
                                temperature=OrchestratorConfig.LLM_TEMPERATURE,
                                max_tokens=OrchestratorConfig.LLM_MAX_TOKENS_RETRY
                            )
                            if retry_llm:
                                retry_response = retry_llm.invoke(messages)
                                if hasattr(retry_response, 'content') and retry_response.content:
                                    response = retry_response
                                    was_truncated = False
                                    logger.info(f"{LOG_OK} Retry successful - got {len(response.content)} chars")
                        except Exception as retry_error:
                            logger.warning(f"{LOG_WARNING} Retry with higher max_tokens failed: {retry_error}")
                
                if hasattr(response, 'content') and response.content:
                    conversational_response = response.content.strip()
                    
                    # Warn if response was truncated and retry failed
                    if was_truncated:
                        logger.warning(f"{LOG_WARNING} Response may still be truncated after retry")
                    
                    # Clean up any technical tags that might have slipped through
                    conversational_response = self._clean_technical_tags(conversational_response)
                    # CRITICAL: Remove quotes from task/event titles to make it more natural
                    conversational_response = self._remove_quotes_from_titles(conversational_response)
                    logger.info(f"{LOG_OK} Generated conversational response using system prompt ({len(conversational_response)} chars)")
                    return conversational_response
            except ImportError as e:
                logger.warning(f"{LOG_WARNING} Import error generating conversational response: {e}, using fallback")
            except Exception as e:
                logger.warning(f"{LOG_WARNING} Failed to generate conversational response: {e}, using fallback")
        
        # Use format_multi_step_response from utils.py and clean it up (use filtered successful_results)
        formatted_response = format_multi_step_response(successful_results)
        return self._clean_technical_tags(formatted_response)
    
    def _clean_technical_tags(self, text: str) -> str:
        """Remove technical tags and prefixes from response text"""
        import re
        # Remove [OK], [ERROR], [INFO], [WARNING] tags
        text = re.sub(r'\[OK\]|\[ERROR\]|\[INFO\]|\[WARNING\]', '', text, flags=re.IGNORECASE)
        # Remove "Query:" and "Results:" prefixes
        text = re.sub(r'^Query:\s*', '', text, flags=re.MULTILINE | re.IGNORECASE)
        text = re.sub(r'^Results:\s*', '', text, flags=re.MULTILINE | re.IGNORECASE)
        # Remove "Performance:" section and everything after it
        text = re.sub(r'\nPerformance:.*', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove "Multi-Step Processing Complete" lines
        text = re.sub(r'Multi-Step Processing Complete\s*\n*', '', text, flags=re.IGNORECASE)
        # Clean up extra whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 consecutive newlines
        return text.strip()
    
    def _remove_quotes_from_titles(self, text: str) -> str:
        """Remove quotes from task/event titles and replace with bold formatting"""
        import re
        # Pattern to find quoted strings that look like titles
        quoted_patterns = [
            r'"([^"]{3,})"',  # Double quotes with content
            r"'([^']{3,})'",  # Single quotes with content
        ]
        
        cleaned_text = text
        for pattern in quoted_patterns:
            matches = re.finditer(pattern, cleaned_text)
            # Process matches in reverse order to preserve indices
            for match in reversed(list(matches)):
                content = match.group(1)
                quoted_str = match.group(0)
                
                # Skip if it looks like punctuation or special formatting
                if content.startswith(('(', '[', '{', '*', '_')):
                    continue
                
                # Check context to see if it's likely a title (task, event, email subject)
                start_idx = max(0, match.start() - 50)
                end_idx = min(len(cleaned_text), match.end() + 50)
                context = cleaned_text[start_idx:end_idx].lower()
                
                # If near title-related words, it's likely a title
                title_indicators = self._get_title_indicators()
                
                if any(word in context for word in title_indicators):
                    # Simply remove quotes completely - keep text natural without any formatting
                    # This applies to both creation and listing responses
                    cleaned_text = (
                        cleaned_text[:match.start()] +
                        content +
                        cleaned_text[match.end():]
                    )
                    logger.debug(f"[ORCHESTRATOR] Removed quotes from title: '{quoted_str}' → {content}")
        
        return cleaned_text
    
    def _update_memory(self,
                      query: str,
                      execution_steps: List[ExecutionStep],
                      success: bool,
                      user_id: Optional[int] = None):
        """Update memory system with execution results"""
        if not self.memory_system:
            return
        
        try:
            tools_used = [step.tool_name for step in execution_steps]
            
            if hasattr(self.memory_system, 'learn_query_pattern'):
                intent = execution_steps[0].intent if execution_steps else 'general'
                self.memory_system.learn_query_pattern(
                    query=query,
                    intent=intent,
                    tools_used=tools_used,
                    success=success,
                    user_id=user_id
                )
            
            logger.info(f"{LOG_INFO} Memory updated with execution pattern")
            
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Failed to update memory: {e}")

    def _get_memory_recommendations(self,
                                    query: str,
                                    user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get memory-based recommendations for query execution"""
        if not self.memory_system:
            return None
        
        try:
            # Determine likely intent for better recommendations
            query_lower = query.lower()
            if any(word in query_lower for word in ['find', 'search', 'get', 'show']):
                if any(word in query_lower for word in ['create', 'add', 'make', 'schedule']):
                    intent = 'multi_step'
                else:
                    intent = 'search'
            elif any(word in query_lower for word in ['create', 'add', 'schedule']):
                intent = 'create'
            else:
                intent = 'general'
            
            # Get similar patterns
            similar_patterns = self.memory_system.get_similar_patterns(query, intent, user_id)
            
            # Get tool recommendations
            recommended_tools = self.memory_system.get_tool_recommendations(query, intent, user_id)
            
            # Get user preferences if available
            user_preferences = []
            if user_id and hasattr(self.memory_system, 'get_user_preferences'):
                user_preferences = self.memory_system.get_user_preferences(user_id)
            
            return {
                'intent': intent,
                'similar_patterns': similar_patterns,
                'recommended_tools': recommended_tools,
                'user_preferences': user_preferences,
                'confidence': similar_patterns[0].confidence if similar_patterns else OrchestratorConfig.MIN_MEMORY_CONFIDENCE
            }
            
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Failed to get memory recommendations: {e}")
            return None


def create_orchestrator(tools: List[Any],
                       config=None,
                       db: Optional[Any] = None,
                       memory_system: Optional[Any] = None,
                       workflow_emitter: Optional[Any] = None,
                       rag_engine: Optional[Any] = None,
                       graph_manager: Optional[Any] = None) -> Orchestrator:
    """
    Factory function to create Orchestrator with full agent role integration
    
    Args:
        tools: List of tools available to the orchestrator
        config: Optional configuration object
        db: Optional database session
        memory_system: Optional memory system for learning
        workflow_emitter: Optional workflow event emitter for streaming
        rag_engine: Optional RAG engine for ResearcherRole
        graph_manager: Optional graph manager for ResearcherRole and ContactResolverRole
        
    Returns:
        Orchestrator instance with all agent roles initialized
    """
    return Orchestrator(
        tools=tools,
        config=config,
        db=db,
        memory_system=memory_system,
        workflow_emitter=workflow_emitter,
        rag_engine=rag_engine,
        graph_manager=graph_manager
    )
