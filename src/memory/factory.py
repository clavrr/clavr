"""
Domain Memory Factory.

Centralizes the creation of specialized memory contexts for agents.
Orchestrates Vector Store (RAG), Knowledge Graph, and Behavioral Memory (Lanes)
into a unified DomainContext.
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from src.utils.config import Config, RAGConfig
from src.utils.logger import setup_logger
from src.ai.rag.core.rag_engine import RAGEngine
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.memory.agent_memory_lane import AgentMemoryLaneManager, get_agent_memory_lane_manager, init_agent_memory_lane_manager
from src.memory.domain_context import DomainContext

logger = setup_logger(__name__)

# Configuration map for domains
# Maps agent names to resources
DOMAIN_CONFIG = {
    "conversations": {
        "vector_collection": "conversations",
        "graph_nodes": ["Message", "Session"],
        "memory_lane": "conversation_agent"
    },
    "email": {
        "vector_collection": "email-knowledge",
        "graph_nodes": ["Email", "Person", "Organization"],
        "memory_lane": "email_agent"
    },
    "drive": {
        "vector_collection": "drive-files",
        "graph_nodes": ["File", "Folder", "Project"],
        "memory_lane": "drive_agent"
    },
    "calendar": {
        "vector_collection": "calendar-events",
        "graph_nodes": ["Event", "Person", "Location"],
        "memory_lane": "calendar_agent"
    },
    "tasks": {
        "vector_collection": "tasks",
        "graph_nodes": ["Task", "Project", "Tag"],
        "memory_lane": "task_agent"
    },
    "notion": {
        "vector_collection": "notion-pages",
        "graph_nodes": ["Page", "Database", "Block"],
        "memory_lane": "notion_agent"
    },
    "research": {
        "vector_collection": "research-knowledge",
        "graph_nodes": ["Topic", "Source", "Fact"],
        "memory_lane": "research_agent"
    },
    "notes": {
        "vector_collection": "notes",
        "graph_nodes": ["Note", "Label"],
        "memory_lane": "keep_agent"
    },
    # Default for others
    "default": {
        "vector_collection": "general-knowledge",
        "graph_nodes": [],
        "memory_lane": "default_agent"
    }
}

class DomainMemoryFactory:
    """
    Factory for creating domain-specific memory contexts.
    """
    
    def __init__(self, config: Config, db_session: Optional[Session] = None):
        """
        Initialize the factory.
        
        Args:
            config: Application configuration
            db_session: Database session for persistence
        """
        self.config = config
        self.db = db_session
        
        # Initialize Lane Manager
        self.lane_manager = get_agent_memory_lane_manager()
        if not self.lane_manager:
            self.lane_manager = init_agent_memory_lane_manager(db_session)
            
        # Initialize Graph Manager (Shared singleton ideally, but creating here if needed)
        # Using "auto" backend heuristic or config
        # Ideally this should be passed in, but we can lazy init
        self.graph_manager = KnowledgeGraphManager(
            config=config, 
            backend="arangodb" if config.database.url else "networkx"
        )
        
        # Cache for RAGEngines to avoid recreating connections
        self._rag_engines: Dict[str, RAGEngine] = {}
        
    def get_domain_context(self, agent_name: str, user_id: int) -> DomainContext:
        """
        Get the memory context for a specific agent.
        
        Args:
            agent_name: Name of the agent (e.g., "email", "drive")
            user_id: ID of the user
            
        Returns:
            DomainContext object with specialized memory components
        """
        domain_cfg = DOMAIN_CONFIG.get(agent_name, DOMAIN_CONFIG["default"])
        
        # 1. Get Behavioral Memory Lane
        lane_name = domain_cfg["memory_lane"]
        memory_lane = self.lane_manager.get_or_create(lane_name, user_id)
        
        # 2. Get Vector Store (RAGEngine) for this domain
        collection = domain_cfg["vector_collection"]
        rag_engine = self._get_rag_engine(collection)
        
        # 3. Get Graph Scope
        graph_scope = domain_cfg["graph_nodes"]
        
        return DomainContext(
            memory_lane=memory_lane,
            vector_store=rag_engine,
            graph_manager=self.graph_manager,
            graph_scope=graph_scope,
            working_memory={} # Fresh working memory
        )
        
    def _get_rag_engine(self, collection_name: str) -> RAGEngine:
        """
        Get or create a RAGEngine for the specified collection.
        This enables separation of vector indices per domain.
        """
        if collection_name in self._rag_engines:
            return self._rag_engines[collection_name]
        
        try:
            # Create RAG Config override for this collection
            rag_config = self.config.rag.copy() if self.config.rag else RAGConfig()
            rag_config.collection_name = collection_name
            
            # Create Engine
            engine = RAGEngine(self.config, rag_config=rag_config)
            self._rag_engines[collection_name] = engine
            logger.info(f"[DomainMemoryFactory] Initialized RAGEngine for collection: {collection_name}")
            return engine
        except Exception as e:
            logger.error(f"[DomainMemoryFactory] Failed to create RAGEngine for {collection_name}: {e}")
            # Fallback to a dummy or default if essential? 
            # For now re-raise or return None? 
            # Better to return None and handle in caller, or let it crash if critical.
            # But let's return None and log.
            # RAGEngine init usually doesn't fail unless DB is down.
            raise e
