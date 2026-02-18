"""
Supervisor Agent (Router)

This is the main entry point for the new Multi-Agent architecture.
It uses a lightweight LLM (Gemini Flash) to route user queries to the appropriate
specialized agent.

Features:
- Stateful routing via Interactions API (previous_interaction_id)
- Multi-step query decomposition and execution
- Research agent for deep analysis queries
- Automatic fallback to standard LLM if Interactions API unavailable
"""
from typing import Dict, Any, Optional, List, TYPE_CHECKING
import json
import re
import asyncio

if TYPE_CHECKING:
    from src.events import WorkflowEventEmitter

from langchain_core.tools import BaseTool
from langchain_core.messages import SystemMessage, HumanMessage

from .base import BaseAgent
from .email.agent import EmailAgent
from .tasks.agent import TaskAgent
from .calendar.agent import CalendarAgent
from .notion.agent import NotionAgent
from .research.agent import ResearchAgent
from .keep.agent import KeepAgent
from .weather.agent import WeatherAgent
from .maps.agent import MapsAgent
from .timezone.agent import TimezoneAgent
from .drive.agent import DriveAgent
from .finance.agent import FinanceAgent

from ..utils.logger import setup_logger
from ..ai.llm_factory import LLMFactory
from ..ai.interactions_client import InteractionsClient
from ..utils.performance import LatencyMonitor

logger = setup_logger(__name__)

from ..ai.prompts.supervisor_prompts import (
    SUPERVISOR_PLANNING_SYSTEM_PROMPT,
    SUPERVISOR_ROUTING_SYSTEM_PROMPT,
    SUPERVISOR_GENERAL_SYSTEM_PROMPT
)

from .constants import (
    DEFAULT_FAST_MODEL,
    SUPERVISOR_LLM_MAX_TOKENS,
    SUPERVISOR_LLM_TEMPERATURE,
    ERROR_GENERAL_UNAVAILABLE,
    ERROR_GENERAL_FAILURE,
    DOMAIN_ALIASES,
    DOMAIN_DISPLAY_NAMES,
    PROVIDER_MAPPINGS,
    DOMAIN_START_MESSAGES
)

from ..ai.prompts.conversational_prompts import get_conversational_enhancement_prompt
from datetime import datetime

# Capabilities
try:
    from ..ai.capabilities import NLPProcessor, PatternRecognition
except ImportError:
    NLPProcessor = None
    PatternRecognition = None
    
# Optional Services
try:
    from src.services.insights.insight_service import get_insight_service
except ImportError:
    get_insight_service = None # type: ignore


