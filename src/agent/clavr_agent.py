"""
Clavr Agent - Orchestrator

Multi-step reasoning agent with intelligent query orchestration.

This provides:
- Complex multi-step query handling via modular orchestrator
- Memory graph learning and adaptation
- Performance monitoring and optimization

Usage:
    # Standard ClavrAgent usage
    agent = ClavrAgent(tools, config, memory, enable_orchestration=True)
    
    # Handles complex multi-step queries automatically
    result = await agent.execute("Find action items from my next week's meetings and create tasks")
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import re
import asyncio
from ..utils.logger import setup_logger

from .events import WorkflowEventEmitter, create_workflow_emitter
from .orchestration import (
    create_orchestrator, 
    create_autonomous_orchestrator,
    OrchestratorConfig
)
from .orchestration.config import (
    LOG_INFO, LOG_ERROR, LOG_OK, LOG_WARNING
)
from .memory import SimplifiedMemorySystem, MemoryIntegrator, create_memory_system
from .intent import (
    should_use_orchestration,
    get_execution_strategy,
    analyze_query_complexity,
    extract_entities,
    classify_query_intent,
    recommend_tools
)
from .caching import IntentPatternsCache, ComplexityAwareCache
from .formatting import ResponseFormatter
from .clavr_agent_config import ClavrAgentConfig
from ..ai.prompts import get_conversational_enhancement_prompt, get_agent_system_prompt
from langchain_core.messages import SystemMessage, HumanMessage

logger = setup_logger(__name__)


class ClavrAgent:
    """
    ClavrAgent with multi-step reasoning capabilities
    
    Intelligent agent with orchestrated features:
    - Multi-step query decomposition and execution (via modular orchestrator)
    - Persistent memory graph with user learning
    - Intelligent tool coordination with dependency resolution
    - Cross-domain context synthesis and enrichment
    - Performance optimization with caching and parallel execution
    """
    
    def __init__(self, 
                 tools: Optional[List] = None, 
                 config: Optional[Any] = None, 
                 memory: Optional[Any] = None,
                 db: Optional[Any] = None,
                 enable_orchestration: bool = True,
                 enable_autonomous_orchestration: bool = False,
                 user_first_name: Optional[str] = None):
        """
        Initialize ClavrAgent
        
        Args:
            tools: List of tools (same as original ClavrAgent)
            config: Configuration object (same as original ClavrAgent)
            memory: ConversationMemory instance (same as original ClavrAgent) 
            db: Database session for orchestration features (new)
            enable_orchestration: Whether to enable multi-step orchestration features (new)
            enable_autonomous_orchestration: Whether to use LangGraph autonomous orchestration (new, experimental)
            user_first_name: Optional user's first name for personalization
        """
        self.tools = tools or []
        self.config = config
        self.memory = memory
        self.db = db
        self.enable_orchestration = enable_orchestration
        self.enable_autonomous_orchestration = enable_autonomous_orchestration
        self.user_first_name = user_first_name
        
        # Initialize memory system for learning and optimization
        self.memory_system = create_memory_system(db)
        self.memory_integrator = MemoryIntegrator(self.memory_system)
        
        # Initialize enhancement modules
        self.intent_cache = IntentPatternsCache()
        self.response_cache = ComplexityAwareCache(enable_high_complexity_cache=False)
        self.response_formatter = ResponseFormatter()
        logger.info(f"{LOG_OK} Enhancements enabled (cache + response formatting)")
        
        # Initialize workflow event emitter BEFORE orchestrator (needed for passing to orchestrator)
        self.workflow_emitter = create_workflow_emitter()
        
        # Initialize orchestration strategy
        self.orchestrator = None
        self.autonomous_orchestrator = None
        
        if enable_orchestration:
            # Initialize RAG engine and graph manager for agent roles
            from api.dependencies import AppState
            from ..services.indexing.graph.manager import KnowledgeGraphManager
            
            rag_engine = AppState.get_rag_engine()
            graph_manager = KnowledgeGraphManager(config=config)
            
            if enable_autonomous_orchestration:
                # Use LangGraph autonomous orchestration with all agent roles
                self.autonomous_orchestrator = create_autonomous_orchestrator(
                    tools=self.tools,
                    config=config,
                    db=db,
                    memory_system=self.memory_system,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager
                )
                logger.info(f"{LOG_OK} ClavrAgent initialized with LangGraph autonomous orchestrator (all agent roles integrated)")
            else:
                # Use pattern-based modular orchestrator with all agent roles
                self.orchestrator = create_orchestrator(
                    tools=self.tools,
                    config=config,
                    db=db,
                    memory_system=self.memory_system,
                    workflow_emitter=self.workflow_emitter,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager
                )
                logger.info(f"{LOG_OK} ClavrAgent initialized with modular orchestrator (all agent roles integrated)")
        else:
            logger.info(f"{LOG_INFO} ClavrAgent initialized (orchestration disabled)")
        
        # Statistics tracking
        self.stats = self._init_stats()

    async def execute(self, 
                     query: str, 
                     user_id: Optional[int] = None, 
                     session_id: Optional[str] = None) -> str:
        """
        Execute query with intelligent orchestration routing
        
        Uses intent_patterns.py to automatically decide between:
        - Orchestrated execution (for complex multi-step queries)
        - Direct execution (for simple single-step queries)
        - Request-level caching (eliminates redundant analysis)
        - Complexity-aware response caching (TTL based on query complexity)
        - Entity-aware context synthesis (richer responses)
        
        Args:
            query: User query string
            user_id: Optional user ID for personalization
            session_id: Optional session ID for conversation tracking
            
        Returns:
            Formatted response string
        """
        start_time = datetime.now()
        self.stats[ClavrAgentConfig.STATS_QUERIES_PROCESSED] += 1
        execution_result = None
        
        # Initialize request-level cache for this query
        if self.intent_cache:
            request_id = f"req_{self.stats[ClavrAgentConfig.STATS_QUERIES_PROCESSED]}_{start_time.timestamp()}"
            self.intent_cache.new_request(request_id)
        
        try:
            # Execute query directly
            # NOTE: Response caching is currently disabled to ensure fresh data for all queries.
            # The complexity detection in ComplexityAwareCache works correctly, but we prioritize
            # real-time results over caching to avoid stale data issues with emails, tasks, and calendar.
            # To re-enable: wrap _execute_with_routing with self.response_cache.get_or_execute_async()
            response, execution_result = await self._execute_with_routing(
                query, user_id, session_id, start_time
            )
            return response
        
        except Exception as e:
            import traceback
            error_msg = f"{LOG_ERROR} Failed to process query: {str(e)}"
            print(error_msg)
            print(f"{LOG_ERROR} Full traceback:")
            print(traceback.format_exc())
            
            execution_result = {
                'success': False,
                'execution_type': 'error',
                'tools_used': [],
                'execution_time': f"{(datetime.now() - start_time).total_seconds():.2f}s",
                'error': str(e),
                'traceback': traceback.format_exc()
            }
            
            return error_msg
        
        finally:
            # Learn from this execution using memory system
            if self.memory_integrator and execution_result:
                try:
                    self.memory_integrator.learn_from_orchestrator_execution(
                        query=query,
                        execution_result=execution_result,
                        user_id=user_id
                    )
                except Exception as e:
                    print(f"{LOG_WARNING} Failed to record execution in memory: {e}")
            
            # Clear request cache after execution
            cache_stats = self.intent_cache.get_stats()
            hit_count = cache_stats.get('hit_count', cache_stats.get('cache_hits', 0))
            if hit_count > 0:
                hit_rate = cache_stats.get('hit_rate', cache_stats.get('hit_rate_percent', 0) / 100)
                logger.info(f"{LOG_OK} Intent cache: {hit_count} hits, {hit_rate:.0%} hit rate")
    
    async def _execute_with_routing(self, 
                                    query: str, 
                                    user_id: Optional[int],
                                    session_id: Optional[str],
                                    start_time: datetime) -> tuple[str, Dict[str, Any]]:
        """Internal method for executing query with intelligent routing
        
        Returns:
            Tuple of (response, execution_result)
        """
        execution_result = None
        
        # Intelligent routing: Use intent_patterns to decide execution strategy
        use_orchestrator = False
        complexity_info = {'complexity_level': 'unknown', 'complexity_score': 0}
        entities = {'entities': []}
        
        if self.orchestrator:
            # Use intent cache for caching
            orchestration_decision = self.intent_cache.get_orchestration_decision(query)
            complexity_result = self.intent_cache.get_complexity(query)
            entities_result = self.intent_cache.get_entities(query)
            
            # Ensure we don't overwrite with None values
            if orchestration_decision is not None:
                use_orchestrator = orchestration_decision
            if complexity_result is not None:
                complexity_info = complexity_result
            if entities_result is not None:
                entities = entities_result
            
            logger.info(f"{LOG_INFO} Query complexity: {complexity_info.get('complexity_level', 'unknown')}")
            logger.info(f"{LOG_INFO} Orchestration recommended: {use_orchestrator}")
            
            # Log extracted entities
            if entities and entities.get('entities'):
                entity_list = entities.get('entities', [])
                if entity_list:
                    logger.info(f"{LOG_INFO} Extracted entities: {', '.join(entity_list[:3])}")
        
        # Use orchestrator (can handle both simple and complex queries)
        if self.orchestrator:
            # Log execution type
            if use_orchestrator:
                logger.info(f"{LOG_INFO} Using orchestrated execution for complex query: {query[:50]}...")
                self.stats[ClavrAgentConfig.STATS_ORCHESTRATED_QUERIES] += 1
            else:
                logger.info(f"{LOG_INFO} Using orchestrated execution for simple query: {query[:50]}...")
                self.stats[ClavrAgentConfig.STATS_SIMPLE_QUERIES] += 1
            
            result = await self.orchestrator.execute_query(
                query=query,
                user_id=user_id,
                session_id=session_id
            )
            
            # Format orchestration result with response formatting
            if self.response_formatter and entities:
                response = self.response_formatter.synthesize(
                    query=query,
                    results={'orchestration_result': result},
                    entities=entities
                )
                # Also add formatted orchestration details
                response += "\n\n" + self._format_orchestration_result(result, query)
            else:
                response = self._format_orchestration_result(result, query)
            
            execution_result = {
                'success': result.success,
                'execution_type': 'orchestrated',
                'tools_used': ['modular_orchestrator'],
                'execution_time': f"{result.execution_time:.2f}s",
                'steps_executed': result.steps_executed,
                'total_steps': result.total_steps,
                'complexity_score': complexity_info.get('complexity_score', 0),
                'entities_extracted': len(entities.get('entities', [])) if entities else 0
            }
        else:
            # Use standard processing for simple queries
            logger.info(f"{LOG_INFO} Using direct execution for simple query")
            self.stats[ClavrAgentConfig.STATS_SIMPLE_QUERIES] += 1
            
            # Apply response formatting
            if self.response_formatter and entities:
                raw_response = await self._execute_standard(query, user_id, session_id)
                response = self.response_formatter.synthesize(
                    query=query,
                    results={'raw_response': raw_response},
                    entities=entities
                )
            else:
                response = await self._execute_standard(query, user_id, session_id)
            
            execution_result = {
                'success': True,
                'execution_type': 'standard',
                'tools_used': ['standard_processor'],
                'execution_time': f"{(datetime.now() - start_time).total_seconds():.2f}s",
                'complexity_score': complexity_info.get('complexity_score', 0),
                'entities_extracted': len(entities.get('entities', [])) if entities else 0
            }
        
        # Update statistics
        execution_time = (datetime.now() - start_time).total_seconds()
        self._update_stats(execution_time)
        
        return response, execution_result
    
    def _format_orchestration_result(self, result, query: str) -> str:
        """Format OrchestrationResult into a user-friendly string with conversational enhancement"""
        if not result.success:
            # For errors, return a clean error message without technical tags
            error_msg = result.final_result
            # Remove any [ERROR] or similar tags if present
            if error_msg.startswith(LOG_ERROR):
                error_msg = error_msg[len(LOG_ERROR):].strip()
            return error_msg
        
        response = result.final_result
        
        # Check if response is already conversational
        if self._is_robotic_response(response):
            # Try to enhance with conversational formatting using LLM
            enhanced = self._enhance_response_conversationally(query, response)
            if enhanced:
                return enhanced
        
        # Return original response (either already conversational or enhancement failed)
        return response
    
    async def _execute_standard(self, query: str, _user_id: Optional[int], _session_id: Optional[str]) -> str:
        """Execute query using standard processing"""
        return f"Standard Processing\n\nQuery: {query}\n\nNote: Multi-step orchestration is disabled. Enable it for advanced query processing."
    
    async def stream_execute(self, 
                           query: str, 
                           user_id: Optional[int] = None, 
                           session_id: Optional[str] = None,
                           chunk_size: int = ClavrAgentConfig.DEFAULT_CHUNK_SIZE,
                           stream_workflow: bool = True) -> Any:
        """
        Execute query and stream the response (with optional workflow events)
        
        This method can stream in two modes:
        1. Workflow mode (stream_workflow=True): Yields structured workflow events
           showing agent reasoning, tool calls, and actions in real-time
        2. Text mode (stream_workflow=False): Yields text chunks of final response
        
        Args:
            query: User query string
            user_id: Optional user ID for personalization
            session_id: Optional session ID for conversation tracking
            chunk_size: Number of characters per chunk (for text mode)
            stream_workflow: Whether to stream workflow events (default: True)
            
        Yields:
            WorkflowEvent objects (if stream_workflow=True) or
            String chunks (if stream_workflow=False)
        """
        if stream_workflow and self.workflow_emitter:
            # Enable workflow event emission FIRST, before subscribing
            self.workflow_emitter.enable()
            self.workflow_emitter.clear_history()
            
            # Set up event capture queue
            event_queue = asyncio.Queue()
            execution_complete = asyncio.Event()
            final_response_container: Optional[str] = None
            
            async def event_callback(event):
                """Callback to capture events and put them in queue"""
                try:
                    await event_queue.put(event)
                    # If this is a workflow_complete event, mark execution as complete
                    if hasattr(event, 'type') and hasattr(event.type, 'value') and event.type.value == 'workflow_complete':
                        execution_complete.set()
                except Exception as e:
                    # Log but don't break the workflow
                    import logging
                    logging.warning(f"Error in event callback: {e}")
            
            # CRITICAL: Subscribe to events BEFORE starting execution
            # This ensures we capture all events from the start
            self.workflow_emitter.on_event(event_callback)
            
            # Start execution in background
            async def run_execution():
                nonlocal final_response_container
                try:
                    result = await self.execute(query, user_id, session_id)
                    final_response_container = result
                    execution_complete.set()
                except Exception as e:
                    final_response_container = f"Error: {str(e)}"
                    execution_complete.set()
            
            execution_task = asyncio.create_task(run_execution())
            
            # Stream events as they come
            events_yielded = set()
            start_time = asyncio.get_event_loop().time()
            
            # Stream events from queue
            async for event in self._stream_events_from_queue(
                event_queue, 
                execution_complete, 
                execution_task, 
                start_time
            ):
                event_key = self._get_event_key(event)
                if event_key not in events_yielded:
                    yield event
                    events_yielded.add(event_key)
            
            # Get any remaining events from queue
            async for event in self._drain_event_queue(event_queue):
                event_key = self._get_event_key(event)
                if event_key not in events_yielded:
                    yield event
                    events_yielded.add(event_key)
            
            # Ensure execution task completes
            if not execution_task.done():
                try:
                    await asyncio.wait_for(
                        execution_task, 
                        timeout=ClavrAgentConfig.STREAM_TASK_COMPLETION_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
            
            # Get final response
            if final_response_container is None and execution_task.done():
                try:
                    final_response_container = execution_task.result()
                except Exception as e:
                    final_response_container = f"Error: {str(e)}"
            
            # Yield final response as workflow complete event if not already yielded
            if final_response_container:
                # Check if workflow_complete was already emitted
                workflow_complete_emitted = any(
                    hasattr(e, 'type') and e.type.value == 'workflow_complete'
                    for e in self.workflow_emitter.event_history
                )
                
                if not workflow_complete_emitted:
                    # CRITICAL: Don't include response in workflow_complete event when streaming
                    # The response will be streamed as text chunks, so including it here causes duplication
                    await self.workflow_emitter.emit_workflow_complete(
                        "Query completed successfully",
                        data={'streaming': True}  # Signal that text chunks will follow
                    )
                    # Get the last event from history
                    if self.workflow_emitter.event_history:
                        yield self.workflow_emitter.event_history[-1]
                
                # CRITICAL: Stream the final response text character by character
                # This ensures the text appears to stream naturally, not all at once
                response_text = final_response_container
                if response_text and isinstance(response_text, str):
                    async for chunk in self._stream_text_chunks(response_text, chunk_size):
                        yield chunk
            
            # Clean up
            self.workflow_emitter.remove_listener(event_callback)
            self.workflow_emitter.disable()
        else:
            # Fallback to text streaming
            full_response = await self.execute(query, user_id, session_id)
            
            # Stream the response in chunks
            for i in range(0, len(full_response), chunk_size):
                chunk = full_response[i:i + chunk_size]
                yield chunk

    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution statistics and performance metrics"""
        total_queries = self.stats[ClavrAgentConfig.STATS_QUERIES_PROCESSED]
        orchestrated_count = self.stats[ClavrAgentConfig.STATS_ORCHESTRATED_QUERIES]
        orchestrated_rate = (orchestrated_count / total_queries) if total_queries > 0 else 0
        avg_time = self.stats[ClavrAgentConfig.STATS_AVERAGE_EXECUTION_TIME]
        
        base_stats = {
            **self.stats,
            "orchestrated_rate": orchestrated_rate,
            "orchestration_percentage": f"{orchestrated_rate:.1%}",
            "queries_per_second": 1 / avg_time if avg_time > 0 else 0
        }
        
        # Add memory system statistics if available
        if self.memory_system:
            try:
                memory_stats = self.memory_system.get_execution_stats()
                base_stats["memory_system"] = memory_stats
            except Exception as e:
                base_stats["memory_system"] = {"error": str(e)}
        
        return base_stats
    
    def get_memory_recommendations(self, query: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Get memory-based recommendations for query optimization"""
        if not self.memory_integrator:
            return {"error": "Memory system not available"}
        
        try:
            return self.memory_integrator.get_orchestrator_recommendations(query, user_id)
        except Exception as e:
            return {"error": str(e)}
    
    def clear_caches(self):
        """Clear all caches for memory management"""
        # Reset statistics
        self.stats = self._init_stats()
        
        # Clear caches
        self.response_cache.clear()
        logger.info(f"{LOG_OK} Response cache cleared")
        
        # Intent cache is request-level, no need to clear
        logger.info(f"{LOG_OK} Intent cache ready (request-level)")
        
        # Clear memory system old patterns
        try:
            self.memory_system.clear_old_patterns(max_age_days=ClavrAgentConfig.MEMORY_CLEAR_MAX_AGE_DAYS)
            logger.info(f"{LOG_OK} Memory system caches cleared")
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Failed to clear memory system caches: {e}")
        
        logger.info(f"{LOG_OK} Agent caches and statistics cleared")
    
    # === Helper Methods ===
    
    def _init_stats(self) -> Dict[str, Any]:
        """Initialize statistics dictionary"""
        return {
            ClavrAgentConfig.STATS_QUERIES_PROCESSED: 0,
            ClavrAgentConfig.STATS_ORCHESTRATED_QUERIES: 0,
            ClavrAgentConfig.STATS_SIMPLE_QUERIES: 0,
            ClavrAgentConfig.STATS_SUCCESS_RATE: 0.0,
            ClavrAgentConfig.STATS_TOTAL_EXECUTION_TIME: 0.0,
            ClavrAgentConfig.STATS_AVERAGE_EXECUTION_TIME: 0.0
        }
    
    def _update_stats(self, execution_time: float) -> None:
        """Update statistics after query execution"""
        self.stats[ClavrAgentConfig.STATS_TOTAL_EXECUTION_TIME] += execution_time
        queries = self.stats[ClavrAgentConfig.STATS_QUERIES_PROCESSED]
        self.stats[ClavrAgentConfig.STATS_AVERAGE_EXECUTION_TIME] = (
            self.stats[ClavrAgentConfig.STATS_TOTAL_EXECUTION_TIME] / queries if queries > 0 else 0.0
        )
        
        success_count = (
            self.stats[ClavrAgentConfig.STATS_ORCHESTRATED_QUERIES] + 
            self.stats[ClavrAgentConfig.STATS_SIMPLE_QUERIES]
        )
        self.stats[ClavrAgentConfig.STATS_SUCCESS_RATE] = success_count / queries if queries > 0 else 0.0
    
    def _is_robotic_response(self, response: str) -> bool:
        """Check if a response contains robotic patterns"""
        # Check string patterns
        is_robotic_string = any(
            pattern in response 
            for pattern in ClavrAgentConfig.ROBOTIC_STRING_PATTERNS
        )
        
        # Check regex patterns
        is_robotic_regex = any(
            re.search(pattern, response, re.MULTILINE | re.IGNORECASE) 
            for pattern in ClavrAgentConfig.ROBOTIC_REGEX_PATTERNS
        )
        
        return is_robotic_string or is_robotic_regex
    
    def _enhance_response_conversationally(self, query: str, response: str) -> Optional[str]:
        """Enhance a robotic response into conversational language using LLM"""
        if not self.config:
            return None
        
        try:
            from ..ai.llm_factory import LLMFactory
            
            llm = LLMFactory.get_llm_for_provider(
                self.config, 
                temperature=ClavrAgentConfig.ENHANCEMENT_LLM_TEMPERATURE
            )
            if not llm:
                return None
            
            prompt = get_conversational_enhancement_prompt(query, response)
            system_prompt = get_agent_system_prompt(user_first_name=self.user_first_name)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt)
            ]
            
            enhanced_response = llm.invoke(messages)
            if hasattr(enhanced_response, 'content') and enhanced_response.content:
                enhanced = enhanced_response.content.strip()
                # Double-check it's not still robotic
                if not self._is_robotic_response(enhanced):
                    logger.info(f"[AGENT] Enhanced robotic response conversationally")
                    return enhanced
                else:
                    logger.warning(f"[AGENT] Enhanced response still robotic, using original")
        except Exception as e:
            logger.debug(f"Failed to enhance response conversationally: {e}")
        
        return None
    
    def _get_event_key(self, event: Any) -> str:
        """Generate a unique key for event deduplication"""
        if hasattr(event, 'type') and hasattr(event, 'timestamp'):
            return f"{event.type.value}_{event.timestamp.isoformat() if event.timestamp else id(event)}"
        return str(id(event))
    
    async def _stream_events_from_queue(
        self,
        event_queue: asyncio.Queue,
        execution_complete: asyncio.Event,
        execution_task: asyncio.Task,
        start_time: float
    ):
        """Stream events from queue until execution completes or timeout"""
        while True:
            try:
                event = await asyncio.wait_for(
                    event_queue.get(), 
                    timeout=ClavrAgentConfig.STREAM_EVENT_TIMEOUT_SECONDS
                )
                yield event
                
                # Check if execution is complete
                if execution_complete.is_set():
                    break
                    
            except asyncio.TimeoutError:
                # Check if execution is done
                if execution_complete.is_set() or execution_task.done():
                    break
                
                # Check if we've exceeded max wait time
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > ClavrAgentConfig.MAX_STREAM_WAIT_TIME_SECONDS:
                    break
                
                # Continue loop to check for more events
                continue
    
    async def _drain_event_queue(self, event_queue: asyncio.Queue):
        """Drain remaining events from queue"""
        while not event_queue.empty():
            try:
                event = await asyncio.wait_for(
                    event_queue.get(), 
                    timeout=ClavrAgentConfig.STREAM_EVENT_TIMEOUT_SECONDS
                )
                yield event
            except asyncio.TimeoutError:
                break
    
    async def _stream_text_chunks(self, text: str, chunk_size: int):
        """Stream text in chunks with natural delay"""
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            if chunk:  # Only yield non-empty chunks
                yield chunk
                # Delay for natural text streaming effect
                await asyncio.sleep(ClavrAgentConfig.STREAM_CHUNK_DELAY_SECONDS)


def create_clavr_agent(tools: Optional[List] = None,
                      config: Optional[Any] = None,
                      memory: Optional[Any] = None,
                      db: Optional[Any] = None,
                      enable_orchestration: bool = True) -> 'ClavrAgent':
    """
    Factory function to create ClavrAgent
    
    Args:
        tools: List of tools
        config: Configuration object
        memory: ConversationMemory instance
        db: Database session (required for orchestration features)
        enable_orchestration: Whether to enable orchestration features
        
    Returns:
        ClavrAgent instance
    """
    return ClavrAgent(
        tools=tools,
        config=config,
        memory=memory,
        db=db,
        enable_orchestration=enable_orchestration
    )
