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

from .state import StepResult
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

# Intent Classification (SkillRegistry + FastClassifier)
try:
    from src.ai.intent.skill_registry import get_skill_registry
    from src.ai.intent.fast_classifier import get_fast_classifier
    from src.ai.intent.user_skill_prefs import get_skill_tracker
except ImportError:
    get_skill_registry = None  # type: ignore
    get_fast_classifier = None  # type: ignore
    get_skill_tracker = None  # type: ignore

# Entity Extraction (pre-routing resolution)
try:
    from src.services.entity_extractor import get_entity_extractor, init_entity_extractor
except ImportError:
    get_entity_extractor = None  # type: ignore
    init_entity_extractor = None  # type: ignore


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

        # Initialize SkillRegistry + FastClassifier + UserSkillTracker
        self.skill_registry = get_skill_registry() if get_skill_registry else None
        self.fast_classifier = get_fast_classifier() if get_fast_classifier else None
        self.skill_tracker = get_skill_tracker() if get_skill_tracker else None
        if self.skill_registry:
            logger.info(f"[OK] SkillRegistry initialized with {self.skill_registry.skill_count} skills")

        # Initialize EntityExtractor
        self.entity_extractor = get_entity_extractor() if get_entity_extractor else None
        if not self.entity_extractor and init_entity_extractor:
            try:
                self.entity_extractor = init_entity_extractor(config)
            except Exception:
                self.entity_extractor = None

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

        # Task workflows can run through either Google Tasks or Asana.
        tasks_connected = "google_tasks" in active_providers or "asana" in active_providers
        
        connected_services = []
        disconnected_services = []
        processed_providers = set()
        
        # Dynamically check all mapped providers
        for domain, display_name in DOMAIN_DISPLAY_NAMES.items():
            if domain == "tasks":
                if tasks_connected:
                    connected_services.append(display_name)
                else:
                    disconnected_services.append(display_name)
                continue

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

    async def _fetch_person_dossiers(self, query: str, user_id: Optional[int]) -> str:
        """Fetch person dossiers for names mentioned in the query. Returns formatted context string."""
        try:
            from src.services.person_intelligence import get_person_intelligence
            person_intel = get_person_intelligence()
            if not person_intel or not user_id:
                return ""
            
            import re as _re
            name_pattern = r'\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)?)\b'
            skip_words = {
                'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday',
                'January','February','March','April','May','June','July','August',
                'September','October','November','December','Today','Tomorrow',
                'What','When','Where','Who','How','Why','Which','Tell','Show',
                'Find','Get','Send','Schedule','Create','Update','Delete','Can',
                'Could','Would','Should','The','This','That','About','With',
                'Please','Thanks','Hello','Email','Meeting','Draft','Slack',
                'Gmail','Google','Calendar','Drive','Notion','Linear','Asana',
            }
            names = [
                n for n in _re.findall(name_pattern, query)
                if n not in skip_words and n.split()[0] not in skip_words
            ]
            if not names:
                return ""
            
            dossier_tasks = [
                person_intel.get_dossier(name, user_id=user_id)
                for name in names[:2]
            ]
            try:
                dossiers = await asyncio.wait_for(
                    asyncio.gather(*dossier_tasks, return_exceptions=True),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.info("[SupervisorAgent] Person dossier lookup timed out (2s), skipping")
                return ""
            
            dossier_texts = []
            for d in dossiers:
                if isinstance(d, Exception) or not d or not d.name:
                    continue
                dossier_texts.append(d.format_for_prompt(max_length=800))
            if dossier_texts:
                return "\n\n[PERSON INTELLIGENCE]\n" + "\n---\n".join(dossier_texts) + "\n"
        except Exception as e:
            logger.debug(f"[SupervisorAgent] Person intelligence injection failed: {e}")
        return ""

    async def _plan_execution(self, query: str, user_id: Optional[int] = None, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Decompose a complex query into a list of execution steps.
        Each step has a 'domain', 'action', and 'query' (context-aware).
        
        Uses Interactions API with previous_interaction_id for stateful planning.
        Also includes recent conversation context AND extracted entities for pronoun resolution.
        
        Improvement #3: All context sources are gathered in parallel for ~60% latency reduction.
        """
        from src.services.context_service import get_context_service
        
        # Fire ALL context sources simultaneously instead of sequentially
        with LatencyMonitor("Parallel Context Retrieval"):
            logger.info(f"[SupervisorAgent] Starting parallel context retrieval for query: {query[:50]}...")
            
            context_task = get_context_service().get_unified_context(
                user_id=user_id, query=query, session_id=session_id, memory_client=self.memory
            )
            person_task = self._fetch_person_dossiers(query, user_id)
            integration_task = self._get_integration_status(user_id)
            session_task = self._get_session_interaction_id(user_id)
            
            results = await asyncio.gather(
                context_task, person_task, integration_task, session_task,
                return_exceptions=True
            )
            
            # Unpack with graceful fallbacks
            context_data = results[0] if not isinstance(results[0], Exception) else {}
            person_context = results[1] if not isinstance(results[1], Exception) else ""
            integration_status = results[2] if not isinstance(results[2], Exception) else ""
            previous_id = results[3] if not isinstance(results[3], Exception) else None
            
            if isinstance(results[0], Exception):
                logger.warning(f"[SupervisorAgent] Context retrieval failed: {results[0]}")
            if isinstance(results[2], Exception):
                logger.warning(f"[SupervisorAgent] Integration status failed: {results[2]}")
                
            logger.info(f"[SupervisorAgent] Parallel context retrieval complete.")
        
        conversation_context = context_data.get("conversation_context", "") if isinstance(context_data, dict) else ""
        entity_context = context_data.get("entity_context", "") if isinstance(context_data, dict) else ""
        semantic_context = context_data.get("semantic_context", "") if isinstance(context_data, dict) else ""
        graph_context = context_data.get("graph_context", "") if isinstance(context_data, dict) else ""
        
        # Try Interactions API first for stateful planning
        if self.interactions_client.is_available:
            try:
                # Prepare System Prompt with Dynamic Examples
                from src.ai.prompts.planning_examples import get_planning_examples_str
                examples_str = get_planning_examples_str(count=2)
                
                # Format the system prompt with examples and current query
                formatted_system_prompt = SUPERVISOR_PLANNING_SYSTEM_PROMPT.format(
                    examples=examples_str,
                    query=query
                )
                
                # Inject available skills into planner context
                skills_context = ""
                if self.skill_registry:
                    active_providers = await self._get_active_providers(user_id)
                    skills_context = "\n" + self.skill_registry.get_prompt_injection(active_providers) + "\n"
                
                # Combine into final input for Interactions API
                planning_input = f"{integration_status}{skills_context}\n[PLANNING]\n\nSystem Instructions:\n{formatted_system_prompt}{conversation_context}{entity_context}{semantic_context}{graph_context}{person_context}"
                
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
            
            # integration_status already fetched in parallel above
            
            # Format system prompt
            formatted_prompt = SUPERVISOR_PLANNING_SYSTEM_PROMPT.format(
                examples=examples_str,
                query=query
            )
            
            # Inject available skills into planner context
            skills_context = ""
            if self.skill_registry:
                active_providers = await self._get_active_providers(user_id)
                skills_context = "\n" + self.skill_registry.get_prompt_injection(active_providers) + "\n"
            
            # Combine context
            planning_prompt = integration_status + skills_context + "\n" + formatted_prompt + conversation_context + entity_context + semantic_context + graph_context + person_context
            
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

        if domain == 'tasks':
            return 'google_tasks' in active_providers or 'asana' in active_providers
            
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


    async def _inject_advocacy_context(self, response: str, user_id: Optional[int]) -> str:
        """
        Surface background tracking items as natural co-worker advocacy.
        
        Checks FollowUpTracker (overdue email threads) and GoalTracker (overdue goals)
        and appends 1-2 natural nudges to the response.
        """
        if not user_id:
            return response
        
        advocacy_items = []
        
        # 1. Check for overdue follow-ups
        try:
            from src.services.follow_up_tracker import FollowUpTracker
            tracker = FollowUpTracker()
            overdue = tracker.get_overdue(user_id)
            for thread in overdue[:2]:
                sender = thread.sender if hasattr(thread, 'sender') else thread.get('sender', 'someone')
                subject = thread.subject if hasattr(thread, 'subject') else thread.get('subject', '')
                if subject:
                    advocacy_items.append(
                        f"💬 **Heads up** — {sender} hasn't replied to \"{subject}\" yet. Want me to draft a follow-up?"
                    )
        except Exception:
            pass  # FollowUpTracker not available or no overdue items
        
        # 2. Check for overdue goals
        if len(advocacy_items) < 2:
            try:
                from src.memory.goal_tracker import GoalTracker
                goal_tracker = GoalTracker(db=self.db)
                overdue_goals = goal_tracker.get_overdue_goals(user_id)
                for goal in overdue_goals[:1]:
                    desc = goal.description if hasattr(goal, 'description') else str(goal)
                    days = goal.days_until_due() if hasattr(goal, 'days_until_due') else None
                    if days is not None and days < 0:
                        advocacy_items.append(
                            f"📋 **I noticed** your goal \"{desc}\" is {abs(days)} days overdue. Want me to help reprioritize?"
                        )
            except Exception:
                pass  # GoalTracker not available or no overdue goals
        
        # Append advocacy items (max 2 per turn)
        if advocacy_items:
            advocacy_text = "\n".join(advocacy_items[:2])
            return f"{response}\n\n---\n{advocacy_text}"
        
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
    ) -> StepResult:
        """Execute a single plan step. Returns structured StepResult (improvement #5)."""
        import time as _time
        step_start = _time.monotonic()
        
        domain_raw = step.get("domain", "general").lower()
        step_query = step.get("query", "")
        
        # Inject context if needed
        if "context" in step_query.lower() or "previous" in step_query.lower():
            if context_str:
                step_query = f"{step_query}\n\nContext:\n{context_str}"
        
        # Normalize domain
        domain = DOMAIN_ALIASES.get(domain_raw, domain_raw)
        step_id = f"step_{step_num}"
        
        # Check permission
        if not await self._is_service_enabled(domain, active_providers):
            display_name = DOMAIN_DISPLAY_NAMES.get(domain, domain.capitalize())
            return StepResult(
                step_id=step_id, tool=domain, domain=domain, success=False,
                result=f"{display_name} integration is disabled in Settings.",
                execution_time=_time.monotonic() - step_start,
                error="service_disabled",
                timestamp=datetime.utcnow().isoformat()
            )
            
        # Emit start event
        start_msg = DOMAIN_START_MESSAGES.get(domain, f"Checking {domain}...")
        await self._emit_event('tool_call_start', start_msg, data={'tool': domain, 'step': step_num})
        
        # Execute
        error_msg = None
        try:
            if domain == "general":
                res = await self._handle_general(step_query, user_id)
            else:
                agent = self.agents.get(domain)
                if not agent:
                    return StepResult(
                        step_id=step_id, tool=domain, domain=domain, success=False,
                        result=f"Domain '{domain}' not found.",
                        execution_time=_time.monotonic() - step_start,
                        error="domain_not_found",
                        timestamp=datetime.utcnow().isoformat()
                    )
                
                ctx = {
                    "user_id": user_id, 
                    "user_name": user_name, 
                    "session_id": session_id,
                    "previous_context": context_str,
                    "active_providers": sorted(active_providers),
                }
                
                with LatencyMonitor(f"Agent Execution: {domain}", threshold_ms=30000):
                    res = await agent.run(step_query, context=ctx)
        except Exception as e:
            res = f"Error executing {domain}: {e}"
            error_msg = str(e)
        
        elapsed = _time.monotonic() - step_start
        success = error_msg is None and "Error" not in res[:20]
        
        # Emit complete event
        await self._emit_event('tool_complete', f'Done with {domain}', data={
            'tool': domain, 'step': step_num, 'success': success, 'elapsed_ms': round(elapsed * 1000)
        })
        
        return StepResult(
            step_id=step_id, tool=domain, domain=domain, success=success,
            result=res, execution_time=elapsed, error=error_msg,
            timestamp=datetime.utcnow().isoformat()
        )

    async def _enhance_response_stream(
        self, 
        query: str, 
        response: str, 
        user_name: Optional[str] = None
    ) -> Optional[str]:
        """Enhance response conversationally using LLM with real-time streaming.
        
        Falls back to non-streaming invoke() if streaming fails, ensuring
        the user always gets a natural-language response instead of raw tool output.
        """
        if not self.llm or not response or len(response) < 30:
            logger.warning(f"[Enhancement] Skipped: llm={'present' if self.llm else 'None'}, response_len={len(response) if response else 0}")
            return None
        

            
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Reduced from 4000 to 2000 chars — enhancement LLM doesn't need the full response
            # to produce a conversational rewrite. Less input = faster inference.
            truncated_res = response[:2000] if len(response) > 2000 else response
            
            prompt = get_conversational_enhancement_prompt(
                query=query, 
                response=truncated_res, 
                current_time=current_time, 
                user_name=user_name
            )
            
            full_content = ""
            
            # Attempt 1: Streaming path (preferred — enables real-time typing effect)
            try:
                from src.utils.streaming import ThreadedStreamer
                
                def _generate():
                    return self.llm.stream(prompt)

                with LatencyMonitor("Response Enhancement (stream)", threshold_ms=10000):
                    async for chunk in ThreadedStreamer.stream_from_sync(_generate, logger_context="Enhancer"):
                        content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                        if content:
                            full_content += content
                            await self._emit_event('content_chunk', content, data={'chunk': content})

                if len(full_content) > 10:
                    logger.info(f"[Enhancement] Streaming succeeded: {len(full_content)} chars")
                    return full_content
                    
                logger.warning(f"[Enhancement] Streaming produced insufficient content ({len(full_content)} chars), trying fallback")
            except Exception as stream_err:
                logger.warning(f"[Enhancement] Streaming failed: {stream_err}, trying non-streaming fallback")
            
            # Attempt 2: Non-streaming fallback (ensures we still get enhanced output)
            try:
                from langchain_core.messages import HumanMessage
                
                with LatencyMonitor("Response Enhancement (fallback)", threshold_ms=8000):
                    result = self.llm.invoke(prompt)
                
                fallback_content = result.content if hasattr(result, 'content') else str(result)
                
                if fallback_content and len(fallback_content) > 10:
                    logger.info(f"[Enhancement] Fallback succeeded: {len(fallback_content)} chars")
                    # Emit as a single content chunk for the streaming path
                    await self._emit_event('content_chunk', fallback_content, data={'chunk': fallback_content})
                    return fallback_content
                    
                logger.warning(f"[Enhancement] Fallback also produced insufficient content")
                return None
                
            except Exception as fallback_err:
                logger.error(f"[Enhancement] Fallback also failed: {fallback_err}")
                return None
            
        except Exception as e:
            logger.error(f"[Enhancement] Complete failure: {e}")
            return None

    async def route_and_execute(self, query: str, user_id: Optional[int] = None, user_name: Optional[str] = None, session_id: Optional[str] = None) -> str:
        """
        Main entry point: Route query and execute agents.
        Now with structured observability for latency, routing, and error tracking.
        """
        import time as _time
        _start_ts = _time.monotonic()
        _metrics: Dict[str, Any] = {
            "query_length": len(query),
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "route": None,
            "steps": 0,
            "latency_ms": 0,
            "planning_ms": 0,
            "execution_ms": 0,
            "enhancement_ms": 0,
            "error": None,
        }

        if user_id is None:
            logger.warning("[SupervisorAgent] route_and_execute called without user_id - authentication may be missing")
            return "I cannot process your request because your session is not authenticated. Please log in again."
        
        # 1. Security Check
        if not await self._check_security(query, user_id):
            _metrics["error"] = "security_blocked"
            self._record_metrics(_metrics, _start_ts)
            return "I cannot process that request due to security restrictions."

        await self._emit_event('reasoning_start', "Understanding your request...")
        
        # 2. Follow-Up Reference Resolution (before any classification)
        # Detect and rewrite vague references ("the email", "it", "that meeting") 
        # using recent conversation history BEFORE the planner/router sees the query.
        query = await self._resolve_followup_references(query, user_id, session_id)

        # 2.5 Entity Extraction (pre-routing — resolve names before classification)
        extracted_entities = None
        if self.entity_extractor:
            try:
                extracted_entities = await self.entity_extractor.extract(query, user_id)
                if extracted_entities and extracted_entities.has_entities:
                    logger.info(
                        f"[SupervisorAgent] Pre-resolved entities: "
                        f"{extracted_entities.resolved_count} contacts, "
                        f"{len(extracted_entities.unresolved_names)} unresolved"
                    )
                    _metrics["entities_resolved"] = extracted_entities.resolved_count
            except Exception as e:
                logger.debug(f"[SupervisorAgent] Entity extraction failed (non-critical): {e}")

        # 2.7 Research Bypass (Fast Path)
        if ResearchAgent.is_research_query(query):
            logger.info(f"Supervisor routing -> RESEARCH")
            _metrics["route"] = "research"
            await self._emit_event('domain_selected', DOMAIN_START_MESSAGES['research'], data={'domain': 'research'})
            _exec_start = _time.monotonic()
            res = await self.agents["research"].run(query)
            _metrics["execution_ms"] = round((_time.monotonic() - _exec_start) * 1000)
            self._record_metrics(_metrics, _start_ts)
            return self._sanitize_response(res, user_id)
        
        # 3. Fast-Path Classification (sub-5ms, no LLM call)
        active_providers = await self._get_active_providers(user_id)
        
        fast_result = None
        _skip_enhancement = False
        if self.fast_classifier:
            fast_result = self.fast_classifier.classify(query, active_providers, user_id=user_id)
            logger.info(
                f"[SupervisorAgent] FastClassifier: skill={fast_result.skill_name}, "
                f"confidence={fast_result.confidence:.2f}, needs_llm={fast_result.needs_llm}, "
                f"reason={fast_result.reason}"
            )
            _metrics["fast_classifier_confidence"] = fast_result.confidence
            _metrics["fast_classifier_skill"] = fast_result.skill_name
        
        # 3.5. NLP Analysis
        nlp_context = {}
        if self.nlp:
            nlp_context = self.nlp.process_query(query)
            if nlp_context.get('is_complex'):
                logger.info(f"Complex query detected: {nlp_context['complexity_score']:.2f}")

        # 4. Routing Decision: Fast-Path vs LLM Planner
        #    - If FastClassifier resolved with high confidence → skip LLM entirely
        #    - If multi-step or low confidence → use LLM planner
        
        steps = None  # Track whether multi-step was used (for metrics)
        final_result = None  # Will hold the response
        
        if fast_result and not fast_result.needs_llm and fast_result.domain:
            # FAST PATH: Route directly to agent (no LLM call needed)
            domain = fast_result.domain
            _metrics["route"] = f"fast_path:{domain}"
            _metrics["planning_ms"] = 0
            _metrics["steps"] = 1
            
            # Phase 4: Confidence Gating — if ambiguous between domains, ask user
            if fast_result.is_ambiguous and len(fast_result.skill_matches) >= 2:
                m1 = fast_result.skill_matches[0]
                m2 = fast_result.skill_matches[1]
                if m1.skill.domain != m2.skill.domain:
                    # Cross-domain ambiguity — ask for clarification
                    d1_display = self._get_service_display_name(m1.skill.domain)
                    d2_display = self._get_service_display_name(m2.skill.domain)
                    _metrics["route"] = "clarification"
                    _skip_enhancement = True  # Already user-friendly
                    final_result = (
                        f"I want to make sure I help with the right thing. "
                        f"Did you mean:\n"
                        f"1. **{m1.skill.description}** ({d1_display})\n"
                        f"2. **{m2.skill.description}** ({d2_display})\n\n"
                        f"Just let me know which one!"
                    )
                    _metrics["execution_ms"] = 0
                    # Skip to response enhancement
                    agent = None  # signal to skip agent execution
                else:
                    agent = self.agents.get(domain)
            else:
                agent = self.agents.get(domain)
            
            if agent and await self._is_service_enabled(domain, active_providers):
                start_msg = DOMAIN_START_MESSAGES.get(domain, f"Working on {domain}...")
                await self._emit_event('domain_selected', start_msg, data={'domain': domain})
                
                _exec_start = _time.monotonic()
                try:
                    agent_context = {'user_id': user_id, 'user_name': user_name, 'session_id': session_id}
                    # Inject pre-resolved entities into agent context
                    if extracted_entities and extracted_entities.has_entities:
                        agent_context['resolved_entities'] = extracted_entities
                        agent_context['resolved_contacts'] = extracted_entities.get_emails()
                    final_result = await agent.run(query, context=agent_context)
                    
                    # Phase 5: Record successful skill usage for personalization
                    if self.skill_tracker and fast_result.skill_name and user_id:
                        self.skill_tracker.record_usage(user_id, fast_result.skill_name, was_successful=True)
                except Exception as e:
                    logger.error(f"[SupervisorAgent] Fast-path agent {domain} failed: {e}")
                    final_result = f"I encountered an error while processing your request: {str(e)}"
                _metrics["execution_ms"] = round((_time.monotonic() - _exec_start) * 1000)
            elif not await self._is_service_enabled(domain, active_providers):
                display_name = self._get_service_display_name(domain)
                final_result = f"To help with that, you'll need to connect {display_name} in Settings → Integrations."
                _skip_enhancement = True  # Already user-friendly, don't let LLM rewrite
                _metrics["execution_ms"] = 0
            else:
                # Domain exists but no agent — fall through to LLM
                fast_result = None  # Force LLM path below
        
        if fast_result is None or fast_result.needs_llm or not fast_result.domain:
            # Pre-planning check: if fast classifier identified a domain that isn't connected,
            # skip planning entirely and respond immediately
            if fast_result and fast_result.domain:
                domain = DOMAIN_ALIASES.get(fast_result.domain, fast_result.domain)
                if domain != "general" and not await self._is_service_enabled(domain, active_providers):
                    display_name = self._get_service_display_name(domain)
                    final_result = f"To help with that, you'll need to connect {display_name} in Settings → Integrations."
                    _skip_enhancement = True
                    _metrics["route"] = f"service_not_connected:{domain}"
                    _metrics["execution_ms"] = 0

            # Only proceed with LLM planning if we don't already have a result
            if not final_result:
                # LLM PATH: Planning & Decomposition
                await self._emit_event('supervisor_planning_start', "Planning how to help you...")
            
                # Prioritize urgent queries
                planning_query = f"[URGENT] {query}" if nlp_context.get('sentiment', {}).get('type') == 'urgent' else query
                
                _plan_start = _time.monotonic()
                with LatencyMonitor("Planning Execution", threshold_ms=10000):
                    steps = await self._plan_execution(planning_query, user_id, session_id)
                _metrics["planning_ms"] = round((_time.monotonic() - _plan_start) * 1000)
                _metrics["steps"] = len(steps) if steps else 1
                    
                # 5. Execution Logic
                _exec_start = _time.monotonic()
                if steps:
                    _metrics["route"] = "multi_step"
                    final_result = await self._execute_multi_step_plan(
                        steps, user_id, user_name, session_id, active_providers
                    )
                else:
                    _metrics["route"] = "single_step"
                    final_result = await self._execute_single_routing(
                        query, user_id, user_name, session_id, active_providers
                    )
                _metrics["execution_ms"] = round((_time.monotonic() - _exec_start) * 1000)

        # 6. Response Enhancement & Sanitation
        _enhance_start = _time.monotonic()
        if not _skip_enhancement:
            enhanced = await self._enhance_response_stream(query, final_result, user_name)
        else:
            enhanced = None
            logger.info("[SupervisorAgent] Skipping enhancement for system-generated response")
        _metrics["enhancement_ms"] = round((_time.monotonic() - _enhance_start) * 1000)

        if enhanced:
            final_result = enhanced
        elif final_result:
            # Formatting cleanup if not enhanced (remove step markers)
            final_result = re.sub(r'\[Step \d+ Result\]:\s*', '', final_result).strip()
        else:
            final_result = "I'm sorry, I wasn't able to process that request. Please try again."
            
        # 7. Inject Urgent and Contextual Insights (timeout-capped, non-blocking)
        try:
            final_result = await asyncio.wait_for(
                self._inject_urgent_insights(final_result, user_id, query=query),
                timeout=3.0
            )
        except asyncio.TimeoutError:
            logger.info("[SupervisorAgent] Insight injection timed out (3s), skipping")
        
        # 7b. Inject Advocacy Context — surface background tracking naturally
        try:
            final_result = await asyncio.wait_for(
                self._inject_advocacy_context(final_result, user_id),
                timeout=3.0
            )
        except asyncio.TimeoutError:
            logger.debug("[SupervisorAgent] Advocacy injection timed out, skipping")
        
        await self._emit_event('workflow_complete', 'Here is what I found.')
        
        # 8. Fire-and-forget: Record interaction + track patterns (don't block response)
        asyncio.create_task(self._record_interaction(
            user_id=user_id, 
            session_id=session_id, 
            query=query, 
            response=final_result, 
            agent_name="supervisor_multi_step" if steps else "supervisor_single_step"
        ))
        
        if self.patterns and user_id:
            try:
                self.patterns.analyze_behavior(
                    user_id=user_id,
                    action_type="supervisor_completion",
                    context={'query': query}
                )
            except Exception:
                pass  # Non-critical

        # Record observability metrics
        self._record_metrics(_metrics, _start_ts)
            
        return self._sanitize_response(final_result, user_id)

    def _record_metrics(
        self, metrics: Dict[str, Any], start_time: float
    ) -> None:
        """Record structured observability metrics for this request."""
        import time as _time
        metrics["latency_ms"] = round((_time.monotonic() - start_time) * 1000)

        # Initialize metrics storage if needed
        if not hasattr(self, "_obs_metrics"):
            self._obs_metrics: List[Dict[str, Any]] = []

        self._obs_metrics.append(metrics)

        # Keep only last 500 requests
        if len(self._obs_metrics) > 500:
            self._obs_metrics = self._obs_metrics[-500:]

        logger.info(
            f"[Observability] route={metrics.get('route')} "
            f"latency={metrics['latency_ms']}ms "
            f"(plan={metrics.get('planning_ms', 0)}ms, "
            f"exec={metrics.get('execution_ms', 0)}ms, "
            f"enhance={metrics.get('enhancement_ms', 0)}ms) "
            f"steps={metrics.get('steps', 0)}"
        )

    def get_observability_report(self) -> Dict[str, Any]:
        """
        Get structured observability report for dashboarding.
        
        Returns aggregate statistics across recent requests:
        - p50/p95/p99 latencies
        - routing distribution
        - error rate
        - average step count
        """
        metrics = getattr(self, "_obs_metrics", [])
        if not metrics:
            return {"message": "No metrics collected yet", "total_requests": 0}

        latencies = sorted(m["latency_ms"] for m in metrics)
        n = len(latencies)

        routing_dist: Dict[str, int] = {}
        errors = 0
        total_steps = 0

        for m in metrics:
            route = m.get("route", "unknown")
            routing_dist[route] = routing_dist.get(route, 0) + 1
            if m.get("error"):
                errors += 1
            total_steps += m.get("steps", 0)

        return {
            "total_requests": n,
            "latency": {
                "p50_ms": latencies[n // 2] if n else 0,
                "p95_ms": latencies[int(n * 0.95)] if n else 0,
                "p99_ms": latencies[int(n * 0.99)] if n else 0,
                "avg_ms": round(sum(latencies) / n) if n else 0,
            },
            "routing_distribution": routing_dist,
            "avg_steps_per_request": round(total_steps / n, 1) if n else 0,
            "error_rate": round(errors / n, 3) if n else 0,
            "avg_planning_ms": round(
                sum(m.get("planning_ms", 0) for m in metrics) / n
            ) if n else 0,
            "avg_execution_ms": round(
                sum(m.get("execution_ms", 0) for m in metrics) / n
            ) if n else 0,
        }

    # --- Follow-Up Reference Resolution ---
    
    # Patterns that indicate vague follow-up references needing resolution
    _FOLLOWUP_PATTERNS = re.compile(
        r'\b('
        r'the email|that email|this email|the message|that message|this message|'
        r'the meeting|that meeting|this meeting|the event|that event|this event|'
        r'the task|that task|this task|the note|that note|this note|'
        r'the file|that file|this file|the document|that document|this document|'
        r'tell me more|read more|more about it|more details|'
        r'what does it|what did it|who sent it|who is it from|'
        r'summarize it|open it|reply to it|forward it|delete it|'
        r'what\'s it about|what is it about|'
        r'the first one|the second one|the last one|'
        r'about that|about this|about it'
        r')\b',
        re.IGNORECASE
    )
    
    async def _resolve_followup_references(
        self, query: str, user_id: Optional[int], session_id: Optional[str]
    ) -> str:
        """
        Detect follow-up references in a query and rewrite them using conversation history.
        
        Handles TWO scenarios:
        1. Vague references: "the email", "it", "that meeting" etc.
        2. Human-in-the-loop: User providing info that the assistant explicitly asked for
           (e.g., assistant asked "What's Emmanuel's email?" → user says "emmanuel@clavr.me")
        
        Returns the rewritten query, or the original if no rewriting is needed.
        """
        # --- Phase 1: Determine if this is a follow-up ---
        has_vague_reference = bool(self._FOLLOWUP_PATTERNS.search(query))
        is_hitl_response = False  # Human-in-the-loop response
        
        # Check if the last assistant response asked the user for information
        # This catches the case where user is providing info the agent requested
        if not has_vague_reference and self.memory and user_id and session_id:
            try:
                recent = await self.memory.get_recent_messages(
                    user_id=user_id,
                    session_id=session_id,
                    limit=2
                )
                if recent:
                    # Find the last assistant message
                    last_assistant_msg = None
                    for msg in reversed(recent):
                        if msg.get('role') == 'assistant':
                            last_assistant_msg = msg.get('content', '')
                            break
                    
                    if last_assistant_msg:
                        last_content = last_assistant_msg[-500:]  # Check the tail
                        last_lower = last_content.lower()
                        
                        # Detect if assistant asked the user a question or requested info
                        hitl_signals = [
                            '?' in last_content[-200:],  # Ends with a question
                            'let me know' in last_lower,
                            'tell me' in last_lower,
                            'what is' in last_lower and '?' in last_content,
                            'what\'s' in last_lower and '?' in last_content,
                            'could you' in last_lower,
                            'please provide' in last_lower,
                            'you\'ll need to' in last_lower,
                            'email is' in query.lower(),  # User explicitly providing an email
                            'address is' in query.lower(),
                            'his email' in query.lower() or 'her email' in query.lower(),
                        ]
                        
                        if any(hitl_signals):
                            is_hitl_response = True
                            logger.info(
                                f"[SupervisorAgent] Human-in-the-loop detected: "
                                f"previous assistant response asked for info, "
                                f"user is providing it: '{query[:80]}'"
                            )
            except Exception as e:
                logger.debug(f"[SupervisorAgent] HITL detection failed: {e}")
        
        # Fast path: skip if neither a vague reference nor a HITL response
        if not has_vague_reference and not is_hitl_response:
            return query
        
        logger.info(
            f"[SupervisorAgent] Follow-up detected (vague_ref={has_vague_reference}, "
            f"hitl={is_hitl_response}) in: {query}"
        )
        
        # Fetch recent conversation history
        conversation_history = ""
        try:
            if self.memory and user_id and session_id:
                recent = await self.memory.get_recent_messages(
                    user_id=user_id,
                    session_id=session_id,
                    limit=4
                )
                if recent:
                    history_lines = []
                    for msg in recent[-4:]:
                        role = msg.get('role', 'user').upper()
                        content = msg.get('content', '')[:800]
                        history_lines.append(f"{role}: {content}")
                    conversation_history = "\n".join(history_lines)
        except Exception as e:
            logger.debug(f"[SupervisorAgent] Could not fetch history for reference resolution: {e}")
        
        if not conversation_history:
            logger.info("[SupervisorAgent] No conversation history available, keeping original query.")
            return query
        
        # Use LLM to rewrite the query with resolved references
        try:
            rewrite_prompt = (
                "You are a query rewriter. The user sent a follow-up message that is "
                "related to the previous conversation.\n\n"
                "This could be:\n"
                "A) A message with vague references ('the email', 'it', 'that meeting')\n"
                "B) The user providing information the assistant ASKED for (e.g., the "
                "assistant asked for someone's email, and the user is providing it)\n\n"
                "Using the conversation history below, rewrite the user's message into a "
                "FULLY SELF-CONTAINED ACTION REQUEST that can be understood without any "
                "prior context.\n\n"
                "RULES:\n"
                "- Return ONLY the rewritten query, nothing else.\n"
                "- If the assistant asked for info to complete an action (like scheduling "
                "a meeting), the rewrite MUST include the original action with all "
                "details PLUS the new info the user provided.\n"
                "  Example: Assistant asked for Emmanuel's email to schedule a meeting → "
                "User says 'his email is e@x.com' → Rewrite: "
                "'Schedule a Clavr meeting tomorrow at 9am with Emmanuel (emmanuel@x.com)'\n"
                "- Keep the user's intent exactly the same.\n"
                "- If you cannot determine the context, return the original query unchanged.\n"
                "- Do NOT add extra information beyond what's in the conversation.\n\n"
                f"CONVERSATION HISTORY:\n{conversation_history}\n\n"
                f"USER'S FOLLOW-UP: {query}\n\n"
                "REWRITTEN QUERY:"
            )
            
            if self.interactions_client.is_available:
                previous_id = await self._get_session_interaction_id(user_id)
                result = await self.interactions_client.create_interaction(
                    input=rewrite_prompt,
                    model=DEFAULT_FAST_MODEL,
                    previous_interaction_id=previous_id,
                    generation_config={"temperature": 0.0}
                )
                await self._update_session_interaction_id(user_id, result.id)
                rewritten = result.text.strip()
            elif self.llm:
                response = await asyncio.to_thread(
                    self.llm.invoke,
                    [
                        SystemMessage(content=rewrite_prompt),
                        HumanMessage(content=query)
                    ]
                )
                rewritten = (response.content if hasattr(response, 'content') else str(response)).strip()
            else:
                return query
            
            # Sanity checks
            if rewritten and len(rewritten) > 5 and rewritten.lower() != query.lower():
                # Remove any wrapping quotes the LLM might add
                rewritten = rewritten.strip('"\'')
                logger.info(f"[SupervisorAgent] Query rewritten: '{query}' → '{rewritten}'")
                return rewritten
            else:
                logger.info(f"[SupervisorAgent] LLM returned same/empty query, keeping original.")
                return query
                
        except Exception as e:
            logger.warning(f"[SupervisorAgent] Follow-up resolution failed: {e}")
            return query

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

                    normalized = DOMAIN_ALIASES.get(category, category)
                    if normalized in self.agents or normalized == "general":
                        return normalized
                        
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

                normalized = DOMAIN_ALIASES.get(category, category)
                if normalized in self.agents or normalized == "general":
                    return normalized
                
            return "general"
            
        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return self._keyword_fallback(query)

    def _keyword_fallback(self, query: str) -> str:
        """Keyword fallback for routing — uses SkillRegistry for domain resolution."""
        if self.fast_classifier:
            result = self.fast_classifier.classify_to_domain(query)
            if result:
                logger.info(f"[SupervisorAgent] SkillRegistry resolved to: {result}")
                return result
        
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


    # Global execution budget for multi-step plans (improvement #7)
    EXECUTION_BUDGET_SECONDS = 45.0
    PER_STEP_TIMEOUT_SECONDS = 30.0

    @staticmethod
    def _format_step_result(sr: StepResult) -> str:
        """Format a StepResult into a labelled text block for context passing."""
        status = "OK" if sr.get("success") else "FAILED"
        domain = sr.get("domain", "unknown")
        return f"\n[Step {sr.get('step_id', '?')} — {domain} {status}]: {sr.get('result', '')}\n"

    async def _execute_multi_step_plan(
        self, 
        steps: List[Dict[str, Any]], 
        user_id: int, 
        user_name: Optional[str], 
        session_id: Optional[str],
        active_providers: set
    ) -> str:
        """Execute a decomposed multi-step plan with structured results and execution budget."""
        import time as _time
        budget_start = _time.monotonic()
        
        logger.info(f"Supervisor Plan: {len(steps)} steps (budget={self.EXECUTION_BUDGET_SECONDS}s)")
        summary = ", ".join([s.get('domain', 'general').title() for s in steps])
        await self._emit_event('supervisor_plan_created', f"I'll check: {summary}", data={'steps': steps})
        
        # Identify dependencies (uses explicit depends_on from planner)
        dep_indices = []
        ind_indices = []
        for i, s in enumerate(steps):
            if s.get("depends_on", []):
                dep_indices.append(i)
            else:
                ind_indices.append(i)
        
        step_results: List[StepResult] = []
        context_text = ""  # Accumulated text for dependent steps
        
        # Run independent steps in parallel (budget-aware)
        if ind_indices:
            elapsed = _time.monotonic() - budget_start
            remaining = self.EXECUTION_BUDGET_SECONDS - elapsed
            
            if remaining > 2.0:
                with LatencyMonitor("Parallel Steps", threshold_ms=30000):
                    tasks = [
                        asyncio.wait_for(
                            self._execute_single_step(
                                steps[i], i+1, "", user_id, user_name, session_id, active_providers
                            ),
                            timeout=min(self.PER_STEP_TIMEOUT_SECONDS, remaining)
                        ) for i in ind_indices
                    ]
                    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
                    for i, r in zip(ind_indices, raw_results):
                        if isinstance(r, asyncio.TimeoutError):
                            sr = StepResult(
                                step_id=f"step_{i+1}", tool="", domain=steps[i].get("domain", "unknown"),
                                success=False, result="Timed out.",
                                execution_time=self.PER_STEP_TIMEOUT_SECONDS, error="timeout",
                                timestamp=datetime.utcnow().isoformat()
                            )
                        elif isinstance(r, Exception):
                            sr = StepResult(
                                step_id=f"step_{i+1}", tool="", domain=steps[i].get("domain", "unknown"),
                                success=False, result=str(r),
                                execution_time=0, error=str(r),
                                timestamp=datetime.utcnow().isoformat()
                            )
                        else:
                            sr = r
                        step_results.append(sr)
                        context_text += self._format_step_result(sr)
            else:
                context_text += "\n[Budget exceeded before parallel steps could run]\n"
        
        # Run dependent steps sequentially (budget-aware)
        for i in dep_indices:
            elapsed = _time.monotonic() - budget_start
            remaining = self.EXECUTION_BUDGET_SECONDS - elapsed
            
            if remaining <= 2.0:
                sr = StepResult(
                    step_id=f"step_{i+1}", tool="", domain=steps[i].get("domain", "unknown"),
                    success=False, result=f"Skipped (budget of {self.EXECUTION_BUDGET_SECONDS}s exceeded).",
                    execution_time=0, error="budget_exceeded",
                    timestamp=datetime.utcnow().isoformat()
                )
                step_results.append(sr)
                context_text += self._format_step_result(sr)
                logger.warning(f"[SupervisorAgent] Step {i+1} skipped — budget exhausted ({elapsed:.1f}s used)")
                continue
            
            try:
                sr = await asyncio.wait_for(
                    self._execute_single_step(
                        steps[i], i+1, context_text, user_id, user_name, session_id, active_providers
                    ),
                    timeout=min(self.PER_STEP_TIMEOUT_SECONDS, remaining)
                )
            except asyncio.TimeoutError:
                sr = StepResult(
                    step_id=f"step_{i+1}", tool="", domain=steps[i].get("domain", "unknown"),
                    success=False, result="Timed out.",
                    execution_time=remaining, error="timeout",
                    timestamp=datetime.utcnow().isoformat()
                )
            except Exception as e:
                sr = StepResult(
                    step_id=f"step_{i+1}", tool="", domain=steps[i].get("domain", "unknown"),
                    success=False, result=str(e),
                    execution_time=0, error=str(e),
                    timestamp=datetime.utcnow().isoformat()
                )
            step_results.append(sr)
            context_text += self._format_step_result(sr)
            
            # Stream step result preview to frontend
            if self.event_emitter:
                preview = sr.get("result", "")[:200]
                await self._emit_event('step_result_preview', preview, data={
                    'step': i+1, 'domain': sr.get('domain'), 'success': sr.get('success')
                })
        
        # Step-level observability (#11)
        failed_count = 0
        for sr in step_results:
            is_success = sr.get('success', False)
            if not is_success:
                failed_count += 1
            logger.info(
                f"[StepResult] {sr.get('step_id')}: domain={sr.get('domain')}, "
                f"success={is_success}, time={sr.get('execution_time', 0):.2f}s"
            )
        
        # Observe phase — evaluate if multi-step execution achieved the goal
        if len(steps) > 1 and failed_count > 0:
            observation = await self._evaluate_execution(steps, step_results, user_id)
            if observation:
                context_text += f"\n[Observation]: {observation}\n"
        
        return context_text

    async def _evaluate_execution(
        self,
        steps: List[Dict[str, Any]],
        step_results: List[StepResult],
        user_id: Optional[int]
    ) -> Optional[str]:
        """
        Observe phase (improvement #2): Evaluate whether multi-step execution
        achieved the overall goal. Returns an observation note if issues detected.
        """
        failed = [sr for sr in step_results if not sr.get("success")]
        if not failed:
            return None
        
        # Build a concise summary for the LLM to evaluate
        summary_parts = []
        for sr in step_results:
            status = "OK" if sr.get("success") else "FAILED"
            summary_parts.append(
                f"- {sr.get('step_id')} ({sr.get('domain')}): {status} — {str(sr.get('result', ''))[:100]}"
            )
        
        results_summary = "\n".join(summary_parts)
        
        try:
            # Lightweight evaluation using fast LLM
            eval_prompt = (
                f"The following multi-step plan was executed. Some steps failed.\n\n"
                f"Steps planned: {len(steps)}\n"
                f"Results:\n{results_summary}\n\n"
                f"In ONE sentence, summarize what was NOT achieved and what the user should know."
            )
            
            if self.interactions_client.is_available:
                result = await asyncio.wait_for(
                    self.interactions_client.create_interaction(
                        input=eval_prompt,
                        model=DEFAULT_FAST_MODEL,
                        generation_config={"temperature": 0.0, "max_output_tokens": 150}
                    ),
                    timeout=5.0
                )
                return result.text.strip()
            elif self.llm:
                messages = [HumanMessage(content=eval_prompt)]
                response = await asyncio.wait_for(
                    asyncio.to_thread(self.llm.invoke, messages),
                    timeout=5.0
                )
                return response.content.strip() if hasattr(response, 'content') else str(response).strip()
        except asyncio.TimeoutError:
            logger.info("[SupervisorAgent] Observe phase timed out (5s), skipping")
        except Exception as e:
            logger.debug(f"[SupervisorAgent] Observe phase evaluation failed: {e}")
        
        return None

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
            
            ctx = {
                "user_id": user_id,
                "user_name": user_name,
                "session_id": session_id,
                "active_providers": sorted(active_providers),
            }
        
            # Fetch conversation context for follow-up reference resolution
            try:
                from src.services.context_service import get_context_service
                context_data = await get_context_service().get_unified_context(
                    user_id=user_id, query=query, session_id=session_id,
                    memory_client=self.memory, limit_history=4
                )
                previous_context = context_data.get("conversation_context", "")
                if previous_context:
                    ctx["previous_context"] = previous_context
            except Exception as e:
                logger.debug(f"[SupervisorAgent] Could not fetch context for single routing: {e}")
        
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
