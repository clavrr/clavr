"""
Context Service

Centralized service for gathering context from various sources (Memory, Graph, Preferences)
to be used by Agents (Text) and Gemini Live (Voice).

This ensures consistent "brain" state across different interfaces.
"""
from typing import Dict, Any, Optional, List, Tuple
import asyncio
from datetime import datetime

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class ContextService:
    """
    Service to aggregate context for AI agents.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ContextService()
        return cls._instance
    
    async def get_unified_context(
        self,
        user_id: int,
        query: str = "",
        session_id: Optional[str] = None,
        memory_client: Optional[Any] = None,
        limit_history: int = 4
    ) -> Dict[str, str]:
        """
        Gather all relevant context for a user in parallel.
        
        Args:
            user_id: The ID of the user
            query: Current user query (for relevancy search)
            session_id: Current session ID (for short-term memory)
            memory_client: MemoryOrchestrator or simplified Memory client
            limit_history: Number of history turns to fetch
            
        Returns:
            Dict containing formatted strings:
            - conversation_context: Recent chat history
            - entity_context: Recently mentioned entities (for pronoun resolution)
            - semantic_context: User preferences/facts
            - graph_context: Relevant nodes from the knowledge graph
        """
        if not user_id:
            return {}

        results = {
            "conversation_context": "",
            "entity_context": "",
            "semantic_context": "",
            "graph_context": ""
        }
        
        # Define tasks
        
        # 1. Fetch recent messages
        async def fetch_history():
            if not memory_client: return ""
            logger.info("[ContextService] Fetching conversation history...")
            try:
                recent = await memory_client.get_recent_messages(
                    user_id=user_id,
                    session_id=session_id,
                    limit=limit_history
                )
                if recent:
                    history_lines = []
                    for msg in recent[-limit_history:]:
                        role = msg.get('role', 'user')
                        content = msg.get('content', '')[:500]
                        history_lines.append(f"{role.upper()}: {content}")
                    if history_lines:
                        return "\n\nRecent conversation (for context/pronoun resolution):\n" + "\n".join(history_lines)
            except Exception as e:
                logger.debug(f"Could not fetch conversation history: {e}")
            logger.info("[ContextService] Conversation history fetched.")
            return ""

        # 2. Fetch structured entities (Working Memory)
        async def fetch_entities():
            if not memory_client: return ""
            logger.info("[ContextService] Fetching recent entities...")
            try:
                # Assuming memory client has get_recent_context
                if hasattr(memory_client, 'get_recent_context'):
                    from src.services.service_constants import ServiceConstants
                    context_data = await memory_client.get_recent_context(
                        user_id=user_id,
                        session_id=session_id,
                        max_age_minutes=ServiceConstants.CONTEXT_MAX_AGE_MINUTES
                    )
                    entities = context_data.get('recent_entities', {})
                    entity_parts = []
                    for entity_type, values in entities.items():
                        if values:
                            unique_values = list(dict.fromkeys(values))[:3]
                            entity_parts.append(f"- {entity_type}: {', '.join(str(v) for v in unique_values)}")
                    if entity_parts:
                        return "\n\nRecent entities mentioned (use for resolving 'her', 'that email', 'the meeting', etc.):\n" + "\n".join(entity_parts)
            except Exception as e:
                logger.debug(f"Could not fetch entity context: {e}")
            logger.info("[ContextService] Recent entities fetched.")
            return ""

        # 3. Fetch User Preferences (Semantic Memory)
        async def fetch_prefs():
            if not memory_client: return ""
            try:
                if hasattr(memory_client, 'get_user_preferences'):
                    prefs = await memory_client.get_user_preferences(user_id)
                    if prefs:
                        return f"\n\n{prefs}"
            except Exception as e:
                logger.debug(f"Could not fetch semantic context: {e}")
            return ""

        # 4. Fetch Graph Context (Knowledge Graph)
        async def fetch_graph_context():
            if not query: return "" # Need query for graph search
            logger.info(f"[ContextService] Fetching graph context for query: {query[:50]}...")
            try:
                from src.services.graph_search_service import GraphSearchService
                graph_service = GraphSearchService.get_instance()
                if graph_service:
                    # Pass user_id explicitly to prevent data leaks
                    related = await graph_service.search(query, user_id=user_id, max_results=5)
                    if related:
                        graph_parts = []
                        for item in related:
                            node_type = item.get("type", "Unknown")
                            title = item.get("title") or item.get("name") or item.get("subject", "")[:50]
                            graph_parts.append(f"- [{node_type}] {title}")
                        if graph_parts:
                            return "\n\nRelated Graph Entities:\n" + "\n".join(graph_parts)
            except ImportError:
                pass 
            except Exception as e:
                logger.debug(f"Could not fetch graph context: {e}")
            logger.info("[ContextService] Graph context fetched.")
            return ""

        # Execute parallel tasks
        retrieval_tasks = {
            "conversation_context": fetch_history(),
            "entity_context": fetch_entities(),
            "semantic_context": fetch_prefs(),
            "graph_context": fetch_graph_context()
        }
        
        task_names = list(retrieval_tasks.keys())
        task_coros = list(retrieval_tasks.values())
        
        fetch_results = await asyncio.gather(*task_coros, return_exceptions=True)
        
        # Process results with keyed mapping
        for name, result in zip(task_names, fetch_results):
            if isinstance(result, Exception):
                logger.warning(f"[ContextService] {name} fetch failed: {result}")
                continue
            
            if result:
                results[name] = result
        
        return results

# Convenience helper
def get_context_service():
    return ContextService.get_instance()
