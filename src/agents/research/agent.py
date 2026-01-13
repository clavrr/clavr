"""
Research Agent

Specialized agent for deep research queries using Google's Deep Research agent.
Handles complex research tasks that require synthesizing information from multiple sources.

Features:
- Background execution for long-running research
- Polling with timeout handling
- Fallback to standard LLM if Deep Research unavailable
- Formatted research reports
"""
from typing import Dict, Any, Optional, List
import asyncio
from datetime import datetime
from langchain_core.tools import BaseTool

from ..base import BaseAgent
from ..constants import (
    INTENT_KEYWORDS,
    RESEARCH_DEFAULT_TIMEOUT,
    RESEARCH_POLL_INTERVAL,
    ERROR_RESEARCH_TIMEOUT,
    ERROR_RESEARCH_UNAVAILABLE
)
from .constants import (
    FALLBACK_SYSTEM_PROMPT,
    RESEARCH_ROUTING_PATTERNS,
    FINANCE_EXCLUSION_KEYWORDS
)
from src.utils.logger import setup_logger
from src.ai.interactions_client import InteractionsClient
from src.ai.rag.query.query_decomposer import DecomposedRAGExecutor
from src.utils.performance import LatencyMonitor

logger = setup_logger(__name__)


class ResearchAgent(BaseAgent):
    """
    Specialized agent for complex research queries.
    
    Uses Google's Deep Research agent (deep-research-pro-preview-12-2025)
    for synthesizing comprehensive research reports.
    
    Best for queries like:
    - "Research all discussions about Q4 budget"
    - "Summarize all emails from the marketing team this month"
    - "Analyze patterns in my Chase banking notifications"
    """
    
    # Maximum time to wait for research completion (uses centralized constant)
    DEFAULT_TIMEOUT = RESEARCH_DEFAULT_TIMEOUT
    
    
    def __init__(
        self, 
        config: Dict[str, Any], 
        tools: List[BaseTool], 
        domain_context: Optional[Any] = None,
        event_emitter: Optional[Any] = None
    ):
        super().__init__(config, tools, domain_context, event_emitter)
        self.interactions_client = InteractionsClient()
        self.name = "ResearchAgent"
        self._research_sessions = {}
    
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute a research query.
        
        Args:
            query: The research query from the user
            context: Optional context from previous steps
            
        Returns:
            Formatted research report or findings
        """
        logger.info(f"[{self.name}] Processing research query: {query[:100]}...")
        
        # Check if Interactions API is available for Deep Research
        if self.interactions_client.is_available:
            return await self._execute_deep_research(query, context)
        else:
            logger.warning(f"[{self.name}] Deep Research unavailable, using standard LLM")
            return await self._execute_fallback_research(query, context)
    
    async def _execute_deep_research(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Execute research using Google's Deep Research agent.
        
        This runs in the background and may take several minutes.
        """
        # Build research prompt with context if available
        # Enhance context with graph search AND internal tool search
        graph_context = ""
        internal_tool_context = ""
        user_id = context.get('user_id') if context else None
        
        if user_id:
             # NEW: Use unified MemoryOrchestrator for high-fidelity multi-layer context
             # This automatically handles Graph, Semantic Facts, and Working Memory
             if self.memory_orchestrator:
                 with LatencyMonitor(f"[{self.name}] Memory Context Retrieval"):
                     mem_context = await self.memory_orchestrator.get_context_for_agent(
                         user_id=int(user_id),
                         agent_name=self.name,
                         query=query,
                         session_id=self._current_session_id,
                         task_type="research"
                     )
                     graph_context = mem_context.to_prompt_string()

             # NEW: Use DecomposedRAGExecutor for deep, split-query searching
             # This ensures we don't just search the query literally, but break it down.
             try:
                 executor = DecomposedRAGExecutor(self.domain_context.vector_store if self.domain_context else None)
                 with LatencyMonitor(f"[{self.name}] Decomposed RAG Search"):
                     rag_results = await executor.execute(query, k=5)
                     internal_tool_context = self._format_rag_search_results(rag_results)
             except Exception as e:
                 logger.debug(f"[{self.name}] Decomposed RAG Search failed: {e}")
            
        # Merge contexts
        enhanced_context = context.copy() if context else {}
        context_additions = []
        
        if graph_context:
            context_additions.append(f"Internal Knowledge & Memory:\n{graph_context}")
        
        if internal_tool_context:
            context_additions.append(f"Internal Application Data (RAG):\n{internal_tool_context}")
            
        if context_additions:
            current_prev = enhanced_context.get('previous_results', '')
            additions_str = "\n\n".join(context_additions)
            enhanced_context['previous_results'] = f"{current_prev}\n\n{additions_str}"
            
        research_prompt = self._build_research_prompt(query, enhanced_context)
        
        logger.info(f"[{self.name}] Starting Deep Research...")
        
        # Define progress callback
        async def on_progress(result: Any, elapsed: int):
            if not self.event_emitter:
                return
            
            try:
                status = getattr(result, 'status', 'running')
                message = f"Researching... ({elapsed}s elapsed)"
                
                # Use standard emit_tool_progress if available (preferred)
                if hasattr(self.event_emitter, 'emit_tool_progress'):
                    await self.event_emitter.emit_tool_progress(
                        message, 
                        data={'elapsed': elapsed, 'status': status, 'agent': 'ResearchAgent'}
                    )
                # Fallback to generic emit
                elif hasattr(self.event_emitter, 'emit'):
                    from src.events import WorkflowEvent, WorkflowEventType
                    # Map to generic type if available
                    event_type = getattr(WorkflowEventType, 'TOOL_CALL_PROGRESS', None)
                    
                    if event_type:
                        await self.event_emitter.emit(WorkflowEvent(
                            type=event_type,
                            message=message,
                            data={'elapsed': elapsed, 'status': status, 'agent': 'ResearchAgent'}
                        ))
            except Exception as e:
                logger.debug(f"[{self.name}] Failed to emit progress: {e}")

        # Use previous interaction ID if available for session continuity
        previous_id = self._research_sessions.get(int(user_id)) if user_id else None

        result = await self.interactions_client.create_research_interaction(
            input=research_prompt,
            timeout_seconds=self.DEFAULT_TIMEOUT,
            poll_interval=RESEARCH_POLL_INTERVAL,
            on_progress=on_progress,
            previous_interaction_id=previous_id
        )
        
        if result.status == "completed":
            if user_id:
                self._research_sessions[int(user_id)] = result.id
            return self._format_research_result(result.text, query)
        elif result.status == "timeout":
            return ERROR_RESEARCH_TIMEOUT
        else:
            logger.error(f"[{self.name}] Research failed: {result.error}")
            # Fallback to standard LLM
            return await self._execute_fallback_research(query, context)
    
    async def _execute_fallback_research(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Fallback research using standard LLM when Deep Research is unavailable.
        """
        if not self.llm:
            return ERROR_RESEARCH_UNAVAILABLE
        
        from langchain_core.messages import SystemMessage, HumanMessage
        import asyncio
        
        system_prompt = FALLBACK_SYSTEM_PROMPT
        
        research_prompt = self._build_research_prompt(query, context)
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=research_prompt)
        ]
        
        try:
            response = await asyncio.to_thread(self.llm.invoke, messages)
            content = response.content if hasattr(response, 'content') else str(response)
            return self._format_research_result(content, query)
        except Exception as e:
            logger.error(f"[{self.name}] Fallback research failed: {e}")
            return f"I encountered an error while researching: {e}"
    
    def _build_research_prompt(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build the research prompt with optional context from previous steps.
        """
        prompt_parts = [query]
        
        # Inject current date context to ensure temporal awareness in research
        now = datetime.now()
        current_date_context = f"Today is {now.strftime('%A, %B %d, %Y')}. The current time is {now.strftime('%I:%M %p')}."
        prompt_parts.insert(0, f"[CONTEXT]\n{current_date_context}\n")
        
        if context:
            # Add context from previous steps if available
            if 'previous_results' in context:
                prompt_parts.append(
                    f"\n\nContext from previous analysis:\n{context['previous_results']}"
                )
            
            if 'email_data' in context:
                prompt_parts.append(
                    f"\n\nRelevant email data:\n{context['email_data']}"
                )
            
            if 'time_range' in context:
                prompt_parts.append(
                    f"\n\nTime range: {context['time_range']}"
                )
        
        return "\n".join(prompt_parts)
    
    def _format_research_result(self, result: str, query: str) -> str:
        """
        Format the research result for user presentation.
        
        Adds header and ensures consistent formatting.
        """
        if not result or not result.strip():
            return "The research did not return any findings. Please try refining your query."
        
        # Check if result already has good formatting
        if result.startswith('#') or result.startswith('## '):
            # Already formatted with markdown headers
            return result
        
        # Add a simple header if none exists
        # FIX: Only add ellipsis if query is actually truncated
        query_display = f'{query[:100]}...' if len(query) > 100 else query
        formatted = f"""## Research Findings

{result}

---
*Research completed for: "{query_display}"*
"""
        return formatted
    
    def _format_rag_search_results(self, results: Dict[str, Any]) -> str:
        """Format decomposed RAG results for the research agent."""
        if not results or not results.get('results'):
            return ""
            
        formatted = []
        # If it was a decomposed query, show the plan
        decomp = results.get('decomposition')
        if decomp and len(decomp.sub_queries) > 1:
            formatted.append(f"### Research Plan Executed\n- {decomp.reasoning}")
            
        # Group results by source/type
        items = results.get('results', [])
        for item in items:
            source = item.get('metadata', {}).get('source', 'General')
            doc_type = item.get('metadata', {}).get('doc_type', 'Document')
            content = item.get('content', '')[:300]
            if len(item.get('content', '')) > 300:
                content += "..."
            formatted.append(f"#### [{doc_type}] Source: {source}\n{content}")
            
        return "\n\n".join(formatted)

    @classmethod
    def is_research_query(cls, query: str) -> bool:
        """
        Determine if a query should be handled by the ResearchAgent.
        
        Useful for routing decisions in the SupervisorAgent.
        
        Args:
            query: User query to analyze
            
        Returns:
            True if this appears to be a research query
        """
        query_lower = query.lower()
        
        # Check for research keywords from centralized constants
        research_keywords = INTENT_KEYWORDS.get('research', {}).get('deep', [])
        for keyword in research_keywords:
            if keyword in query_lower:
                return True
        
        # Check for patterns like "all emails about X" or "summary of Y"
        # Narrowing patterns to avoid catching simple finance lookups
        patterns = RESEARCH_ROUTING_PATTERNS
        
        for pattern in patterns:
            if pattern in query_lower:
                # Extra check: if it mentions finance/money/how much, default to FinanceAgent
                if any(fw in query_lower for fw in FINANCE_EXCLUSION_KEYWORDS):
                    return False
                return True
        
        return False
