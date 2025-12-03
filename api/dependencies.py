"""
API Dependencies
Provides shared dependencies for FastAPI routers using proper dependency injection
"""
from typing import Optional, Generator, Any
from fastapi import Depends, Request

from src.utils.config import load_config, Config
from src.ai.rag import RAGEngine
from src.ai.llm_factory import LLMFactory
from src.utils.logger import setup_logger
from src.tools import EmailTool, CalendarTool, TaskTool, SummarizeTool, NotionTool

logger = setup_logger(__name__)


# ============================================
# APPLICATION STATE (Singleton Pattern)
# ============================================

class AppState:
    """Application state holder for singleton instances"""
    _config: Optional[Config] = None
    _rag_engine: Optional[RAGEngine] = None
    _email_tool: Optional[EmailTool] = None
    _calendar_tool: Optional[CalendarTool] = None
    _task_tool: Optional[TaskTool] = None
    _summarize_tool: Optional[SummarizeTool] = None
    _notion_tool: Optional[NotionTool] = None
    _orchestrator: Optional[Any] = None
    
    @classmethod
    def get_config(cls) -> Config:
        """Get or create config singleton"""
        if cls._config is None:
            cls._config = load_config()
            logger.info("[OK] Configuration loaded")
        return cls._config
    
    @classmethod
    def get_rag_engine(cls) -> RAGEngine:
        """Get or create RAG engine singleton"""
        if cls._rag_engine is None:
            config = cls.get_config()
            cls._rag_engine = RAGEngine(config, collection_name="email-knowledge")
            logger.info("[OK] RAG engine initialized")
        return cls._rag_engine
    
    @classmethod
    def get_rag_tool(cls) -> RAGEngine:
        """Get or create RAG tool singleton (deprecated - use get_rag_engine instead)"""
        logger.warning("get_rag_tool is deprecated. Use get_rag_engine instead.")
        return cls.get_rag_engine()
    
    @classmethod
    def get_email_tool(cls, user_id: int = 1, request: Optional[Any] = None, user_first_name: Optional[str] = None) -> EmailTool:
        """
        Get or create EmailTool with user credentials.
        
        Creates a new instance each time to ensure fresh credentials from the session.
        This is important because tokens can be refreshed between requests.
        
        Args:
            user_id: User ID
            request: Optional FastAPI Request object to get session credentials
            user_first_name: Optional user's first name for personalization
        """
        config = cls.get_config()
        rag_engine = cls.get_rag_engine()
        
        # Get credentials from request session if available
        credentials = None
        if request and hasattr(request.state, 'session') and request.state.session:
            try:
                from src.database import get_db_context
                from src.auth.token_refresh import get_valid_credentials
                
                session = request.state.session
                if session.gmail_access_token:
                    with get_db_context() as db:
                        credentials_obj = get_valid_credentials(db, session, auto_refresh=True)
                        if credentials_obj:
                            credentials = credentials_obj
                            logger.debug(f"EmailTool using credentials from session (user_id={user_id})")
            except Exception as e:
                logger.warning(f"Failed to get credentials from request: {e}")
        
        email_tool = EmailTool(config=config, rag_engine=rag_engine, user_id=user_id, credentials=credentials, user_first_name=user_first_name)
        return email_tool
    
    @classmethod
    def get_calendar_tool(cls, user_id: Optional[int] = None, request: Optional[Any] = None) -> CalendarTool:
        """
        Get or create CalendarTool with user credentials.
        
        Creates a new instance each time to ensure fresh credentials from the session.
        
        Args:
            user_id: Optional user ID for session-based credential retrieval
            request: Optional FastAPI Request object to get session credentials
        """
        config = cls.get_config()
        rag_engine = cls.get_rag_engine()  # Get RAG engine for email indexing and contact resolution
        
        # Get credentials from request session if available
        # Use same method as get_email_tool to ensure token refresh
        credentials = None
        if request and hasattr(request.state, 'session') and request.state.session:
            try:
                from src.database import get_db_context
                from src.auth.token_refresh import get_valid_credentials
                
                session = request.state.session
                if session.gmail_access_token:
                    with get_db_context() as db:
                        credentials_obj = get_valid_credentials(db, session, auto_refresh=True)
                        if credentials_obj:
                            credentials = credentials_obj
                            logger.debug(f"CalendarTool using credentials from session (user_id={user_id})")
            except Exception as e:
                logger.warning(f"Failed to get credentials from request: {e}")
        
        calendar_tool = CalendarTool(config=config, user_id=user_id, credentials=credentials, rag_engine=rag_engine)
        return calendar_tool
    
    @classmethod
    def get_task_tool(cls, user_id: int = 1, request: Optional[Any] = None, user_first_name: Optional[str] = None) -> TaskTool:
        """
        Get or create TaskTool (cached per user_id) with user credentials.
        
        Caches instances per user_id since TaskTool manages local storage files.
        Updates credentials if a new request is provided.
        
        Args:
            user_id: User ID
            request: Optional FastAPI Request object to get session credentials
            user_first_name: Optional user's first name for personalization
        """
        cache_key = f"task_tool_{user_id}"
        if not hasattr(cls, '_task_tool_cache'):
            cls._task_tool_cache = {}
        
        config = cls.get_config()
        storage_path = f"./data/tasks_{user_id}.json"
        
        # Get credentials from request session if available
        credentials = None
        if request and hasattr(request.state, 'session') and request.state.session:
            try:
                from src.database import get_db_context
                from src.auth.token_refresh import get_valid_credentials
                
                session = request.state.session
                if session.gmail_access_token:
                    with get_db_context() as db:
                        credentials_obj = get_valid_credentials(db, session, auto_refresh=True)
                        if credentials_obj:
                            credentials = credentials_obj
                            logger.debug(f"TaskTool using credentials from session (user_id={user_id})")
            except Exception as e:
                logger.warning(f"Failed to get credentials from request: {e}")
        
        # Create new instance if not cached
        if cache_key not in cls._task_tool_cache:
            cls._task_tool_cache[cache_key] = TaskTool(
                storage_path=storage_path, 
                config=config,
                user_id=user_id,
                credentials=credentials,
                user_first_name=user_first_name
            )
        else:
            # Update credentials and user_first_name if provided (for token refresh scenarios)
            tool = cls._task_tool_cache[cache_key]
            if credentials:
                object.__setattr__(tool, '_credentials', credentials)
                # Reset google_client to force re-initialization with new credentials
                tool._google_client = None
            if user_first_name:
                object.__setattr__(tool, 'user_first_name', user_first_name)
                # Update parser's user_first_name if it exists
                if hasattr(tool, '_parser') and tool._parser:
                    tool._parser.user_first_name = user_first_name
        
        return cls._task_tool_cache[cache_key]
    
    @classmethod
    def get_summarize_tool(cls) -> SummarizeTool:
        """Get or create SummarizeTool singleton"""
        if cls._summarize_tool is None:
            config = cls.get_config()
            cls._summarize_tool = SummarizeTool(config=config)
            logger.info("[OK] SummarizeTool initialized")
        return cls._summarize_tool
    
    @classmethod
    def get_notion_tool(cls, graph_manager: Optional[Any] = None, rag_engine: Optional[Any] = None) -> NotionTool:
        """
        Get or create NotionTool singleton.
        
        Args:
            graph_manager: Optional KnowledgeGraphManager for Neo4j
            rag_engine: Optional RAGEngine for Pinecone (defaults to singleton)
        """
        if cls._notion_tool is None:
            config = cls.get_config()
            if rag_engine is None:
                rag_engine = cls.get_rag_engine()
            
            cls._notion_tool = NotionTool(
                config=config,
                graph_manager=graph_manager,
                rag_engine=rag_engine
            )
            logger.info("[OK] NotionTool initialized")
        
        return cls._notion_tool
    
    @classmethod
    def get_orchestrator(cls, db: Optional[Any] = None, user_id: Optional[int] = None, request: Optional[Any] = None) -> Any:
        """
        Get or create orchestrator singleton.
        
        The orchestrator handles multi-step query execution with intelligent routing,
        query decomposition, and cross-domain coordination.
        
        Args:
            db: Optional database session for orchestrator operations
            user_id: Optional user ID for user-specific orchestration
            request: Optional FastAPI Request object for session-based credentials
        
        Returns:
            Orchestrator instance for handling complex multi-step queries
        """
        if cls._orchestrator is None:
            try:
                from src.agent.orchestration import create_orchestrator
                
                config = cls.get_config()
                
                # Get tools with optional request context for credentials
                tools = [
                    cls.get_email_tool(user_id=user_id or 1, request=request),
                    cls.get_calendar_tool(user_id=user_id, request=request),
                    cls.get_task_tool(user_id=user_id or 1, request=request),
                    cls.get_summarize_tool(),
                    cls.get_notion_tool()  # Include NotionTool
                ]
                
                # Get RAG engine and graph manager for agent roles
                rag_engine = cls.get_rag_engine()
                graph_manager = None
                try:
                    from src.services.indexing.graph.manager import KnowledgeGraphManager
                    graph_manager = KnowledgeGraphManager(config=config)
                except Exception as e:
                    logger.debug(f"Could not initialize graph manager: {e}")
                
                cls._orchestrator = create_orchestrator(
                    tools=tools,
                    config=config,
                    db=db,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager
                )
                logger.info("[OK] Orchestrator initialized")
            except ImportError:
                logger.warning("Orchestration module not available. Install required dependencies.")
                return None
        
        return cls._orchestrator
    
    @classmethod
    def reset(cls):
        """Reset all singletons (useful for testing)"""
        cls._config = None
        cls._rag_engine = None
        cls._email_tool = None
        cls._calendar_tool = None
        cls._task_tool = None
        cls._summarize_tool = None
        cls._orchestrator = None
        if hasattr(cls, '_email_tool_cache'):
            cls._email_tool_cache = {}
        if hasattr(cls, '_task_tool_cache'):
            cls._task_tool_cache = {}
        logger.info("Reset application state")


