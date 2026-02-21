"""
Memory Orchestrator

The unified memory interface for all agents. This is the "brain" of the Perfect Memory system.

Responsibilities:
1. Retrieve context from all memory layers (working, semantic, graph, conversation)
2. Score and prioritize memories by salience
3. Format context for LLM consumption
4. Write back to appropriate layers
5. Manage working memory for the session
6. Provide proactive memory injection

This is the single source of truth for agent memory access.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import asyncio
import time

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.ai.capabilities.nlp_processor import NLPProcessor

logger = setup_logger(__name__)


@dataclass
class AssembledContext:
    """
    Assembled context from all memory layers.
    
    This is what gets injected into agent prompts.
    """
    # Working memory context
    recent_turns: List[Dict[str, Any]] = field(default_factory=list)
    active_entities: List[str] = field(default_factory=list)
    active_topics: List[str] = field(default_factory=list)
    current_goal: Optional[str] = None
    
    # Semantic memory context
    relevant_facts: List[Dict[str, Any]] = field(default_factory=list)
    user_preferences: List[Dict[str, Any]] = field(default_factory=list)
    
    # Graph context
    graph_context: List[Dict[str, Any]] = field(default_factory=list)
    related_people: List[Dict[str, Any]] = field(default_factory=list)
    related_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # Conversation history
    cross_session_context: List[Dict[str, Any]] = field(default_factory=list)
    
    # Proactive insights
    proactive_insights: List[Dict[str, Any]] = field(default_factory=list)
    
    # New Context Layers
    protection_level: str = "normal"
    linear_context: Dict[str, Any] = field(default_factory=dict)
    cross_stack_summary: str = ""
    
    # Metadata
    retrieval_time_ms: float = 0.0
    sources_queried: List[str] = field(default_factory=list)
    confidence: float = 0.5
    
    def to_prompt_string(self, max_length: int = 3000) -> str:
        """
        Convert assembled context to a string for LLM prompt injection.
        
        Args:
            max_length: Maximum character length for the context string
            
        Returns:
            Formatted context string
        """
        sections = []
        
        # 1. Recent conversation (highest priority)
        if self.recent_turns:
            turn_lines = ["RECENT CONVERSATION:"]
            for turn in self.recent_turns[-5:]:  # Last 5 turns
                role = turn.get("role", "unknown").upper()
                content = turn.get("content", "")[:150]
                if len(turn.get("content", "")) > 150:
                    content += "..."
                agent = turn.get("agent_name")
                agent_suffix = f" ({agent})" if agent else ""
                turn_lines.append(f"- {role}{agent_suffix}: {content}")
            sections.append("\n".join(turn_lines))
        
        # 2. Current focus
        if self.current_goal or self.active_entities or self.active_topics:
            focus_lines = ["CURRENT FOCUS:"]
            if self.current_goal:
                focus_lines.append(f"- Goal: {self.current_goal}")
            if self.active_entities:
                focus_lines.append(f"- Key entities: {', '.join(self.active_entities[:5])}")
            if self.active_topics:
                focus_lines.append(f"- Topics: {', '.join(self.active_topics[:3])}")
            sections.append("\n".join(focus_lines))
        
        # 3. Proactive insights (important warnings/connections)
        if self.proactive_insights:
            insight_lines = ["PROACTIVE INSIGHTS:"]
            for insight in self.proactive_insights[:3]:
                insight_type = insight.get("type", "info")
                content = insight.get("content", "")
                icon = {"conflict": "⚠️", "connection": "🔗", "suggestion": "💡"}.get(insight_type, "ℹ️")
                insight_lines.append(f"{icon} {content}")
            sections.append("\n".join(insight_lines))
        
        # 4. Relevant facts (from semantic memory)
        if self.relevant_facts:
            fact_lines = ["KNOWN FACTS:"]
            for fact in self.relevant_facts[:5]:
                content = fact.get("content", "")
                confidence = fact.get("confidence", 0.5)
                if confidence > 0.8:
                    fact_lines.append(f"- ★ {content}")
                else:
                    fact_lines.append(f"- {content}")
            sections.append("\n".join(fact_lines))
        
        # 5. User preferences
        if self.user_preferences:
            pref_lines = ["USER PREFERENCES:"]
            for pref in self.user_preferences[:3]:
                pref_lines.append(f"- {pref.get('content', pref.get('pattern', ''))}")
            sections.append("\n".join(pref_lines))
        
        # 6. Graph context (cross-app relationships)
        if self.graph_context:
            graph_lines = ["RELATED CONTEXT:"]
            for item in self.graph_context[:5]:
                node_type = item.get("type", "Item")
                content = item.get("content", "")[:100]
                source = item.get("source", "")
                source_label = f" ({source})" if source else ""
                graph_lines.append(f"- [{node_type}]{source_label}: {content}")
            sections.append("\n".join(graph_lines))
        
        # 7. Related people
        if self.related_people:
            people_lines = ["RELATED PEOPLE:"]
            for person in self.related_people[:5]: # Increased to 5
                name = person.get("name", "Unknown")
                email = person.get("email")
                context = person.get("context", "")
                
                label = f"{name}"
                if email:
                    label += f" <{email}>"
                
                people_lines.append(f"- {label}: {context[:50]}" if context else f"- {label}")
            sections.append("\n".join(people_lines))
        
        # 8. Protection Status (Deep Work)
        if self.protection_level and self.protection_level != "normal":
            protection_lines = ["PROTECTION STATUS:"]
            status_text = {
                "meeting_heavy": "In back-to-back meetings. Use brevity.",
                "deep_work": "Currently in DEEP WORK mode. Do not interrupt unless urgent."
            }.get(self.protection_level, self.protection_level)
            protection_lines.append(f"● {status_text}")
            sections.append("\n".join(protection_lines))

        # 9. Linear Context
        if self.linear_context and self.linear_context.get("issues"):
            linear_lines = ["LINEAR WORKSPACE:"]
            for issue in self.linear_context.get("issues", [])[:3]:
                linear_lines.append(f"- [{issue.get('id')}] {issue.get('title')} ({issue.get('state')})")
            sections.append("\n".join(linear_lines))

        # 10. Cross-Stack Summary (Autonomous Glue)
        if self.cross_stack_summary:
            sections.append(f"CROSS-STACK SUMMARY:\n{self.cross_stack_summary}")

        # 11. Cross-session context
        if self.cross_session_context:
            cross_lines = ["FROM PREVIOUS SESSIONS:"]
            for item in self.cross_session_context[:2]:
                content = item.get("content", "")[:100]
                cross_lines.append(f"- {content}")
            sections.append("\n".join(cross_lines))
        
        # Combine all sections
        full_context = "\n\n".join(sections)
        
        # Truncate if too long
        if len(full_context) > max_length:
            full_context = full_context[:max_length] + "\n... [context truncated]"
        
        return full_context
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "recent_turns": self.recent_turns,
            "active_entities": self.active_entities,
            "active_topics": self.active_topics,
            "current_goal": self.current_goal,
            "relevant_facts": self.relevant_facts,
            "user_preferences": self.user_preferences,
            "graph_context": self.graph_context,
            "related_people": self.related_people,
            "related_events": self.related_events,
            "cross_session_context": self.cross_session_context,
            "proactive_insights": self.proactive_insights,
            "protection_level": self.protection_level,
            "linear_context": self.linear_context,
            "cross_stack_summary": self.cross_stack_summary,
            "retrieval_time_ms": self.retrieval_time_ms,
            "sources_queried": self.sources_queried,
            "confidence": self.confidence
        }


class MemoryOrchestrator:
    """
    The unified memory interface for all agents.
    
    This is the brain of Perfect Memory. All agents go through this
    orchestrator to retrieve and store memories.
    
    Features:
    - Parallel retrieval from all memory layers
    - Salience-based scoring and prioritization
    - Formatted context for LLM injection
    - Write-back to appropriate layers
    - Working memory management
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        graph_manager: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        semantic_memory: Optional[Any] = None,
        conversation_memory: Optional[Any] = None,
        working_memory_manager: Optional[Any] = None,
        salience_scorer: Optional[Any] = None,
        goal_tracker: Optional[Any] = None,
        deep_work_logic: Optional[Any] = None,
        cross_stack_context: Optional[Any] = None,
        linear_service: Optional[Any] = None,
        nlp_processor: Optional[NLPProcessor] = None
    ):
        """
        Initialize the Memory Orchestrator.
        
        Args:
            config: Application configuration
            graph_manager: KnowledgeGraphManager instance
            rag_engine: RAGEngine instance
            semantic_memory: SemanticMemory instance
            conversation_memory: ConversationMemory instance
            working_memory_manager: WorkingMemoryManager instance
            salience_scorer: SalienceScorer for memory prioritization
            goal_tracker: GoalTracker for intent persistence
        """
        self.config = config
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        self.semantic_memory = semantic_memory
        self.conversation_memory = conversation_memory
        
        # Initialize working memory manager if not provided
        if working_memory_manager is None:
            from src.memory.working_memory import get_working_memory_manager
            working_memory_manager = get_working_memory_manager()
        self.working_memory_manager = working_memory_manager
        
        # Initialize salience scorer if not provided
        if salience_scorer is None:
            from src.memory.salience_scorer import get_salience_scorer
            salience_scorer = get_salience_scorer()
        self.salience_scorer = salience_scorer
        
        # Initialize goal tracker if not provided
        if goal_tracker is None:
            from src.memory.goal_tracker import get_goal_tracker, init_goal_tracker
            goal_tracker = get_goal_tracker()
            if goal_tracker is None:
                goal_tracker = init_goal_tracker()
        self.goal_tracker = goal_tracker
        
        # New features
        self.deep_work_logic = deep_work_logic
        self.cross_stack_context = cross_stack_context
        self.linear_service = linear_service
        self.nlp_processor = nlp_processor or NLPProcessor()
        
        # Caches for performance
        self._graph_rag_service = None
        self._insight_service = None
        
        logger.info("[MemoryOrchestrator] Initialized with SalienceScorer and GoalTracker")
    
    def get_working_memory(self, user_id: int, session_id: str):
        """
        Get or create working memory for a user session.
        
        Args:
            user_id: User ID
            session_id: Session ID
            
        Returns:
            WorkingMemory instance
        """
        return self.working_memory_manager.get_or_create(user_id, session_id)
    
    async def get_context_for_agent(
        self,
        user_id: int,
        agent_name: str,
        query: str,
        session_id: Optional[str] = None,
        task_type: str = "general",
        include_layers: Optional[List[str]] = None,
        max_context_length: int = 3000
    ) -> AssembledContext:
        """
        Assemble comprehensive context for an agent.
        
        This is the main entry point for agents to get memory context.
        Retrieves from all memory layers in parallel for performance.
        
        Args:
            user_id: User ID
            agent_name: Name of the requesting agent
            query: The current user query
            session_id: Optional session ID for working memory
            task_type: Type of task (research, fact_check, planning, general)
            include_layers: Which layers to query (default: all)
            max_context_length: Maximum context string length
            
        Returns:
            AssembledContext with all relevant memories
        """
        start_time = time.time()
        
        # Default to all layers
        if include_layers is None:
            include_layers = [
                "working", "semantic", "graph", "conversation", 
                "insights", "protection", "linear", "cross_stack"
            ]
        
        context = AssembledContext()
        tasks = []
        
        # 1. Working Memory (synchronous, fast)
        if "working" in include_layers and session_id:
            wm = self.working_memory_manager.get(user_id, session_id)
            if wm:
                context.recent_turns = [t.to_dict() for t in wm.get_context_window(5)]
                context.active_entities = wm.active_entities[:10]
                context.active_topics = wm.active_topics[:5]
                context.current_goal = wm.current_goal
                context.sources_queried.append("working_memory")
        
        # 1b. Add active goals to context
        if self.goal_tracker:
            try:
                active_goals = await self.goal_tracker.get_active_goals(user_id)
                if active_goals:
                    # Use most important goal as current_goal if not set by working memory
                    if not context.current_goal and active_goals:
                        context.current_goal = active_goals[0].format_for_context()
                    
                    # Add goal-related insights
                    for goal in active_goals[:3]:
                        if goal.is_overdue():
                            context.proactive_insights.append({
                                "type": "conflict",
                                "content": f"⚠️ Overdue: {goal.description}"
                            })
                        elif goal.days_until_due() is not None and goal.days_until_due() <= 2:
                            context.proactive_insights.append({
                                "type": "suggestion",
                                "content": f"Due soon: {goal.description}"
                            })
            except Exception as e:
                logger.debug(f"[MemoryOrchestrator] Goal retrieval failed: {e}")
        
        # 2. Semantic Memory (async)
        if "semantic" in include_layers and self.semantic_memory:
            tasks.append(self._retrieve_semantic_context(user_id, query))
        
        # 3. Graph Context (async)
        if "graph" in include_layers and self.graph_manager:
            tasks.append(self._retrieve_graph_context(user_id, query, task_type))
        
        # 4. Cross-Session Conversation (async)
        if "conversation" in include_layers and self.conversation_memory:
            tasks.append(self._retrieve_conversation_context(user_id, query, session_id))
        
        # 5. Proactive Insights (async)
        if "insights" in include_layers:
            tasks.append(self._retrieve_proactive_insights(user_id, query, context.active_entities))
        
        # Execute all async retrievals in parallel
        retrieval_tasks = {}
        if "semantic" in include_layers and self.semantic_memory:
            retrieval_tasks["semantic"] = self._retrieve_semantic_context(user_id, query)
        
        if "graph" in include_layers and self.graph_manager:
            retrieval_tasks["graph"] = self._retrieve_graph_context(user_id, query, task_type)
        
        if "conversation" in include_layers and self.conversation_memory:
            retrieval_tasks["conversation"] = self._retrieve_conversation_context(user_id, query, session_id)
        
        if "insights" in include_layers:
            retrieval_tasks["insights"] = self._retrieve_proactive_insights(user_id, query, context.active_entities)
            
        if "protection" in include_layers:
            retrieval_tasks["protection"] = self._retrieve_protection_status(user_id)
            
        if "linear" in include_layers:
            retrieval_tasks["linear"] = self._retrieve_linear_context(user_id, query)
            
        if "cross_stack" in include_layers:
            retrieval_tasks["cross_stack"] = self._retrieve_cross_stack_context(user_id, query)
            
        if retrieval_tasks:
            try:
                task_names = list(retrieval_tasks.keys())
                task_coros = list(retrieval_tasks.values())
                results = await asyncio.gather(*task_coros, return_exceptions=True)
                
                # Process results with keyed mapping
                for name, result in zip(task_names, results):
                    if isinstance(result, Exception):
                        logger.warning(f"[MemoryOrchestrator] {name} retrieval failed: {result}")
                        continue
                    
                    if result is None:
                        continue
                        
                    if name == "semantic":
                        self._merge_semantic_results(context, result)
                    elif name == "graph":
                        self._merge_graph_results(context, result)
                    elif name == "conversation":
                        self._merge_conversation_results(context, result)
                    elif name == "insights":
                        self._merge_insight_results(context, result)
                    elif name == "protection":
                        context.protection_level = result
                        context.sources_queried.append("deep_work_shield")
                    elif name == "linear":
                        context.linear_context = result
                        context.sources_queried.append("linear")
                    elif name == "cross_stack":
                        context.cross_stack_summary = result.get("summary", "") if isinstance(result, dict) else ""
                        context.sources_queried.append("autonomous_glue")
                            
            except Exception as e:
                logger.error(f"[MemoryOrchestrator] Context assembly failed: {e}", exc_info=True)
        
        # Calculate retrieval time
        context.retrieval_time_ms = (time.time() - start_time) * 1000
        
        logger.debug(
            f"[MemoryOrchestrator] Assembled context for {agent_name} in "
            f"{context.retrieval_time_ms:.1f}ms (sources: {context.sources_queried})"
        )
        
        return context
    
    async def _retrieve_semantic_context(
        self, 
        user_id: int, 
        query: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve relevant facts and preferences from semantic memory."""
        try:
            results = {"facts": [], "preferences": []}
            
            # Search for relevant facts
            if hasattr(self.semantic_memory, "search_facts"):
                facts = await self.semantic_memory.search_facts(
                    query=query,
                    user_id=user_id,
                    limit=5
                )
                results["facts"] = facts or []
            
            # Get user preferences
            if hasattr(self.semantic_memory, "get_facts"):
                prefs = await self.semantic_memory.get_facts(
                    user_id=user_id,
                    category="preference",
                    limit=5
                )
                results["preferences"] = prefs or []
            
            return results
            
        except Exception as e:
            logger.warning(f"[MemoryOrchestrator] Semantic retrieval failed: {e}")
            return None
    
    async def _retrieve_graph_context(
        self, 
        user_id: int, 
        query: str,
        task_type: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve context from knowledge graph via RAG-Graph bridge."""
        try:
            # Lazy load integration service
            if self._graph_rag_service is None and self.rag_engine and self.graph_manager:
                from src.services.indexing.rag_graph_bridge import GraphRAGIntegrationService
                self._graph_rag_service = GraphRAGIntegrationService(
                    self.rag_engine, 
                    self.graph_manager
                )
            
            if not self._graph_rag_service:
                return None
            
            # Use search_for_agent if available
            if hasattr(self._graph_rag_service, "search_for_agent"):
                results = await self._graph_rag_service.search_for_agent(
                    query=query,
                    task_type=task_type,
                    user_id=user_id,
                    limit=7
                )
                return results
            else:
                # Fallback to basic search
                # Fallback to basic search
                results = await self._graph_rag_service.search_with_context(
                    query=query,
                    max_results=7,
                    graph_depth=2,
                    filters={'user_id': str(user_id)}
                )
                return {"results": results}
                
        except Exception as e:
            logger.warning(f"[MemoryOrchestrator] Graph retrieval failed: {e}")
            return None
    
    async def _retrieve_conversation_context(
        self, 
        user_id: int, 
        query: str,
        current_session_id: Optional[str]
    ) -> Optional[List[Dict[str, Any]]]:
        """Retrieve relevant context from past conversation sessions."""
        try:
            if hasattr(self.conversation_memory, "get_relevant_context_from_history"):
                results = await self.conversation_memory.get_relevant_context_from_history(
                    current_query=query,
                    user_id=user_id,
                    exclude_session_id=current_session_id,
                    k=3
                )
                return results
            return None
            
        except Exception as e:
            logger.warning(f"[MemoryOrchestrator] Conversation retrieval failed: {e}")
            return None
    
    async def _retrieve_proactive_insights(
        self, 
        user_id: int, 
        query: str,
        active_entities: List[str]
    ) -> Optional[List[Dict[str, Any]]]:
        """Retrieve proactive insights relevant to current context."""
        try:
            # Lazy load insight service
            if self._insight_service is None:
                try:
                    from src.services.insights import get_insight_service
                    self._insight_service = get_insight_service()
                except ImportError:
                    return None
            
            if not self._insight_service:
                return None
            
            insights = await self._insight_service.get_contextual_insights(
                user_id=user_id,
                current_context=query,
                max_insights=3
            )
            return insights
            
        except Exception as e:
            logger.debug(f"[MemoryOrchestrator] Insight retrieval failed: {e}")
            return None

    async def _retrieve_protection_status(self, user_id: int) -> str:
        """Fetch current protection (Deep Work) status for the user."""
        if not self.deep_work_logic:
            return "normal"
        
        try:
            # In a real impl, this would query the DB for the current user's protection state
            # or analyze the calendar on the fly.
            # For now, let's assume it has access to a service that provides this.
            if hasattr(self.deep_work_logic, "get_current_status"):
                return await self.deep_work_logic.get_current_status(user_id)
            return "normal"
        except Exception as e:
            logger.debug(f"[MemoryOrchestrator] Protection status retrieval failed: {e}")
            return "normal"

    async def _retrieve_linear_context(self, user_id: int, query: str) -> Dict[str, Any]:
        """Retrieve relevant Linear context."""
        if not self.linear_service:
            return {}
        
        try:
            # Search for issues relevant to the current query
            issues = await self.linear_service.search(query, limit=3)
            return {"issues": issues}
        except Exception as e:
            logger.debug(f"[MemoryOrchestrator] Linear context retrieval failed: {e}")
            return {}

    async def _retrieve_cross_stack_context(self, user_id: int, query: str) -> Dict[str, Any]:
        """Retrieve synthesized cross-stack context."""
        if not self.cross_stack_context:
            return {}
        
        try:
            # 1. Extract the core topic/ID if possible for cleaner search
            topic = query
            if self.nlp_processor:
                nlp_results = self.nlp_processor.process_query(query)
                entities = nlp_results.get("entities", [])
                
                # Prioritize Linear IDs then Project Names
                linear_ids = [e.resolved_value for e in entities if e.entity_type == "linear_id"]
                project_names = [e.resolved_value for e in entities if e.entity_type == "project_name"]
                
                if linear_ids:
                    topic = linear_ids[0]
                elif project_names:
                    topic = project_names[0]
            
            # 2. Use the "Autonomous Glue" to build context for the specific topic
            return await self.cross_stack_context.build_topic_context(topic, user_id)
        except Exception as e:
            logger.debug(f"[MemoryOrchestrator] Cross-stack context retrieval failed: {e}")
            return {}
    
    def _merge_semantic_results(self, context: AssembledContext, results: Dict[str, Any]):
        """Merge semantic memory results into context."""
        if not results:
            return
            
        facts = results.get("facts", [])
        for fact in facts:
            if isinstance(fact, dict):
                context.relevant_facts.append(fact)
            else:
                # Handle SQLAlchemy model objects
                context.relevant_facts.append({
                    "content": getattr(fact, "content", str(fact)),
                    "category": getattr(fact, "category", "general"),
                    "confidence": getattr(fact, "confidence", 0.5)
                })
        
        prefs = results.get("preferences", [])
        for pref in prefs:
            if isinstance(pref, dict):
                context.user_preferences.append(pref)
            else:
                context.user_preferences.append({
                    "content": getattr(pref, "content", str(pref)),
                    "category": getattr(pref, "category", "preference")
                })
        
        context.sources_queried.append("semantic_memory")
    
    def _merge_graph_results(self, context: AssembledContext, results: Dict[str, Any]):
        """Merge graph context results into context."""
        if not results:
            return
            
        graph_results = results.get("results", [])
        for item in graph_results:
            node_type = item.get("type", item.get("metadata", {}).get("node_type", "Item"))
            
            if node_type in ["Person", "Contact"]:
                context.related_people.append({
                    "name": item.get("name", item.get("metadata", {}).get("name", "Unknown")),
                    "email": item.get("email", item.get("metadata", {}).get("email")),
                    "context": item.get("content", "")[:100]
                })
            elif node_type in ["CalendarEvent", "Event"]:
                context.related_events.append(item)
            else:
                context.graph_context.append({
                    "type": node_type,
                    "content": item.get("content", item.get("text", "")),
                    "source": item.get("source", item.get("metadata", {}).get("source", ""))
                })
        
        context.sources_queried.append("knowledge_graph")
    
    def _merge_conversation_results(self, context: AssembledContext, results: List[Dict[str, Any]]):
        """Merge conversation memory results into context."""
        if results:
            context.cross_session_context = results
            context.sources_queried.append("conversation_memory")

    def _merge_insight_results(self, context: AssembledContext, results: List[Any]):
        """Merge proactive insights into context."""
        if results:
            for insight in results:
                if isinstance(insight, dict):
                    context.proactive_insights.append(insight)
                else:
                    context.proactive_insights.append({"content": str(insight), "type": "suggestion"})
            context.sources_queried.append("insight_service")
    
    async def _create_memory_node(
        self,
        user_id: int,
        content: str,
        category: str,
        source: str,
        confidence: float
    ) -> bool:
        """
        Create a graph node for high-importance memories.
        
        Maps categories to appropriate node types and creates
        nodes in the knowledge graph for persistent storage.
        
        Args:
            user_id: User ID
            content: Memory content
            category: Category (preference, contact, project, etc.)
            source: Origin of the memory
            confidence: Importance/confidence score
            
        Returns:
            True if node was created successfully
        """
        try:
            from src.services.indexing.graph.schema import NodeType
            from datetime import datetime
            
            # Map categories to node types
            category_to_node_type = {
                "preference": NodeType.INSIGHT,
                "contact": NodeType.PERSON,
                "project": NodeType.PROJECT,
                "topic": NodeType.TOPIC,
                "fact": NodeType.FACT,
                "work": NodeType.FACT,
                "personal": NodeType.FACT,
                "commitment": NodeType.ACTION_ITEM,
            }
            
            node_type = category_to_node_type.get(category, NodeType.FACT)
            
            # Build node properties
            properties = {
                "content": content,
                "category": category,
                "source": source,
                "confidence": confidence,
                "user_id": user_id,
                "created_at": datetime.utcnow().isoformat(),
                "memory_source": "orchestrator"
            }
            
            # Add category-specific properties
            if category == "contact" or node_type == NodeType.PERSON:
                # Try to extract name from content
                properties["name"] = content.split(":")[0] if ":" in content else content[:50]
            elif category == "project" or node_type == NodeType.PROJECT:
                properties["name"] = content[:100]
                properties["status"] = "active"
            elif node_type == NodeType.TOPIC:
                properties["name"] = content[:50]
            
            # Create the node
            await self.graph_manager.create_node(node_type, properties)
            
            logger.info(
                f"[MemoryOrchestrator] Created graph node ({node_type.value}) "
                f"for memory: '{content[:30]}...'"
            )
            
            return True
            
        except ImportError as e:
            logger.debug(f"[MemoryOrchestrator] Graph schema not available: {e}")
            return False
        except Exception as e:
            logger.warning(f"[MemoryOrchestrator] Failed to create memory node: {e}")
            return False
    
    async def remember(
        self,
        user_id: int,
        content: str,
        category: str,
        source: str = "agent",
        importance: float = 0.5,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Store a memory in the appropriate layer based on importance.
        
        Args:
            user_id: User ID
            content: The content to remember
            category: Category (preference, contact, work, etc.)
            source: Source of the memory (agent, user, inferred)
            importance: Importance score (0-1) determines storage layer
            session_id: Optional session for working memory
            
        Returns:
            True if successful
            
        Importance determines layer:
        - 0.0-0.3: Working memory only (ephemeral)
        - 0.3-0.6: Short-term (working + semantic with low confidence)
        - 0.6-0.8: Long-term (semantic + potentially graph)
        - 0.8-1.0: Permanent (semantic with high confidence + graph)
        """
        try:
            success = False
            
            # 1. Always add to working memory if session provided
            if session_id:
                wm = self.working_memory_manager.get(user_id, session_id)
                if wm:
                    wm.add_pending_fact(content, category, source, importance)
                    success = True
            
            # 2. Store in semantic memory based on importance
            if importance >= 0.3 and self.semantic_memory:
                confidence = min(importance, 1.0)
                if hasattr(self.semantic_memory, "learn_fact"):
                    await self.semantic_memory.learn_fact(
                        user_id=user_id,
                        content=content,
                        category=category,
                        source=source,
                        confidence=confidence
                    )
                    success = True
            
            # 3. High importance: also consider graph storage
            if importance >= 0.8 and self.graph_manager:
                await self._create_memory_node(
                    user_id=user_id,
                    content=content,
                    category=category,
                    source=source,
                    confidence=importance
                )
            
            logger.debug(
                f"[MemoryOrchestrator] Stored memory for user {user_id}: "
                f"'{content[:30]}...' (importance: {importance}, category: {category})"
            )
            
            return success
            
        except Exception as e:
            logger.error(f"[MemoryOrchestrator] Failed to store memory: {e}")
            return False
    
    async def learn_from_turn(
        self,
        user_id: int,
        session_id: str,
        user_message: str,
        assistant_response: str,
        agent_name: str,
        entities: Optional[List[str]] = None,
        topics: Optional[List[str]] = None,
        tools_used: Optional[List[str]] = None,
        success: bool = True
    ):
        """
        Learn from a complete conversation turn.
        
        This is called after each agent response to:
        1. Evaluate the PREVIOUS turn (did the user like it?)
        2. Update working memory with the current turn
        3. Extract and store any learnable facts
        4. Update entity/topic tracking
        
        Args:
            user_id: User ID
            session_id: Session ID
            user_message: The user's message
            assistant_response: The agent's response
            agent_name: Name of the responding agent
            entities: Entities mentioned
            topics: Topics discussed
            tools_used: Tools that were used
            success: Whether the interaction was successful
        """
        try:
            # Get/create working memory
            wm = self.working_memory_manager.get_or_create(user_id, session_id)
            
            # --- OUTCOME DETECTION: Evaluate previous turn ---
            # Before adding the new turn, check if the user's new message 
            # tells us whether the previous response was good or bad.
            try:
                from src.ai.capabilities.outcome_detector import get_outcome_detector, OutcomeSignal
                detector = get_outcome_detector()
                
                # Get the previous turn context from working memory
                turns = wm.get_context_window(3)
                prev_response = ""
                prev_query = ""
                for turn in reversed(turns):
                    if hasattr(turn, 'role'):
                        if turn.role == "assistant" and not prev_response:
                            prev_response = turn.content
                        elif turn.role == "user" and not prev_query:
                            prev_query = turn.content
                    elif isinstance(turn, dict):
                        if turn.get("role") == "assistant" and not prev_response:
                            prev_response = turn.get("content", "")
                        elif turn.get("role") == "user" and not prev_query:
                            prev_query = turn.get("content", "")
                
                if prev_response:
                    # Calculate time gap (approximate)
                    time_gap = 0.0
                    if hasattr(wm, '_last_activity') and wm._last_activity:
                        from datetime import datetime
                        time_gap = (datetime.utcnow() - wm._last_activity).total_seconds()
                    
                    outcome = detector.detect(
                        user_message=user_message,
                        previous_response=prev_response,
                        previous_query=prev_query,
                        time_gap_seconds=time_gap
                    )
                    
                    if outcome.signal in (OutcomeSignal.NEGATIVE, OutcomeSignal.CORRECTION, OutcomeSignal.RETRY):
                        # Mark the current interaction as not successful
                        success = False
                        
                        logger.info(
                            f"[MemoryOrchestrator] Outcome detected: {outcome.signal.value} "
                            f"(confidence: {outcome.confidence:.2f}) — {outcome.reasoning}"
                        )
                        
                        # Store correction as a fact for future learning
                        if outcome.signal == OutcomeSignal.CORRECTION and outcome.correction:
                            correction = outcome.correction
                            if correction.correct_element and self.semantic_memory:
                                correction_fact = (
                                    f"User corrected: wanted '{correction.correct_element}' "
                                    f"not '{correction.wrong_element or 'previous response'}'"
                                )
                                try:
                                    await self.semantic_memory.learn_fact(
                                        user_id=user_id,
                                        content=correction_fact,
                                        category="correction",
                                        source="outcome_detector",
                                        confidence=outcome.confidence
                                    )
                                except Exception:
                                    pass  # Non-critical
                            
                            # Forward domain corrections to routing system
                            if correction.wrong_domain and correction.correct_domain:
                                try:
                                    from src.ai.intent.user_skill_prefs import get_skill_tracker
                                    skill_tracker = get_skill_tracker()
                                    skill_tracker.get_profile(user_id).record_correction(
                                        wrong_skill=correction.wrong_domain,
                                        correct_skill=correction.correct_domain
                                    )
                                    logger.info(
                                        f"[MemoryOrchestrator] Routing correction: "
                                        f"{correction.wrong_domain} → {correction.correct_domain}"
                                    )
                                except Exception:
                                    pass  # Non-critical
                        
                        if outcome.signal == OutcomeSignal.RETRY:
                            # Store that the previous response format/content didn't work
                            if self.semantic_memory:
                                try:
                                    await self.semantic_memory.learn_fact(
                                        user_id=user_id,
                                        content=f"User rephrased query (possible dissatisfaction with previous answer by {agent_name})",
                                        category="feedback",
                                        source="outcome_detector",
                                        confidence=outcome.confidence * 0.7  # Lower confidence for inferred retries
                                    )
                                except Exception:
                                    pass
                    
                    elif outcome.signal == OutcomeSignal.POSITIVE and outcome.confidence > 0.7:
                        logger.debug(
                            f"[MemoryOrchestrator] Positive outcome: {outcome.reasoning}"
                        )
            
            except ImportError:
                pass  # OutcomeDetector not available
            except Exception as e:
                logger.debug(f"[MemoryOrchestrator] Outcome detection failed (non-critical): {e}")
            
            # --- Add current turn to working memory ---
            
            # Add user turn
            wm.add_turn(
                role="user",
                content=user_message,
                entities=entities or [],
                topics=topics or []
            )
            
            # Add assistant turn
            wm.add_turn(
                role="assistant",
                content=assistant_response,
                agent_name=agent_name,
                metadata={"tools_used": tools_used, "success": success}
            )
            
            # NOTE: Conversation message persistence is handled by ChatService.
            # Do NOT call conversation_memory.add_message() here — it would create
            # duplicate messages since ChatService already saves both the user query
            # and assistant response to the database.
            
            # Detect and track goals from user message
            if self.goal_tracker:
                try:
                    detected = await self.goal_tracker.detect_goal(
                        user_id=user_id,
                        message=user_message,
                        entities=entities
                    )
                    if detected and detected.confidence >= 0.7:
                        goal = await self.goal_tracker.add_goal(
                            user_id=user_id,
                            description=detected.description,
                            priority=detected.priority,
                            due_date=detected.due_date,
                            entities=detected.entities,
                            source="inferred"
                        )
                        # Set in working memory for immediate context
                        wm.set_goal(goal.description)
                        logger.info(f"[MemoryOrchestrator] Detected goal: {goal.description[:30]}...")
                    
                    # Check for goal completion
                    completed = await self.goal_tracker.detect_completion(user_id, user_message)
                    if completed:
                        logger.info(f"[MemoryOrchestrator] Goal completed: {completed.description[:30]}...")
                        
                except Exception as e:
                    logger.debug(f"[MemoryOrchestrator] Goal detection failed: {e}")
            
            logger.debug(
                f"[MemoryOrchestrator] Learned from turn for user {user_id}, "
                f"agent: {agent_name}, success: {success}"
            )
            
        except Exception as e:
            logger.error(f"[MemoryOrchestrator] Failed to learn from turn: {e}")
    
    def get_working_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about working memory usage."""
        return self.working_memory_manager.get_stats()
    
    def get_goal_stats(self, user_id: int) -> Dict[str, Any]:
        """Get goal statistics for a user."""
        if self.goal_tracker:
            return self.goal_tracker.get_stats(user_id)
        return {"error": "GoalTracker not initialized"}
    
    async def get_active_goals(self, user_id: int) -> List[str]:
        """Get formatted active goals for context injection."""
        if self.goal_tracker:
            return await self.goal_tracker.get_goals_for_context(user_id)
        return []


# Global instance management
_memory_orchestrator: Optional[MemoryOrchestrator] = None


def get_memory_orchestrator() -> Optional[MemoryOrchestrator]:
    """Get the global MemoryOrchestrator instance."""
    return _memory_orchestrator


def init_memory_orchestrator(
    config: Optional[Config] = None,
    graph_manager: Optional[Any] = None,
    rag_engine: Optional[Any] = None,
    semantic_memory: Optional[Any] = None,
    conversation_memory: Optional[Any] = None,
    deep_work_logic: Optional[Any] = None,
    cross_stack_context: Optional[Any] = None,
    linear_service: Optional[Any] = None
) -> MemoryOrchestrator:
    """
    Initialize the global MemoryOrchestrator.
    
    Should be called during application startup.
    """
    global _memory_orchestrator
    _memory_orchestrator = MemoryOrchestrator(
        config=config,
        graph_manager=graph_manager,
        rag_engine=rag_engine,
        semantic_memory=semantic_memory,
        conversation_memory=conversation_memory,
        deep_work_logic=deep_work_logic,
        cross_stack_context=cross_stack_context,
        linear_service=linear_service
    )
    logger.info("[MemoryOrchestrator] Global instance initialized")
    return _memory_orchestrator
