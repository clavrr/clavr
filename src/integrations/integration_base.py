"""
Integration Base Module

Provides base classes and utilities for all integrations.
Ensures consistent integration with services/, ai/, and agent/roles/.
"""
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod

from ..utils.logger import setup_logger
from ..utils.config import load_config, Config

logger = setup_logger(__name__)


class BaseIntegration(ABC):
    """
    Base class for all integrations.
    
    Provides common functionality for:
    - Service integration (EmailService, CalendarService, TaskService)
    - AI component integration (RAGEngine, LLMFactory, ConversationMemory)
    - Agent role integration (AnalyzerRole, ResearcherRole, ContactResolverRole, etc.)
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        db: Optional[Any] = None,
        enable_services: bool = True,
        enable_ai: bool = True
    ):
        """
        Initialize base integration
        
        Args:
            config: Optional configuration object
            db: Optional database session
            enable_services: Whether to initialize services
            enable_ai: Whether to initialize AI components
        """
        self.config = config or load_config()
        self.db = db
        
        # Initialize services
        self.services = {}
        if enable_services:
            self._initialize_services()
        
        # Initialize AI components
        self.ai_components = {}
        if enable_ai:
            self._initialize_ai_components()
        
        logger.info(f"{self.__class__.__name__} initialized")
    
    def _initialize_services(self):
        """Initialize service layer components"""
        try:
            from api.dependencies import AppState
            
            # Get services via tools (they provide service access)
            # Services are accessed through tools to ensure proper credential handling
            self.services['email_tool'] = AppState.get_email_tool(user_id=1, request=None)
            self.services['calendar_tool'] = AppState.get_calendar_tool(user_id=1, request=None)
            self.services['task_tool'] = AppState.get_task_tool(user_id=1, request=None, db=self.db)
            
            logger.debug(f"[{self.__class__.__name__}] Services initialized")
        except Exception as e:
            logger.warning(f"Could not initialize services: {e}")
    
    def _initialize_ai_components(self):
        """Initialize AI components"""
        try:
            from api.dependencies import AppState
            from ..ai.llm_factory import LLMFactory
            from ..ai.conversation_memory import ConversationMemory
            
            # RAG Engine (Qdrant)
            self.ai_components['rag_engine'] = AppState.get_rag_engine()
            
            # LLM Factory
            self.ai_components['llm_factory'] = LLMFactory
            
            # Conversation Memory (with RAG for semantic search)
            if self.db:
                rag_engine = self.ai_components.get('rag_engine')
                self.ai_components['memory'] = ConversationMemory(self.db, rag_engine=rag_engine)
            
            logger.debug(f"[{self.__class__.__name__}] AI components initialized")
        except Exception as e:
            logger.warning(f"Could not initialize AI components: {e}")
    
    def _get_graph_manager(self) -> Optional[Any]:
        """Get graph manager instance"""
        try:
            from ..services.indexing.graph.manager import KnowledgeGraphManager
            return KnowledgeGraphManager(config=self.config)
        except Exception as e:
            logger.debug(f"Could not get graph manager: {e}")
            return None
    
    @abstractmethod
    async def process_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Process a query through the integration
        
        Args:
            query: User query string
            context: Optional context (user_id, channel_id, etc.)
            
        Returns:
            Response string
        """
        pass
    
    def get_service(self, service_name: str) -> Optional[Any]:
        """
        Get a service by name.
        
        Services are accessed via tools. To get the actual service instance:
        - email_service: self.get_service('email_tool').email_service
        - calendar_service: self.get_service('calendar_tool').calendar_service
        - task_service: self.get_service('task_tool').task_service
        
        Args:
            service_name: Service name ('email_tool', 'calendar_tool', 'task_tool')
            
        Returns:
            Tool instance (not the service directly)
        """
        return self.services.get(service_name)
    
    def get_email_service(self) -> Optional[Any]:
        """Get EmailService instance from email_tool"""
        email_tool = self.get_service('email_tool')
        if email_tool and hasattr(email_tool, 'email_service'):
            return email_tool.email_service
        return None
    
    def get_calendar_service(self) -> Optional[Any]:
        """Get CalendarService instance from calendar_tool"""
        calendar_tool = self.get_service('calendar_tool')
        if calendar_tool and hasattr(calendar_tool, 'calendar_service'):
            return calendar_tool.calendar_service
        return None
    
    def get_task_service(self) -> Optional[Any]:
        """Get TaskService instance from task_tool"""
        task_tool = self.get_service('task_tool')
        if task_tool and hasattr(task_tool, 'task_service'):
            return task_tool.task_service
        return None
    
    def get_ai_component(self, component_name: str) -> Optional[Any]:
        """Get an AI component by name"""
        return self.ai_components.get(component_name)