# ============================================
# FASTAPI DEPENDENCIES
# ============================================

def get_config() -> Config:
    """
    FastAPI dependency for configuration
    
    Usage:
        @app.get("/")
        def endpoint(config: Config = Depends(get_config)):
            ...
    
    Returns:
        Config object loaded from config/config.yaml
    """
    return AppState.get_config()


def get_rag_engine() -> RAGEngine:
    """
    FastAPI dependency for RAG engine
    
    Usage:
        @app.get("/search")
        def search(rag: RAGEngine = Depends(get_rag_engine)):
            ...
    
    Returns:
        RAGEngine instance for email search and retrieval
    """
    return AppState.get_rag_engine()

def get_rag_tool() -> RAGEngine:
    """
    FastAPI dependency for RAG tool (deprecated - use get_rag_engine instead)
    
    Usage:
        @app.get("/search")
        def search(rag: RAGEngine = Depends(get_rag_tool)):
            ...
    
    Returns:
        RAGEngine instance for email search and retrieval
    """
    logger.warning("get_rag_tool dependency is deprecated. Use get_rag_engine instead.")
    return AppState.get_rag_engine()


def get_llm(config: Config = Depends(get_config)):
    """
    FastAPI dependency for LLM client
    
    Usage:
        @app.post("/generate")
        def generate(llm = Depends(get_llm)):
            ...
    
    Returns:
        LLM client instance (Google Gemini by default)
    """
    return LLMFactory.get_llm_for_provider(config, temperature=0.0)