class SupervisorAgent:
    """
    Supervisor Agent that routes queries to specialized domain agents.
    
    Features:
    - Stateful routing using Interactions API (previous_interaction_id)
    - Session tracking per user for context continuity
    - Research agent for deep analysis queries
    - Automatic fallback to LLMFactory if Interactions API unavailable
    - Perfect Memory integration via MemoryOrchestrator
    """
    
    def __init__(self, 
                 config: Dict[str, Any], 
                 tools: List[BaseTool], 
                 memory: Optional[Any] = None,
                 db: Optional[Any] = None,
                 event_emitter: Optional['WorkflowEventEmitter'] = None,
                 memory_orchestrator: Optional[Any] = None,
                 user_id: int = None):  # REQUIRED
        
        if user_id is None:
            raise ValueError("user_id is required for SupervisorAgent - cannot default for multi-tenancy")
        
        self.config = config
        self.memory = memory
        self.db = db
        self.event_emitter = event_emitter
        self.user_id = user_id
        
        # Initialize DomainMemoryFactory
        from src.memory.factory import DomainMemoryFactory
        self.memory_factory = DomainMemoryFactory(config)
        
        # Perfect Memory: Initialize or get orchestrator
        self.memory_orchestrator = memory_orchestrator
        if self.memory_orchestrator is None:
            try:
                from src.memory import get_memory_orchestrator
                self.memory_orchestrator = get_memory_orchestrator()
            except ImportError:
                logger.debug("MemoryOrchestrator not available, falling back to basic memory.")
        
        # Initialize Domain Agents with specialized DomainContext
        # We retrieve a specific context for each agent based on its domain config
        self.agents: Dict[str, BaseAgent] = {}
        
        # Helper to safely create agents with DomainContext
        # Note: We pass None for memory/memory_orchestrator legacy args as they are replaced by domain_context
        # But we must update the specific Agent classes to accept domain_context first.
        # Assuming we will update them next, we pass it now.
        
        agent_map = {
            "email": EmailAgent,
            "tasks": TaskAgent,
            "calendar": CalendarAgent,
            "notion": NotionAgent,
            "research": ResearchAgent,
            "notes": KeepAgent,
            "weather": WeatherAgent,
            "maps": MapsAgent,
            "timezone": TimezoneAgent,
            "drive": DriveAgent,
            "finance": FinanceAgent
        }
        
        for name, cls in agent_map.items():
            # Create specialized context for this agent
            domain_context = self.memory_factory.get_domain_context(agent_name=name, user_id=user_id)
            
            # Initialize agent with domain context
            # All agents now follow the updated __init__ signature: (config, tools, domain_context, event_emitter)
            self.agents[name] = cls(
                config=config, 
                tools=tools, 
                domain_context=domain_context, 
                event_emitter=self.event_emitter
            )

        
        # Initialize Router LLM (fallback)
        with LatencyMonitor("LLM Init"):
            self.llm = self._init_llm(config)
        
        # Initialize Interactions API client for stateful routing
        self.interactions_client = InteractionsClient()
        
        # Track interaction sessions per user for stateful conversations
        # In-memory cache for performance, with DB persistence for restarts
        self._interaction_sessions: Dict[int, str] = {}
        
        if self.interactions_client.is_available:
            logger.info("[OK] SupervisorAgent initialized with Interactions API (stateful routing enabled)")
        else:
            logger.info("[INFO] SupervisorAgent initialized with LLM fallback (Interactions API unavailable)")
        
        if self.memory_orchestrator:
            logger.info("[OK] SupervisorAgent initialized with MemoryOrchestrator (Perfect Memory enabled)")

        # Initialize Capabilities
        self.nlp = NLPProcessor() if NLPProcessor else None
        self.patterns = PatternRecognition() if PatternRecognition else None

    async def _get_active_providers(self, user_id: int) -> set:
        """Fetch set of active providers for the user (only enabled integrations)"""
        if not self.db or not user_id:
            logger.debug(f"_get_active_providers: No db ({self.db}) or user_id ({user_id})")
            return set()
        
        from sqlalchemy import select
        from src.database.models import UserIntegration
        
        # Proactively rollback any aborted transaction state
        # This prevents "current transaction is aborted" errors
        try:
            await self.db.rollback()
        except Exception:
            pass  # Ignore if no transaction to rollback
        
        # Only get integrations that are enabled (is_active=True)
        stmt = select(UserIntegration.provider).where(
            UserIntegration.user_id == user_id,
            UserIntegration.is_active == True
        )
        
        try:
            result = await self.db.execute(stmt)
            providers = set(result.scalars().all())
            logger.info(f"_get_active_providers: user_id={user_id}, found providers={providers}")
            return providers
        except Exception as e:
            logger.debug(f"Failed to fetch active providers (non-critical): {e}")
            return set()

    def _get_service_display_name(self, domain: str) -> str:
        """Get user-friendly display name for a service domain"""
        from .constants import DOMAIN_DISPLAY_NAMES
        return DOMAIN_DISPLAY_NAMES.get(domain.lower(), domain.capitalize())

    def _resolve_provider(self, domain: str) -> Optional[str]:
        """Map agent domain to required provider"""
        from .constants import PROVIDER_MAPPINGS
        return PROVIDER_MAPPINGS.get(domain.lower())

    def _init_llm(self, config: Dict[str, Any]):
        """Initialize a fast LLM for routing (fallback)"""
        try:
            return LLMFactory.get_llm_for_provider(
                config,
                temperature=SUPERVISOR_LLM_TEMPERATURE,
                max_tokens=SUPERVISOR_LLM_MAX_TOKENS
            )
        except Exception as e:
            logger.error(f"Failed to initialize Supervisor LLM: {e}")
            return None

    async def _get_integration_status(self, user_id: int) -> str:
        """Fetch integration status for context-aware routing"""
        active_providers = await self._get_active_providers(user_id)
        
        from .constants import DOMAIN_DISPLAY_NAMES, PROVIDER_MAPPINGS
        
        connected_services = []
        disconnected_services = []
        processed_providers = set()
        
        # Dynamically check all mapped providers
        for domain, display_name in DOMAIN_DISPLAY_NAMES.items():
            provider_key = PROVIDER_MAPPINGS.get(domain)
            if not provider_key or provider_key in processed_providers:
                continue
                
            processed_providers.add(provider_key)
            if provider_key in active_providers:
                connected_services.append(display_name)
            else:
                disconnected_services.append(display_name)
        
        # Ensure lists are sorted for consistent output
        connected_services.sort()
        disconnected_services.sort()
        
        return f"""
[INTEGRATION STATUS]
CONNECTED SERVICES: {', '.join(connected_services) if connected_services else "None"}
DISCONNECTED SERVICES: {', '.join(disconnected_services) if disconnected_services else "None"}

CRITICAL ROUTING RULES:
1. You CANNOT use tools/agents for DISCONNECTED services.
2. If user asks for a DISCONNECTED service, do NOT route to that domain.
3. Instead, route to 'general' and explain: "You need to enable [Service] integration in Settings to do that."
4. KEEP REFUSALS CONCISE. Do NOT apologize profusely. Do NOT mention other disconnected services.
"""

    async def _get_session_interaction_id(self, user_id: Optional[int]) -> Optional[str]:
        """
        Get the last interaction ID for a user's session.
        
        Checks in-memory cache first, then falls back to database.
        """
        if user_id is None:
            return None
        
        # Check in-memory cache first (fast path)
        if user_id in self._interaction_sessions:
            return self._interaction_sessions[user_id]
        
        # Fallback to database for cold starts / restarts
        if self.db:
            try:
                from sqlalchemy import select
                from src.database.models import InteractionSession
                
                stmt = select(InteractionSession).where(InteractionSession.user_id == user_id)
                result = await self.db.execute(stmt)
                session_record = result.scalar_one_or_none()
                
                if session_record:
                    # Cache it in memory for subsequent requests
                    self._interaction_sessions[user_id] = session_record.interaction_id
                    return session_record.interaction_id
            except Exception as e:
                logger.debug(f"Could not fetch interaction session from DB: {e}")
        
        return None
    
    async def _update_session_interaction_id(self, user_id: Optional[int], interaction_id: str):
        """
        Update the last interaction ID for a user's session.
        
        Updates both in-memory cache and database for persistence.
        """
        if user_id is None or not interaction_id or interaction_id == "fallback":
            return
        
        # Always update in-memory cache
        self._interaction_sessions[user_id] = interaction_id
        
        # Persist to database
        if self.db:
            try:
                from sqlalchemy import select
                from sqlalchemy.dialects.postgresql import insert
                from src.database.models import InteractionSession
                from datetime import datetime
                
                # Upsert: insert or update if exists
                stmt = insert(InteractionSession).values(
                    user_id=user_id,
                    interaction_id=interaction_id,
                    updated_at=datetime.utcnow()
                ).on_conflict_do_update(
                    index_elements=['user_id'],
                    set_={
                        'interaction_id': interaction_id,
                        'updated_at': datetime.utcnow()
                    }
                )
                await self.db.execute(stmt)
                await self.db.commit()
                logger.debug(f"Updated session for user {user_id}: {interaction_id[:8]}... (persisted)")
            except Exception as e:
                logger.debug(f"Could not persist interaction session to DB: {e}")
                # Still log the in-memory update
                logger.debug(f"Updated session for user {user_id}: {interaction_id[:8]}... (memory only)")

    async def _plan_execution(self, query: str, user_id: Optional[int] = None, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Decompose a complex query into a list of execution steps.
        Each step has a 'domain', 'action', and 'query' (context-aware).
        
        Uses Interactions API with previous_interaction_id for stateful planning.
        Also includes recent conversation context AND extracted entities for pronoun resolution.
        """
        # Build conversation context and others via ContextService
        from src.services.context_service import get_context_service
        
        with LatencyMonitor("Context Retrieval"):
            logger.info(f"[SupervisorAgent] Starting context retrieval for query: {query[:50]}...")
            context_data = await get_context_service().get_unified_context(
                user_id=user_id,
                query=query,
                session_id=session_id,
                memory_client=self.memory
            )
            logger.info(f"[SupervisorAgent] Context retrieval complete.")
        
        conversation_context = context_data.get("conversation_context", "")
        entity_context = context_data.get("entity_context", "")
        semantic_context = context_data.get("semantic_context", "")
        graph_context = context_data.get("graph_context", "")
        
        # Try Interactions API first for stateful planning
        if self.interactions_client.is_available:
            try:
                previous_id = await self._get_session_interaction_id(user_id)
                
                # Prepare System Prompt with Dynamic Examples
                from src.ai.prompts.planning_examples import get_planning_examples_str
                examples_str = get_planning_examples_str(count=2)
                
                # Fetch integration status
                integration_status = await self._get_integration_status(user_id)
                
                # Format the system prompt with examples and current query
                formatted_system_prompt = SUPERVISOR_PLANNING_SYSTEM_PROMPT.format(
                    examples=examples_str,
                    query=query
                )
                
                # Combine into final input for Interactions API
                planning_input = f"{integration_status}\n[PLANNING]\n\nSystem Instructions:\n{formatted_system_prompt}{conversation_context}{entity_context}{semantic_context}{graph_context}"
                
                logger.info("[SupervisorAgent] Calling Interactions API for planning...")
                result = await self.interactions_client.create_interaction(
                    input=planning_input,
                    model=DEFAULT_FAST_MODEL,
                    previous_interaction_id=previous_id,
                    generation_config={"temperature": 0.0}
                )
                logger.info(f"[SupervisorAgent] Interactions API call complete result_id={result.id[:8]}")
                
                # Update session with new interaction ID
                await self._update_session_interaction_id(user_id, result.id)
                
                content = result.text
                
                # Extract JSON list
                match = re.search(r'\[.*\]', content, re.DOTALL)
                if match:
                    logger.info(f"[SupervisorAgent] Planning JSON extraction successful.")
                    return json.loads(match.group(0))
                    
            except Exception as e:
                logger.warning(f"Interactions API planning failed, falling back to LLM: {e}")
        
        # Fallback to standard LLM
        if not self.llm:
            return []
            
        try:
            # Prepare System Prompt with Dynamic Examples (Fallback path)
            from src.ai.prompts.planning_examples import get_planning_examples_str
            examples_str = get_planning_examples_str(count=2)
            
            # Fetch integration status
            integration_status = await self._get_integration_status(user_id)
            
            # Format system prompt
            formatted_prompt = SUPERVISOR_PLANNING_SYSTEM_PROMPT.format(
                examples=examples_str,
                query=query
            )
            
            # Combine context
            planning_prompt = integration_status + "\n" + formatted_prompt + conversation_context + entity_context + semantic_context + graph_context
            
            messages = [
                SystemMessage(content=planning_prompt),
                HumanMessage(content=query)
            ]
            response = await asyncio.to_thread(self.llm.invoke, messages)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Extract JSON list
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return []
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            return []

    async def _emit_event(self, event_type: str, message: str, **kwargs):
        """Helper to emit workflow events if emitter is available"""
        if self.event_emitter:
            try:
                emit_method = getattr(self.event_emitter, f'emit_{event_type}', None)
                if emit_method:
                    await emit_method(message, **kwargs)
                else:
                    # Fallback to generic emit
                    from src.events import WorkflowEvent, WorkflowEventType
                    # Map generic string to Enum if possible, else default to REASONING
                    try:
                        event_type_enum = getattr(WorkflowEventType, event_type.upper())
                    except AttributeError:
                        event_type_enum = WorkflowEventType.REASONING_STEP
                        
                    await self.event_emitter.emit(WorkflowEvent(
                        type=event_type_enum,
                        message=message,
                        data=kwargs.get('data'),
                        metadata=kwargs.get('metadata')
                    ))
            except Exception as e:
                logger.debug(f"Failed to emit workflow event: {e}")

    async def _check_security(self, query: str, user_id: int) -> bool:
        """
        Validate input via COR layer (Security).
        Returns True if safe, False if blocked.
        """
        try:
            from src.security.cor_layer import CORLayer
            cor = CORLayer.get_instance(self.config)
            
            is_safe, reason = await cor.validate_input(query, user_id)
            if not is_safe:
                logger.warning(f"COR Security blocked input: {reason}")
                await self._emit_event('workflow_complete', 'Security Check Failed')
                return False
            return True
        except ImportError:
            return True  # Open if security layer missing
        except Exception as e:
            logger.error(f"COR Security check failed: {e}")
            return True # Fail open to avoid service denial
            
    def _sanitize_response(self, response: str, user_id: int) -> str:
        """Sanitize output via COR layer."""
        if not response:
            return response
            
        try:
            from src.security.cor_layer import CORLayer
            cor = CORLayer.get_instance(self.config)
            return cor.sanitize_output(response, user_id)
        except ImportError:
            return response
        except Exception as e:
            logger.debug(f"Sanitization failed: {e}")
            return response

    async def _is_service_enabled(self, domain: str, active_providers: set) -> bool:
        """Check if a domain's provider is enabled for the user."""
        if domain == 'research' or domain == 'general':
            return True
            
        provider = PROVIDER_MAPPINGS.get(domain)
        # If no mapping, assume enabled (e.g. weather, maps)
        if not provider:
            return True
            
        return provider in active_providers

    async def _inject_urgent_insights(self, response: str, user_id: Optional[int], query: str = None) -> str:
        """Inject urgent AND contextual insights into the response."""
        if not user_id or not get_insight_service:
            return response
            
        try:
            insight_service = get_insight_service()
            if not insight_service:
                return response
                
            # 1. Get urgent insights (existing behavior)
            urgent_insights = await insight_service.get_urgent_insights(user_id)
            
            # 2. Get contextually-relevant insights based on query
            contextual_insights = []
            if query:
                contextual_insights = await insight_service.get_contextual_insights(
                    user_id=user_id,
                    current_context=query,
                    max_insights=2
                )
            
            # Combine and deduplicate (urgent insights take priority)
            urgent_ids = {i.get('id') for i in urgent_insights if i.get('id')}
            all_insights = urgent_insights + [
                i for i in contextual_insights 
                if i.get('id') not in urgent_ids
            ]
            
            if all_insights:
                formatted = await insight_service.format_insights_for_response(all_insights)
                if formatted:
                    return f"{response}\n\n{formatted}"
                    
        except Exception as e:
            logger.debug(f"Failed to inject insights: {e}")
            
        return response


    async def _execute_single_step(
        self, 
        step: Dict[str, Any], 
        step_num: int, 
        context_str: str, 
        user_id: int, 
        user_name: Optional[str], 
        session_id: Optional[str],
        active_providers: set
    ) -> str:
        """Execute a single plan step."""
        domain_raw = step.get("domain", "general").lower()
        step_query = step.get("query", "")
        
        # Inject context if needed
        if "context" in step_query.lower() or "previous" in step_query.lower():
            if context_str:
                step_query = f"{step_query}\n\nContext:\n{context_str}"
        
        # Normalize domain
        domain = DOMAIN_ALIASES.get(domain_raw, domain_raw)
        
        # Check permission
        if not await self._is_service_enabled(domain, active_providers):
            display_name = DOMAIN_DISPLAY_NAMES.get(domain, domain.capitalize())
            return f"[Step {step_num} Blocked]: {display_name} integration is disabled in Settings."
            
        # Emit start event
        start_msg = DOMAIN_START_MESSAGES.get(domain, f"Checking {domain}...")
        await self._emit_event('tool_call_start', start_msg, data={'tool': domain, 'step': step_num})
        
        # Execute
        if domain == "general":
            res = await self._handle_general(step_query, user_id)
        else:
            agent = self.agents.get(domain)
            if not agent:
                return f"[Step {step_num} Error]: Domain '{domain}' not found."
            
            ctx = {
                "user_id": user_id, 
                "user_name": user_name, 
                "session_id": session_id,
                "previous_context": context_str
            }
            
            with LatencyMonitor(f"Agent Execution: {domain}", threshold_ms=30000):
                res = await agent.run(step_query, context=ctx)
        
        # Emit complete event
        await self._emit_event('tool_complete', f'Done with {domain}', data={'tool': domain, 'step': step_num})
        
        return f"\n[Step {step_num} Result]: {res}\n"

    async def _enhance_response_stream(
        self, 
        query: str, 
        response: str, 
        user_name: Optional[str] = None
    ) -> Optional[str]:
        """Enhance response conversationally using LLM with real-time streaming."""
        if not self.llm or not response or len(response) < 30:
            return None
            
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            truncated_res = response[:4000] if len(response) > 4000 else response
            
            prompt = get_conversational_enhancement_prompt(
                query=query, 
                response=truncated_res, 
                current_time=current_time, 
                user_name=user_name
            )
            
            full_content = ""
            full_content = ""
            
            # Use reusable ThreadedStreamer
            from src.utils.streaming import ThreadedStreamer
            
            # Define generation lambda
            def _generate():
                return self.llm.stream(prompt)

            with LatencyMonitor("Response Enhancement", threshold_ms=25000):
                async for chunk in ThreadedStreamer.stream_from_sync(_generate, logger_context="Enhancer"):
                    content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                    if content:
                        full_content += content
                        await self._emit_event('content_chunk', content, data={'chunk': content})

            return full_content if len(full_content) > 10 else None
            
        except Exception as e:
            logger.error(f"Response enhancement complex failure: {e}")
            return None

    async def route_and_execute(self, query: str, user_id: Optional[int] = None, user_name: Optional[str] = None, session_id: Optional[str] = None) -> str:
        """
        Main entry point: Route query and execute agents.
        """
        if user_id is None:
            logger.warning("[SupervisorAgent] route_and_execute called without user_id - authentication may be missing")
            return "I cannot process your request because your session is not authenticated. Please log in again."
        
        # 1. Security Check
        if not await self._check_security(query, user_id):
            return "I cannot process that request due to security restrictions."

        await self._emit_event('reasoning_start', "Understanding your request...")
        
        # 2. Research Bypass (Fast Path)
        if ResearchAgent.is_research_query(query):
            logger.info(f"Supervisor routing -> RESEARCH")
            await self._emit_event('domain_selected', DOMAIN_START_MESSAGES['research'], data={'domain': 'research'})
            res = await self.agents["research"].run(query)
            return self._sanitize_response(res, user_id)
            
        # 3. NLP Analysis
        nlp_context = {}
        if self.nlp:
            nlp_context = self.nlp.process_query(query)
            if nlp_context.get('is_complex'):
                logger.info(f"Complex query detected: {nlp_context['complexity_score']:.2f}")

        # 4. Planning & Decomposition
        await self._emit_event('supervisor_planning_start', "Planning how to help you...")
        
        active_providers = await self._get_active_providers(user_id)
        
        # Prioritize urgent queries
        planning_query = f"[URGENT] {query}" if nlp_context.get('sentiment', {}).get('type') == 'urgent' else query
        
        with LatencyMonitor("Planning Execution", threshold_ms=10000):
            steps = await self._plan_execution(planning_query, user_id, session_id)
            
        # 5. Execution Logic
        if steps:
            final_result = await self._execute_multi_step_plan(
                steps, user_id, user_name, session_id, active_providers
            )
        else:
            final_result = await self._execute_single_routing(
                query, user_id, user_name, session_id, active_providers
            )

        # 6. Response Enhancement & Sanitation
        enhanced = await self._enhance_response_stream(query, final_result, user_name)
        if enhanced:
            final_result = enhanced
        else:
            # Formatting cleanup if not enhanced (remove step markers)
            final_result = re.sub(r'\[Step \d+ Result\]:\s*', '', final_result).strip()
            
        # 7. Inject Urgent and Contextual Insights
        final_result = await self._inject_urgent_insights(final_result, user_id, query=query)
        
        # 8. Perfect Memory Learning
        # 8. Record interaction for learning
        await self._record_interaction(
            user_id=user_id, 
            session_id=session_id, 
            query=query, 
            response=final_result, 
            agent_name="supervisor_multi_step" if steps else "supervisor_single_step"
        )
        
        await self._emit_event('workflow_complete', 'Here is what I found.')
        
        # Track patterns
        if self.patterns and user_id:
            self.patterns.analyze_behavior(
                user_id=user_id,
                action_type="supervisor_completion",
                context={'query': query}
            )
            
        return self._sanitize_response(final_result, user_id)

    async def _decide_route(self, query: str, user_id: Optional[int] = None) -> str:
        """
        Use LLM to decide which agent should handle the query.
        Returns: 'email', 'tasks', 'calendar', 'notion', 'research', or 'general'
        
        Uses Interactions API for stateful routing decisions.
        """
        # Try Interactions API first
        if self.interactions_client.is_available:
            try:
                previous_id = await self._get_session_interaction_id(user_id)
                
                # Fetch integration status
                integration_status = await self._get_integration_status(user_id)
                
                result = await self.interactions_client.create_interaction(
                    input=f"{integration_status}\n[ROUTING]\n\nSystem Instructions:\n{SUPERVISOR_ROUTING_SYSTEM_PROMPT}\n\nUser Query:\n{query}",
                    model=DEFAULT_FAST_MODEL,
                    previous_interaction_id=previous_id,
                    generation_config={"temperature": 0.0}
                )
                
                await self._update_session_interaction_id(user_id, result.id)
                
                content = result.text
                
                # Parse JSON
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    data = json.loads(match.group(0))
                    category = data.get("category", "general").lower()
                    
                    if category in self.agents:
                        return category
                        
            except Exception as e:
                logger.warning(f"Interactions API routing failed, falling back to LLM: {e}")
        
        # Fallback to standard LLM
        if not self.llm:
            return self._keyword_fallback(query)

        try:
            # Fetch integration status for fallback
            integration_status = await self._get_integration_status(user_id)
            
            messages = [
                SystemMessage(content=f"{integration_status}\n{SUPERVISOR_ROUTING_SYSTEM_PROMPT}"),
                HumanMessage(content=query)
            ]
            
            response = await asyncio.to_thread(self.llm.invoke, messages)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                json_str = match.group(0)
                data = json.loads(json_str)
                category = data.get("category", "general").lower()
                
                if category in self.agents:
                    return category
                
            return "general"
            
        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return self._keyword_fallback(query)

    def _keyword_fallback(self, query: str) -> str:
        """Simple keyword fallback for routing using standard constants"""
        from .constants import INTENT_KEYWORDS
        q = query.lower()
        
        # Check Research first (specific)
        if any(w in q for w in INTENT_KEYWORDS['research']['deep']):
            return 'research'
            
        # Check Notes (specific)
        if any(w in q for w in INTENT_KEYWORDS['notes']['quick']):
            return 'notes'
            
        # Check standard domains
        # We flatten the nested dicts for checking broad domain matches
        for domain in ['drive', 'email', 'calendar', 'tasks', 'notion']:
            keywords = []
            for category in INTENT_KEYWORDS.get(domain, {}).values():
                keywords.extend(category)
            
            if any(w in q for w in keywords):
                return domain
        
        return 'general'

    async def _handle_general(self, query: str, user_id: Optional[int] = None) -> str:
        """
        Handle general conversation queries.
        Uses Interactions API for stateful conversations.
        """
        await self._emit_event('reasoning_step', 'Handling general conversation...')
        
        # Get context
        interaction_id = await self._get_session_interaction_id(user_id)
        
        # Fetch integration status for context
        integration_status = await self._get_integration_status(user_id)
        
        # We'll use the LLM fallback for now as it's easier to stream
        if not self.llm:
            return "I'm sorry, my conversational engine is currently unavailable."
            
        messages = [
            SystemMessage(content=f"{integration_status}\n{SUPERVISOR_GENERAL_SYSTEM_PROMPT}"),
            HumanMessage(content=query)
        ]
        
        full_response = ""
        try:
            # Stream the response using robust sync-to-async wrap
            for chunk in self.llm.stream(messages):
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if content:
                    full_response += content
                    # Emit chunk to the event emitter for real-time streaming
                    await self._emit_event('content_chunk', content, data={'chunk': content})
                await asyncio.sleep(0) # Yield control
            
            return full_response
        except Exception as e:
            logger.error(f"General chat streaming failed: {e}")
            return "I'm sorry, I encountered an error while processing your request."

    def clear_session(self, user_id: int):
        """Clear the interaction session for a user (useful for starting fresh conversations)"""
        if user_id in self._interaction_sessions:
            del self._interaction_sessions[user_id]
            logger.info(f"Cleared interaction session for user {user_id}")


    async def _execute_multi_step_plan(
        self, 
        steps: List[Dict[str, Any]], 
        user_id: int, 
        user_name: Optional[str], 
        session_id: Optional[str],
        active_providers: set
    ) -> str:
        """Execute a decomposed multi-step plan."""
        logger.info(f"Supervisor Plan: {len(steps)} steps")
        summary = ", ".join([s.get('domain', 'general').title() for s in steps])
        await self._emit_event('supervisor_plan_created', f"I'll check: {summary}", data={'steps': steps})
        
        # Identify dependencies
        dep_indices = [i for i, s in enumerate(steps) if any(x in s.get("query", "").lower() for x in ["previous", "step ", "result"])]
        ind_indices = [i for i in range(len(steps)) if i not in dep_indices]
        
        results_accumulated = ""
        
        # Run independent steps in parallel
        if ind_indices:
            with LatencyMonitor("Parallel Steps", threshold_ms=30000):
                tasks = [
                    self._execute_single_step(
                        steps[i], i+1, "", user_id, user_name, session_id, active_providers
                    ) for i in ind_indices
                ]
                results = await asyncio.gather(*tasks)
                results_accumulated += "".join(results)
        
        # Run dependent steps sequentially
        for i in dep_indices:
            res = await self._execute_single_step(
                steps[i], i+1, results_accumulated, user_id, user_name, session_id, active_providers
            )
            results_accumulated += res
            
        return results_accumulated

    async def _execute_single_routing(
        self, 
        query: str, 
        user_id: int, 
        user_name: Optional[str], 
        session_id: Optional[str],
        active_providers: set
    ) -> str:
        """Fallback to single-step routing if no decomposition is possible."""
        with LatencyMonitor("Route Decision"):
            target_agent = await self._decide_route(query, user_id)
        
        target_agent = DOMAIN_ALIASES.get(target_agent, target_agent)
        
        # Check permission
        if not await self._is_service_enabled(target_agent, active_providers):
            display = DOMAIN_DISPLAY_NAMES.get(target_agent, target_agent.capitalize())
            return f"Please enable {display} integration in Settings to use this feature."
        
        # Execute
        if target_agent == "general" or target_agent not in self.agents:
            if target_agent != "general":
                logger.warning(f"Routed to unknown agent '{target_agent}', falling back to general.")
            return await self._handle_general(query, user_id)
        else:
            agent = self.agents[target_agent]
            start_msg = DOMAIN_START_MESSAGES.get(target_agent, f"Checking {target_agent}...")
            await self._emit_event('tool_call_start', start_msg, data={'tool': target_agent})
            
            ctx = {"user_id": user_id, "user_name": user_name, "session_id": session_id}
            with LatencyMonitor(f"Agent Execution: {target_agent}"):
                final_result = await agent.run(query, context=ctx)
            
            await self._emit_event('tool_complete', f"Done with {target_agent}", data={'tool': target_agent})
            return final_result

    async def _record_interaction(
        self, 
        user_id: Optional[int], 
        session_id: Optional[str], 
        query: str, 
        response: str,
        success: bool = True,
        agent_name: Optional[str] = None
    ):
        """
        Record the interaction for persistent learning and session context.
        Uses the Unified Memory System (MemoryOrchestrator).
        """
        if not self.memory_orchestrator or not user_id or not session_id:
            return
            
        try:
            with LatencyMonitor("[SupervisorAgent] Recording Memory"):
                await self.memory_orchestrator.learn_from_turn(
                    user_id=user_id,
                    session_id=session_id,
                    user_message=query,
                    assistant_response=response,
                    agent_name=agent_name or "SupervisorAgent",
                    success=success
                )
        except Exception as e:
            logger.debug(f"[SupervisorAgent] Interaction recording failed: {e}")
