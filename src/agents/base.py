from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from langchain_core.tools import BaseTool

from ..utils.logger import setup_logger
from ..ai.llm_factory import LLMFactory
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
from datetime import datetime
import asyncio

from .constants import (
    DEFAULT_FAST_MODEL,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_TEMPERATURE,
    ERROR_TOOL_NOT_AVAILABLE
)
from src.ai.prompts.agent_prompts import PARAMETER_EXTRACTION_SYSTEM_PROMPT
from src.events import WorkflowEventType, WorkflowEvent

logger = setup_logger(__name__)

from src.memory.domain_context import DomainContext
from ..utils.performance import LatencyMonitor
from src.memory.orchestrator import get_memory_orchestrator

class BaseAgent(ABC):
    """
    Abstract base class for domain-specific agents.
    
    Each agent is responsible for:
    1. Managing its own tools
    2. Maintaining its own domain-specific memory/context (via DomainContext)
    3. Executing queries within its domain
    """
    
    def __init__(self, 
                 config: Dict[str, Any],
                 tools: List[BaseTool],
                 domain_context: Optional[DomainContext] = None,
                 event_emitter: Optional[Any] = None):
        """
        Initialize the agent.
        
        Args:
            config: Application configuration
            tools: List of tools available to this agent
            domain_context: Specialized memory context (Vector, Graph, Lane)
            event_emitter: Optional workflow event emitter for progress updates
        """
        self.config = config
        self.tools = {t.name: t for t in tools}
        self.domain_context = domain_context
        
        # Shortcuts for convenience
        self.memory_lane = domain_context.memory_lane if domain_context else None
        
        # Memory Orchestrator is no longer passed directly, accessed via import or if needed
        # But we previously used self.memory_orchestrator.
        # Ideally, DomainContext might not hold MemoryOrchestrator as that's "Global".
        # But for backward compatibility with existing method calls, we should check if we need it.
        # Current retrieve_relevant_memory uses it.
        # We'll assume we can get it from global or pass it? 
        # Actually, let's allow it to be None for now and rely on imports if possible,
        # OR better: add it to DomainContext as a reference if the factory puts it there?
        # The Factory has access to LaneManager.
        # Implementation Plan didn't specify MemoryOrchestrator in DomainContext explicitly but implies "Specialized".
        # Let's keep self.memory_orchestrator as None for now and fix methods to use imports or context.
        # Unified Memory System
        self.memory_orchestrator = get_memory_orchestrator()
        
        self.event_emitter = event_emitter
        self.name = self.__class__.__name__
        self.llm = self._init_llm()
        
        # Session tracking for working memory
        self._current_session_id: Optional[str] = None

    def _init_llm(self):
        """Initialize the LLM for this agent"""
        try:
            return LLMFactory.get_llm_for_provider(
                self.config,
                temperature=DEFAULT_LLM_TEMPERATURE,
                max_tokens=DEFAULT_LLM_MAX_TOKENS
            )
        except Exception as e:
            logger.error(f"[{self.name}] Failed to initialize LLM: {e}")
            return None
        
    @abstractmethod
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute a user query.
        
        Args:
            query: The user's natural language query
            context: Optional context from the supervisor/router
            
        Returns:
            The agent's response as a string
        """
        pass
    
    def _route_query(self, query: str, routes: Dict[str, List[str]]) -> Optional[str]:
        """
        Route a query based on keyword matching.
        
        Helper method to reduce boilerplate in agent run() methods.
        
        Args:
            query: User query to route
            routes: Dict mapping action names to keyword lists
                    e.g., {"send": ["send", "compose"], "list": ["show", "list"]}
                    
        Returns:
            Matched action name or None if no match
            
        Example:
            routes = {
                "create": INTENT_KEYWORDS['tasks']['create'],
                "complete": INTENT_KEYWORDS['tasks']['complete'],
                "list": INTENT_KEYWORDS['tasks']['list']
            }
            action = self._route_query(query, routes)
            if action == "create":
                return await self._handle_create(query)
        """
        query_lower = query.lower()
        for action, keywords in routes.items():
            if any(keyword in query_lower for keyword in keywords):
                return action
        return None
        
    async def retrieve_user_preferences(self, user_id: Optional[int] = None) -> str:
        """
        Retrieve user preferences to personalize agent interactions.
        Uses DomainContext (Memory Lane + Vector Store).
        """
        if not self.domain_context or not user_id:
            return ""
            
        try:
            # 1. Try to get explicit preferences from Memory Lane (Behavioral)
            if self.memory_lane:
                facts = self.memory_lane.get_facts_for_context(category="preference")
                if facts:
                    context_str = "KNOWN PREFERENCES:\n"
                    for fact in facts:
                        context_str += f"- {fact.content}\n"
                    return context_str
            
            # 2. Fallback to Vector Search for historical preferences
            if self.domain_context.vector_store:
                # Search for general and domain-specific preference keywords
                pref_query = f"user preferences for {self.name} {self.name} settings always never likes dislikes"
                with LatencyMonitor(f"[{self.name}] Pref Query"):
                    results = await self.domain_context.vector_store.asearch(
                        query=pref_query, 
                        filters={"user_id": user_id},
                        k=3, 
                        min_confidence=0.75
                    )
                
                if not results:
                    return ""
                    
                context_str = "HISTORICAL PREFERENCES:\n"
                for res in results:
                    content = res.get('content', '').strip()
                    if content:
                        context_str += f"- {content}\n"
                
                return context_str
                
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to retrieve user preferences: {e}")
            
        return ""

    async def learn_fact(self, user_id: int, content: str, category: str = "general") -> bool:
        """
        Learn a persistent fact about the user.
        
        Args:
            user_id: User ID
            content: The fact to learn
            category: Category (preference, contact, work, etc.)
            
        Returns:
            True if successful
        """
        if not self.memory_lane:
            return False
            
        try:
            result = await self.memory_lane.learn_fact(content, category) # Lane uses content, category
            if result:
                logger.info(f"[{self.name}] Learned new fact: {content[:30]}...")
                return True
        except Exception as e:
            logger.error(f"[{self.name}] Failed to learn fact: {e}")
            
        return False

    async def record_interaction(self, user_id: int, interaction_type: str, details: Dict[str, Any]) -> bool:
        """
        Record a significant agent interaction to the graph ('Write-Back').
        
        This enables:
        1. Relationship reinforcement (e.g. email sent -> strengthens connection with sender)
        2. Behavior learning (e.g. task completed -> feeds pattern miner)
        
        Args:
            user_id: ID of the user
            interaction_type: Type of interaction (email_sent, task_created, etc.)
            details: Metadata (e.g., related_person_email, target_id)
        """
        try:
            from api.dependencies import AppState
            graph_manager = AppState.get_graph_manager()
            
            if not graph_manager:
                return False
                
            # 1. Reinforce Relationships
            target_person = details.get('related_person_email') or details.get('related_person_name')
            if target_person:
                # We need to find the Person node first. logic simplified for brevity.
                # Ideally, RelationshipStrengthManager handles this via UnifiedIndexer.
                pass
                
            # 2. Feed Behavior Learner (via creating Event nodes if they don't exist)
            # Most tools (Gmail, Asana) create events via Crawlers eventually.
            # But for immediate feedback, we might want to log 'AgentAction' nodes?
            # For now, we'll rely on Crawlers for the 'Event' nodes, but we can
            # manually trigger a lightweight 'Action' node for the agent's contribution.
            
            # Create AGENT_ACTION node
            props = {
                "type": interaction_type,
                "agent": self.name,
                "details": json.dumps(details),
                "timestamp": datetime.utcnow().isoformat(),
                "user_id": user_id
            }
            # Just logging for now until we have a formal schema for Agent Actions
            logger.info(f"[{self.name}] Recorded interaction: {interaction_type}")
            return True
            
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to record interaction: {e}")
            return False
        
    async def _extract_params(
        self, 
        query: str, 
        schema: Dict[str, str], 
        user_id: Optional[int] = None,
        task_type: str = "general",
        use_fast_model: bool = True
    ) -> Dict[str, Any]:
        """
        Extract detailed parameters from the query using LLM.
        
        Optimized for latency:
        - Uses Flash model by default (use_fast_model=True)
        - Skips heavy memory retrieval for simple extraction tasks
        """
        if not self.llm:
            logger.warning(f"[{self.name}] LLM not available for parameter extraction")
            return {}
            
        # Get current time context with weekday for relative date resolution
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        
        # Determine if we should skip heavy memory retrieval
        # "planning", "research", "deep_search" need memory context. "simple_extraction" does not.
        is_heavy_task = task_type in ["planning", "research", "complex", "deep_search"]
        
        # Retrieve relevant memory context ONLY if user_id is provided AND it's a heavy task
        memory_context = ""
        if user_id and is_heavy_task:
            # Parallelize memory and preferences retrieval
            async def _fetch_memory():
                with LatencyMonitor(f"[{self.name}] Memory Retrieval (Param Extract)"):
                    return await self.retrieve_relevant_memory(
                        query, 
                        user_id=user_id,
                        task_type=task_type
                    )
            
            async def _fetch_prefs():
                 return await self.retrieve_user_preferences(user_id)
            
            # Execute in parallel
            try:
                # Use return_exceptions=False to raise errors, or handle gracefully?
                # Usually we want both.
                rel_mem, u_prefs = await asyncio.gather(_fetch_memory(), _fetch_prefs())
            except Exception as e:
                logger.warning(f"[{self.name}] Parallel param context fetch failed: {e}")
                rel_mem, u_prefs = "", ""

            # Combine them
            parts = []
            if rel_mem:
                parts.append(rel_mem)
            if u_prefs:
                parts.append(u_prefs)
                
            memory_context = "\n\n".join(parts)
            
            if memory_context:
                logger.debug(f"[{self.name}] Injected memory context for extraction: {len(memory_context)} chars")
            
        schema_str = json.dumps(schema, indent=2)
        
        try:
            # Format prompt with or without memory context
            # We handle the KeyException strictly in case the prompt template wasn't updated yet
            system_prompt = PARAMETER_EXTRACTION_SYSTEM_PROMPT.format(
                current_time_str=current_time_str,
                schema_str=schema_str,
                memory_context=memory_context
            )
        except KeyError:
            # Fallback for old prompt template without memory_context
            system_prompt = PARAMETER_EXTRACTION_SYSTEM_PROMPT.format(
                current_time_str=current_time_str,
                schema_str=schema_str
            )
        
        # Select LLM - Default to Fast model for simple extraction unless overridden
        # We try to use a cheaper/faster model for simple tasks
        model_to_use = self.llm
        if use_fast_model:
            try:
                # Try to get a dedicated fast model instance
                config = self.config if hasattr(self, 'config') else {}
                model_to_use = LLMFactory.get_google_llm(config, model=DEFAULT_FAST_MODEL, temperature=0.0)
            except Exception as e:
                logger.debug(f"[{self.name}] Could not get fast LLM, falling back to default: {e}")

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=query)
            ]
            
            # Use sync invoke wrapped in a thread for reliability (avoids async driver bugs)
            with LatencyMonitor(f"[{self.name}] LLM Param Extract"):
                response = await asyncio.to_thread(model_to_use.invoke, messages)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Clean up potential markdown formatting
            content = content.replace("```json", "").replace("```", "").strip()
            
            # Robust JSON extraction using regex
            json_match = re.search(r'(\{.*\})', content, re.DOTALL)
            if json_match:
                content = json_match.group(1)
            
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Attempt to repair common JSON errors
                repaired = self._repair_json(content)
                return json.loads(repaired)
                
        except Exception as e:
            logger.error(f"[{self.name}] Parameter extraction failed: {e}")
            logger.debug(f"[{self.name}] Failed JSON content: {content}")
            return {}

    def _repair_json(self, json_str: str) -> str:
        """
        Attempt to repair malformed JSON strings common from LLMs.
        - Replaces single quotes with double quotes
        - Fixes trailing commas
        - Fixes unquoted keys
        - Adds missing commas between key-value pairs
        """
        # 1. Replace single quotes with double quotes, but try to preserve apostrophes inside strings
        # This is tricky regex. A simple heuristic is: if it starts with { or [, replace 'key': with "key":
        
        # Replace 'key': with "key":
        json_str = re.sub(r"\'(\w+)\'\s*:", r'"\1":', json_str)
        # Replace : 'value' with : "value"
        json_str = re.sub(r":\s*\'([^\']*)\'", r': "\1"', json_str)
        
        # 2. Remove trailing commas
        json_str = re.sub(r",\s*([\]\}])", r"\1", json_str)
        
        # 3. Fix unquoted keys (e.g. key: "value")
        # Look for word characters followed by colon, not preceded by quote
        json_str = re.sub(r'(?<!")(\b\w+\b)\s*:', r'"\1":', json_str)
        
        # 4. Add missing commas between key-value pairs
        # Pattern: "value" "next_key" (with optional whitespace/newlines)
        # We look for: (ending quote) (whitespace) (starting quote of next key)
        # And ensure it's not inside a structural element? 
        # Actually, simpler: "value"\s+"key":  -> "value", "key":
        json_str = re.sub(r'\"\s+\"', '", "', json_str)
        
        return json_str

    def _get_tool(self, name: str) -> Optional[BaseTool]:
        """Retrieve a tool by exact name."""
        return self.tools.get(name)

    def _get_tool_by_alias(self, aliases: List[str]) -> Optional[BaseTool]:
        """
        Retrieve a tool by checking a list of aliases against tool names.
        Case-insensitive partial matching.
        """
        # First try exact matches from known tools (fast path)
        for alias in aliases:
            if alias in self.tools:
                return self.tools[alias]
        
        # Then search by checking if alias is contained in tool name logic
        for tool_name, tool in self.tools.items():
            name_lower = tool_name.lower()
            for alias in aliases:
                if alias.lower() in name_lower:
                    return tool
        
        return None

    def _get_tool_or_fail(self, alias_list: List[str]) -> Tuple[Optional[BaseTool], Optional[str]]:
        """
        Helper to retrieve a tool or return error message.
        Using a tuple return (tool, error_message) is safer for async flows without exceptions.
        
        Returns:
            (tool, None) if found
            (None, error_message) if not found
        """
        tool = self._get_tool_by_alias(alias_list)
        if not tool:
            return None, ERROR_TOOL_NOT_AVAILABLE
        return tool, None

    def _filter_none_values(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Filter out None values from a dictionary."""
        return {k: v for k, v in d.items() if v is not None}

    async def _safe_tool_execute(
        self,
        alias_list: List[str],
        tool_input: Dict[str, Any],
        action_description: str = "operation"
    ) -> str:
        """
        Safely execute a tool with standard error handling and event emission.
        """
        tool, error = self._get_tool_or_fail(alias_list)
        if error:
            return error
        
        # Identify if this is a "write" action for enhanced event logging
        action_name = tool_input.get("action", "").lower()
        is_write_action = any(
            x in action_name for x in ["create", "send", "update", "delete", "schedule", "archive", "trash"]
        )
        
        try:
            clean_input = self._filter_none_values(tool_input)
            
            # 1. Emit start events
            if self.event_emitter:
                # Always emit generic tool call start
                await self.event_emitter.emit_tool_call_start(
                    tool_name=tool.name,
                    action=action_name,
                    data={"input": clean_input}
                )
                
                # For write actions, emit specific ACTION_EXECUTING event
                if is_write_action:
                    await self.event_emitter.emit_action_executing(
                        action=action_description,
                        data={"tool": tool.name, "params": clean_input}
                    )
            
            # 2. Execute
            result = await tool.arun(clean_input)
            
            # 3. Emit completion events
            if self.event_emitter:
                # Generic tool completion
                summary = result[:100] + "..." if len(result) > 100 else result
                await self.event_emitter.emit_tool_complete(
                    tool_name=tool.name,
                    result_summary=summary
                )
                
                # For write actions, emit ACTION_COMPLETE
                if is_write_action:
                    await self.event_emitter.emit_action_complete(
                        action=action_description,
                        result=summary
                    )
            
            return result
            
        except Exception as e:
            error_msg = f"Error in {action_description}: {e}"
            logger.error(f"[{self.name}] {error_msg}")
            
            if self.event_emitter:
                await self.event_emitter.emit_error(
                    error_type="tool",
                    message=error_msg,
                    data={"tool": tool.name if tool else "unknown", "error": str(e)}
                )
                
            return error_msg

    def set_session_id(self, session_id: str):
        """Set the current session ID for working memory integration."""
        self._current_session_id = session_id
    
    async def retrieve_relevant_memory(
        self, 
        query: str, 
        user_id: Optional[int] = None,
        task_type: str = "general",
        session_id: Optional[str] = None
    ) -> str:
        """
        Retrieve relevant memory content from all memory layers.
        
        If a MemoryOrchestrator is available, uses the unified Perfect Memory system.
        Otherwise falls back to legacy retrieval methods.
        
        This enhanced method provides:
        - Working memory (recent turns, active entities/topics)
        - Semantic search via RAG (conversation history)
        - Multi-hop graph traversal (cross-app relationships)
        - Graph context enrichment (people, topics, projects)
        - Proactive insights
        
        Args:
            query: The query to find relevant memories for
            user_id: The user ID to scope the memory retrieval
            task_type: The type of task for optimized search (research, fact_check, planning, general)
            session_id: Optional session ID for working memory (uses _current_session_id if not provided)
            
        Returns:
            Formatted string of relevant memories from all sources
        """
        # Use provided session_id or fall back to current session
        effective_session_id = session_id or self._current_session_id
        
        # NEW: Use MemoryOrchestrator if available (Perfect Memory path)
        if self.memory_orchestrator and user_id:
            try:
                with LatencyMonitor(f"[{self.name}] Perfect Memory Retrieval"):
                    context = await self.memory_orchestrator.get_context_for_agent(
                        user_id=user_id,
                        agent_name=self.name,
                        query=query,
                        session_id=effective_session_id,
                        task_type=task_type
                    )
                formatted = context.to_prompt_string()
                if formatted:
                    logger.debug(
                        f"[{self.name}] Retrieved {len(formatted)} chars from MemoryOrchestrator "
                        f"(sources: {context.sources_queried})"
                    )
                    return "\n" + formatted
            except Exception as e:
                logger.warning(f"[{self.name}] MemoryOrchestrator retrieval failed, falling back: {e}")
        
        # LEGACY: Fall back to direct memory access
        if not self.domain_context or not user_id:
            return ""
        
        memory_parts = []
            
        try:

            # Parallelize independent fetch operations
            async def _fetch_vector():
                if self.domain_context.vector_store:
                    with LatencyMonitor(f"[{self.name}] Vector Search"):
                        results = await self.domain_context.vector_store.asearch(
                            query=query,
                            filters={"user_id": user_id},
                            k=3,
                            min_confidence=0.65
                        )
                        if results:
                            semantic_text = "CONVERSATION CONTEXT:\n"
                            for res in results:
                                content = res.get('content', '').strip()
                                if content:
                                    semantic_text += f"- {content}\n"
                            return semantic_text
                return None

            async def _fetch_graph():
                return await self._retrieve_graph_context(query, user_id, task_type)
                
            async def _fetch_insights():
                return await self._retrieve_relevant_insights(query, user_id)

            # Execute all in parallel
            results = await asyncio.gather(
                _fetch_vector(),
                _fetch_graph(),
                _fetch_insights(),
                return_exceptions=True
            )
            
            # Process results (results is a list: [vector, graph, insights])
            for res in results:
                if isinstance(res, Exception):
                    logger.debug(f"[{self.name}] One memory source failed: {res}")
                    continue
                if res:
                    memory_parts.append(res)
            
            if memory_parts:
                return "\n" + "\n".join(memory_parts)
            return ""
            
        except Exception as e:
            logger.warning(f"[{self.name}] Memory retrieval failed: {e}")
            return ""
    
    async def _retrieve_graph_context(self, query: str, user_id: int, task_type: str = "general") -> str:
        """
        Retrieve context via enhanced multi-hop graph traversal.
        
      
        - 3-hop traversal for deeper connections
        - Temporal awareness (prioritize recent content)
        - Relationship strength weighting (prioritize strong connections)
        - TimeBlock-based temporal queries
        
        Enables queries like "What did I discuss with Sarah about Project X last week?"
        """
        try:
            from src.services.indexing.rag_graph_bridge import GraphRAGIntegrationService
            
            # Use scoped graph manager from DomainContext
            graph_manager = self.domain_context.graph_manager if self.domain_context else None
            # Use scoped vector store from DomainContext
            rag_engine = self.domain_context.vector_store if self.domain_context else None
            
            if not graph_manager or not rag_engine:
                return ""
            
            integration = GraphRAGIntegrationService(rag_engine, graph_manager)
            
            # Check for temporal queries
            temporal_hint = self._extract_temporal_hint(query)
            
            # Use search_for_agent with task-specific tuning
            # This automatically selects depth and weights based on task_type
            with LatencyMonitor(f"[{self.name}] Graph Search"):
                results = await integration.search_for_agent(
                    query=query,
                    task_type=task_type,
                    user_id=user_id,
                    limit=7
                )
            
            if not results or not results.get('results'):
                # Fallback: Try temporal-aware search if we have temporal hints
                if temporal_hint:
                    results = await self._search_with_temporal_context(
                        query=query, 
                        user_id=user_id, 
                        temporal_hint=temporal_hint,
                        graph_manager=graph_manager
                    )
                
                if not results:
                    return ""
            
            # Format results with strength and temporal info
            graph_text = "CROSS-APP CONTEXT:\\n"
            seen_content = set()
            
            for result in results.get('results', [])[:7]:
                content = result.get('content', '') or result.get('text', '')
                if not content or content in seen_content:
                    continue
                seen_content.add(content)
                
                node_type = result.get('type', result.get('metadata', {}).get('node_type', 'Item'))
                source = result.get('source', result.get('metadata', {}).get('source', ''))
                
                # Get relationship strength if available
                strength = result.get('relationship_strength')
                timestamp = result.get('timestamp') or result.get('metadata', {}).get('timestamp')
                
                # Truncate content
                if len(content) > 200:
                    content = content[:200] + "..."
                
                # Build context line with metadata
                source_label = f" ({source})" if source else ""
                strength_indicator = "★" if strength and strength > 0.7 else ""
                recency = self._format_relative_time(timestamp) if timestamp else ""
                time_label = f" [{recency}]" if recency else ""
                
                graph_text += f"- {strength_indicator}[{node_type}]{source_label}{time_label}: {content}\\n"
                
                # Include related entities
                graph_context = result.get('graph_context', {})
                neighbors = graph_context.get('neighbors', [])
                if neighbors:
                    # Sort neighbors by relationship strength
                    sorted_neighbors = sorted(
                        neighbors, 
                        key=lambda n: n.get('relationship_strength', 0), 
                        reverse=True
                    )[:4]
                    related_items = []
                    for n in sorted_neighbors:
                        name = n.get('name', n.get('title', ''))[:25]
                        if name:
                            rel_strength = n.get('relationship_strength', 0)
                            if rel_strength > 0.7:
                                related_items.append(f"★{name}")
                            else:
                                related_items.append(name)
                    if related_items:
                        graph_text += f"  → Related: {', '.join(related_items)}\\n"
            
            return graph_text if len(graph_text) > 30 else ""
            
        except ImportError:
            return ""
        except Exception as e:
            logger.debug(f"[{self.name}] Graph context retrieval failed: {e}")
            return ""
    
    def _extract_temporal_hint(self, query: str) -> Optional[Dict[str, Any]]:
        """Extract temporal hints from query for time-based filtering."""
        import re
        
        query_lower = query.lower()
        
        # Common temporal patterns
        patterns = {
            'today': {'time_range': 'today'},
            'yesterday': {'time_range': 'yesterday'},
            'this week': {'time_range': 'week'},
            'last week': {'time_range': 'last_week'},
            'this month': {'time_range': 'month'},
            'last month': {'time_range': 'last_month'},
            'recent': {'time_range': 'week'},
            'recently': {'time_range': 'week'},
        }
        
        for pattern, hint in patterns.items():
            if pattern in query_lower:
                return hint
        
        # Check for relative time patterns
        match = re.search(r'(\\d+)\\s*(day|week|month)s?\\s*ago', query_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            return {'time_range': f'{amount}_{unit}s_ago'}
        
        return None
    
    def _format_relative_time(self, timestamp: Any) -> str:
        """Format timestamp as relative time (e.g., '2 days ago')."""
        try:
            if isinstance(timestamp, str):
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            elif isinstance(timestamp, datetime):
                dt = timestamp
            else:
                return ""
            
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            delta = now - dt
            
            if delta.days == 0:
                hours = delta.seconds // 3600
                if hours == 0:
                    return "just now"
                return f"{hours}h ago"
            elif delta.days == 1:
                return "yesterday"
            elif delta.days < 7:
                return f"{delta.days}d ago"
            elif delta.days < 30:
                weeks = delta.days // 7
                return f"{weeks}w ago"
            else:
                months = delta.days // 30
                return f"{months}mo ago"
        except:
            return ""
    
    async def _search_with_temporal_context(
        self, 
        query: str, 
        user_id: int, 
        temporal_hint: Dict[str, Any],
        graph_manager: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Search using TimeBlock-based temporal queries.
        
        Uses the TemporalIndexer's TimeBlock nodes to filter content by time.
        """
        try:
            time_range = temporal_hint.get('time_range', 'week')
            
            # Calculate date bounds based on time range
            from datetime import datetime, timedelta
            now = datetime.utcnow()
            today_str = now.strftime('%Y-%m-%d')
            
            if time_range == 'today':
                start_date = today_str
                end_date = today_str
            elif time_range == 'yesterday':
                yesterday = now - timedelta(days=1)
                start_date = yesterday.strftime('%Y-%m-%d')
                end_date = start_date
            elif time_range == 'week':
                start_date = (now - timedelta(days=7)).strftime('%Y-%m-%d')
                end_date = today_str
            elif time_range == 'last_week':
                start_date = (now - timedelta(days=14)).strftime('%Y-%m-%d')
                end_date = (now - timedelta(days=7)).strftime('%Y-%m-%d')
            elif time_range == 'month':
                start_date = (now - timedelta(days=30)).strftime('%Y-%m-%d')
                end_date = today_str
            else:
                start_date = (now - timedelta(days=7)).strftime('%Y-%m-%d')
                end_date = today_str
            
            # Build AQL query for temporal content search
            aql_query = """
            FOR tb IN TimeBlock
                FILTER tb.date >= @start_date AND tb.date <= @end_date
                
                FOR edge IN OCCURRED_DURING
                    FILTER edge._to == tb._id OR edge._from == tb._id
                    
                    LET content_id = edge._to == tb._id ? edge._from : edge._to
                    
                    FOR content IN UNION(
                        (FOR e IN Email FILTER e._id == content_id AND e.user_id == @user_id RETURN e),
                        (FOR c IN CalendarEvent FILTER c._id == content_id AND c.user_id == @user_id RETURN c),
                        (FOR t IN ActionItem FILTER t._id == content_id AND t.user_id == @user_id RETURN t)
                    )
                        RETURN {
                            id: content.id,
                            type: content.node_type,
                            text: content.text,
                            subject: content.subject,
                            title: content.title,
                            date: tb.date
                        }
            """
            
            results = await graph_manager.execute_query(aql_query, {
                'user_id': user_id,
                'start_date': start_date,
                'end_date': end_date
            })
            
            if not results:
                return None
            
            # Format results
            formatted = []
            for r in results:
                content = r.get('text') or r.get('subject') or r.get('title', '')
                if content:
                    formatted.append({
                        'content': content,
                        'type': r.get('type', 'Item'),
                        'timestamp': str(r.get('date'))
                    })
            
            return {'results': formatted} if formatted else None
            
        except Exception as e:
            logger.debug(f"[{self.name}] Temporal search failed: {e}")
            return None
    
    async def _retrieve_relevant_insights(self, query: str, user_id: int) -> str:
        """
        Retrieve proactive insights relevant to the current query.
        
        Surfaces insights generated by GraphObserver that are relevant
        to the user's current context.
        """
        try:
            from src.services.insights import get_insight_service
            
            insight_service = get_insight_service()
            if not insight_service:
                return ""
            
            insights = await insight_service.get_contextual_insights(
                user_id=user_id,
                current_context=query,
                max_insights=2
            )
            
            if not insights:
                return ""
            
            # Format insights for LLM context
            insight_text = "PROACTIVE INSIGHTS:\n"
            for insight in insights:
                insight_type = insight.get('type', 'info')
                content = insight.get('content', '')
                
                if insight_type == 'conflict':
                    insight_text += f"⚠️ CONFLICT: {content}\n"
                elif insight_type == 'connection':
                    insight_text += f"🔗 CONNECTION: {content}\n"
                else:
                    insight_text += f"💡 SUGGESTION: {content}\n"
            
            return insight_text
            
        except ImportError:
            return ""
        except Exception as e:
            logger.debug(f"[{self.name}] Insight retrieval failed: {e}")
            return ""