def get_email_tool(user_id: int = 1, config: Config = Depends(get_config)) -> EmailTool:
    """
    FastAPI dependency for EmailTool (cached singleton)
    
    Note: This version doesn't have access to request. Use AppState.get_email_tool() 
    directly with request parameter when you need user credentials.
    
    Usage:
        @app.post("/chat")
        def chat(email_tool: EmailTool = Depends(get_email_tool)):
            ...
    
    Returns:
        EmailTool instance (without user credentials - will load from session if user_id provided)
    """
    return AppState.get_email_tool(user_id=user_id, request=None)


def get_calendar_tool(user_id: Optional[int] = None, request: Optional[Request] = None, config: Config = Depends(get_config)) -> CalendarTool:
    """
    FastAPI dependency for CalendarTool with user credentials
    
    Args:
        user_id: Optional user ID (will be extracted from request if not provided)
        request: FastAPI Request object to get session credentials
        config: Configuration object
    """
    # Extract user_id from request if not provided
    if not user_id and request:
        try:
            # Try to get user from request state if available
            if hasattr(request.state, 'user') and request.state.user:
                user_id = request.state.user.id
        except:
            pass
    
    return AppState.get_calendar_tool(user_id=user_id, request=request)


def get_task_tool(user_id: int = 1, config: Config = Depends(get_config)) -> TaskTool:
    """FastAPI dependency for TaskTool (cached singleton per user)"""
    return AppState.get_task_tool(user_id=user_id)


def get_summarize_tool(config: Config = Depends(get_config)) -> SummarizeTool:
    """FastAPI dependency for SummarizeTool (cached singleton)"""
    return AppState.get_summarize_tool()


def get_orchestrator(
    user_id: Optional[int] = None,
    request: Optional[Request] = None,
    db: Optional[Any] = None
) -> Any:
    """
    FastAPI dependency for Orchestrator
    
    The orchestrator handles multi-step query execution with intelligent routing,
    query decomposition, execution planning, and cross-domain coordination.
    
    Usage:
        @app.post("/orchestrate")
        async def orchestrate(
            query: str,
            orchestrator = Depends(get_orchestrator),
            db: AsyncSession = Depends(get_db)
        ):
            result = await orchestrator.execute_query(query)
            return {"result": result}
    
    Args:
        user_id: Optional user ID for user-specific orchestration
        request: Optional FastAPI Request object for session-based credentials
        db: Optional database session for orchestrator operations
    
    Returns:
        Orchestrator instance or None if orchestration module not available
    """
    return AppState.get_orchestrator(db=db, user_id=user_id, request=request)
