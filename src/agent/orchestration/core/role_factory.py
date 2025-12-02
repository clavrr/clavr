"""
Role Factory - Centralized role initialization to reduce boilerplate

This factory pattern reduces repetitive try/except blocks for role initialization
and provides a consistent interface for creating agent roles.
"""

from typing import Optional, Any, Callable, TypeVar, Dict
from ....utils.logger import setup_logger
from ..config import LOG_OK, LOG_WARNING

logger = setup_logger(__name__)

T = TypeVar('T')


class RoleFactory:
    """Factory for initializing agent roles with consistent error handling"""
    
    @staticmethod
    def create_role(
        role_name: str,
        import_func: Callable[[], Any],
        init_func: Callable[[Any], T],
        **init_kwargs
    ) -> Optional[T]:
        """
        Create a role instance with consistent error handling.
        
        Args:
            role_name: Human-readable name for logging
            import_func: Function that imports the role class
            init_func: Function that initializes the role with the imported class
            **init_kwargs: Additional keyword arguments for initialization
            
        Returns:
            Initialized role instance or None if initialization fails
        """
        try:
            role_class = import_func()
            instance = init_func(role_class, **init_kwargs)
            logger.info(f"{LOG_OK} {role_name} initialized")
            return instance
        except Exception as e:
            logger.warning(f"{LOG_WARNING} Could not initialize {role_name}: {e}")
            return None
    
    @staticmethod
    def create_analyzer_role(config: Optional[Any] = None) -> Optional[Any]:
        """Create AnalyzerRole instance"""
        def import_role():
            from ...roles.analyzer_role import AnalyzerRole
            return AnalyzerRole
        
        def init_role(cls, **kwargs):
            return cls(config=kwargs.get('config'))
        
        return RoleFactory.create_role(
            'AnalyzerRole',
            import_role,
            init_role,
            config=config
        )
    
    @staticmethod
    def create_researcher_role(
        rag_engine: Optional[Any] = None,
        graph_manager: Optional[Any] = None,
        config: Optional[Any] = None
    ) -> Optional[Any]:
        """Create ResearcherRole instance"""
        def import_role():
            from ...roles.researcher_role import ResearcherRole
            return ResearcherRole
        
        def init_role(cls, **kwargs):
            return cls(
                rag_engine=kwargs.get('rag_engine'),
                graph_manager=kwargs.get('graph_manager'),
                config=kwargs.get('config')
            )
        
        return RoleFactory.create_role(
            'ResearcherRole',
            import_role,
            init_role,
            rag_engine=rag_engine,
            graph_manager=graph_manager,
            config=config
        )
    
    @staticmethod
    def create_contact_resolver_role(
        slack_client: Optional[Any] = None,
        graph_manager: Optional[Any] = None,
        email_service: Optional[Any] = None,
        config: Optional[Any] = None
    ) -> Optional[Any]:
        """Create ContactResolverRole instance"""
        def import_role():
            from ...roles.contact_resolver_role import ContactResolverRole
            return ContactResolverRole
        
        def init_role(cls, **kwargs):
            return cls(
                slack_client=kwargs.get('slack_client'),
                graph_manager=kwargs.get('graph_manager'),
                email_service=kwargs.get('email_service'),
                config=kwargs.get('config')
            )
        
        return RoleFactory.create_role(
            'ContactResolverRole',
            import_role,
            init_role,
            slack_client=slack_client,
            graph_manager=graph_manager,
            email_service=email_service,
            config=config
        )
    
    @staticmethod
    def create_orchestrator_role(
        config: Optional[Any] = None,
        tools: Optional[list] = None
    ) -> Optional[Any]:
        """Create OrchestratorRole instance"""
        def import_role():
            from ...roles.orchestrator_role import OrchestratorRole
            return OrchestratorRole
        
        def init_role(cls, **kwargs):
            return cls(
                config=kwargs.get('config'),
                tools=kwargs.get('tools', [])
            )
        
        return RoleFactory.create_role(
            'OrchestratorRole',
            import_role,
            init_role,
            config=config,
            tools=tools
        )
    
    @staticmethod
    def create_synthesizer_role(config: Optional[Any] = None) -> Optional[Any]:
        """Create SynthesizerRole instance"""
        def import_role():
            from ...roles.synthesizer_role import SynthesizerRole
            return SynthesizerRole
        
        def init_role(cls, **kwargs):
            return cls(config=kwargs.get('config'))
        
        return RoleFactory.create_role(
            'SynthesizerRole',
            import_role,
            init_role,
            config=config
        )
    
    @staticmethod
    def create_memory_role(
        config: Optional[Any] = None,
        db: Optional[Any] = None,
        graph_manager: Optional[Any] = None
    ) -> Optional[Any]:
        """Create MemoryRole instance"""
        def import_role():
            from ...roles.memory_role import MemoryRole
            return MemoryRole
        
        def init_role(cls, **kwargs):
            return cls(
                config=kwargs.get('config'),
                db=kwargs.get('db'),
                graph_manager=kwargs.get('graph_manager')
            )
        
        return RoleFactory.create_role(
            'MemoryRole',
            import_role,
            init_role,
            config=config,
            db=db,
            graph_manager=graph_manager
        )

